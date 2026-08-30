#!/usr/bin/env python3

import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parent.parent
SWITCHER = ROOT / "waybar/scripts/theme-switcher.sh"
SCHEDULE = ROOT / "scripts/theme-schedule.py"
PRIVATE_HASH = "b795a1231176884c2b144ddf38ffbc436505df03592fa2d4010df26100867277"
LABELS = {
    "after-school": "After School Stroll — Gruvbox",
    "reze": "Reze — Cassan Nighthowler",
}
DESKTOP_COMMANDS = {
    "awww", "awww-daemon", "hyprctl", "pkill", "swaync-client", "notify-send",
    "pgrep", "pidof", "pywalfox", "pipx", "systemctl", "loginctl", "killall",
    "gsettings", "spotify", "spotify-launcher", "spicetify", "firefox",
    "vesktop", "kitty", "waybar", "swaync", "wofi",
}


class ThemeScheduleIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="theme-schedule-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.config = self.root / "config"
        self.cache = self.root / "cache"
        self.state = self.root / "state/hyprland-dots/theme-schedule.json"
        self.active = self.cache / "hyprland-dots/active-theme"
        self.events = self.root / "commands.jsonl"
        self.displayed = self.root / "displayed-wallpaper.txt"
        self.private = self.root / "data/hyprland-dots/wallpapers/reze.jpg"
        self.override = self.config / "hyprland-dots/schedule.toml"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.home.mkdir()
        source = self.home / "cassan-hyprland/assets/nighthowler/wallpaper.jpg"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"isolated private wallpaper fixture\n")

        self.environment = {
            **os.environ,
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_DATA_HOME": str(self.root / "data"),
            "XDG_CACHE_HOME": str(self.cache),
            "XDG_STATE_HOME": str(self.root / "state"),
            "XDG_RUNTIME_DIR": str(self.root / "run"),
            "WAYLAND_DISPLAY": "isolated-no-real-display",
            "HYPRLAND_INSTANCE_SIGNATURE": "isolated-no-real-hyprland",
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={self.root}/no-real-bus",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "HYPRLAND_DOTS_TEST_EVENTS": str(self.events),
            "HYPRLAND_DOTS_TEST_DISPLAYED": str(self.displayed),
            "HYPRLAND_DOTS_TEST_GOOD": str(source),
            "HYPRLAND_DOTS_TEST_HASH": PRIVATE_HASH,
            "HYPRLAND_DOTS_TEST_AWWW_EXIT": "0",
            "HYPRLAND_DOTS_TEST_AWWW_QUERY_EXIT": "0",
            "HYPRLAND_DOTS_TEST_NOTIFY_EXIT": "0",
            "HYPRLAND_DOTS_TEST_WOFI_SELECTION": "",
            "HYPRLAND_DOTS_TEST_REAL_PYTHON": sys.executable,
            "HYPRLAND_DOTS_TEST_SCHEDULE": str(SCHEDULE),
            "HYPRLAND_DOTS_TEST_FAIL_STATE_COMMAND": "",
        }
        interpreter = self.bin / "python3"
        interpreter.write_text(
            '#!/bin/sh\n'
            'if [ "${1:-}" = "$HYPRLAND_DOTS_TEST_SCHEDULE" ] && '
            '[ "${2:-}" = "$HYPRLAND_DOTS_TEST_FAIL_STATE_COMMAND" ]; then\n'
            '  printf "injected state write failure\\n" >&2\n'
            '  exit 74\n'
            'fi\n'
            'exec "$HYPRLAND_DOTS_TEST_REAL_PYTHON" "$@"\n',
            encoding="utf-8",
        )
        interpreter.chmod(0o755)
        self.install_stubs()
        self.configure_target("after-school")
        self.target = self.helper("target").stdout.strip()
        self.opposite = "reze" if self.target == "after-school" else "after-school"

    def install_stubs(self) -> None:
        dispatcher = self.bin / "stub-command"
        dispatcher.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                from pathlib import Path
                import sys

                command = Path(sys.argv[0]).name
                arguments = sys.argv[1:]
                event = {"command": command, "arguments": arguments}
                if command == "wofi":
                    event["input"] = sys.stdin.read()
                with Path(os.environ["HYPRLAND_DOTS_TEST_EVENTS"]).open("a") as log:
                    log.write(json.dumps(event) + "\\n")
                if command in {"sha256sum", "shasum"}:
                    target = Path(arguments[-1])
                    good = Path(os.environ["HYPRLAND_DOTS_TEST_GOOD"])
                    digest = os.environ["HYPRLAND_DOTS_TEST_HASH"]
                    if target.read_bytes() != good.read_bytes():
                        digest = "0" * 64
                    print(f"{digest}  {target}")
                elif command == "awww":
                    if arguments[0] == "query":
                        raise SystemExit(int(os.environ["HYPRLAND_DOTS_TEST_AWWW_QUERY_EXIT"]))
                    if arguments[0] != "img":
                        raise SystemExit(2)
                    result = int(os.environ["HYPRLAND_DOTS_TEST_AWWW_EXIT"])
                    if result == 0:
                        Path(os.environ["HYPRLAND_DOTS_TEST_DISPLAYED"]).write_text(arguments[1])
                    raise SystemExit(result)
                elif command in {"pgrep", "pidof"}:
                    raise SystemExit(1)
                elif command == "notify-send":
                    raise SystemExit(int(os.environ["HYPRLAND_DOTS_TEST_NOTIFY_EXIT"]))
                elif command == "wofi":
                    selected = os.environ["HYPRLAND_DOTS_TEST_WOFI_SELECTION"]
                    if selected:
                        print(selected)
                    else:
                        raise SystemExit(1)
                """
            ),
            encoding="utf-8",
        )
        dispatcher.chmod(0o755)
        for command in DESKTOP_COMMANDS | {"flock", "sha256sum", "shasum"}:
            (self.bin / command).symlink_to(dispatcher)
        launcher = self.config / "wofi/launch.sh"
        launcher.parent.mkdir(parents=True)
        launcher.write_text('#!/bin/sh\nexec wofi "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)

    def configure_target(self, slug: str) -> None:
        # Put the current clock six hours away from either boundary so these
        # integration checks do not become flaky near the real 08:00/20:00.
        now = dt.datetime.now()
        minute = now.hour * 60 + now.minute
        earlier = (minute - 6 * 60) % (24 * 60)
        later = (minute + 6 * 60) % (24 * 60)
        day, night = (earlier, later) if slug == "after-school" else (later, earlier)

        def label(value: int) -> str:
            hour, minute = divmod(value, 60)
            return f"{hour:02d}:{minute:02d}"

        self.override.parent.mkdir(parents=True, exist_ok=True)
        self.override.write_text(
            f'day_start = "{label(day)}"\nnight_start = "{label(night)}"\n',
            encoding="utf-8",
        )

    def run_command(self, *arguments: str, success: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(arguments), env=self.environment, text=True, capture_output=True,
            check=False, timeout=20,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def switch(self, *arguments: str, success: bool = True) -> subprocess.CompletedProcess[str]:
        return self.run_command(str(SWITCHER), *arguments, success=success)

    def helper(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return self.run_command(sys.executable, str(SCHEDULE), *arguments)

    def records(self, command: str | None = None) -> list[dict]:
        if not self.events.exists():
            return []
        entries = [json.loads(line) for line in self.events.read_text().splitlines()]
        return entries if command is None else [item for item in entries if item["command"] == command]

    def image_calls(self) -> list[dict]:
        return [item for item in self.records("awww") if item["arguments"][0] == "img"]

    def clear_records(self) -> None:
        self.events.write_text("", encoding="utf-8")

    def assert_state(self, mode: str, selected: str) -> None:
        self.assertEqual(json.loads(self.state.read_text()), {"mode": mode, "selected": selected})
        self.assertEqual(self.helper("mode").stdout.strip(), mode)
        self.assertEqual(self.helper("selected").stdout.strip(), selected)

    def assert_active(self, slug: str) -> None:
        self.assertTrue(self.active.is_symlink())
        self.assertEqual((self.active / "current-theme").read_text().strip(), slug)
        wallpaper = ROOT / "assets/after_school_stroll_gruvbox.png" if slug == "after-school" else self.private
        self.assertEqual((self.active / "wallpaper").resolve(), wallpaper.resolve())
        self.assertEqual(json.loads((self.active / "spotify-palette.json").read_text())["theme"], slug)

    def assert_no_display_changes(self) -> None:
        self.assertEqual(self.image_calls(), [])
        for command in ("awww-daemon", "hyprctl", "pkill", "swaync-client"):
            self.assertEqual(self.records(command), [], command)

    def test_prepare_and_restore_choose_the_current_schedule_target(self) -> None:
        self.switch("prepare")
        self.assert_active(self.target)
        self.assert_state("auto", self.target)
        self.assert_no_display_changes()

        self.configure_target(self.opposite)
        self.assertEqual(self.helper("target").stdout.strip(), self.opposite)
        self.switch("restore")
        self.assert_active(self.opposite)
        self.assert_state("auto", self.opposite)
        self.assertEqual(len(self.image_calls()), 1)
        self.assertEqual(Path(self.displayed.read_text()), (self.active / "wallpaper").resolve())

        self.configure_target(self.target)
        self.clear_records()
        self.switch("prepare")
        self.assert_active(self.target)
        self.assert_state("auto", self.target)
        self.assert_no_display_changes()

    def test_auto_off_keeps_the_applied_wallpaper(self) -> None:
        self.switch("restore")
        before_link = self.active.resolve()
        before_image = self.displayed.read_text()
        self.clear_records()
        self.switch("auto-off")
        self.assert_state("manual", self.target)
        self.assertEqual(self.active.resolve(), before_link)
        self.assertEqual(self.displayed.read_text(), before_image)
        self.assert_no_display_changes()
        self.configure_target(self.opposite)
        self.clear_records()
        self.switch("scheduled")
        self.assert_active(self.target)
        self.assert_state("manual", self.target)
        self.assert_no_display_changes()

    def test_auto_on_and_toggle_follow_the_schedule(self) -> None:
        self.switch("set", self.opposite)
        self.assert_state("manual", self.opposite)
        self.clear_records()
        self.switch("auto-on")
        self.assert_active(self.target)
        self.assert_state("auto", self.target)
        self.assertEqual(len(self.image_calls()), 1)

        self.clear_records()
        self.switch("auto-on")
        self.assert_state("auto", self.target)
        self.assert_no_display_changes()
        self.switch("auto-toggle")
        self.assert_state("manual", self.target)
        self.assert_no_display_changes()

        self.configure_target(self.opposite)
        self.clear_records()
        self.switch("auto-toggle")
        self.assert_active(self.opposite)
        self.assert_state("auto", self.opposite)
        self.assertEqual(len(self.image_calls()), 1)

    def test_each_manual_choice_pauses_automatic_switching(self) -> None:
        for arguments in (("next",), ("random",), ("set", self.opposite), ("list",)):
            with self.subTest(arguments=arguments):
                self.switch("auto-on")
                self.assert_active(self.target)
                self.assert_state("auto", self.target)
                self.environment["HYPRLAND_DOTS_TEST_WOFI_SELECTION"] = LABELS[self.opposite]
                self.clear_records()
                self.switch(*arguments)
                self.assert_active(self.opposite)
                self.assert_state("manual", self.opposite)
                self.assertEqual(len(self.image_calls()), 1)
                if arguments == ("list",):
                    entries = self.records("wofi")
                    self.assertEqual(len(entries), 1)
                    self.assertEqual(entries[0]["input"].splitlines(), list(LABELS.values()))
                self.clear_records()
                self.switch("scheduled")
                self.assert_state("manual", self.opposite)
                self.assert_no_display_changes()

    def test_cancelled_picker_preserves_mode_and_selection(self) -> None:
        self.switch("prepare")
        before_state = self.state.read_bytes()
        before_link = self.active.resolve()
        self.clear_records()
        self.switch("list")
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assertEqual(self.active.resolve(), before_link)
        self.assert_no_display_changes()

    def test_notification_failure_does_not_prevent_manual_mode(self) -> None:
        self.switch("restore")
        self.environment["HYPRLAND_DOTS_TEST_NOTIFY_EXIT"] = "1"
        self.switch("next")
        self.assert_active(self.opposite)
        self.assert_state("manual", self.opposite)

    def test_scheduled_is_noop_when_already_correct_or_manual(self) -> None:
        self.switch("prepare")
        before_state = self.state.read_bytes()
        before_link = self.active.resolve()
        self.clear_records()
        self.switch("scheduled")
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assertEqual(self.active.resolve(), before_link)
        self.assert_no_display_changes()

        self.switch("set", self.opposite)
        before_state = self.state.read_bytes()
        before_link = self.active.resolve()
        self.clear_records()
        self.switch("scheduled")
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assertEqual(self.active.resolve(), before_link)
        self.assert_no_display_changes()

    def test_scheduled_applies_a_changed_target_only_once(self) -> None:
        self.switch("prepare")
        self.configure_target(self.opposite)
        self.clear_records()
        self.switch("scheduled")
        self.assert_active(self.opposite)
        self.assert_state("auto", self.opposite)
        self.assertEqual(len(self.image_calls()), 1)
        self.clear_records()
        self.switch("scheduled")
        self.assert_active(self.opposite)
        self.assert_no_display_changes()

    def test_scheduled_and_auto_on_repair_missing_generated_assets(self) -> None:
        self.switch("prepare")
        for argument, missing in (("scheduled", "waybar.css"), ("auto-on", "current-theme")):
            with self.subTest(argument=argument, missing=missing):
                if argument == "auto-on":
                    self.switch("auto-off")
                (self.active / missing).unlink()
                self.clear_records()
                self.switch(argument)
                self.assertTrue((self.active / missing).is_file())
                self.assert_active(self.target)
                self.assert_state("auto", self.target)
                self.assertEqual(len(self.image_calls()), 1)

    def test_failed_manual_requests_preserve_auto_mode_and_selection(self) -> None:
        self.switch("restore")
        self.environment["HYPRLAND_DOTS_TEST_AWWW_EXIT"] = "7"
        self.environment["HYPRLAND_DOTS_TEST_WOFI_SELECTION"] = LABELS[self.opposite]
        before_state = self.state.read_bytes()
        before_link = self.active.resolve()
        before_image = self.displayed.read_text()
        for arguments in (("next",), ("random",), ("set", self.opposite), ("list",)):
            with self.subTest(arguments=arguments):
                self.clear_records()
                result = self.switch(*arguments, success=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.read_bytes(), before_state)
                self.assertEqual(self.active.resolve(), before_link)
                self.assertEqual(self.displayed.read_text(), before_image)
                self.assertEqual(len(self.image_calls()), 1)
                for command in ("hyprctl", "pkill", "swaync-client", "notify-send"):
                    self.assertEqual(self.records(command), [], command)

    def test_failed_auto_enable_preserves_manual_mode_and_selection(self) -> None:
        self.switch("set", self.opposite)
        self.environment["HYPRLAND_DOTS_TEST_AWWW_EXIT"] = "7"
        before_state = self.state.read_bytes()
        before_link = self.active.resolve()
        before_image = self.displayed.read_text()
        for argument in ("auto-on", "auto-toggle"):
            with self.subTest(argument=argument):
                self.clear_records()
                result = self.switch(argument, success=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.read_bytes(), before_state)
                self.assertEqual(self.active.resolve(), before_link)
                self.assertEqual(self.displayed.read_text(), before_image)
                self.assertEqual(len(self.image_calls()), 1)
                self.assertEqual(self.records("notify-send"), [])

    def test_failed_scheduled_or_restore_preserves_auto_selection(self) -> None:
        self.switch("restore")
        self.configure_target(self.opposite)
        self.environment["HYPRLAND_DOTS_TEST_AWWW_EXIT"] = "7"
        before_state = self.state.read_bytes()
        before_link = self.active.resolve()
        before_image = self.displayed.read_text()
        for argument in ("scheduled", "restore"):
            with self.subTest(argument=argument):
                result = self.switch(argument, success=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.read_bytes(), before_state)
                self.assertEqual(self.active.resolve(), before_link)
                self.assertEqual(self.displayed.read_text(), before_image)

    def test_failed_remember_rolls_back_automatic_target(self) -> None:
        self.switch("restore")
        before_state = self.state.read_bytes()
        before_link = self.active.resolve()
        before_image = self.displayed.read_text()
        self.configure_target(self.opposite)
        self.environment["HYPRLAND_DOTS_TEST_FAIL_STATE_COMMAND"] = "remember"
        result = self.switch("scheduled", success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assertEqual(self.active.resolve(), before_link)
        self.assertEqual(self.displayed.read_text(), before_image)

    def test_failed_manual_state_write_rolls_back_manual_request(self) -> None:
        self.switch("restore")
        before_state = self.state.read_bytes()
        before_link = self.active.resolve()
        before_image = self.displayed.read_text()
        self.environment["HYPRLAND_DOTS_TEST_FAIL_STATE_COMMAND"] = "manual"
        result = self.switch("next", success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assertEqual(self.active.resolve(), before_link)
        self.assertEqual(self.displayed.read_text(), before_image)

    def test_failed_automatic_state_write_rolls_back_automatic_request(self) -> None:
        self.switch("set", self.opposite)
        before_state = self.state.read_bytes()
        before_link = self.active.resolve()
        before_image = self.displayed.read_text()
        self.environment["HYPRLAND_DOTS_TEST_FAIL_STATE_COMMAND"] = "automatic"
        result = self.switch("auto-on", success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assertEqual(self.active.resolve(), before_link)
        self.assertEqual(self.displayed.read_text(), before_image)

    def test_manual_selection_survives_cache_loss_prepare_and_restore(self) -> None:
        self.switch("set", self.opposite)
        before_state = self.state.read_bytes()
        shutil.rmtree(self.cache)
        self.clear_records()
        self.switch("prepare")
        self.assert_active(self.opposite)
        self.assert_state("manual", self.opposite)
        self.assertEqual(self.state.read_bytes(), before_state)
        self.assert_no_display_changes()
        generations = [
            entry for entry in (self.cache / "hyprland-dots/themes").iterdir()
            if entry.is_dir() and not entry.is_symlink()
        ]
        self.assertEqual(len(generations), 2)
        self.switch("restore")
        self.assert_active(self.opposite)
        self.assert_state("manual", self.opposite)
        self.assertEqual(len(self.image_calls()), 1)
        self.assertEqual(Path(self.displayed.read_text()), (self.active / "wallpaper").resolve())

    def test_corrupt_state_stops_before_desktop_changes(self) -> None:
        self.switch("prepare")
        self.state.write_text("unrecognized state\n", encoding="utf-8")
        before_link = self.active.resolve()
        for argument in ("prepare", "next", "auto-off", "auto-on", "scheduled", "restore"):
            with self.subTest(argument=argument):
                self.clear_records()
                result = self.switch(argument, success=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state.read_text(), "unrecognized state\n")
                self.assertEqual(self.active.resolve(), before_link)
                self.assert_no_display_changes()


if __name__ == "__main__":
    unittest.main(verbosity=2)
