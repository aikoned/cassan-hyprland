#!/usr/bin/env python3

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parent.parent
SLUGS = {"after-school", "reze"}
LABELS = {"after-school": "After School Stroll", "reze": "Reze"}
WATCH_INTERVAL = 30.0
WATCH_TIMEOUT = 30.0


class ScheduleError(Exception):
    pass


@dataclass(frozen=True)
class State:
    mode: str = "auto"
    selected: str = ""


@dataclass(frozen=True)
class Schedule:
    day_start: int
    night_start: int

    def target(self, local_time: dt.datetime) -> str:
        minute = local_time.hour * 60 + local_time.minute
        if self.day_start < self.night_start:
            daytime = self.day_start <= minute < self.night_start
        else:
            daytime = minute >= self.day_start or minute < self.night_start
        return "after-school" if daytime else "reze"


def xdg_path(name: str, fallback: str, environ: Mapping[str, str]) -> Path:
    value = environ.get(name)
    if not value:
        home = environ.get("HOME")
        if not home:
            raise ScheduleError("HOME must be set")
        value = str(Path(home) / fallback)
    path = Path(value)
    if not path.is_absolute():
        raise ScheduleError(f"{name} must be an absolute path")
    return path


def state_path(environ: Mapping[str, str] | None = None) -> Path:
    values = os.environ if environ is None else environ
    return (
        xdg_path("XDG_STATE_HOME", ".local/state", values)
        / "hyprland-dots/theme-schedule.json"
    )


def validate_state(value: object) -> State:
    if not isinstance(value, dict) or set(value) != {"mode", "selected"}:
        raise ScheduleError("schedule state must contain only mode and selected")
    mode = value["mode"]
    selected = value["selected"]
    if not isinstance(mode, str) or mode not in {"auto", "manual"}:
        raise ScheduleError("schedule state mode must be auto or manual")
    if not isinstance(selected, str) or selected not in SLUGS | {""}:
        raise ScheduleError("schedule state has an unrecognized wallpaper")
    if mode == "manual" and not selected:
        raise ScheduleError("manual schedule state must remember a wallpaper")
    return State(mode, selected)


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ScheduleError(f"duplicate schedule state key: {key}")
        value[key] = item
    return value


def read_state(path: Path) -> State:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        )
    except FileNotFoundError:
        if path.is_symlink():
            raise ScheduleError(f"refusing symlinked schedule state: {path}")
        return State()
    except OSError as error:
        raise ScheduleError(f"cannot read schedule state {path}: {error.strerror}") from error
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
            raise ScheduleError(f"schedule state is not a small regular file: {path}")
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
            return validate_state(json.load(handle, object_pairs_hook=unique_object))
    except (ValueError, UnicodeError, OSError) as error:
        raise ScheduleError(f"invalid schedule state {path}: {error}") from error
    finally:
        os.close(descriptor)


def write_state(path: Path, state: State) -> None:
    value = {"mode": state.mode, "selected": state.selected}
    validate_state(value)
    read_state(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".theme-schedule.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(value, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_clock(value: object, name: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value
    ):
        raise ScheduleError(f"{name} must use 24-hour HH:MM format")
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def read_schedule(environ: Mapping[str, str] | None = None) -> Schedule:
    values = os.environ if environ is None else environ
    override = (
        xdg_path("XDG_CONFIG_HOME", ".config", values)
        / "hyprland-dots/schedule.toml"
    )
    path = override if os.path.lexists(override) else ROOT / "themes/schedule.toml"
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, ValueError) as error:
        raise ScheduleError(f"cannot read wallpaper schedule {path}: {error}") from error
    if set(value) != {"day_start", "night_start"}:
        raise ScheduleError("wallpaper schedule must contain only day_start and night_start")
    day = parse_clock(value["day_start"], "day_start")
    night = parse_clock(value["night_start"], "night_start")
    if day == night:
        raise ScheduleError("day_start and night_start must be different")
    return Schedule(day, night)


def local_now(timestamp: float | None = None) -> dt.datetime:
    if timestamp is None:
        return dt.datetime.now().astimezone()
    return dt.datetime.fromtimestamp(timestamp).astimezone()


def clock_label(minute: int) -> str:
    hour, minute = divmod(minute, 60)
    return f"{hour:02d}:{minute:02d}"


