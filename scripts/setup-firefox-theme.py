#!/usr/bin/env python3

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


PYWALFOX_VERSION = "2.9.0"
ADDON_URL = "https://addons.mozilla.org/firefox/addon/pywalfox/"
ADDON_ID = "pywalfox@frewacom.org"


class SetupError(Exception):
    pass


@dataclass(frozen=True)
class Paths:
    wrapper: Path
    cache: Path
    palette: Path
    palette_source: Path
    manifest: Path
    backups: Path

    @classmethod
    def for_user(cls, home: Path | None = None, environ=None) -> Paths:
        home = Path.home() if home is None else home
        environ = os.environ if environ is None else environ

        def xdg(name, default):
            path = Path(environ.get(name) or default)
            if not path.is_absolute():
                raise SetupError(f"{name} must be an absolute path: {path}")
            return path

        cache_root = xdg("XDG_CACHE_HOME", home / ".cache") / "hyprland-dots"
        data_root = xdg("XDG_DATA_HOME", home / ".local/share") / "hyprland-dots"
        state_root = xdg("XDG_STATE_HOME", home / ".local/state") / "hyprland-dots"
        cache = cache_root / "firefox"
        return cls(
            wrapper=data_root / "firefox/native-host.sh",
            cache=cache,
            palette=cache / "wal/colors.json",
            palette_source=cache_root / "active-theme/pywalfox.json",
            manifest=home / ".mozilla/native-messaging-hosts/pywalfox.json",
            backups=state_root / "backups/firefox",
        )


def run_command(args, *, timeout=30):
    try:
        return subprocess.run(
            [str(arg) for arg in args], check=True, capture_output=True,
            text=True, timeout=timeout,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise SetupError(f"{args[0]} failed: {detail or exc.returncode}") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError(f"Could not run {args[0]}: {exc}") from exc


def lexists(path):
    return path.exists() or path.is_symlink()


def validate_leaf(path):
    if lexists(path) and not (path.is_symlink() or path.is_file()):
        raise SetupError(f"Refusing to replace a non-file: {path}")


def pywalfox_binary(*, install):
    pipx = shutil.which("pipx")
    if pipx is None:
        raise SetupError("pipx is missing; install the official python-pipx package first.")
    bin_dir = Path(run_command([pipx, "environment", "--value", "PIPX_BIN_DIR"]))
    if not bin_dir.is_absolute():
        raise SetupError(f"pipx returned a non-absolute binary directory: {bin_dir}")
    binary = bin_dir / "pywalfox"
    if not lexists(binary):
        if not install:
            raise SetupError("Pywalfox is not installed; run this helper without --check.")
        print(f"Installing user-local pywalfox=={PYWALFOX_VERSION} with pipx.")
        run_command([pipx, "install", f"pywalfox=={PYWALFOX_VERSION}"], timeout=300)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise SetupError(f"The pipx entry point is unavailable: {binary}")
    version = run_command([binary, "--version"])
    if version != f"v{PYWALFOX_VERSION}":
        raise SetupError(
            f"{binary} reports {version!r}, expected v{PYWALFOX_VERSION}. "
            "The existing installation was left unchanged; review it with pipx "
            "before replacing or upgrading it."
        )
    return binary


def wrapper_text(paths, binary):
    return (
        "#!/bin/sh\n"
        "# Managed by hyprland-dots: Firefox native messaging only.\n"
        f"export XDG_CACHE_HOME={shlex.quote(str(paths.cache))}\n"
        'if [ "${1-}" = "--update" ]; then\n'
        f"    exec {shlex.quote(str(binary))} update\n"
        "fi\n"
        f"exec {shlex.quote(str(binary))} start --profile-path "
        f"{shlex.quote(str(paths.cache / 'profile-access-disabled'))}\n"
    )


def manifest_matches(paths):
    try:
        if paths.manifest.is_symlink() or not paths.manifest.is_file():
            return False
        data = json.loads(paths.manifest.read_text(encoding="utf-8"))
        return (
            data.get("name") == "pywalfox"
            and data.get("path") == str(paths.wrapper)
            and data.get("type") == "stdio"
            and data.get("allowed_extensions") == [ADDON_ID]
        )
    except (OSError, ValueError, AttributeError):
        return False


def wrapper_matches(paths, binary):
    try:
        return (
            not paths.wrapper.is_symlink()
            and paths.wrapper.is_file()
            and paths.wrapper.read_text(encoding="utf-8") == wrapper_text(paths, binary)
            and paths.wrapper.stat().st_mode & 0o777 == 0o700
        )
    except (OSError, UnicodeError):
        return False


def palette_matches(paths):
    return paths.palette.is_symlink() and os.readlink(paths.palette) == str(paths.palette_source)


def atomic_copy(source, target):
    with tempfile.TemporaryDirectory(prefix=".firefox-theme-", dir=target.parent) as temporary:
        staged = Path(temporary) / "file"
        shutil.copy2(source, staged, follow_symlinks=False)
        os.replace(staged, target)


class Transaction:
    def __init__(self, paths):
        self.paths = paths
        self.directory = None
        self.originals = []

    def remember(self, path, name):
        validate_leaf(path)
        saved = None
        if lexists(path):
            if self.directory is None:
                self.paths.backups.mkdir(parents=True, exist_ok=True, mode=0o700)
                prefix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
                self.directory = Path(tempfile.mkdtemp(prefix=prefix, dir=self.paths.backups))
                print(f"Firefox helper backups: {self.directory}")
            saved = self.directory / name
            shutil.copy2(path, saved, follow_symlinks=False)
        self.originals.append((path, saved))

    def rollback(self):
        failures = []
        for path, saved in reversed(self.originals):
            try:
                validate_leaf(path)
                if saved is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_copy(saved, path)
            except OSError as exc:
                failures.append(f"{path}: {exc}")
            except SetupError as exc:
                failures.append(str(exc))
        if failures:
            raise SetupError("Rollback needs attention; backups retained: " + "; ".join(failures))


@contextmanager
def setup_lock(paths):
    paths.wrapper.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = paths.wrapper.parent / "setup.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def setup_host(paths, binary):
    for path in (paths.wrapper, paths.palette, paths.manifest):
        validate_leaf(path)
    paths.palette.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    transaction = Transaction(paths)
    try:
        if not wrapper_matches(paths, binary):
            transaction.remember(paths.wrapper, "native-host.sh")
            with tempfile.TemporaryDirectory(prefix=".firefox-theme-", dir=paths.wrapper.parent) as temporary:
                staged = Path(temporary) / "native-host.sh"
                staged.write_text(wrapper_text(paths, binary), encoding="utf-8")
                staged.chmod(0o700)
                os.replace(staged, paths.wrapper)
        if not palette_matches(paths):
            transaction.remember(paths.palette, "colors.json")
            with tempfile.TemporaryDirectory(prefix=".firefox-theme-", dir=paths.palette.parent) as temporary:
                staged = Path(temporary) / "colors.json"
                staged.symlink_to(paths.palette_source)
                os.replace(staged, paths.palette)
        if not manifest_matches(paths):
            transaction.remember(paths.manifest, "pywalfox.json")
            # Upstream follows a dangling manifest symlink when copying its template.
            paths.manifest.unlink(missing_ok=True)
            run_command([binary, "install", "--executable", paths.wrapper])
            if not manifest_matches(paths):
                raise SetupError("Pywalfox did not install the expected per-user native manifest.")
    except (SetupError, OSError) as exc:
        transaction.rollback()
        raise SetupError(f"Firefox helper setup failed; previous files restored. {exc}") from exc


def palette_errors(paths):
    if not paths.palette.is_file():
        return [f"The active Firefox palette is missing or not a regular file: {paths.palette_source}"]
    try:
        data = json.loads(paths.palette.read_text(encoding="utf-8"))
        colors = data.get("colors")
        if not isinstance(data.get("wallpaper"), str):
            return ["The Firefox palette needs a wallpaper string."]
        if not isinstance(colors, dict) or list(colors) != [f"color{i}" for i in range(16)]:
            return ["The Firefox palette must contain color0 through color15 in numeric insertion order."]
        if any(not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value)
               for value in colors.values()):
            return ["The Firefox palette contains a color that is not #RRGGBB."]
    except (OSError, ValueError, AttributeError) as exc:
        return [f"The active Firefox palette is not ready: {paths.palette_source} ({exc})"]
    return []


