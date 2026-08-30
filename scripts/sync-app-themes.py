#!/usr/bin/env python3

import argparse
import configparser
from contextlib import contextmanager
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BEGIN = "/* hyprland-dots palette: begin */"
END = "/* hyprland-dots palette: end */"
COLOR_KEYS = {
    "background", "panel", "panel_alt", "text", "text_secondary",
    "text_muted", "disabled", "border", "focus", "focus_alt", "blue",
    "purple", "green", "urgent",
}


def atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"refusing to replace a non-regular file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def backup(path: Path, state: Path) -> Path:
    parent = state / "app-theme-backups"
    parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="vesktop-", dir=parent))
    destination = directory / path.name
    if path.is_symlink():
        destination.symlink_to(os.readlink(path))
    else:
        shutil.copy2(path, destination)
        destination.chmod(0o600)
    return destination


def prepare_vesktop(config: Path, state: Path, template: Path = ROOT / "vesktop") -> None:
    for query in (
        ["pgrep", "-i", "-x", "vesktop"],
        ["pgrep", "-f", r"(^|[[:space:]])/usr/lib/vesktop/app\.asar([[:space:]]|$)"],
    ):
        running = subprocess.run(query, capture_output=True, timeout=5, check=False)
        if running.returncode == 0:
            raise ValueError("close Vesktop before installing its live-theme integration")
        if running.returncode != 1:
            raise ValueError("could not verify that Vesktop is closed")

    destination = config / "vesktop"
    if destination.is_symlink() and destination.resolve() != template.resolve():
        raise ValueError(f"refusing to replace a custom Vesktop symlink: {destination}")
    if destination.exists() and not destination.is_dir():
        raise ValueError(f"Vesktop configuration is not a directory: {destination}")
    if destination.is_symlink() or not destination.exists():
        config.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".vesktop-stage-", dir=config))
        previous = None
        try:
            shutil.copytree(template, staging, dirs_exist_ok=True, symlinks=True)
            staging.chmod(0o700)
            if destination.is_symlink():
                previous = backup(destination, state)
                destination.unlink()
            try:
                os.replace(staging, destination)
            except BaseException:
                if previous is not None:
                    destination.symlink_to(os.readlink(previous))
                raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    settings_dir = destination / "settings"
    if settings_dir.is_symlink():
        raise ValueError("Vesktop settings must be a real runtime directory")
    settings_file = settings_dir / "settings.json"
    if settings_file.is_symlink():
        raise ValueError("Vesktop settings.json must not be a symlink")
    if settings_file.exists() and not settings_file.is_file():
        raise ValueError("Vesktop settings.json must be a regular file")
    settings = {}
    if settings_file.exists():
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        raise ValueError("Vesktop settings must contain a JSON object")
    if settings.get("useQuickCss") is not True:
        if settings_file.exists():
            backup(settings_file, state)
        settings["useQuickCss"] = True
        atomic_write(settings_file, (json.dumps(settings, indent=4) + "\n").encode())


def merge_quick_css(existing: str, palette: str) -> str:
    if existing.count(BEGIN) != existing.count(END) or existing.count(BEGIN) > 1:
        raise ValueError("QuickCSS contains an incomplete or duplicate managed palette block")
    block = f"{BEGIN}\n{palette.rstrip()}\n{END}"
    if BEGIN in existing:
        start = existing.index(BEGIN)
        finish = existing.index(END)
        if finish < start:
            raise ValueError("QuickCSS palette markers are out of order")
        return existing[:start] + block + existing[finish + len(END):]
    separator = "" if not existing or existing.endswith("\n\n") else "\n"
    return existing + separator + block + "\n"


def sync_vesktop(config: Path, state: Path, palette: str) -> bool:
    root = config / "vesktop"
    if not root.exists():
        return False
    if root.is_symlink() or (root / "settings").is_symlink():
        raise ValueError("rerun the installer to separate Vesktop runtime settings from the repository")
    path = root / "settings/quickCss.css"
    if path.is_symlink():
        raise ValueError("refusing to overwrite a symlinked Vesktop QuickCSS file")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "r+", encoding="utf-8") as handle:
        snapshot = os.fstat(handle.fileno())
        if not stat.S_ISREG(snapshot.st_mode):
            raise ValueError("Vesktop QuickCSS is not a regular file")
        existing = handle.read()
        updated = merge_quick_css(existing, palette)
        if existing == updated:
            return True
        atomic_write(state / "app-theme-backups/quickCss.previous.css", existing.encode())
        # Best-effort conflict detection: editors do not share our lock.
        handle.seek(0)
        unchanged = handle.read() == existing
        current = os.fstat(handle.fileno())
        live = path.lstat()
        if (
            not unchanged
            or not stat.S_ISREG(live.st_mode)
            or any(
                getattr(candidate, field) != getattr(snapshot, field)
                for candidate in (current, live)
                for field in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            )
        ):
            raise ValueError("Vesktop QuickCSS changed during theme sync; retry after saving the file")
        # Vencord watches this inode, so replace only its contents.
        handle.seek(0)
        handle.write(updated)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
    return True