def status(state: State, schedule: Schedule) -> dict[str, str]:
    day = clock_label(schedule.day_start)
    night = clock_label(schedule.night_start)
    selected = LABELS.get(state.selected, "not selected yet")
    description = (
        "Automatic wallpaper schedule"
        if state.mode == "auto"
        else "Manual wallpaper — stays fixed until you change it"
    )
    return {
        "text": "AUTO" if state.mode == "auto" else "MAN",
        "alt": state.mode,
        "class": state.mode,
        "tooltip": (
            f"{description}\n"
            f"After School Stroll: {day}–{night}\n"
            f"Reze: {night}–{day}\n"
            f"Laptop local time; scheduled now: {LABELS[schedule.target(local_now())]}\n"
            f"Selected: {selected}"
        ),
    }


@dataclass(frozen=True)
class Session:
    socket: Path
    device: int
    inode: int
    identity: str

    def alive(self) -> bool:
        try:
            info = self.socket.stat()
        except OSError:
            return False
        return (
            stat.S_ISSOCK(info.st_mode)
            and info.st_dev == self.device
            and info.st_ino == self.inode
        )


def inherited_session(environ: Mapping[str, str]) -> Session | None:
    runtime = environ.get("XDG_RUNTIME_DIR", "")
    display = environ.get("WAYLAND_DISPLAY", "")
    signature = environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    if not runtime or not display or not signature or not Path(runtime).is_absolute():
        return None
    socket = Path(display)
    if not socket.is_absolute():
        socket = Path(runtime) / socket
    try:
        info = socket.stat()
    except OSError:
        return None
    if not stat.S_ISSOCK(info.st_mode):
        return None
    identity = hashlib.sha256(
        f"{signature}\0{socket}\0{info.st_dev}\0{info.st_ino}".encode()
    ).hexdigest()[:24]
    return Session(socket, info.st_dev, info.st_ino, identity)


def watch(environ: Mapping[str, str] | None = None) -> int:
    values = dict(os.environ if environ is None else environ)
    session = inherited_session(values)
    if session is None:
        return 0
    runtime = Path(values["XDG_RUNTIME_DIR"]) / "hyprland-dots"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = runtime / f"theme-schedule-{session.identity}.lock"
    descriptor = os.open(
        lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ScheduleError(f"watcher lock is not a regular file: {lock_path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        while session.alive():
            try:
                result = subprocess.run(
                    [str(ROOT / "waybar/scripts/theme-switcher.sh"), "scheduled"],
                    env=values,
                    close_fds=True,
                    check=False,
                    timeout=WATCH_TIMEOUT,
                )
                if result.returncode:
                    print(
                        f"wallpaper schedule check failed ({result.returncode}); retrying",
                        file=sys.stderr,
                    )
            except subprocess.TimeoutExpired:
                print(
                    f"wallpaper schedule check timed out after {WATCH_TIMEOUT:g}s; retrying",
                    file=sys.stderr,
                )
            except OSError as error:
                print(f"cannot run wallpaper schedule check: {error}", file=sys.stderr)
            time.sleep(WATCH_INTERVAL)
        return 0
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("mode", "selected", "target", "enable", "status", "watch"):
        commands.add_parser(command)
    for command in ("remember", "manual", "automatic"):
        commands.add_parser(command).add_argument("slug", choices=sorted(SLUGS))
    args = parser.parse_args(argv)
    try:
        if args.command == "watch":
            return watch()
        if args.command == "target":
            print(read_schedule().target(local_now()))
            return 0
        path = state_path()
        state = read_state(path)
        if args.command == "mode":
            print(state.mode)
        elif args.command == "selected":
            print(state.selected)
        elif args.command == "status":
            print(json.dumps(status(state, read_schedule()), ensure_ascii=False))
        elif args.command == "remember":
            write_state(path, State(state.mode, args.slug))
        elif args.command == "manual":
            write_state(path, State("manual", args.slug))
        elif args.command == "automatic":
            write_state(path, State("auto", args.slug))
        elif args.command == "enable":
            write_state(path, State("auto", state.selected))
        return 0
    except (ScheduleError, OSError) as error:
        if args.command == "status":
            print(json.dumps({"text": "ERR", "class": "error", "tooltip": str(error)}))
        print(f"theme schedule: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