def check_host(paths, binary):
    errors = []
    if not wrapper_matches(paths, binary):
        errors.append(f"The native wrapper is missing or outdated: {paths.wrapper}")
    if not palette_matches(paths):
        errors.append(f"The managed palette link is missing or outdated: {paths.palette}")
    if not manifest_matches(paths):
        errors.append(f"The per-user native manifest is missing or outdated: {paths.manifest}")
    return errors + palette_errors(paths)


def print_next_steps():
    print(f"In Firefox, install the signed Pywalfox add-on yourself: {ADDON_URL}")
    print("Review its permissions: native messaging, browser tabs, and duckduckgo.com access.")
    print("Restart Firefox once, open Pywalfox, select Dark, and choose Fetch Pywal colors.")
    print("Keep Fetch on startup enabled. Optional userChrome/userContent CSS modifications are disabled.")
    print("No Firefox profiles or user.js files were edited, and no add-on was installed automatically.")
    print("A successful pywalfox update command alone does not prove Firefox received the colors.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Set up per-user, wallpaper-aware Firefox theming.")
    parser.add_argument("--check", action="store_true", help="check local setup without installing or changing it")
    args = parser.parse_args(argv)
    try:
        if not sys.platform.startswith("linux"):
            raise SetupError("This helper targets the native Firefox package on Linux, not Flatpak or Snap.")
        if os.geteuid() == 0:
            raise SetupError("Run this helper as your normal desktop user, without sudo.")
        paths = Paths.for_user()
        if args.check:
            binary = pywalfox_binary(install=False)
            errors = check_host(paths, binary)
            if errors:
                raise SetupError("\n".join(errors))
            print("Local native helper and active palette checks passed; add-on consent and live delivery are not checked.")
        else:
            for path in (paths.wrapper, paths.palette, paths.manifest):
                validate_leaf(path)
            with setup_lock(paths):
                binary = pywalfox_binary(install=True)
                setup_host(paths, binary)
            print("The per-user Firefox native theme helper is configured.")
            for warning in palette_errors(paths):
                print(f"warning: {warning}", file=sys.stderr)
        print_next_steps()
        return 0
    except (SetupError, OSError) as exc:
        print(f"Firefox theme setup: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
