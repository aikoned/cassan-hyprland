#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Mapping, Optional


CSS_START = "/* >>> CASSAN NIGHTHOWLER >>> */"
CSS_END = "/* <<< CASSAN NIGHTHOWLER <<< */"
PREF_START = "// >>> CASSAN NIGHTHOWLER >>>"
PREF_END = "// <<< CASSAN NIGHTHOWLER <<<"

LEGACY_NETWORKMANAGER_SHA256 = (
    "b8fdf543297ef1373e6b11866cf928b1e83f4d83935f54d2dcc2061d2409193b"
)
LEGACY_SPICETIFY_SHA256 = (
    "64a5da252a17df678182e12f92c39d3747f3b6abfb8ee17481c890b48c3c6db3"
)

FIREFOX_ASSETS = {
    "cassan-nighthowler.css": (
        "bc7246d8a039ee7ff4dce7fa0c95222cba29014c0ab4c5acddf2750c981ff10d"
    ),
    "cassan-nighthowler-content.css": (
        "efaa2e3b3f7530ca5510bd847acf385cb67aa5584175a576e2f53ffeed12460a"
    ),
}
FIREFOX_WRAPPERS = {
    "userChrome.css": (
        CSS_START,
        CSS_END,
        CSS_START + '\n@import url("cassan-nighthowler.css");\n' + CSS_END + "\n",
    ),
    "userContent.css": (
        CSS_START,
        CSS_END,
        CSS_START
        + '\n@import url("cassan-nighthowler-content.css");\n'
        + CSS_END
        + "\n",
    ),
    "user.js": (
        PREF_START,
        PREF_END,
        PREF_START
        + '\nuser_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);\n'
        + PREF_END
        + "\n",
    ),
}


class MigrationError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Roots:
    home: Path
    xdg_config: Path
    state_base: Path
    legacy_state: Path
    backup_root: Path

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
        if home in (xdg_config, state_base):
            raise MigrationError("XDG_CONFIG_HOME and XDG_STATE_HOME must not equal HOME")
        legacy_state = state_base / "cassan"
        backup_root = state_base / "hyprland-dots" / "legacy-cassan"
        if overlaps(legacy_state, backup_root):
            raise MigrationError("legacy and replacement state directories overlap")
        return cls(home, xdg_config, state_base, legacy_state, backup_root)


@dataclasses.dataclass
class Action:
    kind: str
    path: Path
    backup_relative: Path
    detail: str
    observed: tuple[object, ...]
    replacement: Optional[bytes] = None
    mode: Optional[int] = None


@dataclasses.dataclass(frozen=True)
class Review:
    path: Path
    detail: str
    blocking: bool = False