def validate_spotify_palette(content: bytes) -> dict:
    if len(content) > 4096:
        raise ValueError("Spotify palette is unexpectedly large")
    palette = json.loads(content)
    if (
        not isinstance(palette, dict)
        or set(palette) != {"schema", "theme", "colors"}
        or type(palette.get("schema")) is not int
        or palette["schema"] != 1
        or not isinstance(palette.get("theme"), str)
        or palette["theme"] not in {"after-school", "reze"}
    ):
        raise ValueError("Spotify palette has an unknown schema or theme")
    colors = palette.get("colors")
    if not isinstance(colors, dict) or set(colors) != COLOR_KEYS:
        raise ValueError("Spotify palette has an unexpected color set")
    if any(not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value)
           for value in colors.values()):
        raise ValueError("Spotify palette contains an invalid color")
    return palette


def sync_spotify(config: Path, home: Path, content: bytes) -> bool:
    validate_spotify_palette(content)
    spotify = home / ".local/share/spotify-launcher/install/usr/share/spotify"
    settings = config / "spicetify/config-xpui.ini"
    if settings.is_file():
        parser = configparser.ConfigParser(delimiters=("=",), interpolation=None)
        parser.read(settings, encoding="utf-8")
        configured = parser.get("Setting", "spotify_path", fallback="").strip()
        if len(configured) > 1 and configured[0] == configured[-1] and configured[0] in {"'", '"'}:
            configured = configured[1:-1]
        if configured:
            spotify = Path(os.path.expandvars(configured)).expanduser()
            if not spotify.is_absolute():
                raise ValueError("Spicetify spotify_path must resolve to an absolute path")
    xpui = spotify / "Apps/xpui"
    if not xpui.is_dir() or not (xpui / "helper/spicetifyWrapper.js").is_file():
        return False
    managed = xpui.resolve() / "hyprland-dots"
    if managed.is_symlink():
        raise ValueError("refusing to publish through a symlinked Spotify palette directory")
    destination = managed / "palette.json"
    if destination.is_symlink():
        raise ValueError("refusing to overwrite a symlinked Spotify palette")
    if destination.exists() and not destination.is_file():
        raise ValueError("Spotify palette must be a regular file")
    if destination.exists():
        existing = destination.read_bytes()
        validate_spotify_palette(existing)
        if existing == content:
            return True
    atomic_write(destination, content, mode=0o644)
    return True


def update_firefox(cache: Path, home: Path) -> bool:
    manifest = home / ".mozilla/native-messaging-hosts/pywalfox.json"
    if manifest.is_symlink() or not manifest.is_file():
        return False
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    wrapper = data / "hyprland-dots/firefox/native-host.sh"
    try:
        settings = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if (
        not isinstance(settings, dict)
        or settings.get("name") != "pywalfox"
        or settings.get("type") != "stdio"
        or settings.get("path") != str(wrapper)
        or settings.get("allowed_extensions") != ["pywalfox@frewacom.org"]
        or not wrapper.is_file()
        or wrapper.is_symlink()
        or not os.access(wrapper, os.X_OK)
    ):
        return False
    environment = os.environ.copy()
    environment["XDG_CACHE_HOME"] = str(cache / "hyprland-dots/firefox")
    subprocess.run(
        [str(wrapper), "--update"], env=environment, capture_output=True,
        timeout=10, check=True,
    )
    return True


@contextmanager
def sync_lock(state: Path):
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(
        state / "app-theme-sync.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    with os.fdopen(descriptor, "a") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("application theme lock must be a regular file")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def sync_apps(args, home: Path, config: Path, cache: Path, state: Path) -> int:
    if args.install_vesktop:
        prepare_vesktop(config, state)
        return 0
    active_link = cache / "hyprland-dots/active-theme"
    if not (active_link / "spotify-palette.json").is_file():
        return 0
    active = active_link.resolve(strict=True)
    failed = False
    operations = (
        ("Vesktop", lambda: sync_vesktop(config, state, (active / "vesktop.css").read_text(encoding="utf-8"))),
        ("Spotify", lambda: sync_spotify(config, home, (active / "spotify-palette.json").read_bytes())),
        ("Firefox", lambda: update_firefox(cache, home)),
    )
    for name, operation in operations:
        try:
            available = operation()
            if args.verbose:
                result = "palette published"
                if name == "Firefox":
                    result = "update requested (delivery depends on the add-on)"
                if not available:
                    result = "one-time app setup not present; skipped"
                print(f"{name}: {result}")
        except (OSError, ValueError, configparser.Error, subprocess.SubprocessError) as error:
            failed = True
            print(f"warning: {name} theme sync: {error}", file=sys.stderr)
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-vesktop", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    cache = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    state = Path(os.environ.get("XDG_STATE_HOME") or home / ".local/state") / "hyprland-dots"
    if not all(path.is_absolute() for path in (home, config, cache, state)):
        raise ValueError("HOME and XDG paths must be absolute")
    with sync_lock(state):
        return sync_apps(args, home, config, cache, state)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"app-theme setup failed: {error}", file=sys.stderr)
        raise SystemExit(1)
