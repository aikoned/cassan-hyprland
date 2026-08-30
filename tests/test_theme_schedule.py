#!/usr/bin/env python3

import contextlib
import datetime as dt
import fcntl
import importlib.util
import io
import json
import os
import pathlib
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/theme-schedule.py"
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("theme_schedule", SCRIPT)
schedule = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = schedule
SPEC.loader.exec_module(schedule)


class ThemeScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.environment = {
            "HOME": str(self.root / "home"),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_RUNTIME_DIR": str(self.root / "run"),
        }
        self.state = schedule.state_path(self.environment)

    def cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            env={**os.environ, **self.environment},
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )

    def local_time(self, hour: int, minute: int = 0, second: int = 0) -> dt.datetime:
        return dt.datetime(2026, 8, 29, hour, minute, second)

    def test_default_schedule_all_hours_and_boundaries(self) -> None:
        configured = schedule.read_schedule(self.environment)
        self.assertEqual(configured, schedule.Schedule(8 * 60, 20 * 60))
        for hour in range(24):
            with self.subTest(hour=hour):
                expected = "after-school" if 8 <= hour < 20 else "reze"
                self.assertEqual(configured.target(self.local_time(hour)), expected)
        for moment, expected in (
            (self.local_time(7, 59, 59), "reze"),
            (self.local_time(8), "after-school"),
            (self.local_time(19, 59, 59), "after-school"),
            (self.local_time(20), "reze"),
            (self.local_time(23, 59, 59), "reze"),
            (self.local_time(0), "reze"),
        ):
            with self.subTest(moment=moment):
                self.assertEqual(configured.target(moment), expected)

    def test_wrapped_interval_and_minute_boundaries(self) -> None:
        configured = schedule.Schedule(20 * 60 + 30, 8 * 60 + 15)
        for moment, expected in (
            (self.local_time(20, 29, 59), "reze"),
            (self.local_time(20, 30), "after-school"),
            (self.local_time(23), "after-school"),
            (self.local_time(0), "after-school"),
            (self.local_time(8, 14, 59), "after-school"),
            (self.local_time(8, 15), "reze"),
            (self.local_time(12), "reze"),
        ):
            with self.subTest(moment=moment):
                self.assertEqual(configured.target(moment), expected)

    def test_clock_parser_rejects_invalid_values(self) -> None:
        self.assertEqual(schedule.parse_clock("08:09", "time"), 489)
        for value in ("8:00", "24:00", "08:60", "-1:00", "00:00:00", 8, None, ""):
            with self.subTest(value=value), self.assertRaises(schedule.ScheduleError):
                schedule.parse_clock(value, "time")

    def test_user_configuration_overrides_repo_defaults(self) -> None:
        path = self.root / "config/hyprland-dots/schedule.toml"
        path.parent.mkdir(parents=True)
        path.write_text('day_start = "07:30"\nnight_start = "22:15"\n')
        configured = schedule.read_schedule(self.environment)
        self.assertEqual(configured, schedule.Schedule(450, 1335))
        self.assertEqual(configured.target(self.local_time(7, 30)), "after-school")
        self.assertEqual(configured.target(self.local_time(22, 15)), "reze")

    def test_bad_override_is_not_silently_replaced_with_defaults(self) -> None:
        path = self.root / "config/hyprland-dots/schedule.toml"
        path.parent.mkdir(parents=True)
        for content in (
            'day_start = "08:00"\nnight_start = "08:00"\n',
            'day_start = "08:00"\n',
            'day_start = "08:00"\nnight_start = "20:00"\nextra = true\n',
            'day_start = "invalid"\nnight_start = "20:00"\n',
            "this is not TOML",
        ):
            path.write_text(content)
            with self.subTest(content=content), self.assertRaises(schedule.ScheduleError):
                schedule.read_schedule(self.environment)
            self.assertEqual(path.read_text(), content)
        path.unlink()
        path.symlink_to(path.parent / "missing.toml")
        with self.assertRaises(schedule.ScheduleError):
            schedule.read_schedule(self.environment)

    @unittest.skipUnless(hasattr(time, "tzset"), "requires local timezone control")
    def test_local_clock_uses_laptop_timezone(self) -> None:
        timestamp = dt.datetime(2026, 8, 29, 12, tzinfo=dt.timezone.utc).timestamp()
        configured = schedule.Schedule(480, 1200)
        previous = os.environ.get("TZ")
        try:
            for timezone, hour, expected in (
                ("UTC0", 12, "after-school"),
                ("EST5", 7, "reze"),
                ("JST-9", 21, "reze"),
            ):
                os.environ["TZ"] = timezone
                time.tzset()
                moment = schedule.local_now(timestamp)
                self.assertEqual(moment.hour, hour)
                self.assertIsNotNone(moment.utcoffset())
                self.assertEqual(configured.target(moment), expected)
            os.environ["TZ"] = "UTC0"
            time.tzset()
            before = dt.datetime.now().astimezone()
            actual = schedule.local_now()
            after = dt.datetime.now().astimezone()
            self.assertLessEqual(before, actual)
            self.assertLessEqual(actual, after)
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
            time.tzset()

    def test_default_state_is_auto_without_creating_files(self) -> None:
        self.assertEqual(schedule.read_state(self.state), schedule.State())
        self.assertFalse(self.state.parent.exists())
        self.assertEqual(self.cli("mode").stdout, "auto\n")
        self.assertEqual(self.cli("selected").stdout, "\n")
        self.assertFalse(self.state.exists())

    def test_remember_manual_enable_and_persistence(self) -> None:
        for arguments, expected in (
            (("remember", "reze"), schedule.State("auto", "reze")),
            (("manual", "after-school"), schedule.State("manual", "after-school")),
            (("remember", "reze"), schedule.State("manual", "reze")),
            (("enable",), schedule.State("auto", "reze")),
        ):
            with self.subTest(arguments=arguments):
                result = self.cli(*arguments)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(schedule.read_state(self.state), expected)
                self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)
                self.assertEqual(self.cli("mode").stdout.strip(), expected.mode)
                self.assertEqual(self.cli("selected").stdout.strip(), expected.selected)
        self.assertFalse((self.root / "cache").exists())
        self.assertEqual(list(self.state.parent.glob(".theme-schedule.*")), [])

    def test_automatic_updates_mode_and_selection_atomically(self) -> None:
        schedule.write_state(self.state, schedule.State("manual", "reze"))
        with mock.patch.dict(os.environ, self.environment):
            with mock.patch.object(schedule.os, "replace", wraps=os.replace) as replace:
                self.assertEqual(schedule.main(["automatic", "after-school"]), 0)
                replace.assert_called_once()
        self.assertEqual(schedule.read_state(self.state), schedule.State("auto", "after-school"))
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o600)

    def test_unrecognized_corrupt_and_symlinked_state_is_preserved(self) -> None:
        self.state.parent.mkdir(parents=True)
        for content in (
            "invalid JSON",
            '[]',
            '{"mode": "automatic", "selected": "reze"}',
            '{"mode": "manual", "selected": ""}',
            '{"mode": "auto", "selected": "unknown"}',
            '{"mode": "auto", "selected": null}',
            '{"mode": "auto"}',
            '{"mode": "auto", "selected": "", "extra": true}',
            '{"mode": "manual", "mode": "auto", "selected": "reze"}',
        ):
            self.state.write_text(content)
            with self.subTest(content=content):
                for arguments in (
                    ("enable",), ("manual", "reze"), ("remember", "reze"),
                    ("automatic", "reze"),
                ):
                    result = self.cli(*arguments)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(self.state.read_text(), content)
        self.state.unlink()
        target = self.root / "existing.json"
        target.write_text('{"mode": "auto", "selected": "reze"}')
        self.state.symlink_to(target)
        result = self.cli("enable")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.state.is_symlink())
        self.assertEqual(target.read_text(), '{"mode": "auto", "selected": "reze"}')

    def test_atomic_write_failure_preserves_previous_state(self) -> None:
        original = schedule.State("manual", "reze")
        schedule.write_state(self.state, original)
        with mock.patch.object(schedule.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                schedule.write_state(self.state, schedule.State("auto", "reze"))
        self.assertEqual(schedule.read_state(self.state), original)
        self.assertEqual(list(self.state.parent.glob(".theme-schedule.*")), [])

    def test_nonregular_or_oversized_state_is_rejected_without_blocking(self) -> None:
        self.state.parent.mkdir(parents=True)
        self.state.mkdir()
        self.assertNotEqual(self.cli("enable").returncode, 0)
        self.assertTrue(self.state.is_dir())
        self.state.rmdir()
        os.mkfifo(self.state)
        self.assertNotEqual(self.cli("enable").returncode, 0)
        self.assertTrue(stat.S_ISFIFO(self.state.stat().st_mode))
        self.state.unlink()
        self.state.write_text(" " * 16385)
        self.assertNotEqual(self.cli("enable").returncode, 0)
        self.assertEqual(self.state.stat().st_size, 16385)

    def test_status_is_waybar_json_and_target_uses_local_now(self) -> None:
        with mock.patch.dict(os.environ, self.environment):
            with mock.patch.object(schedule, "local_now", return_value=self.local_time(20)):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(schedule.main(["target"]), 0)
                self.assertEqual(output.getvalue(), "reze\n")
        automatic = json.loads(self.cli("status").stdout)
        self.assertEqual(automatic["text"], "AUTO")
        self.assertEqual(automatic["class"], "auto")
        self.assertIn("08:00–20:00", automatic["tooltip"])
        self.assertIn("Laptop local time", automatic["tooltip"])
        self.cli("manual", "reze")
        manual = json.loads(self.cli("status").stdout)
        self.assertEqual(manual["text"], "MAN")
        self.assertEqual(manual["class"], "manual")
        self.assertIn("stays fixed", manual["tooltip"])
        self.assertIn("Selected: Reze", manual["tooltip"])

    def make_session(self) -> socket.socket:
        runtime = pathlib.Path(self.environment["XDG_RUNTIME_DIR"])
        runtime.mkdir(parents=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        server.bind(str(runtime / "wayland-test"))
        self.environment.update(
            {"WAYLAND_DISPLAY": "wayland-test", "HYPRLAND_INSTANCE_SIGNATURE": "test-session"}
        )
        return server

    def test_watcher_requires_inherited_session_socket(self) -> None:
        with mock.patch.object(schedule.subprocess, "run") as run:
            self.assertEqual(schedule.watch(self.environment), 0)
            run.assert_not_called()
        self.make_session()
        session = schedule.inherited_session(self.environment)
        self.assertIsNotNone(session)
        self.assertTrue(session.alive())
        session.socket.unlink()
        session.socket.write_text("not a socket")
        self.assertFalse(session.alive())

    def test_watcher_is_single_instance_and_closes_lock_for_children(self) -> None:
        self.make_session()
        session = schedule.inherited_session(self.environment)
        runtime = pathlib.Path(self.environment["XDG_RUNTIME_DIR"]) / "hyprland-dots"
        runtime.mkdir()
        lock = runtime / f"theme-schedule-{session.identity}.lock"
        with lock.open("w") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with mock.patch.object(schedule.subprocess, "run") as run:
                self.assertEqual(schedule.watch(self.environment), 0)
                run.assert_not_called()

        def stop_after_tick(*arguments: object, **keywords: object) -> subprocess.CompletedProcess:
            self.assertTrue(keywords["close_fds"])
            self.assertEqual(keywords["timeout"], 30.0)
            self.assertEqual(arguments[0][-1], "scheduled")
            session.socket.unlink()
            return subprocess.CompletedProcess(arguments[0], 0)

        with mock.patch.object(schedule.subprocess, "run", side_effect=stop_after_tick) as run:
            with mock.patch.object(schedule.time, "sleep") as sleep:
                self.assertEqual(schedule.watch(self.environment), 0)
                run.assert_called_once()
                sleep.assert_called_once_with(schedule.WATCH_INTERVAL)
        with lock.open("w") as released:
            fcntl.flock(released.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_watcher_keeps_retrying_after_a_failed_tick(self) -> None:
        self.make_session()
        session = schedule.inherited_session(self.environment)
        failures = [subprocess.CompletedProcess([], 1), subprocess.CompletedProcess([], 0)]

        def tick(*arguments: object, **keywords: object) -> subprocess.CompletedProcess:
            result = failures.pop(0)
            if not failures:
                session.socket.unlink()
            return result

        with mock.patch.object(schedule.subprocess, "run", side_effect=tick) as run:
            with mock.patch.object(schedule.time, "sleep"), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(schedule.watch(self.environment), 0)
        self.assertEqual(run.call_count, 2)

    def test_watcher_recovers_on_the_next_tick_after_timeout(self) -> None:
        self.make_session()
        session = schedule.inherited_session(self.environment)
        attempts = 0

        def tick(*arguments: object, **keywords: object) -> subprocess.CompletedProcess:
            nonlocal attempts
            attempts += 1
            self.assertEqual(keywords["timeout"], 30.0)
            if attempts == 1:
                raise subprocess.TimeoutExpired(arguments[0], keywords["timeout"])
            session.socket.unlink()
            return subprocess.CompletedProcess(arguments[0], 0)

        errors = io.StringIO()
        with mock.patch.object(schedule.subprocess, "run", side_effect=tick) as run:
            with mock.patch.object(schedule.time, "sleep"), contextlib.redirect_stderr(errors):
                self.assertEqual(schedule.watch(self.environment), 0)
        self.assertEqual(run.call_count, 2)
        self.assertIn("timed out after 30s; retrying", errors.getvalue())

    def test_watcher_exits_if_session_disappears_during_timed_out_tick(self) -> None:
        self.make_session()
        session = schedule.inherited_session(self.environment)

        def tick(*arguments: object, **keywords: object) -> subprocess.CompletedProcess:
            session.socket.unlink()
            raise subprocess.TimeoutExpired(arguments[0], keywords["timeout"])

        with mock.patch.object(schedule.subprocess, "run", side_effect=tick) as run:
            with mock.patch.object(schedule.time, "sleep"), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(schedule.watch(self.environment), 0)
        run.assert_called_once()
        runtime = pathlib.Path(self.environment["XDG_RUNTIME_DIR"]) / "hyprland-dots"
        with (runtime / f"theme-schedule-{session.identity}.lock").open("w") as released:
            fcntl.flock(released.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


if __name__ == "__main__":
    unittest.main(verbosity=2)