def canonical_root(value: str, label: str) -> Path:
    if not value or "\x00" in value:
        raise MigrationError(f"{label} is empty or invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise MigrationError(f"{label} must be an absolute path without '..'")
    return path.resolve(strict=False)


def is_below(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def overlaps(left: Path, right: Path) -> bool:
    return is_below(left, right) or is_below(right, left)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def observation(path: Path) -> tuple[object, ...]:
    if not os.path.lexists(str(path)):
        return ("missing",)
    item = os.lstat(str(path))
    if stat.S_ISLNK(item.st_mode):
        kind = "symlink"
    elif stat.S_ISREG(item.st_mode):
        kind = "file"
    elif stat.S_ISDIR(item.st_mode):
        kind = "directory"
    else:
        kind = "special"
    return (
        kind,
        item.st_dev,
        item.st_ino,
        item.st_size,
        item.st_mtime_ns,
        item.st_uid,
        stat.S_IMODE(item.st_mode),
    )


def regular_bytes(path: Path) -> bytes:
    item = os.lstat(str(path))
    if stat.S_ISLNK(item.st_mode) or not stat.S_ISREG(item.st_mode):
        raise MigrationError(f"legacy target is not a regular file: {path}")
    return path.read_bytes()


def safe_relative(path: Path, root: Path, label: str) -> Path:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise MigrationError(f"{label} escapes its expected root: {path}") from error
    if not relative.parts or ".." in relative.parts:
        raise MigrationError(f"{label} has an unsafe relative path: {path}")
    return relative


def safe_parent_chain(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    cursor = root
    for part in relative.parts[:-1]:
        cursor = cursor / part
        if not os.path.lexists(str(cursor)):
            continue
        item = os.lstat(str(cursor))
        if stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode):
            return False
    return True


def ensure_private_backup_root(roots: Roots) -> None:
    if not os.path.lexists(str(roots.state_base)):
        roots.state_base.mkdir(parents=True, mode=0o700)
    state_item = os.lstat(str(roots.state_base))
    if (
        stat.S_ISLNK(state_item.st_mode)
        or not stat.S_ISDIR(state_item.st_mode)
        or state_item.st_uid != os.geteuid()
    ):
        raise MigrationError("XDG_STATE_HOME is not a safe current-user directory")

    cursor = roots.state_base
    for part in roots.backup_root.relative_to(roots.state_base).parts:
        cursor = cursor / part
        if not os.path.lexists(str(cursor)):
            cursor.mkdir(mode=0o700)
        item = os.lstat(str(cursor))
        if (
            stat.S_ISLNK(item.st_mode)
            or not stat.S_ISDIR(item.st_mode)
            or item.st_uid != os.geteuid()
        ):
            raise MigrationError(f"legacy backup path is not a safe directory: {cursor}")
    os.chmod(roots.backup_root, 0o700)


def load_json(path: Path) -> Optional[object]:
    if not os.path.lexists(str(path)):
        return None
    try:
        raw = regular_bytes(path)
        return json.loads(raw.decode("utf-8"))
    except (MigrationError, UnicodeError, ValueError, OSError):
        return None


def managed_network_hashes(roots: Roots) -> set[str]:
    checksums = {LEGACY_NETWORKMANAGER_SHA256}
    value = load_json(roots.legacy_state / "manifest.json")
    if not isinstance(value, dict) or value.get("schema") != 1:
        return checksums
    files = value.get("files")
    if not isinstance(files, list):
        return checksums
    root_identity = value.get("roots")
    if not isinstance(root_identity, dict):
        return checksums
    expected_roots = {
        "xdg_config": str(roots.xdg_config),
        "home_config": str(roots.home / ".config"),
        "state": str(roots.legacy_state),
    }
    if any(root_identity.get(key) != expected for key, expected in expected_roots.items()):
        return checksums
    for entry in files:
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("root") == "xdg_config"
            and entry.get("relative") == "networkmanager-dmenu/config.ini"
        ):
            checksum = entry.get("sha256")
            if isinstance(checksum, str) and len(checksum) == 64:
                checksums.add(checksum)
    return checksums


def app_theme_manifest_entries(roots: Roots) -> dict[Path, dict[str, object]]:
    entries: dict[Path, dict[str, object]] = {}
    value = load_json(roots.legacy_state / "app-themes" / "manifest.json")
    if not isinstance(value, dict) or value.get("schema") != 1:
        return entries
    files = value.get("files")
    if not isinstance(files, dict):
        return entries
    firefox_root = roots.home / ".mozilla" / "firefox"
    for raw_path, entry in files.items():
        if not isinstance(raw_path, str) or not isinstance(entry, dict):
            continue
        if entry.get("app") != "firefox":
            continue
        path = Path(raw_path)
        if not path.is_absolute() or ".." in path.parts:
            continue
        if is_below(path, firefox_root):
            entries[path] = entry
    return entries


def firefox_candidates(roots: Roots) -> set[Path]:
    firefox_root = roots.home / ".mozilla" / "firefox"
    candidates = set(app_theme_manifest_entries(roots))
    if not firefox_root.is_dir() or firefox_root.is_symlink():
        return candidates
    for name in sorted(FIREFOX_ASSETS.keys() | FIREFOX_WRAPPERS.keys()):
        for path in firefox_root.rglob(name):
            candidates.add(path)
    return candidates


def remove_marker_block(
    content: bytes, start: str, end: str, expected: str
) -> Optional[bytes]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise MigrationError("Firefox wrapper with a Cassan marker is not UTF-8") from error
    starts = text.count(start)
    ends = text.count(end)
    if starts == 0 and ends == 0:
        return None
    if starts != 1 or ends != 1:
        raise MigrationError("Firefox wrapper has malformed Cassan markers")
    beginning = text.index(start)
    end_start = text.find(end, beginning + len(start))
    if end_start < 0:
        raise MigrationError("Firefox wrapper has reversed Cassan markers")
    ending = end_start + len(end)
    if ending < len(text) and text[ending] == "\n":
        ending += 1
    if text[beginning:ending] != expected:
        raise MigrationError("Firefox wrapper's Cassan block was edited locally")
    return (text[:beginning] + text[ending:]).encode("utf-8")


def add_archive(
    actions: list[Action],
    reviews: list[Review],
    path: Path,
    safety_root: Path,
    backup_relative: Path,
    detail: str,
) -> None:
    current = observation(path)
    if current[0] == "missing":
        return
    if current[0] not in ("file", "directory"):
        reviews.append(Review(path, "legacy path is not a regular file or directory", True))
        return
    if current[5] != os.geteuid():
        reviews.append(Review(path, "legacy path is not owned by the current user", True))
        return
    if not safe_parent_chain(safety_root, path):
        reviews.append(Review(path, "legacy path traverses an unsafe parent", True))
        return
    actions.append(Action("archive", path, backup_relative, detail, current))


def collapse_covered_actions(actions: list[Action]) -> list[Action]:
    collapsed: list[Action] = []
    for action in actions:
        if any(
            existing.kind == "archive" and is_below(action.path, existing.path)
            for existing in collapsed
        ):
            continue
        if action.kind == "archive":
            descendants = [
                existing for existing in collapsed if is_below(existing.path, action.path)
            ]
            if descendants:
                collapsed = [existing for existing in collapsed if existing not in descendants]
                action.detail += "; includes overlapping legacy targets"
        collapsed.append(action)
    return collapsed


def add_known_atomic_temporaries(
    actions: list[Action],
    reviews: list[Review],
    search_root: Path,
    safety_root: Path,
    backup_prefix: Path,
    destination_names: Iterable[str],
    recursive: bool = False,
) -> None:
    if not search_root.is_dir() or search_root.is_symlink():
        return
    for destination_name in destination_names:
        pattern = f".{destination_name}.cassan-*"
        candidates = search_root.rglob(pattern) if recursive else search_root.glob(pattern)
        for path in sorted(candidates, key=str):
            current = observation(path)
            if current[0] != "file":
                reviews.append(
                    Review(path, "Cassan-like temporary is not a regular file; retained")
                )
                continue
            relative = safe_relative(path, search_root, "Cassan temporary file")
            add_archive(
                actions,
                reviews,
                path,
                safety_root,
                backup_prefix / relative,
                "interrupted Cassan atomic-write temporary",
            )


def spotify_process_running() -> bool:
    proc = Path("/proc")
    if not proc.is_dir():
        return False
    names = {"spotify", "spotify-launcher", "spotify-launche"}
    try:
        processes = list(proc.iterdir())
    except OSError:
        return False
    for process in processes:
        if not process.name.isdigit():
            continue
        try:
            name = (process / "comm").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            continue
        if name in names:
            return True
    return False


def build_plan(roots: Roots) -> tuple[list[Action], list[Review]]:
    actions: list[Action] = []
    reviews: list[Review] = []

    # Cassan deliberately ignored XDG_CONFIG_HOME for this asset root.
    add_archive(
        actions,
        reviews,
        roots.home / ".config" / "cassan",
        roots.home,
        Path("home-config/cassan"),
        "old Cassan-owned wallpaper and asset directory",
    )

    network_config = roots.xdg_config / "networkmanager-dmenu" / "config.ini"
    network_observation = observation(network_config)
    if network_observation[0] == "file":
        checksum = sha256_file(network_config)
        if network_observation[5] != os.geteuid():
            reviews.append(Review(network_config, "file is not owned by the current user", True))
        elif not safe_parent_chain(roots.xdg_config, network_config):
            reviews.append(Review(network_config, "path traverses an unsafe parent", True))
        elif checksum in managed_network_hashes(roots):
            actions.append(
                Action(
                    "archive",
                    network_config,
                    Path("xdg-config/networkmanager-dmenu/config.ini"),
                    "verified legacy NetworkManager menu configuration",
                    network_observation,
                )
            )
        else:
            reviews.append(
                Review(
                    network_config,
                    "content no longer matches Cassan ownership state; retained",
                )
            )
    elif network_observation[0] not in ("missing",):
        reviews.append(Review(network_config, "unexpected path type; retained", True))
    add_known_atomic_temporaries(
        actions,
        reviews,
        roots.xdg_config / "networkmanager-dmenu",
        roots.xdg_config,
        Path("xdg-config/networkmanager-dmenu/temporaries"),
        ("config.ini",),
    )

    firefox_root = roots.home / ".mozilla" / "firefox"
    firefox_manifest = app_theme_manifest_entries(roots)
    for path in sorted(firefox_candidates(roots), key=str):
        if not is_below(path, firefox_root):
            reviews.append(Review(path, "Firefox target escapes the profile root", True))
            continue
        current = observation(path)
        if current[0] == "missing":
            continue
        if current[0] != "file":
            reviews.append(Review(path, "Firefox legacy target is not a regular file", True))
            continue
        if current[5] != os.geteuid():
            reviews.append(Review(path, "Firefox legacy target has an unexpected owner", True))
            continue
        if not safe_parent_chain(roots.home, path):
            reviews.append(Review(path, "Firefox legacy target traverses an unsafe parent", True))
            continue
        relative = safe_relative(path, firefox_root, "Firefox target")
        if path.name in FIREFOX_ASSETS:
            expected_hashes = {FIREFOX_ASSETS[path.name]}
            entry = firefox_manifest.get(path)
            if isinstance(entry, dict):
                manifest_hash = entry.get("sha256")
                if isinstance(manifest_hash, str) and re.fullmatch(r"[0-9a-f]{64}", manifest_hash):
                    expected_hashes.add(manifest_hash)
            if sha256_file(path) in expected_hashes:
                actions.append(
                    Action(
                        "archive",
                        path,
                        Path("firefox") / relative,
                        "verified Cassan-specific Firefox stylesheet",
                        current,
                    )
                )
            else:
                reviews.append(
                    Review(path, "Cassan-named stylesheet was edited locally; retained")
                )
            continue
        markers = FIREFOX_WRAPPERS.get(path.name)
        if markers is None:
            continue
        content = regular_bytes(path)
        try:
            replacement = remove_marker_block(content, *markers)
        except MigrationError as error:
            reviews.append(Review(path, str(error), True))
            continue
        if replacement is None:
            continue
        if not replacement:
            actions.append(
                Action(
                    "archive",
                    path,
                    Path("firefox") / relative,
                    "Firefox wrapper contained only Cassan's managed block",
                    current,
                )
            )
        else:
            actions.append(
                Action(
                    "rewrite",
                    path,
                    Path("firefox") / relative,
                    "remove Cassan's marked block and preserve all other content",
                    current,
                    replacement=replacement,
                    mode=stat.S_IMODE(os.lstat(str(path)).st_mode),
                )
            )
    add_known_atomic_temporaries(
        actions,
        reviews,
        firefox_root,
        roots.home,
        Path("firefox-temporaries"),
        tuple(FIREFOX_ASSETS) + tuple(FIREFOX_WRAPPERS),
        recursive=True,
    )

    old_spicetify = roots.home / ".spicetify" / "spicetify"
    spicetify_observation = observation(old_spicetify)
    if spicetify_observation[0] == "file":
        if spicetify_observation[5] != os.geteuid():
            reviews.append(Review(old_spicetify, "binary has an unexpected owner", True))
        elif not safe_parent_chain(roots.home, old_spicetify):
            reviews.append(Review(old_spicetify, "path traverses an unsafe parent", True))
        elif sha256_file(old_spicetify) == LEGACY_SPICETIFY_SHA256:
            actions.append(
                Action(
                    "archive",
                    old_spicetify,
                    Path("home/.spicetify/spicetify"),
                    "exact Cassan-pinned Spicetify 2.44.0 binary",
                    spicetify_observation,
                )
            )
        else:
            reviews.append(
                Review(
                    old_spicetify,
                    "not the Cassan-pinned binary; retained as user-owned",
                )
            )
    elif spicetify_observation[0] not in ("missing",):
        reviews.append(Review(old_spicetify, "unexpected path type; retained"))
    add_known_atomic_temporaries(
        actions,
        reviews,
        roots.home / ".spicetify",
        roots.home,
        Path("home/.spicetify/temporaries"),
        ("spicetify",),
    )

    add_archive(
        actions,
        reviews,
        roots.xdg_config / "spicetify" / "Themes" / "Cassan-Nighthowler",
        roots.xdg_config,
        Path("xdg-config/spicetify/Themes/Cassan-Nighthowler"),
        "old Cassan Spicetify theme directory",
    )

    # A successful Cassan Spotify activation left both Spicetify state and a
    # patched spotify-launcher installation outside XDG_CONFIG_HOME. Resetting
    # the entire regenerable install avoids treating already-patched files as
    # a pristine backup when the new theme is applied.
    old_spicetify_config = roots.xdg_config / "spicetify" / "config-xpui.ini"
    config_observation = observation(old_spicetify_config)
    if config_observation[0] == "file":
        if config_observation[5] != os.geteuid() or not safe_parent_chain(
            roots.xdg_config, old_spicetify_config
        ):
            reviews.append(
                Review(
                    old_spicetify_config,
                    "path was not created by Cassan's copy-based installer; retained",
                )
            )
        else:
            try:
                config_text = regular_bytes(old_spicetify_config).decode("utf-8")
            except UnicodeDecodeError:
                reviews.append(
                    Review(
                        old_spicetify_config,
                        "Spicetify configuration is not UTF-8 text",
                        True,
                    )
                )
            else:
                theme_selected = re.search(
                    r"(?mi)^\s*current_theme\s*=\s*Cassan-Nighthowler\s*$",
                    config_text,
                )
                scheme_selected = re.search(
                    r"(?mi)^\s*color_scheme\s*=\s*Nighthowler\s*$",
                    config_text,
                )
                if theme_selected and scheme_selected:
                    add_archive(
                        actions,
                        reviews,
                        roots.home
                        / ".local"
                        / "share"
                        / "spotify-launcher"
                        / "install",
                        roots.home,
                        Path("home/.local/share/spotify-launcher/install"),
                        "spotify-launcher installation patched by the old Cassan theme",
                    )
                    if roots.state_base == roots.xdg_config:
                        for state_name in ("Backup", "Extracted"):
                            add_archive(
                                actions,
                                reviews,
                                roots.state_base / "spicetify" / state_name,
                                roots.state_base,
                                Path("state/spicetify") / state_name,
                                "Spicetify backup state associated with the old Cassan theme",
                            )
                    else:
                        add_archive(
                            actions,
                            reviews,
                            roots.state_base / "spicetify",
                            roots.state_base,
                            Path("state/spicetify"),
                            "Spicetify backup state associated with the old Cassan theme",
                        )
                    add_archive(
                        actions,
                        reviews,
                        old_spicetify_config,
                        roots.xdg_config,
                        Path("xdg-config/spicetify/config-xpui.ini"),
                        "machine configuration selecting the old Cassan theme",
                    )
                elif (
                    theme_selected
                    or scheme_selected
                    or re.search(r"Cassan-Nighthowler|Nighthowler", config_text, re.I)
                ):
                    reviews.append(
                        Review(
                            old_spicetify_config,
                            "partial Cassan Spotify selection requires manual review",
                            True,
                        )
                    )
    elif config_observation[0] != "missing":
        reviews.append(
            Review(old_spicetify_config, "unexpected path type; retained")
        )
    add_known_atomic_temporaries(
        actions,
        reviews,
        roots.xdg_config / "spicetify",
        roots.xdg_config,
        Path("xdg-config/spicetify/temporaries"),
        ("config-xpui.ini",),
    )

    # Move state last: the preceding checks use its ownership manifests.
    add_archive(
        actions,
        reviews,
        roots.legacy_state,
        roots.state_base,
        Path("state/cassan"),
        "old deployment manifests and transaction backups",
    )
    actions = collapse_covered_actions(actions)
    for action in actions:
        if overlaps(action.path, roots.backup_root):
            reviews.append(
                Review(
                    action.path,
                    "legacy backup directory overlaps this migration source",
                    True,
                )
            )
    return actions, reviews


def print_plan(actions: Iterable[Action], reviews: Iterable[Review]) -> None:
    actions = list(actions)
    reviews = list(reviews)
    print("Legacy Cassan migration plan:")
    for action in actions:
        verb = "EDIT" if action.kind == "rewrite" else "ARCHIVE"
        print(f"  {verb:7} {action.path} — {action.detail}")
    for review in reviews:
        verb = "CONFLICT" if review.blocking else "KEEP"
        print(f"  {verb:7} {review.path} — {review.detail}")
    print(
        f"Summary: {len(actions)} backed-up change(s), "
        f"{sum(review.blocking for review in reviews)} conflict(s), "
        f"{sum(not review.blocking for review in reviews)} retained item(s)"
    )


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.migration-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fchmod(target.fileno(), mode)
            os.fsync(target.fileno())
        os.replace(str(temporary), str(path))
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_manifest(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        path,
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        0o600,
    )


def action_manifest(action: Action) -> dict[str, object]:
    value: dict[str, object] = {
        "action": action.kind,
        "source": str(action.path),
        "backup": str(action.backup_relative),
        "detail": action.detail,
        "before": list(action.observed),
    }
    if action.observed[0] == "file":
        value["sha256"] = sha256_file(action.path)
    return value


def restore_action(action: Action, backup_dir: Path) -> None:
    backup = backup_dir / action.backup_relative
    if action.kind == "rewrite":
        content = regular_bytes(backup)
        current = regular_bytes(action.path)
        current_mode = stat.S_IMODE(os.lstat(str(action.path)).st_mode)
        expected_mode = action.mode if action.mode is not None else 0o644
        if current == content and current_mode == expected_mode:
            return
        if current != action.replacement or current_mode != expected_mode:
            raise MigrationError(f"cannot roll back over a concurrent change: {action.path}")
        atomic_write(action.path, content, expected_mode)
        return
    if os.path.lexists(str(action.path)):
        raise MigrationError(f"cannot roll back over a new path: {action.path}")
    action.path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(backup), str(action.path))


