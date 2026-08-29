#!/usr/bin/env python3
"""Isolated tests for Cassan's opt-in application-theme adapter."""

from __future__ import annotations

import io
import hashlib
import json
import os
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIRECTORY))

import app_themes  # noqa: E402


class ApplicationThemeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.home = self.base / "home"
        self.config = self.base / "config"
        self.state = self.base / "state" / "cassan" / "app-themes"
        self.home.mkdir()
        self.roots = app_themes.Roots(
            home=self.home,
            xdg_config=self.config,
            state=self.state,
        )

    def create_firefox_profile(self, name: str = "default") -> Path:
        firefox = self.home / ".mozilla" / "firefox"
        profile = firefox / (name + ".profile")
        profile.mkdir(parents=True)
        (firefox / "profiles.ini").write_text(
            "[Profile0]\n"
            "Name=%s\n" % name
            + "IsRelative=1\n"
            + "Path=%s.profile\n" % name
            + "Default=1\n",
            encoding="utf-8",
        )
        return profile

    def build(self, apps, profile_name=None, all_profiles=False):
        return app_themes.build_targets(
            self.roots,
            apps,
            profile_name,
            all_profiles,
            euid=os.geteuid(),
        )

    def spicetify_archive(self, marker: bytes = b"current") -> bytes:
        binary = bytearray(64)
        binary[:4] = b"\x7fELF"
        binary[4] = 2
        binary[5] = 1
        binary[18:20] = b"\x3e\x00"
        binary.extend(marker)
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as bundle:
            member = tarfile.TarInfo("spicetify")
            member.mode = 0o755
            member.size = len(binary)
            bundle.addfile(member, io.BytesIO(bytes(binary)))
        return output.getvalue()

    def write_manifest(self, value, mode=0o600) -> Path:
        self.state.mkdir(parents=True, exist_ok=True)
        self.state.chmod(0o700)
        manifest = self.state / "manifest.json"
        manifest.write_text(json.dumps(value), encoding="utf-8")
        manifest.chmod(mode)
        return manifest

    def apply(self, apps, state=None):
        active_state = app_themes.empty_state() if state is None else state
        targets = app_themes.plan_apply(
            self.roots,
            self.build(apps),
            active_state,
            replace=False,
        )
        app_themes.apply_targets(
            self.roots,
            targets,
            active_state,
            removing=False,
        )
        return active_state, targets

    def test_app_selection_is_explicit_and_deduplicated(self) -> None:
        self.assertEqual(
            app_themes.selected_apps(["vesktop", "firefox", "vesktop"]),
            ("vesktop", "firefox"),
        )
        with self.assertRaises(app_themes.ThemeError):
            app_themes.selected_apps([])

    def test_firefox_profile_flags_are_mutually_exclusive(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            app_themes.parser().parse_args(
                [
                    "plan",
                    "--app",
                    "firefox",
                    "--firefox-profile",
                    "default",
                    "--all-firefox-profiles",
                ]
            )

    def test_plan_command_does_not_expect_apply_only_arguments(self) -> None:
        environment = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_STATE_HOME": str(self.base / "state"),
        }
        output = io.StringIO()
        with mock.patch.dict(os.environ, environment, clear=True), redirect_stdout(output):
            result = app_themes.main(["plan", "--app", "vesktop"])
        self.assertEqual(result, 0)
        self.assertIn("Preview complete; no files were changed.", output.getvalue())
        self.assertFalse(self.config.exists())

    def test_firefox_apply_preserves_user_files_and_is_idempotent(self) -> None:
        profile = self.create_firefox_profile()
        chrome = profile / "chrome"
        chrome.mkdir()
        original_chrome = b'@charset "UTF-8";\n/* my browser rule */\n'
        original_content = b"/* my content rule */\n"
        original_preferences = b'user_pref("browser.tabs.warnOnClose", true);\n'
        (chrome / "userChrome.css").write_bytes(original_chrome)
        (chrome / "userContent.css").write_bytes(original_content)
        (profile / "user.js").write_bytes(original_preferences)

        state, targets = self.apply(("firefox",))
        actions = {target.path.name: target.action for target in targets}
        self.assertEqual(actions["userChrome.css"], "update")
        self.assertEqual(actions["userContent.css"], "update")
        self.assertEqual(actions["user.js"], "update")
        installed_chrome = (chrome / "userChrome.css").read_bytes()
        self.assertTrue(installed_chrome.startswith(b'@charset "UTF-8";\n'))
        self.assertIn(b"/* my browser rule */\n", installed_chrome)
        self.assertIn(original_content, (chrome / "userContent.css").read_bytes())
        self.assertIn(original_preferences, (profile / "user.js").read_bytes())
        self.assertEqual(
            (chrome / "userChrome.css").read_text(encoding="utf-8").count(
                app_themes.CSS_START
            ),
            1,
        )

        second = app_themes.plan_apply(
            self.roots,
            self.build(("firefox",)),
            state,
            replace=False,
        )
        self.assertTrue(all(target.action == "unchanged" for target in second))

    def test_nested_relative_firefox_profile_round_trips_through_state(self) -> None:
        firefox = self.home / ".mozilla" / "firefox"
        profile = firefox / "Profiles" / "abc.default-release"
        profile.mkdir(parents=True)
        (firefox / "profiles.ini").write_text(
            "[Profile0]\n"
            "Name=default-release\n"
            "IsRelative=1\n"
            "Path=Profiles/abc.default-release\n"
            "Default=1\n",
            encoding="utf-8",
        )
        state, _targets = self.apply(("firefox",))
        loaded = app_themes.load_state(self.roots)
        self.assertEqual(loaded, state)
        self.assertTrue((profile / "chrome" / "cassan-nighthowler.css").is_file())

    def test_firefox_remove_only_removes_managed_content(self) -> None:
        profile = self.create_firefox_profile()
        chrome = profile / "chrome"
        chrome.mkdir()
        original = b"/* keep this */\n"
        (chrome / "userChrome.css").write_bytes(original)
        state, _targets = self.apply(("firefox",))
        with (chrome / "userChrome.css").open("ab") as target:
            target.write(b"/* added after Cassan */\n")

        removal = app_themes.plan_remove(
            self.roots,
            ("firefox",),
            state,
            replace=False,
        )
        self.assertNotIn("conflict", [target.action for target in removal])
        app_themes.apply_targets(
            self.roots,
            removal,
            state,
            removing=True,
        )
        remaining = (chrome / "userChrome.css").read_bytes()
        self.assertIn(original, remaining)
        self.assertIn(b"/* added after Cassan */", remaining)
        self.assertNotIn(app_themes.CSS_START.encode(), remaining)
        self.assertFalse((chrome / "cassan-nighthowler.css").exists())
        self.assertFalse((chrome / "userContent.css").exists())
        self.assertFalse((profile / "user.js").exists())

    def test_firefox_round_trip_preserves_exact_non_cassan_bytes(self) -> None:
        profile = self.create_firefox_profile()
        chrome = profile / "chrome"
        chrome.mkdir()
        originals = {
            chrome / "userChrome.css": b'@charset "UTF-8";\r\n\r\n/* chrome */\r\n',
            chrome / "userContent.css": b"\n\n/* content */\r\n",
            profile / "user.js": b'user_pref("browser.startup.page", 3);',
        }
        for path, content in originals.items():
            path.write_bytes(content)
        state, _targets = self.apply(("firefox",))
        removal = app_themes.plan_remove(
            self.roots,
            ("firefox",),
            state,
            replace=False,
        )
        app_themes.apply_targets(
            self.roots,
            removal,
            state,
            removing=True,
        )
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)

    def test_locally_edited_firefox_marker_requires_review(self) -> None:
        profile = self.create_firefox_profile()
        state, _targets = self.apply(("firefox",))
        wrapper = profile / "chrome" / "userChrome.css"
        wrapper.write_text(
            wrapper.read_text(encoding="utf-8").replace(
                "cassan-nighthowler.css", "my-local-copy.css"
            ),
            encoding="utf-8",
        )
        removal = app_themes.plan_remove(
            self.roots,
            ("firefox",),
            state,
            replace=False,
        )
        by_name = {target.path.name: target.action for target in removal}
        self.assertEqual(by_name["userChrome.css"], "conflict")

    def test_firefox_activation_allows_edits_outside_managed_blocks(self) -> None:
        profile = self.create_firefox_profile()
        state, _targets = self.apply(("firefox",))
        wrapper = profile / "chrome" / "userChrome.css"
        with wrapper.open("ab") as target:
            target.write(b"/* my later customization */\n")
        app_themes.verify_installed_apps(self.roots, ("firefox",), state)

    def test_removed_owned_firefox_marker_is_not_silently_reinserted(self) -> None:
        profile = self.create_firefox_profile()
        state, _targets = self.apply(("firefox",))
        wrapper = profile / "chrome" / "userChrome.css"
        wrapper.write_bytes(b"/* user intentionally removed Cassan */\n")
        plan = app_themes.plan_apply(
            self.roots,
            self.build(("firefox",)),
            state,
            replace=False,
        )
        by_name = {target.path.name: target.action for target in plan}
        self.assertEqual(by_name["userChrome.css"], "conflict")

    def test_reversed_firefox_markers_are_a_handled_conflict(self) -> None:
        profile = self.create_firefox_profile()
        chrome = profile / "chrome"
        chrome.mkdir()
        (chrome / "userChrome.css").write_text(
            app_themes.CSS_END + "\n" + app_themes.CSS_START + "\n",
            encoding="utf-8",
        )
        plan = app_themes.plan_apply(
            self.roots,
            self.build(("firefox",)),
            app_themes.empty_state(),
            replace=False,
        )
        by_name = {target.path.name: target.action for target in plan}
        self.assertEqual(by_name["userChrome.css"], "conflict")

    def test_unmanaged_vesktop_theme_is_not_overwritten_without_replace(self) -> None:
        destination = (
            self.config
            / "vesktop"
            / "themes"
            / "Cassan-Nighthowler.theme.css"
        )
        destination.parent.mkdir(parents=True)
        destination.write_text("/* local theme */\n", encoding="utf-8")
        targets = app_themes.plan_apply(
            self.roots,
            self.build(("vesktop",)),
            app_themes.empty_state(),
            replace=False,
        )
        self.assertEqual(targets[0].action, "conflict")
        self.assertEqual(destination.read_text(encoding="utf-8"), "/* local theme */\n")

    def test_symlink_destination_escape_is_rejected(self) -> None:
        self.config.mkdir()
        outside = self.base / "outside"
        outside.mkdir()
        os.symlink(str(outside), str(self.config / "vesktop"))
        with self.assertRaises(app_themes.ThemeError):
            app_themes.plan_apply(
                self.roots,
                self.build(("vesktop",)),
                app_themes.empty_state(),
                replace=False,
            )

    def test_corrupt_state_cannot_target_an_unrelated_file(self) -> None:
        manifest = {
            "schema": app_themes.SCHEMA,
            "files": {
                str(self.base / "unrelated.txt"): {
                    "app": "vesktop",
                    "kind": "asset",
                    "sha256": "0" * 64,
                    "created": True,
                }
            },
        }
        self.write_manifest(manifest)
        with self.assertRaises(app_themes.ThemeError):
            app_themes.load_state(self.roots)

    def test_corrupt_state_nul_destination_is_a_handled_error(self) -> None:
        manifest = {
            "schema": app_themes.SCHEMA,
            "files": {
                "/tmp/invalid\x00destination": {
                    "app": "vesktop",
                    "kind": "asset",
                    "sha256": "0" * 64,
                    "created": True,
                }
            },
        }
        self.write_manifest(manifest)
        with self.assertRaises(app_themes.ThemeError):
            app_themes.load_state(self.roots)

    def test_manifest_requires_private_current_user_metadata(self) -> None:
        manifest = self.write_manifest(app_themes.empty_state(), mode=0o644)
        with self.assertRaises(app_themes.ThemeConflict):
            app_themes.load_state(self.roots)
        manifest.chmod(0o600)
        self.assertEqual(app_themes.load_state(self.roots), app_themes.empty_state())

    def test_symlinked_state_root_is_rejected_before_reading(self) -> None:
        state_base = self.base / "state"
        outside = self.base / "outside-state"
        outside.mkdir()
        state_base.mkdir()
        os.symlink(str(outside), str(state_base / "cassan"))
        with self.assertRaises(app_themes.ThemeError):
            app_themes.load_state(self.roots)

    def test_mutation_lock_rejects_a_concurrent_transaction(self) -> None:
        with app_themes.mutation_lock(self.roots):
            with self.assertRaises(app_themes.ThemeConflict):
                with app_themes.mutation_lock(self.roots):
                    self.fail("a second application-theme lock was acquired")
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual(
            (self.state / "transaction.lock").stat().st_mode & 0o777,
            0o600,
        )

    def test_apply_records_state_and_detects_asset_drift(self) -> None:
        state, targets = self.apply(("vesktop",))
        destination = targets[0].path
        self.assertIn(str(destination), state["files"])
        destination.write_text("/* modified */\n", encoding="utf-8")
        with self.assertRaises(app_themes.ThemeConflict):
            app_themes.verify_installed_apps(self.roots, ("vesktop",), state)

    def test_apply_refuses_a_destination_changed_after_planning(self) -> None:
        state = app_themes.empty_state()
        targets = app_themes.plan_apply(
            self.roots,
            self.build(("vesktop",)),
            state,
            replace=False,
        )
        destination = targets[0].path
        destination.parent.mkdir(parents=True)
        destination.write_text("/* appeared after plan */\n", encoding="utf-8")
        with self.assertRaises(app_themes.ThemeConflict):
            app_themes.apply_targets(
                self.roots,
                targets,
                state,
                removing=False,
            )
        self.assertEqual(
            destination.read_text(encoding="utf-8"),
            "/* appeared after plan */\n",
        )

    def test_rollback_preserves_a_racing_target_cassan_never_mutated(self) -> None:
        state = app_themes.empty_state()
        targets = app_themes.plan_apply(
            self.roots,
            self.build(("spotify",)),
            state,
            replace=False,
        )
        first, second = targets
        original_assert = app_themes.assert_safe_parent
        injected = False

        def race(root, path, create):
            nonlocal injected
            original_assert(root, path, create)
            if (
                create
                and path == second.path
                and first.path.exists()
                and not injected
            ):
                second.path.write_bytes(b"user-owned concurrent file\n")
                injected = True

        with mock.patch.object(app_themes, "assert_safe_parent", side_effect=race):
            with self.assertRaises(app_themes.ThemeConflict):
                app_themes.apply_targets(
                    self.roots, targets, state, removing=False
                )
        self.assertFalse(first.path.exists())
        self.assertEqual(second.path.read_bytes(), b"user-owned concurrent file\n")

    def test_rollback_preserves_unknown_change_to_an_applied_target(self) -> None:
        state = app_themes.empty_state()
        targets = app_themes.plan_apply(
            self.roots,
            self.build(("spotify",)),
            state,
            replace=False,
        )
        first, second = targets
        original_assert = app_themes.assert_safe_parent
        injected = False

        def race(root, path, create):
            nonlocal injected
            original_assert(root, path, create)
            if (
                create
                and path == second.path
                and first.path.exists()
                and not injected
            ):
                first.path.write_bytes(b"concurrent edit of applied target\n")
                second.path.write_bytes(b"concurrent second target\n")
                injected = True

        with mock.patch.object(app_themes, "assert_safe_parent", side_effect=race):
            with self.assertRaises(app_themes.ThemeError) as raised:
                app_themes.apply_targets(
                    self.roots, targets, state, removing=False
                )
        self.assertIn("rollback was incomplete", str(raised.exception))
        self.assertEqual(
            first.path.read_bytes(), b"concurrent edit of applied target\n"
        )
        self.assertEqual(second.path.read_bytes(), b"concurrent second target\n")

    def test_directory_fsync_failure_rolls_back_theme_and_manifest(self) -> None:
        state = app_themes.empty_state()
        targets = app_themes.plan_apply(
            self.roots,
            self.build(("vesktop",)),
            state,
            replace=False,
        )
        destination = targets[0].path
        original_fsync = app_themes.fsync_directory
        failed = False

        def fail_manifest_once(path):
            nonlocal failed
            if path == self.state and not failed:
                failed = True
                raise OSError("injected state-directory fsync failure")
            return original_fsync(path)

        with mock.patch.object(
            app_themes, "fsync_directory", side_effect=fail_manifest_once
        ):
            with self.assertRaises(OSError):
                app_themes.apply_targets(
                    self.roots, targets, state, removing=False
                )
        self.assertFalse(destination.exists())
        self.assertFalse((self.state / "manifest.json").exists())

    def test_find_spicetify_accepts_current_owned_binary(self) -> None:
        executable = self.home / ".spicetify" / "spicetify"
        executable.parent.mkdir()
        executable.write_text("#!/bin/sh\nprintf '2.44.0\\n'\n", encoding="utf-8")
        executable.chmod(0o755)
        self.assertEqual(
            app_themes.find_spicetify(self.roots, euid=os.geteuid()),
            str(executable),
        )

    def test_find_spicetify_rejects_outdated_binary(self) -> None:
        executable = self.home / ".spicetify" / "spicetify"
        executable.parent.mkdir()
        executable.write_text("#!/bin/sh\nprintf '2.43.2\\n'\n", encoding="utf-8")
        executable.chmod(0o755)
        with self.assertRaises(app_themes.ThemeError):
            app_themes.find_spicetify(self.roots, euid=os.geteuid())

    def test_find_spicetify_rejects_a_symlinked_parent(self) -> None:
        outside = self.base / "outside-spicetify"
        outside.mkdir()
        executable = outside / "spicetify"
        executable.write_text("#!/bin/sh\nprintf '2.44.0\\n'\n", encoding="utf-8")
        executable.chmod(0o755)
        os.symlink(str(outside), str(self.home / ".spicetify"))
        with self.assertRaises(app_themes.ThemeError):
            app_themes.find_spicetify(self.roots, euid=os.geteuid())

    def test_spicetify_environment_rejects_redirect_overrides(self) -> None:
        with self.assertRaises(app_themes.ThemeConflict):
            app_themes.spicetify_environment(
                self.roots,
                {
                    "HOME": str(self.home),
                    "SPICETIFY_CONFIG": str(self.base / "outside.ini"),
                },
            )
        environment = app_themes.spicetify_environment(
            self.roots,
            {
                "HOME": "/wrong/home",
                "XDG_CONFIG_HOME": "/wrong/config",
                "SPICETIFY_CONFIG": "",
                "SPICETIFY_STATE": "",
            },
        )
        self.assertEqual(environment["HOME"], str(self.home))
        self.assertEqual(environment["XDG_CONFIG_HOME"], str(self.config))
        self.assertNotIn("SPICETIFY_CONFIG", environment)
        self.assertNotIn("SPICETIFY_STATE", environment)

    def test_pinned_spicetify_installer_verifies_and_writes_only_the_binary(self) -> None:
        archive = self.spicetify_archive()
        expected_hash = hashlib.sha256(archive).hexdigest()
        with mock.patch.object(
            app_themes, "SPICETIFY_ARCHIVE_SHA256", expected_hash
        ):
            destination, backup = app_themes.install_spicetify(
                self.roots,
                replace=False,
                opener=lambda _request, timeout: io.BytesIO(archive),
            )
        self.assertIsNone(backup)
        self.assertEqual(destination, self.home / ".spicetify" / "spicetify")
        self.assertEqual(destination.read_bytes()[0:4], b"\x7fELF")
        self.assertEqual(destination.stat().st_mode & 0o777, 0o755)
        self.assertFalse((destination.parent / "README.md").exists())

    def test_pinned_spicetify_installer_rejects_checksum_mismatch(self) -> None:
        archive = self.spicetify_archive()
        with self.assertRaises(app_themes.ThemeError):
            app_themes.install_spicetify(
                self.roots,
                replace=False,
                opener=lambda _request, timeout: io.BytesIO(archive),
            )
        self.assertFalse((self.home / ".spicetify" / "spicetify").exists())

    def test_pinned_spicetify_installer_requires_replace_and_backs_up(self) -> None:
        destination = self.home / ".spicetify" / "spicetify"
        destination.parent.mkdir()
        destination.write_bytes(b"old binary")
        destination.chmod(0o755)
        archive = self.spicetify_archive(b"replacement")
        expected_hash = hashlib.sha256(archive).hexdigest()
        opener = lambda _request, timeout: io.BytesIO(archive)
        with mock.patch.object(
            app_themes, "SPICETIFY_ARCHIVE_SHA256", expected_hash
        ):
            with self.assertRaises(app_themes.ThemeConflict):
                app_themes.install_spicetify(self.roots, replace=False, opener=opener)
            _installed, backup = app_themes.install_spicetify(
                self.roots, replace=True, opener=opener
            )
        self.assertIsNotNone(backup)
        self.assertEqual((backup / "spicetify").read_bytes(), b"old binary")
        self.assertNotEqual(destination.read_bytes(), b"old binary")

    def test_spicetify_installer_parser_does_not_require_an_app(self) -> None:
        arguments = app_themes.parser().parse_args(["install-spicetify"])
        self.assertEqual(arguments.command, "install-spicetify")
        self.assertFalse(arguments.replace)

    def test_spotify_activation_uses_fixed_argv_without_a_shell(self) -> None:
        state, _targets = self.apply(("spotify",))
        spotify = (
            self.home
            / ".local"
            / "share"
            / "spotify-launcher"
            / "install"
            / "usr"
            / "share"
            / "spotify"
        )
        spotify.mkdir(parents=True)
        prefs = self.config / "spotify" / "prefs"
        prefs.parent.mkdir(parents=True)
        prefs.write_text("app.last-launched-version=1\n", encoding="utf-8")
        completed = mock.Mock(returncode=0)
        with mock.patch.object(
            app_themes, "find_spicetify", return_value="/safe/spicetify"
        ), mock.patch.object(
            app_themes, "verified_system_executable", return_value="/usr/bin/spotify-launcher"
        ), mock.patch.object(app_themes.subprocess, "run", return_value=completed) as run, mock.patch.dict(
            os.environ, {}, clear=True
        ):
            app_themes.activate(self.roots, ("spotify",), state)
        self.assertEqual(run.call_count, 2)
        first = run.call_args_list[0]
        second = run.call_args_list[1]
        self.assertEqual(first.args[0][0:2], ["/safe/spicetify", "config"])
        self.assertIn("Cassan-Nighthowler", first.args[0])
        self.assertEqual(second.args[0], ["/safe/spicetify", "backup", "apply"])
        self.assertNotIn("shell", first.kwargs)
        self.assertNotIn("shell", second.kwargs)
        self.assertEqual(first.kwargs["env"]["HOME"], str(self.home))
        self.assertEqual(
            first.kwargs["env"]["XDG_CONFIG_HOME"], str(self.config)
        )
        self.assertNotIn("SPICETIFY_CONFIG", first.kwargs["env"])
        self.assertNotIn("SPICETIFY_STATE", first.kwargs["env"])

    def test_spotify_activation_restores_config_and_client_after_failure(self) -> None:
        state, _targets = self.apply(("spotify",))
        spotify = (
            self.home
            / ".local"
            / "share"
            / "spotify-launcher"
            / "install"
            / "usr"
            / "share"
            / "spotify"
        )
        spotify.mkdir(parents=True)
        prefs = self.config / "spotify" / "prefs"
        prefs.parent.mkdir(parents=True)
        prefs.write_text("prefs\n", encoding="utf-8")
        config = self.config / "spicetify" / "config-xpui.ini"
        config.write_bytes(b"previous config\n")
        calls = []

        def run(command, check=False, env=None):
            calls.append(command)
            if command[1] == "config":
                config.write_bytes(b"new config\n")
                return mock.Mock(returncode=0)
            if command[1:3] == ["backup", "apply"]:
                return mock.Mock(returncode=1)
            return mock.Mock(returncode=0)

        with mock.patch.object(
            app_themes, "find_spicetify", return_value="/safe/spicetify"
        ), mock.patch.object(
            app_themes, "verified_system_executable", return_value="/usr/bin/spotify-launcher"
        ), mock.patch.object(app_themes.subprocess, "run", side_effect=run), mock.patch.dict(
            os.environ, {}, clear=True
        ):
            with self.assertRaises(app_themes.ThemeError):
                app_themes.activate(self.roots, ("spotify",), state)
        self.assertEqual(config.read_bytes(), b"previous config\n")
        self.assertEqual(calls[-1], ["/safe/spicetify", "restore"])

    def test_spotify_activation_restores_config_when_commands_raise(self) -> None:
        state, _targets = self.apply(("spotify",))
        spotify = (
            self.home
            / ".local"
            / "share"
            / "spotify-launcher"
            / "install"
            / "usr"
            / "share"
            / "spotify"
        )
        spotify.mkdir(parents=True)
        prefs = self.config / "spotify" / "prefs"
        prefs.parent.mkdir(parents=True)
        prefs.write_text("prefs\n", encoding="utf-8")
        config = self.config / "spicetify" / "config-xpui.ini"
        config.write_bytes(b"previous config\n")
        calls = []

        def run(command, check=False, env=None):
            calls.append(command)
            if command[1] == "config":
                config.write_bytes(b"new config\n")
                return mock.Mock(returncode=0)
            if command[1:3] == ["backup", "apply"]:
                raise FileNotFoundError("injected launch failure")
            if command[1] == "restore":
                raise OSError("injected recovery failure")
            return mock.Mock(returncode=0)

        with mock.patch.object(
            app_themes, "find_spicetify", return_value="/safe/spicetify"
        ), mock.patch.object(
            app_themes,
            "verified_system_executable",
            return_value="/usr/bin/spotify-launcher",
        ), mock.patch.object(
            app_themes.subprocess, "run", side_effect=run
        ), mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(app_themes.ThemeError) as raised:
                app_themes.activate(self.roots, ("spotify",), state)
        self.assertEqual(config.read_bytes(), b"previous config\n")
        self.assertEqual(calls[-1], ["/safe/spicetify", "restore"])
        self.assertIn("Spotify restore failed", str(raised.exception))

    def test_root_cannot_apply_user_application_themes(self) -> None:
        environment = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_STATE_HOME": str(self.base / "state"),
        }
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(
            app_themes.os, "geteuid", return_value=0
        ), redirect_stderr(io.StringIO()):
            result = app_themes.main(["apply", "--app", "vesktop"])
        self.assertEqual(result, 3)

    def test_theme_files_remain_private_to_app_configuration_roots(self) -> None:
        for app in ("vesktop", "spotify"):
            for target in self.build((app,)):
                self.assertTrue(app_themes.is_below(target.path, self.config))

    def test_byte_identical_unmanaged_asset_still_requires_replace(self) -> None:
        target = self.build(("vesktop",))[0]
        target.path.parent.mkdir(parents=True)
        target.path.write_bytes(target.desired)
        plan = app_themes.plan_apply(
            self.roots,
            self.build(("vesktop",)),
            app_themes.empty_state(),
            replace=False,
        )
        self.assertEqual(plan[0].action, "conflict")
        replacement = app_themes.plan_apply(
            self.roots,
            self.build(("vesktop",)),
            app_themes.empty_state(),
            replace=True,
        )
        self.assertEqual(replacement[0].action, "replace")


if __name__ == "__main__":
    unittest.main(verbosity=2)
