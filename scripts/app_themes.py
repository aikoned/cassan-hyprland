#!/usr/bin/env python3
"""Plan and safely apply Cassan's optional application themes.

This adapter deliberately lives outside the core desktop deployment.  It only
touches Cassan-owned theme assets and narrowly marked Firefox import blocks;
application profiles, sessions, credentials, extensions, and caches remain
user-owned.
"""

from __future__ import annotations

import argparse
import configparser
import errno
import dataclasses
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


REPO_DIR = Path(__file__).resolve().parent.parent
SCHEMA = 1
APPS = ("firefox", "vesktop", "spotify")
THEME_NAME = "Cassan-Nighthowler"
COLOR_SCHEME = "Nighthowler"
STATE_RELATIVE = Path("cassan") / "app-themes"
PROFILE_NAME_RE = re.compile(r"^[^\x00\r\n/]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(r"(?<![0-9])v?(\d+)\.(\d+)\.(\d+)(?![0-9])")
MINIMUM_SPICETIFY_VERSION = (2, 44, 0)
SPICETIFY_VERSION = "2.44.0"
SPICETIFY_ARCHIVE_URL = (
    "https://github.com/spicetify/cli/releases/download/"
    "v2.44.0/spicetify-2.44.0-linux-amd64.tar.gz"
)
SPICETIFY_ARCHIVE_SHA256 = (
    "115045610a609a2084af389e65aa4f60351a4b8ef1497ce98bdbdf379544ef9b"
)
MAXIMUM_SPICETIFY_ARCHIVE_BYTES = 64 * 1024 * 1024
MAXIMUM_SPICETIFY_BINARY_BYTES = 64 * 1024 * 1024
SPICETIFY_OVERRIDE_VARIABLES = ("SPICETIFY_CONFIG", "SPICETIFY_STATE")

CSS_START = "/* >>> CASSAN NIGHTHOWLER >>> */"
CSS_END = "/* <<< CASSAN NIGHTHOWLER <<< */"
PREF_START = "// >>> CASSAN NIGHTHOWLER >>>"
PREF_END = "// <<< CASSAN NIGHTHOWLER <<<"
CHROME_BLOCK = (
    CSS_START
    + '\n@import url("cassan-nighthowler.css");\n'
    + CSS_END
    + "\n"
)
CONTENT_BLOCK = (
    CSS_START
    + '\n@import url("cassan-nighthowler-content.css");\n'
    + CSS_END
    + "\n"
)
PREF_BLOCK = (
    PREF_START
    + '\nuser_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);\n'
    + PREF_END
    + "\n"
)


class ThemeError(Exception):
    """User-facing application-theme failure."""


class ThemeConflict(ThemeError):
    """A user-owned or locally modified file needs explicit review."""


@dataclasses.dataclass(frozen=True)
class Roots:
    home: Path
    xdg_config: Path
    state: Path

    @classmethod
    def from_environ(cls, environ: Optional[Mapping[str, str]] = None) -> "Roots":
        values = os.environ if environ is None else environ
        home = canonical_root(values.get("HOME", ""), "HOME")
        xdg_config = canonical_root(
            values.get("XDG_CONFIG_HOME", str(home / ".config")),
            "XDG_CONFIG_HOME",
        )
        state_base = canonical_root(
            values.get("XDG_STATE_HOME", str(home / ".local" / "state")),
            "XDG_STATE_HOME",
        )
        if xdg_config == home or state_base == home:
            raise ThemeError("XDG configuration and state roots must not equal HOME")
        state_root = state_base / STATE_RELATIVE
        if overlaps(xdg_config, state_root):
            raise ThemeError("application-theme state must not overlap XDG_CONFIG_HOME")
        return cls(home=home, xdg_config=xdg_config, state=state_root)


@dataclasses.dataclass
class Target:
    app: str
    path: Path
    kind: str
    desired: Optional[bytes]
    action: str = ""
    detail: str = ""
    created: bool = False
    observed: Optional[str] = None

    @property
    def key(self) -> str:
        return str(self.path)


def canonical_root(value: str, label: str) -> Path:
    if not value:
        raise ThemeError("%s is empty" % label)
    if "\x00" in value:
        raise ThemeError("%s contains an invalid NUL byte" % label)
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ThemeError("%s must be an absolute path without '..'" % label)
    return path.resolve(strict=False)


def overlaps(left: Path, right: Path) -> bool:
    return is_below(left, right) or is_below(right, left)


def is_below(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_regular(path: Path) -> Optional[bytes]:
    if not os.path.lexists(str(path)):
        return None
    item_stat = os.lstat(str(path))
    if stat.S_ISLNK(item_stat.st_mode) or not stat.S_ISREG(item_stat.st_mode):
        raise ThemeConflict("destination must be a regular non-symlink file: %s" % path)
    return path.read_bytes()


def checked_source(relative: str) -> bytes:
    source = REPO_DIR / relative
    try:
        source_stat = os.lstat(str(source))
    except OSError as error:
        raise ThemeError("missing application-theme source: %s" % relative) from error
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise ThemeError("application-theme source must be a regular file: %s" % relative)
    resolved = source.resolve(strict=True)
    if not is_below(resolved, REPO_DIR.resolve(strict=True)):
        raise ThemeError("application-theme source escapes the repository")
    return source.read_bytes()


def assert_safe_parent(root: Path, path: Path, create: bool) -> None:
    resolved_root = root.resolve(strict=False)
    if not is_below(path.resolve(strict=False), resolved_root):
        raise ThemeError("destination escapes its application root: %s" % path)
    if os.path.lexists(str(root)):
        root_stat = os.lstat(str(root))
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise ThemeConflict("application root is not a real directory: %s" % root)
    elif create:
        root.mkdir(parents=True, mode=0o755)

    relative_parent = path.parent.relative_to(root)
    cursor = root
    for part in relative_parent.parts:
        cursor = cursor / part
        if os.path.lexists(str(cursor)):
            item_stat = os.lstat(str(cursor))
            if stat.S_ISLNK(item_stat.st_mode) or not stat.S_ISDIR(item_stat.st_mode):
                raise ThemeConflict("refusing to traverse destination: %s" % cursor)
        elif create:
            cursor.mkdir(mode=0o755)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(str(path), flags)
    except OSError as error:
        unsupported = (
            errno.EINVAL,
            errno.ENOTSUP,
            getattr(errno, "EOPNOTSUPP", -1),
        )
        if sys.platform.startswith("linux") or error.errno not in unsupported:
            raise
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            unsupported = (
                errno.EINVAL,
                errno.ENOTSUP,
                getattr(errno, "EOPNOTSUPP", -1),
            )
            if sys.platform.startswith("linux") or error.errno not in unsupported:
                raise
    finally:
        os.close(descriptor)


def atomic_write(path: Path, content: bytes, mode: int = 0o644) -> None:
    if not os.path.lexists(str(path.parent)):
        raise OSError("atomic write parent does not exist: %s" % path.parent)
    parent_stat = os.lstat(str(path.parent))
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise OSError("atomic write parent is not a real directory: %s" % path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".%s.cassan-" % path.name, dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fchmod(target.fileno(), mode)
            os.fsync(target.fileno())
        os.replace(str(temporary), str(path))
        fsync_directory(path.parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def safe_unlink(path: Path) -> None:
    current = read_regular(path)
    if current is not None:
        path.unlink()
        fsync_directory(path.parent)


def marker_span(text: str, start: str, end: str) -> Tuple[int, int]:
    if text.count(start) != 1 or text.count(end) != 1:
        raise ThemeConflict("managed Cassan marker block is missing or malformed")
    beginning = text.index(start)
    end_start = text.find(end, beginning + len(start))
    if end_start < 0:
        raise ThemeConflict("managed Cassan marker block has reversed markers")
    ending = end_start + len(end)
    if ending < len(text) and text[ending] == "\n":
        ending += 1
    return beginning, ending


def css_with_block(current: Optional[bytes], block: str) -> Tuple[bytes, bool]:
    text = "" if current is None else decode_text(current)
    start_count = text.count(CSS_START)
    end_count = text.count(CSS_END)
    if start_count != end_count or start_count > 1:
        raise ThemeConflict("malformed Cassan CSS marker block")
    if start_count == 1:
        beginning, ending = marker_span(text, CSS_START, CSS_END)
        existing = text[beginning:ending]
        if existing != block:
            raise ThemeConflict("Cassan CSS marker block was edited locally")
        return current if current is not None else block.encode(), current is None

    insertion = 0
    if text.startswith("@charset"):
        semicolon = text.find(";")
        if semicolon >= 0:
            insertion = semicolon + 1
            while insertion < len(text) and text[insertion] in "\r\n":
                insertion += 1
    return (text[:insertion] + block + text[insertion:]).encode("utf-8"), current is None


def pref_with_block(current: Optional[bytes]) -> Tuple[bytes, bool]:
    text = "" if current is None else decode_text(current)
    start_count = text.count(PREF_START)
    end_count = text.count(PREF_END)
    if start_count != end_count or start_count > 1:
        raise ThemeConflict("malformed Cassan Firefox preference marker block")
    if start_count == 1:
        beginning, ending = marker_span(text, PREF_START, PREF_END)
        if text[beginning:ending] != PREF_BLOCK:
            raise ThemeConflict("Cassan Firefox preference block was edited locally")
        return current if current is not None else PREF_BLOCK.encode(), current is None
    return (text + PREF_BLOCK).encode("utf-8"), current is None


def without_block(current: bytes, start: str, end: str) -> bytes:
    text = decode_text(current)
    beginning, ending = marker_span(text, start, end)
    result = text[:beginning] + text[ending:]
    return result.encode("utf-8")


def decode_text(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ThemeConflict("managed wrapper is not UTF-8 text") from error


def read_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        raw = read_regular(path)
        if raw is None:
            raise ThemeError("Firefox profile registry is missing: %s" % path)
        parser.read_string(raw.decode("utf-8"), source=str(path))
    except (OSError, configparser.Error, UnicodeError) as error:
        raise ThemeError("cannot read Firefox profile registry: %s" % path) from error
    return parser


def firefox_profiles(
    roots: Roots,
    profile_name: Optional[str] = None,
    all_profiles: bool = False,
    euid: Optional[int] = None,
) -> List[Path]:
    base = roots.home / ".mozilla" / "firefox"
    registry = base / "profiles.ini"
    assert_safe_parent(roots.home, registry, create=False)
    if not registry.is_file():
        raise ThemeError("launch Firefox once before applying its Cassan theme")
    profiles_ini = read_ini(registry)
    profiles: List[Tuple[str, Path, bool]] = []
    for section in profiles_ini.sections():
        if not section.startswith("Profile"):
            continue
        name = profiles_ini.get(section, "Name", fallback="")
        raw_path = profiles_ini.get(section, "Path", fallback="")
        relative = profiles_ini.get(section, "IsRelative", fallback="1") == "1"
        if not name or not PROFILE_NAME_RE.fullmatch(name) or not raw_path:
            raise ThemeError("Firefox profiles.ini contains an invalid profile entry")
        if not relative or Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
            raise ThemeError("Cassan v1 supports only relative Firefox profiles")
        path = validate_profile_directory(base, base / raw_path, euid)
        profiles.append(
            (name, path, profiles_ini.get(section, "Default", fallback="0") == "1")
        )
    if not profiles:
        raise ThemeError("Firefox has no usable profiles; launch it once")

    if profile_name is not None:
        matches = [path for name, path, _default in profiles if name == profile_name]
        if len(matches) != 1:
            raise ThemeError("Firefox profile name must match exactly one profiles.ini entry")
        return matches
    if all_profiles:
        return [path for _name, path, _default in profiles]

    installation_defaults: List[Path] = []
    for filename in ("installs.ini", "profiles.ini"):
        candidate = base / filename
        if not candidate.is_file():
            continue
        document = read_ini(candidate)
        for section in document.sections():
            if not section.startswith("Install"):
                continue
            raw_default = document.get(section, "Default", fallback="")
            if not raw_default or Path(raw_default).is_absolute() or ".." in Path(raw_default).parts:
                continue
            path = validate_profile_directory(base, base / raw_default, euid)
            if path not in installation_defaults:
                installation_defaults.append(path)
    if len(installation_defaults) == 1:
        return installation_defaults
    if len(installation_defaults) > 1:
        raise ThemeError("multiple Firefox installation defaults; choose --firefox-profile")

    defaults = [path for _name, path, default in profiles if default]
    if len(defaults) == 1:
        return defaults
    if len(profiles) == 1:
        return [profiles[0][1]]
    raise ThemeError("multiple Firefox profiles; choose --firefox-profile or --all-firefox-profiles")


def validate_profile_directory(base: Path, path: Path, euid: Optional[int]) -> Path:
    if not os.path.lexists(str(base)):
        raise ThemeError("Firefox profile root is missing")
    base_stat = os.lstat(str(base))
    if stat.S_ISLNK(base_stat.st_mode) or not stat.S_ISDIR(base_stat.st_mode):
        raise ThemeConflict("Firefox profile root must be a real directory")
    resolved = path.resolve(strict=True)
    if not is_below(resolved, base.resolve(strict=True)):
        raise ThemeError("Firefox profile escapes ~/.mozilla/firefox")
    current_uid = os.geteuid() if euid is None else euid
    cursor = base
    for part in path.relative_to(base).parts:
        cursor = cursor / part
        cursor_stat = os.lstat(str(cursor))
        if stat.S_ISLNK(cursor_stat.st_mode) or not stat.S_ISDIR(cursor_stat.st_mode):
            raise ThemeConflict("Firefox profile traverses an unsafe path")
        if cursor_stat.st_uid != current_uid:
            raise ThemeConflict("Firefox profile is not owned by the current user")
    return resolved


def state_target(roots: Roots, path_string: str, entry: Mapping[str, object]) -> Target:
    if "\x00" in path_string:
        raise ThemeError("application-theme state contains an invalid NUL byte")
    path = Path(path_string)
    if not path.is_absolute() or ".." in path.parts:
        raise ThemeError("application-theme state contains an unsafe destination")
    app = entry.get("app")
    kind = entry.get("kind")
    if app not in APPS or kind not in ("asset", "wrapper"):
        raise ThemeError("application-theme state has an invalid file contract")
    target = Target(str(app), path, str(kind), None)
    assert_safe_parent(root_for_target(roots, target), path, create=False)

    if app == "vesktop":
        expected = roots.xdg_config / "vesktop" / "themes" / "Cassan-Nighthowler.theme.css"
        if kind != "asset" or path != expected:
            raise ThemeError("application-theme state has an invalid Vesktop destination")
    elif app == "spotify":
        theme_root = roots.xdg_config / "spicetify" / "Themes" / THEME_NAME
        if kind != "asset" or path not in (theme_root / "color.ini", theme_root / "user.css"):
            raise ThemeError("application-theme state has an invalid Spotify destination")
    else:
        profile_root = roots.home / ".mozilla" / "firefox"
        asset_names = {"cassan-nighthowler.css", "cassan-nighthowler-content.css"}
        wrapper_names = {"userChrome.css", "userContent.css"}
        if path.name == "user.js":
            profile = path.parent
            valid_asset = False
            valid_css_wrapper = False
            valid_pref_wrapper = kind == "wrapper"
        elif path.parent.name == "chrome":
            profile = path.parent.parent
            valid_asset = kind == "asset" and path.name in asset_names
            valid_css_wrapper = kind == "wrapper" and path.name in wrapper_names
            valid_pref_wrapper = False
        else:
            raise ThemeError("application-theme state has an invalid Firefox destination")
        try:
            profile_relative = profile.relative_to(profile_root)
        except ValueError as error:
            raise ThemeError("application-theme state has an invalid Firefox destination") from error
        if not profile_relative.parts:
            raise ThemeError("application-theme state has no Firefox profile directory")
        if kind == "asset" and not valid_asset:
            raise ThemeError("application-theme state has an invalid Firefox asset")
        if kind == "wrapper" and not (valid_css_wrapper or valid_pref_wrapper):
            raise ThemeError("application-theme state has an invalid Firefox wrapper")
    return target


def empty_state() -> Dict[str, object]:
    return {"schema": SCHEMA, "files": {}}


def ensure_state_root(roots: Roots, create: bool) -> None:
    anchor = roots.state.parents[1]
    assert_safe_parent(anchor, roots.state / "manifest.json", create=create)
    if not os.path.lexists(str(roots.state)):
        return
    state_stat = os.lstat(str(roots.state))
    if stat.S_ISLNK(state_stat.st_mode) or not stat.S_ISDIR(state_stat.st_mode):
        raise ThemeConflict("application-theme state root must be a real directory")
    if state_stat.st_uid != os.geteuid():
        raise ThemeConflict("application-theme state root has an unexpected owner")
    if create:
        for private_directory in (roots.state.parent, roots.state):
            directory_stat = os.lstat(str(private_directory))
            if stat.S_ISLNK(directory_stat.st_mode) or not stat.S_ISDIR(directory_stat.st_mode):
                raise ThemeConflict("application-theme state traverses an unsafe directory")
            if directory_stat.st_uid != os.geteuid():
                raise ThemeConflict("application-theme state has an unexpected owner")
            os.chmod(str(private_directory), 0o700)
    elif stat.S_IMODE(state_stat.st_mode) & 0o077:
        raise ThemeConflict("application-theme state root must have mode 0700")


@contextmanager
def mutation_lock(roots: Roots):
    ensure_state_root(roots, create=True)
    lock_path = roots.state / "transaction.lock"
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(lock_path), flags, 0o600)
    except OSError as error:
        raise ThemeError("cannot open the application-theme transaction lock") from error
    try:
        lock_stat = os.fstat(descriptor)
        if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_uid != os.geteuid():
            raise ThemeConflict("application-theme transaction lock is unsafe")
        if stat.S_IMODE(lock_stat.st_mode) & 0o077:
            raise ThemeConflict("application-theme transaction lock must have mode 0600")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN):
                raise ThemeConflict("another application-theme transaction is active") from error
            raise ThemeError("cannot lock application-theme state") from error
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def load_state(roots: Roots) -> Dict[str, object]:
    ensure_state_root(roots, create=False)
    path = roots.state / "manifest.json"
    if not os.path.lexists(str(path)):
        return empty_state()
    manifest_stat = os.lstat(str(path))
    if manifest_stat.st_uid != os.geteuid():
        raise ThemeConflict("application-theme manifest has an unexpected owner")
    if stat.S_IMODE(manifest_stat.st_mode) != 0o600:
        raise ThemeConflict("application-theme manifest must have mode 0600")
    raw = read_regular(path)
    assert raw is not None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise ThemeError("application-theme state is corrupt") from error
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ThemeError("unsupported application-theme state")
    files = value.get("files")
    if not isinstance(files, dict):
        raise ThemeError("application-theme state has no valid file map")
    for key, entry in files.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            raise ThemeError("application-theme state has an invalid file entry")
        state_target(roots, key, entry)
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or not SHA256_RE.fullmatch(checksum):
            raise ThemeError("application-theme state has an invalid checksum")
        if not isinstance(entry.get("created"), bool):
            raise ThemeError("application-theme state has an invalid ownership flag")
    return value


def save_state(roots: Roots, state: Mapping[str, object]) -> None:
    ensure_state_root(roots, create=True)
    atomic_write(
        roots.state / "manifest.json",
        (json.dumps(state, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        0o600,
    )


def selected_apps(values: Sequence[str]) -> Tuple[str, ...]:
    unique: List[str] = []
    for value in values:
        if value not in APPS:
            raise ThemeError("unknown application theme: %s" % value)
        if value not in unique:
            unique.append(value)
    if not unique:
        raise ThemeError("select at least one application with --app")
    return tuple(unique)


def build_targets(
    roots: Roots,
    apps: Sequence[str],
    profile_name: Optional[str],
    all_profiles: bool,
    euid: Optional[int] = None,
) -> List[Target]:
    targets: List[Target] = []
    if "firefox" in apps:
        for profile in firefox_profiles(roots, profile_name, all_profiles, euid):
            chrome = profile / "chrome"
            chrome_asset = chrome / "cassan-nighthowler.css"
            content_asset = chrome / "cassan-nighthowler-content.css"
            user_chrome = chrome / "userChrome.css"
            user_content = chrome / "userContent.css"
            user_js = profile / "user.js"
            targets.extend(
                [
                    Target("firefox", chrome_asset, "asset", checked_source("firefox/cassan-nighthowler.css")),
                    Target("firefox", content_asset, "asset", checked_source("firefox/cassan-nighthowler-content.css")),
                    Target("firefox", user_chrome, "wrapper", None),
                    Target("firefox", user_content, "wrapper", None),
                    Target("firefox", user_js, "wrapper", None),
                ]
            )
    if "vesktop" in apps:
        targets.append(
            Target(
                "vesktop",
                roots.xdg_config / "vesktop" / "themes" / "Cassan-Nighthowler.theme.css",
                "asset",
                checked_source("vesktop/Cassan-Nighthowler.theme.css"),
            )
        )
    if "spotify" in apps:
        theme_root = roots.xdg_config / "spicetify" / "Themes" / THEME_NAME
        targets.extend(
            [
                Target("spotify", theme_root / "color.ini", "asset", checked_source("spicetify/Cassan-Nighthowler/color.ini")),
                Target("spotify", theme_root / "user.css", "asset", checked_source("spicetify/Cassan-Nighthowler/user.css")),
            ]
        )
    return targets


def root_for_target(roots: Roots, target: Target) -> Path:
    if target.app == "firefox":
        return roots.home / ".mozilla" / "firefox"
    return roots.xdg_config


def wrapper_desired(target: Target, current: Optional[bytes]) -> Tuple[bytes, bool]:
    if target.path.name == "userChrome.css":
        return css_with_block(current, CHROME_BLOCK)
    if target.path.name == "userContent.css":
        return css_with_block(current, CONTENT_BLOCK)
    if target.path.name == "user.js":
        return pref_with_block(current)
    raise ThemeError("unknown Firefox wrapper target")


def expected_wrapper_block(target: Target) -> Tuple[str, str, str]:
    if target.path.name == "userChrome.css":
        return CSS_START, CSS_END, CHROME_BLOCK
    if target.path.name == "userContent.css":
        return CSS_START, CSS_END, CONTENT_BLOCK
    if target.path.name == "user.js":
        return PREF_START, PREF_END, PREF_BLOCK
    raise ThemeError("unknown Firefox wrapper target")


def require_exact_wrapper_block(target: Target, current: bytes) -> None:
    start, end, expected = expected_wrapper_block(target)
    text = decode_text(current)
    beginning, ending = marker_span(text, start, end)
    if text[beginning:ending] != expected:
        raise ThemeConflict("Cassan wrapper block was edited locally")


def plan_apply(
    roots: Roots,
    targets: List[Target],
    state: Mapping[str, object],
    replace: bool,
) -> List[Target]:
    entries = state["files"]
    assert isinstance(entries, dict)
    for target in targets:
        assert_safe_parent(root_for_target(roots, target), target.path, create=False)
        current = read_regular(target.path)
        target.observed = None if current is None else sha256_bytes(current)
        previous = entries.get(target.key)
        if target.kind == "wrapper":
            if isinstance(previous, dict) and current is not None:
                try:
                    require_exact_wrapper_block(target, current)
                except ThemeConflict:
                    if not replace:
                        target.action = "conflict"
                        target.detail = "managed marker was removed or edited"
                        continue
            try:
                desired, created = wrapper_desired(target, current)
            except ThemeConflict:
                if not replace:
                    target.action = "conflict"
                    target.detail = "managed marker was edited"
                    continue
                try:
                    desired = forced_wrapper_desired(target, current)
                except ThemeConflict:
                    target.action = "conflict"
                    target.detail = "managed marker is malformed"
                    continue
                created = current is None
            target.desired = desired
            target.created = bool(previous.get("created")) if isinstance(previous, dict) else created
        desired = target.desired
        assert desired is not None
        if current is None:
            target.action = "create"
        elif current == desired:
            if previous:
                target.action = "unchanged"
            else:
                target.action = "replace" if replace else "conflict"
                target.detail = "byte-identical destination is still unmanaged"
        elif target.kind == "wrapper":
            target.action = "update"
        elif previous is None:
            target.action = "replace" if replace else "conflict"
            target.detail = "unmanaged destination already exists"
        elif sha256_bytes(current) == previous.get("sha256"):
            target.action = "update"
        else:
            target.action = "replace" if replace else "conflict"
            target.detail = "managed asset was edited locally"
    return targets


def forced_wrapper_desired(target: Target, current: Optional[bytes]) -> bytes:
    if current is None:
        return wrapper_desired(target, current)[0]
    text = decode_text(current)
    start, end, block = expected_wrapper_block(target)
    if start in text and end in text:
        beginning, ending = marker_span(text, start, end)
        return (text[:beginning] + block + text[ending:]).encode("utf-8")
    return wrapper_desired(target, current)[0]


def plan_remove(
    roots: Roots,
    apps: Sequence[str],
    state: Mapping[str, object],
    replace: bool,
) -> List[Target]:
    entries = state["files"]
    assert isinstance(entries, dict)
    targets: List[Target] = []
    for path_string, entry in entries.items():
        if not isinstance(entry, dict) or entry.get("app") not in apps:
            continue
        path = Path(path_string)
        target = Target(str(entry["app"]), path, str(entry["kind"]), None)
        assert_safe_parent(root_for_target(roots, target), path, create=False)
        current = read_regular(path)
        target.observed = None if current is None else sha256_bytes(current)
        if current is None:
            target.action = "forget"
        elif target.kind == "asset":
            if sha256_bytes(current) == entry.get("sha256") or replace:
                target.action = "remove"
            else:
                target.action = "conflict"
                target.detail = "managed asset was edited locally"
        else:
            try:
                wrapper_desired(target, current)
                if path.name == "user.js":
                    desired = without_block(current, PREF_START, PREF_END)
                else:
                    desired = without_block(current, CSS_START, CSS_END)
            except ThemeConflict:
                if replace:
                    target.action = "forget"
                    target.detail = "marker missing; forgetting ownership after --replace"
                    targets.append(target)
                    continue
                target.action = "conflict"
                target.detail = "managed marker is missing or malformed"
                targets.append(target)
                continue
            target.desired = desired
            if not desired and bool(entry.get("created")):
                target.action = "remove"
            elif current == desired:
                target.action = "forget"
            else:
                target.action = "update"
        targets.append(target)
    return targets


def print_plan(title: str, targets: Sequence[Target]) -> None:
    print(title)
    counts: Dict[str, int] = {}
    for target in targets:
        detail = " — %s" % target.detail if target.detail else ""
        print("  %-9s %-8s %s%s" % (target.action.upper(), target.app, target.path, detail))
        counts[target.action] = counts.get(target.action, 0) + 1
    summary = ", ".join("%d %s" % (count, action) for action, count in sorted(counts.items()))
    print("Summary: %s" % (summary or "no selected managed files"))


def mutation_targets(targets: Iterable[Target]) -> List[Target]:
    return [target for target in targets if target.action in ("create", "update", "replace", "remove")]


def verify_plan_observations(targets: Sequence[Target]) -> None:
    for target in targets:
        current = read_regular(target.path)
        observed = None if current is None else sha256_bytes(current)
        if observed != target.observed:
            raise ThemeConflict(
                "destination changed after planning; review the application-theme plan again: %s"
                % target.path
            )


def backup_before(roots: Roots, targets: Sequence[Target]) -> Tuple[Path, List[Tuple[Target, Optional[bytes], int]]]:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = roots.state / "backups" / (stamp + "-" + secrets.token_hex(4))
    observations: List[Tuple[Target, Optional[bytes], int]] = []
    manifest = []
    for index, target in enumerate(targets):
        before = read_regular(target.path)
        observed = None if before is None else sha256_bytes(before)
        if observed != target.observed:
            raise ThemeConflict(
                "destination changed while preparing the backup: %s" % target.path
            )
        mode = 0o644
        stored = None
        if before is not None:
            mode = stat.S_IMODE(os.lstat(str(target.path)).st_mode)
            stored = "%04d.bin" % index
        observations.append((target, before, mode))
        manifest.append({"path": str(target.path), "before": stored, "mode": mode, "action": target.action})
    try:
        assert_safe_parent(roots.state.parents[1], backup / "transaction.json", create=True)
        os.chmod(str(backup.parent), 0o700)
        os.chmod(str(backup), 0o700)
        for index, (_target, before, _mode) in enumerate(observations):
            if before is not None:
                atomic_write(backup / ("%04d.bin" % index), before, 0o600)
        atomic_write(
            backup / "transaction.json",
            (json.dumps({"schema": SCHEMA, "files": manifest}, indent=2, sort_keys=True) + "\n").encode(),
            0o600,
        )
    except BaseException:
        shutil.rmtree(str(backup), ignore_errors=True)
        raise
    return backup, observations


def apply_targets(
    roots: Roots,
    targets: Sequence[Target],
    state: Dict[str, object],
    removing: bool,
) -> Optional[Path]:
    conflicts = [target for target in targets if target.action == "conflict"]
    if conflicts:
        raise ThemeConflict("resolve conflicts or review again with --replace")
    verify_plan_observations(targets)
    mutations = mutation_targets(targets)
    entries = state["files"]
    assert isinstance(entries, dict)
    if not mutations and not any(target.action in ("adopt", "forget") for target in targets):
        return None
    backup: Optional[Path] = None
    observations: List[Tuple[Target, Optional[bytes], int]] = []
    applied: List[Tuple[Target, Optional[bytes], int]] = []
    manifest_path = roots.state / "manifest.json"
    manifest_before = read_regular(manifest_path)
    manifest_mode = (
        stat.S_IMODE(os.lstat(str(manifest_path)).st_mode)
        if manifest_before is not None
        else 0o600
    )
    manifest_after: Optional[bytes] = None
    manifest_attempted = False
    ensure_state_root(roots, create=True)
    if mutations:
        backup, observations = backup_before(roots, mutations)
    try:
        for target in mutations:
            assert_safe_parent(root_for_target(roots, target), target.path, create=True)
            current = read_regular(target.path)
            observed = None if current is None else sha256_bytes(current)
            if observed != target.observed:
                raise ThemeConflict(
                    "destination changed immediately before mutation: %s" % target.path
                )
            # Mark the operation before touching its destination. A write or
            # deletion may succeed even when its following directory fsync
            # fails, and that destination must still participate in rollback.
            observation = next(item for item in observations if item[0] is target)
            applied.append(observation)
            if target.action == "remove":
                safe_unlink(target.path)
            else:
                assert target.desired is not None
                previous_mode = 0o644
                if os.path.lexists(str(target.path)):
                    previous_mode = stat.S_IMODE(os.lstat(str(target.path)).st_mode)
                atomic_write(target.path, target.desired, previous_mode)
        for target in targets:
            if removing:
                if target.action != "conflict":
                    entries.pop(target.key, None)
            else:
                current = read_regular(target.path)
                if current is None:
                    raise ThemeError("managed theme file disappeared during apply")
                entries[target.key] = {
                    "app": target.app,
                    "kind": target.kind,
                    "sha256": sha256_bytes(current),
                    "created": target.created,
                }
        manifest_after = (
            json.dumps(state, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        manifest_attempted = True
        save_state(roots, state)
    except BaseException as original_error:
        rollback_failures: List[str] = []
        for target, before, mode in reversed(applied):
            try:
                assert_safe_parent(root_for_target(roots, target), target.path, create=True)
                current = read_regular(target.path)
                current_mode = (
                    stat.S_IMODE(os.lstat(str(target.path)).st_mode)
                    if current is not None
                    else None
                )
                before_matches = current == before and (
                    current is None or current_mode == mode
                )
                if before_matches:
                    continue
                if target.action == "remove":
                    after_matches = current is None
                else:
                    after_matches = current == target.desired and current_mode == mode
                if not after_matches:
                    raise ThemeConflict(
                        "rollback target has an unknown concurrent change"
                    )
                if before is None:
                    safe_unlink(target.path)
                else:
                    atomic_write(target.path, before, mode)
            except BaseException as rollback_error:
                rollback_failures.append("%s (%s)" % (target.path, rollback_error))
        if manifest_attempted:
            try:
                current_manifest = read_regular(manifest_path)
                current_manifest_mode = (
                    stat.S_IMODE(os.lstat(str(manifest_path)).st_mode)
                    if current_manifest is not None
                    else None
                )
                manifest_before_matches = current_manifest == manifest_before and (
                    current_manifest is None or current_manifest_mode == manifest_mode
                )
                if not manifest_before_matches:
                    manifest_after_matches = (
                        current_manifest == manifest_after
                        and current_manifest_mode == 0o600
                    )
                    if not manifest_after_matches:
                        raise ThemeConflict(
                            "application-theme manifest has an unknown concurrent change"
                        )
                    assert_safe_parent(roots.state.parents[1], manifest_path, create=True)
                    if manifest_before is None:
                        safe_unlink(manifest_path)
                    else:
                        atomic_write(manifest_path, manifest_before, manifest_mode)
            except BaseException as rollback_error:
                rollback_failures.append("%s (%s)" % (manifest_path, rollback_error))
        if rollback_failures:
            raise ThemeError(
                "application-theme rollback was incomplete; backup %s; failed paths: %s"
                % (backup, ", ".join(rollback_failures))
            ) from original_error
        raise
    return backup


def validate_repo(allow_dirty: bool) -> None:
    check = REPO_DIR / "scripts" / "check.sh"
    result = subprocess.run(
        [str(check)], cwd=str(REPO_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False
    )
    if result.returncode != 0:
        raise ThemeError("repository validation failed:\n%s" % result.stdout.strip())
    git = shutil.which("git")
    if git is None:
        raise ThemeError("git is required to verify application-theme sources")
    status = subprocess.run(
        [git, "-C", str(REPO_DIR), "status", "--porcelain", "--untracked-files=normal"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False,
    )
    if status.returncode != 0:
        raise ThemeError("cannot inspect repository status")
    if status.stdout.strip() and not allow_dirty:
        raise ThemeError("repository has uncommitted files; review them or pass --allow-dirty")


def spicetify_environment(
    roots: Roots, environ: Optional[Mapping[str, str]] = None
) -> Dict[str, str]:
    values = dict(os.environ if environ is None else environ)
    for variable in SPICETIFY_OVERRIDE_VARIABLES:
        if values.get(variable):
            raise ThemeConflict(
                "%s must be unset while Cassan manages Spicetify" % variable
            )
        values.pop(variable, None)
    values["HOME"] = str(roots.home)
    values["XDG_CONFIG_HOME"] = str(roots.xdg_config)
    return values


def find_spicetify(roots: Roots, euid: Optional[int] = None) -> str:
    candidates = [
        roots.home / ".spicetify" / "spicetify",
        roots.home / ".local" / "bin" / "spicetify",
        Path("/usr/bin/spicetify"),
    ]
    current_uid = os.geteuid() if euid is None else euid
    environment = spicetify_environment(roots)
    outdated: List[Tuple[Path, Tuple[int, int, int]]] = []
    for candidate in candidates:
        if not os.path.lexists(str(candidate)):
            continue
        if is_below(candidate, roots.home):
            assert_safe_parent(roots.home, candidate, create=False)
        candidate_stat = os.lstat(str(candidate))
        if stat.S_ISLNK(candidate_stat.st_mode) or not stat.S_ISREG(candidate_stat.st_mode):
            continue
        resolved = candidate.resolve(strict=True)
        item_stat = os.stat(str(resolved))
        expected_owner = 0 if str(candidate).startswith("/usr/") else current_uid
        if item_stat.st_uid != expected_owner or item_stat.st_mode & 0o022:
            continue
        if not item_stat.st_mode & 0o111:
            continue
        result = subprocess.run(
            [str(resolved), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            env=environment,
        )
        match = VERSION_RE.search(result.stdout)
        if result.returncode != 0 or match is None:
            continue
        version = tuple(int(part) for part in match.groups())
        if version < MINIMUM_SPICETIFY_VERSION:
            outdated.append((candidate, version))
            continue
        return str(resolved)
    if outdated:
        details = ", ".join(
            "%s (%s)"
            % (path, ".".join(str(part) for part in version))
            for path, version in outdated
        )
        raise ThemeError("Spicetify 2.44.0 or newer is required; found " + details)
    raise ThemeError("a compatible current Spicetify install is required before activation")


def spicetify_binary_from_archive(archive: bytes) -> bytes:
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
            members = [member for member in bundle.getmembers() if member.name == "spicetify"]
            if len(members) != 1:
                raise ThemeError("Spicetify release archive has no unique top-level binary")
            member = members[0]
            if not member.isfile() or member.size <= 0 or member.size > MAXIMUM_SPICETIFY_BINARY_BYTES:
                raise ThemeError("Spicetify release binary has an invalid archive entry")
            source = bundle.extractfile(member)
            if source is None:
                raise ThemeError("cannot read the Spicetify release binary")
            binary = source.read(MAXIMUM_SPICETIFY_BINARY_BYTES + 1)
    except (tarfile.TarError, OSError) as error:
        raise ThemeError("cannot inspect the Spicetify release archive") from error
    if len(binary) != member.size or len(binary) > MAXIMUM_SPICETIFY_BINARY_BYTES:
        raise ThemeError("Spicetify release binary size is invalid")
    if (
        len(binary) < 20
        or binary[:4] != b"\x7fELF"
        or binary[4] != 2
        or binary[5] != 1
        or binary[18:20] != b"\x3e\x00"
    ):
        raise ThemeError("Spicetify release is not a Linux x86_64 ELF binary")
    return binary


def install_spicetify(
    roots: Roots,
    replace: bool,
    opener=None,
) -> Tuple[Path, Optional[Path]]:
    destination = roots.home / ".spicetify" / "spicetify"
    assert_safe_parent(roots.home, destination, create=False)
    request = urllib.request.Request(
        SPICETIFY_ARCHIVE_URL,
        headers={"User-Agent": "Cassan/%s" % SCHEMA},
        method="GET",
    )
    open_url = urllib.request.urlopen if opener is None else opener
    try:
        with open_url(request, timeout=60) as response:
            archive = response.read(MAXIMUM_SPICETIFY_ARCHIVE_BYTES + 1)
    except (OSError, urllib.error.URLError) as error:
        raise ThemeError("cannot download the pinned Spicetify release") from error
    if len(archive) > MAXIMUM_SPICETIFY_ARCHIVE_BYTES:
        raise ThemeError("Spicetify release archive exceeds the download limit")
    if sha256_bytes(archive) != SPICETIFY_ARCHIVE_SHA256:
        raise ThemeError("Spicetify release checksum does not match the pinned value")
    binary = spicetify_binary_from_archive(archive)

    current = read_regular(destination)
    if current == binary:
        return destination, None
    if current is not None and not replace:
        raise ThemeConflict(
            "a different ~/.spicetify/spicetify already exists; inspect it or use --replace"
        )

    backup: Optional[Path] = None
    if current is not None:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = roots.state / "installer-backups" / (stamp + "-" + secrets.token_hex(4))
        assert_safe_parent(roots.state.parents[1], backup / "spicetify", create=True)
        os.chmod(str(backup.parent), 0o700)
        os.chmod(str(backup), 0o700)
        atomic_write(backup / "spicetify", current, 0o600)
        atomic_write(
            backup / "metadata.json",
            (
                json.dumps(
                    {
                        "schema": SCHEMA,
                        "destination": str(destination),
                        "sha256": sha256_bytes(current),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
            0o600,
        )
    assert_safe_parent(roots.home, destination, create=True)
    atomic_write(destination, binary, 0o755)
    return destination, backup


def verify_installed_apps(
    roots: Roots, apps: Sequence[str], state: Mapping[str, object]
) -> None:
    files = state.get("files")
    if not isinstance(files, dict):
        raise ThemeError("application-theme state has no valid file map")
    expected_names = {
        "firefox": {
            "cassan-nighthowler.css",
            "cassan-nighthowler-content.css",
            "userChrome.css",
            "userContent.css",
            "user.js",
        },
        "vesktop": {"Cassan-Nighthowler.theme.css"},
        "spotify": {"color.ini", "user.css"},
    }
    for app in apps:
        entries = [
            (path_string, entry)
            for path_string, entry in files.items()
            if isinstance(entry, dict) and entry.get("app") == app
        ]
        names = {Path(path_string).name for path_string, _entry in entries}
        if not expected_names[app].issubset(names):
            raise ThemeError("apply the %s theme before activating it" % app)
        for path_string, entry in entries:
            target = state_target(roots, path_string, entry)
            current = read_regular(target.path)
            if current is None:
                raise ThemeConflict("managed %s theme files have drifted; apply again" % app)
            if target.kind == "wrapper":
                try:
                    require_exact_wrapper_block(target, current)
                except ThemeConflict as error:
                    raise ThemeConflict(
                        "managed %s theme files have drifted; apply again" % app
                    ) from error
            elif sha256_bytes(current) != entry.get("sha256"):
                raise ThemeConflict("managed %s theme files have drifted; apply again" % app)


def verified_system_executable(path: Path) -> str:
    if not os.path.lexists(str(path)):
        raise ThemeError("required system executable is missing: %s" % path)
    item_stat = os.lstat(str(path))
    if (
        stat.S_ISLNK(item_stat.st_mode)
        or not stat.S_ISREG(item_stat.st_mode)
        or item_stat.st_uid != 0
        or item_stat.st_mode & 0o022
        or not item_stat.st_mode & 0o111
    ):
        raise ThemeConflict("required system executable is unsafe: %s" % path)
    return str(path)


def require_owned_directory(root: Path, path: Path, euid: Optional[int] = None) -> None:
    assert_safe_parent(root, path / ".cassan-path-check", create=False)
    if not os.path.lexists(str(path)):
        raise ThemeError("required application directory is missing: %s" % path)
    current_uid = os.geteuid() if euid is None else euid
    cursor = root
    for part in path.relative_to(root).parts:
        cursor = cursor / part
        item_stat = os.lstat(str(cursor))
        if stat.S_ISLNK(item_stat.st_mode) or not stat.S_ISDIR(item_stat.st_mode):
            raise ThemeConflict("application path traverses an unsafe directory: %s" % cursor)
        if item_stat.st_uid != current_uid:
            raise ThemeConflict("application directory has an unexpected owner: %s" % cursor)


def activate(roots: Roots, apps: Sequence[str], state: Mapping[str, object]) -> None:
    verify_installed_apps(roots, apps, state)
    if "firefox" in apps:
        print("Firefox theme is installed; fully restart Firefox to load it.")
    if "vesktop" in apps:
        print("Enable Cassan Nighthowler once in Vesktop: Settings > Vencord > Themes > Local Themes.")
    if "spotify" not in apps:
        return
    environment = spicetify_environment(roots)
    spicetify = find_spicetify(roots)
    verified_system_executable(Path("/usr/bin/spotify-launcher"))
    spotify_path = roots.home / ".local" / "share" / "spotify-launcher" / "install" / "usr" / "share" / "spotify"
    prefs_path = roots.xdg_config / "spotify" / "prefs"
    require_owned_directory(roots.home, spotify_path)
    assert_safe_parent(roots.xdg_config, prefs_path, create=False)
    prefs = read_regular(prefs_path)
    if prefs is None or os.lstat(str(prefs_path)).st_uid != os.geteuid():
        raise ThemeError("launch Spotify once before activating the Cassan Spicetify theme")
    spicetify_config = roots.xdg_config / "spicetify" / "config-xpui.ini"
    assert_safe_parent(roots.xdg_config, spicetify_config, create=False)
    config_before = read_regular(spicetify_config)
    config_mode = (
        stat.S_IMODE(os.lstat(str(spicetify_config)).st_mode)
        if config_before is not None
        else 0o600
    )
    commands = [
        [
            spicetify,
            "config",
            "spotify_path",
            str(spotify_path),
            "prefs_path",
            str(prefs_path),
            "current_theme",
            THEME_NAME,
            "color_scheme",
            COLOR_SCHEME,
            "inject_css",
            "1",
            "replace_colors",
            "1",
            "inject_theme_js",
            "0",
            "overwrite_assets",
            "0",
        ],
        [spicetify, "backup", "apply"],
    ]
    failure: Optional[BaseException] = None
    failed_index = -1
    for index, command in enumerate(commands):
        try:
            result = subprocess.run(command, check=False, env=environment)
        except (OSError, subprocess.SubprocessError) as error:
            failure = error
            failed_index = index
            break
        if result.returncode != 0:
            failure = ThemeError(
                "Spicetify command exited with status %d" % result.returncode
            )
            failed_index = index
            break
    if failure is not None:
        recovery_errors: List[str] = []
        if failed_index > 0:
            try:
                restore = subprocess.run(
                    [spicetify, "restore"], check=False, env=environment
                )
                if restore.returncode != 0:
                    recovery_errors.append("Spotify restore failed")
            except (OSError, subprocess.SubprocessError) as recovery_error:
                recovery_errors.append("Spotify restore failed: %s" % recovery_error)
        try:
            assert_safe_parent(roots.xdg_config, spicetify_config, create=True)
            if config_before is None:
                safe_unlink(spicetify_config)
            else:
                atomic_write(spicetify_config, config_before, config_mode)
        except (OSError, ThemeError) as recovery_error:
            recovery_errors.append("config restore failed: %s" % recovery_error)
        detail = "; " + "; ".join(recovery_errors) if recovery_errors else ""
        raise ThemeError("Spicetify activation failed and was rolled back" + detail) from failure
    print("Cassan Nighthowler is active in Spotify.")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    for command in ("plan", "apply", "status", "remove", "activate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--app", action="append", choices=APPS, required=True)
        if command in ("plan", "apply", "status"):
            profiles = subparser.add_mutually_exclusive_group()
            profiles.add_argument("--firefox-profile")
            profiles.add_argument("--all-firefox-profiles", action="store_true")
        if command in ("plan", "apply", "remove"):
            subparser.add_argument("--replace", action="store_true")
        if command == "apply":
            subparser.add_argument("--allow-dirty", action="store_true")
            subparser.add_argument("--dry-run", action="store_true")
    installer = subparsers.add_parser(
        "install-spicetify",
        help="install the pinned, checksum-verified upstream Linux binary",
    )
    installer.add_argument("--replace", action="store_true")
    return result


def run_theme_command(arguments, apps: Sequence[str], roots: Roots) -> int:
    state = load_state(roots)
    if arguments.command == "activate":
        activate(roots, apps, state)
        return 0
    if arguments.command == "remove":
        targets = plan_remove(roots, apps, state, arguments.replace)
        print_plan("Cassan application-theme removal plan", targets)
        backup = apply_targets(roots, targets, state, removing=True)
        print("Application themes removed." + (" Backup: %s" % backup if backup else ""))
        return 0

    targets = build_targets(
        roots,
        apps,
        arguments.firefox_profile,
        arguments.all_firefox_profiles,
    )
    targets = plan_apply(roots, targets, state, getattr(arguments, "replace", False))
    title = (
        "Cassan application-theme status"
        if arguments.command == "status"
        else "Cassan application-theme plan"
    )
    print_plan(title, targets)
    if any(target.action == "conflict" for target in targets):
        raise ThemeConflict("resolve conflicts or review again with --replace")
    if arguments.command in ("plan", "status") or getattr(arguments, "dry_run", False):
        print("Preview complete; no files were changed.")
        return 1 if arguments.command == "status" and any(
            target.action != "unchanged" for target in targets
        ) else 0
    validate_repo(arguments.allow_dirty)
    backup = apply_targets(roots, targets, state, removing=False)
    print("Application themes applied." + (" Backup: %s" % backup if backup else ""))
    print("Run the activate command for restart/toggle/Spotify activation guidance.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        roots = Roots.from_environ()
        if arguments.command == "install-spicetify":
            if os.geteuid() == 0:
                raise ThemeError("Spicetify must be installed as the desktop user, not root")
            with mutation_lock(roots):
                destination, backup = install_spicetify(roots, arguments.replace)
            print("Installed verified Spicetify %s at %s." % (SPICETIFY_VERSION, destination))
            if backup is not None:
                print("Previous binary backup: %s" % backup)
            return 0
        apps = selected_apps(arguments.app)
        mutates_user_state = arguments.command in ("remove", "activate") or (
            arguments.command == "apply" and not arguments.dry_run
        )
        if mutates_user_state and os.geteuid() == 0:
            raise ThemeError("application themes must be changed as the desktop user, not root")
        if mutates_user_state:
            with mutation_lock(roots):
                return run_theme_command(arguments, apps, roots)
        return run_theme_command(arguments, apps, roots)
    except (OSError, ThemeError) as error:
        print("error: %s" % error, file=sys.stderr)
        return 4 if isinstance(error, ThemeConflict) else 3


if __name__ == "__main__":
    raise SystemExit(main())