def apply_plan(roots: Roots, actions: list[Action], reviews: list[Review]) -> Optional[Path]:
    conflicts = [review for review in reviews if review.blocking]
    if conflicts:
        raise MigrationError("resolve the listed conflicts before applying the migration")
    if not actions:
        print("No legacy Cassan files require migration.")
        return None

    spotify_install = roots.home / ".local" / "share" / "spotify-launcher" / "install"
    if any(action.path == spotify_install for action in actions) and spotify_process_running():
        raise MigrationError("fully close Spotify and spotify-launcher before migrating")

    ensure_private_backup_root(roots)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = Path(tempfile.mkdtemp(prefix=f"{stamp}.", dir=roots.backup_root))
    os.chmod(backup_dir, 0o700)
    manifest_path = backup_dir / "migration.json"
    manifest = {
        "schema": 1,
        "status": "preparing",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "nonce": secrets.token_hex(8),
        "actions": [action_manifest(action) for action in actions],
        "retained": [
            {"path": str(review.path), "detail": review.detail}
            for review in reviews
            if not review.blocking
        ],
    }
    write_manifest(manifest_path, manifest)

    applied: list[Action] = []
    try:
        for action in actions:
            if observation(action.path) != action.observed:
                raise MigrationError(f"legacy target changed after planning: {action.path}")
            backup = backup_dir / action.backup_relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            if action.kind == "rewrite":
                shutil.copy2(action.path, backup, follow_symlinks=False)
                if sha256_file(backup) != sha256_file(action.path):
                    raise MigrationError(f"could not verify migration backup: {action.path}")
                applied.append(action)
                assert action.replacement is not None
                atomic_write(
                    action.path,
                    action.replacement,
                    action.mode if action.mode is not None else 0o644,
                )
                if regular_bytes(action.path) != action.replacement:
                    raise MigrationError(f"could not verify migrated wrapper: {action.path}")
            else:
                before_hash = (
                    sha256_file(action.path) if action.observed[0] == "file" else None
                )
                shutil.move(str(action.path), str(backup))
                applied.append(action)
                if os.path.lexists(str(action.path)):
                    raise MigrationError(f"legacy target remained after archival: {action.path}")
                backup_observation = observation(backup)
                if backup_observation[0] != action.observed[0]:
                    raise MigrationError(f"archived target changed type: {action.path}")
                if before_hash is not None and sha256_file(backup) != before_hash:
                    raise MigrationError(f"could not verify archived file: {action.path}")
        manifest["status"] = "completed"
        manifest["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        write_manifest(manifest_path, manifest)
    except BaseException as original_error:
        rollback_errors: list[str] = []
        for action in reversed(applied):
            try:
                restore_action(action, backup_dir)
            except BaseException as rollback_error:
                rollback_errors.append(f"{action.path}: {rollback_error}")
        manifest["status"] = "rolled-back" if not rollback_errors else "rollback-incomplete"
        manifest["error"] = str(original_error)
        manifest["rollback_errors"] = rollback_errors
        write_manifest(manifest_path, manifest)
        if rollback_errors:
            raise MigrationError(
                f"migration failed and rollback was incomplete; inspect {backup_dir}"
            ) from original_error
        raise MigrationError("migration failed and was rolled back") from original_error
    return backup_dir


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or apply backup-first cleanup of the former Cassan setup."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="apply the displayed plan; the default is a read-only preview",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        roots = Roots.from_environ()
        actions, reviews = build_plan(roots)
        print_plan(actions, reviews)
        if any(review.blocking for review in reviews):
            print("Nothing was changed because manual review is required.", file=sys.stderr)
            return 2
        if not arguments.apply:
            print("Preview only; no files were changed. Re-run with --apply to continue.")
            return 0
        backup = apply_plan(roots, actions, reviews)
        if backup is not None:
            print(f"Legacy Cassan backup: {backup}")
        for review in reviews:
            if not review.blocking:
                print(f"Retained for safety: {review.path} ({review.detail})")
        return 0
    except (MigrationError, OSError) as error:
        print(f"Legacy Cassan migration failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
