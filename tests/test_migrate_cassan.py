#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
MIGRATION = REPO / "scripts" / "migrate-cassan.py"
NETWORK_CONFIG = """[dmenu]
dmenu_command = wofi
compact = True
list_saved = True
active_chars = 󰄬
highlight = True
highlight_bold = True
prompt = Networks
wifi_icons = 󰤟󰤢󰤥󰤨

[editor]
gui_if_available = True
gui = nm-connection-editor
terminal = kitty

[nmdm]
rescan_delay = 5
show_notifications = True
notification_timeout = 5
"""
CSS_START = "/* >>> CASSAN NIGHTHOWLER >>> */"
CSS_END = "/* <<< CASSAN NIGHTHOWLER <<< */"
CHROME_BLOCK = (
    CSS_START + '\n@import url("cassan-nighthowler.css");\n' + CSS_END + "\n"
)
CONTENT_BLOCK = (
    CSS_START
    + '\n@import url("cassan-nighthowler-content.css");\n'
    + CSS_END
    + "\n"
)


def load_migration_module():
    module_name = "hyprland_dots_legacy_migration"
    specification = importlib.util.spec_from_file_location(module_name, MIGRATION)
    if specification is None or specification.loader is None:
        raise RuntimeError("cannot load the migration module")
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


class MigrationIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="hyprland-dots-migration-")
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / "home"
        self.config = self.root / "xdg-config"
        self.state = self.root / "xdg-state"
        self.home.mkdir()
        self.config.mkdir()
        self.state.mkdir()
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.config),
                "XDG_STATE_HOME": str(self.state),
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def write(path: Path, content: bytes | str, mode: int = 0o644) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        path.chmod(mode)

    def run_migration(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(MIGRATION), *arguments],
            cwd=REPO,
            env=self.environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    def backup_directories(self) -> list[Path]:
        root = self.state / "hyprland-dots" / "legacy-cassan"
        if not root.exists():
            return []
        return sorted(path for path in root.iterdir() if path.is_dir())

    def prepare_full_legacy_fixture(self) -> dict[str, Path | bytes]:
        cassan_assets = self.home / ".config" / "cassan" / "assets" / "nighthowler"
        self.write(cassan_assets / "wallpaper.jpg", b"legacy wallpaper")

        network = self.config / "networkmanager-dmenu" / "config.ini"
        self.write(network, NETWORK_CONFIG)
        network_temporary = network.parent / ".config.ini.cassan-interrupted"
        self.write(network_temporary, "temporary\n")
        self.assertEqual(
            hashlib.sha256(NETWORK_CONFIG.encode("utf-8")).hexdigest(),
            "b8fdf543297ef1373e6b11866cf928b1e83f4d83935f54d2dcc2061d2409193b",
        )

        profile = self.home / ".mozilla" / "firefox" / "example.default"
        chrome_asset = profile / "chrome" / "cassan-nighthowler.css"
        content_asset = profile / "chrome" / "cassan-nighthowler-content.css"
        chrome_asset_bytes = b"fixture chrome asset\n"
        content_asset_bytes = b"fixture content asset\n"
        self.write(chrome_asset, chrome_asset_bytes)
        self.write(content_asset, content_asset_bytes)
        wrapper_before = "@namespace url(example);\n" + CHROME_BLOCK + "button { color: red; }\n"
        wrapper_after = "@namespace url(example);\nbutton { color: red; }\n"
        self.write(profile / "chrome" / "userChrome.css", wrapper_before)
        self.write(profile / "chrome" / "userContent.css", CONTENT_BLOCK)
        firefox_temporary = profile / "chrome" / ".userChrome.css.cassan-interrupted"
        self.write(firefox_temporary, "temporary\n")
        self.write(profile / "user.js", 'user_pref("example", true);\n')

        app_manifest = {
            "schema": 1,
            "files": {
                str(chrome_asset): {
                    "app": "firefox",
                    "kind": "asset",
                    "sha256": hashlib.sha256(chrome_asset_bytes).hexdigest(),
                    "created": False,
                },
                str(content_asset): {
                    "app": "firefox",
                    "kind": "asset",
                    "sha256": hashlib.sha256(content_asset_bytes).hexdigest(),
                    "created": False,
                },
            },
        }
        legacy_manifest = self.state / "cassan" / "app-themes" / "manifest.json"
        self.write(legacy_manifest, json.dumps(app_manifest) + "\n", 0o600)

        spicetify_config = self.config / "spicetify" / "config-xpui.ini"
        self.write(
            spicetify_config,
            "[Setting]\ncurrent_theme = Cassan-Nighthowler\ncolor_scheme = Nighthowler\n",
        )
        old_spicetify_theme = (
            self.config / "spicetify" / "Themes" / "Cassan-Nighthowler"
        )
        self.write(old_spicetify_theme / "user.css", "legacy theme\n")
        spotify_install = self.home / ".local" / "share" / "spotify-launcher" / "install"
        self.write(
            spotify_install / "usr" / "share" / "spotify" / "Apps" / "xpui" / "index.html",
            "patched",
        )
        spicetify_state = self.state / "spicetify"
        self.write(spicetify_state / "Backup" / "xpui.spa", b"stock backup")

        user_spicetify = self.home / ".spicetify" / "spicetify"
        self.write(user_spicetify, b"unrelated user binary", 0o755)
        return {
            "network": network,
            "network_temporary": network_temporary,
            "profile": profile,
            "firefox_temporary": firefox_temporary,
            "wrapper_after": wrapper_after.encode("utf-8"),
            "spotify_install": spotify_install,
            "spicetify_state": spicetify_state,
            "spicetify_config": spicetify_config,
            "old_spicetify_theme": old_spicetify_theme,
            "user_spicetify": user_spicetify,
        }

    def test_preview_then_full_apply_is_backup_first_and_idempotent(self) -> None:
        fixture = self.prepare_full_legacy_fixture()
        preview = self.run_migration()
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("Preview only", preview.stdout)
        self.assertTrue((self.home / ".config" / "cassan").exists())
        self.assertTrue(fixture["network"].exists())
        self.assertEqual(self.backup_directories(), [])

        module = load_migration_module()
        roots = module.Roots.from_environ(self.environment)
        actions, reviews = module.build_plan(roots)
        self.assertTrue(any("user-owned" in review.detail for review in reviews))
        with mock.patch.object(module, "spotify_process_running", return_value=False):
            applied_backup = module.apply_plan(roots, actions, reviews)
        self.assertIsNotNone(applied_backup)
        self.assertFalse((self.home / ".config" / "cassan").exists())
        self.assertFalse(fixture["network"].exists())
        self.assertFalse(fixture["network_temporary"].exists())
        profile = fixture["profile"]
        self.assertFalse((profile / "chrome" / "cassan-nighthowler.css").exists())
        self.assertFalse((profile / "chrome" / "cassan-nighthowler-content.css").exists())
        self.assertEqual(
            (profile / "chrome" / "userChrome.css").read_bytes(),
            fixture["wrapper_after"],
        )
        self.assertFalse((profile / "chrome" / "userContent.css").exists())
        self.assertFalse(fixture["firefox_temporary"].exists())
        self.assertEqual(
            (profile / "user.js").read_text(encoding="utf-8"),
            'user_pref("example", true);\n',
        )
        self.assertFalse(fixture["spotify_install"].exists())
        self.assertFalse(fixture["spicetify_state"].exists())
        self.assertFalse(fixture["spicetify_config"].exists())
        self.assertFalse(fixture["old_spicetify_theme"].exists())
        self.assertTrue(fixture["user_spicetify"].exists())
        self.assertFalse((self.state / "cassan").exists())

        backups = self.backup_directories()
        self.assertEqual(len(backups), 1)
        backup = backups[0]
        manifest = json.loads((backup / "migration.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "completed")
        network_entries = [
            item for item in manifest["actions"] if item["source"] == str(fixture["network"])
        ]
        self.assertEqual(
            network_entries[0]["sha256"],
            "b8fdf543297ef1373e6b11866cf928b1e83f4d83935f54d2dcc2061d2409193b",
        )
        self.assertTrue((backup / "home-config" / "cassan").is_dir())
        self.assertTrue((backup / "xdg-config" / "networkmanager-dmenu" / "config.ini").is_file())
        self.assertTrue((backup / "firefox" / "example.default" / "chrome" / "userChrome.css").is_file())
        self.assertTrue((backup / "home" / ".local" / "share" / "spotify-launcher" / "install").is_dir())
        self.assertTrue((backup / "state" / "spicetify").is_dir())
        self.assertTrue((backup / "xdg-config" / "spicetify" / "config-xpui.ini").is_file())
        self.assertTrue(
            (backup / "xdg-config" / "spicetify" / "Themes" / "Cassan-Nighthowler").is_dir()
        )
        self.assertTrue((backup / "state" / "cassan").is_dir())

        repeated = self.run_migration("--apply")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("No legacy Cassan files require migration", repeated.stdout)
        self.assertEqual(self.backup_directories(), backups)

    def test_edited_marker_block_stops_before_any_change(self) -> None:
        cassan = self.home / ".config" / "cassan"
        self.write(cassan / "asset", "must survive")
        wrapper = self.home / ".mozilla" / "firefox" / "profile" / "chrome" / "userChrome.css"
        self.write(
            wrapper,
            CSS_START + '\n@import url("locally-edited.css");\n' + CSS_END + "\n",
        )

        result = self.run_migration("--apply")
        self.assertEqual(result.returncode, 2)
        self.assertIn("manual review", result.stderr)
        self.assertTrue(cassan.exists())
        self.assertTrue(wrapper.exists())
        self.assertEqual(self.backup_directories(), [])

    def test_unverified_generic_files_are_retained(self) -> None:
        network = self.config / "networkmanager-dmenu" / "config.ini"
        firefox_asset = (
            self.home
            / ".mozilla"
            / "firefox"
            / "profile"
            / "chrome"
            / "cassan-nighthowler.css"
        )
        self.write(network, "user configuration\n")
        self.write(firefox_asset, "locally edited theme\n")

        result = self.run_migration("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(network.exists())
        self.assertTrue(firefox_asset.exists())
        self.assertIn("Retained for safety", result.stdout)
        self.assertEqual(self.backup_directories(), [])

    def test_unrelated_cassan_like_temporary_name_is_retained(self) -> None:
        unrelated = (
            self.home
            / ".mozilla"
            / "firefox"
            / "profile"
            / ".notes.cassan-backup"
        )
        self.write(unrelated, "user notes\n")

        result = self.run_migration("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(unrelated.is_file())
        self.assertEqual(self.backup_directories(), [])

    def test_partial_case_insensitive_spotify_selection_blocks_all_changes(self) -> None:
        cassan = self.home / ".config" / "cassan"
        self.write(cassan / "asset", "must remain")
        self.write(
            self.config / "spicetify" / "config-xpui.ini",
            "[Setting]\ncurrent_theme = cassan-nighthowler\ncolor_scheme = Other\n",
        )

        result = self.run_migration("--apply")
        self.assertEqual(result.returncode, 2)
        self.assertTrue((cassan / "asset").is_file())
        self.assertEqual(self.backup_directories(), [])

    def test_archive_failure_rolls_back_prior_moves(self) -> None:
        cassan = self.home / ".config" / "cassan"
        legacy_state = self.state / "cassan"
        self.write(cassan / "asset", "first action")
        self.write(legacy_state / "manifest.json", "{}\n")
        module = load_migration_module()
        roots = module.Roots.from_environ(self.environment)
        actions, reviews = module.build_plan(roots)
        self.assertEqual(len(actions), 2)
        self.assertFalse(any(review.blocking for review in reviews))

        original_move = module.shutil.move
        calls = 0

        def fail_second_move(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated second archive failure")
            return original_move(source, destination)

        with mock.patch.object(module.shutil, "move", side_effect=fail_second_move):
            with self.assertRaises(module.MigrationError):
                module.apply_plan(roots, actions, reviews)

        self.assertTrue((cassan / "asset").is_file())
        self.assertTrue((legacy_state / "manifest.json").is_file())
        backups = self.backup_directories()
        self.assertEqual(len(backups), 1)
        manifest = json.loads((backups[0] / "migration.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "rolled-back")

    def test_symlinked_legacy_root_is_never_followed(self) -> None:
        outside = self.root / "outside"
        self.write(outside / "keep", "not Cassan-owned")
        legacy = self.home / ".config" / "cassan"
        legacy.parent.mkdir(parents=True)
        legacy.symlink_to(outside, target_is_directory=True)

        result = self.run_migration("--apply")
        self.assertEqual(result.returncode, 2)
        self.assertTrue((outside / "keep").is_file())
        self.assertTrue(legacy.is_symlink())
        self.assertEqual(self.backup_directories(), [])

    def test_symlinked_backup_root_is_rejected_before_migration(self) -> None:
        cassan = self.home / ".config" / "cassan"
        self.write(cassan / "asset", "must remain")
        outside = self.root / "outside-backups"
        outside.mkdir()
        backup_root = self.state / "hyprland-dots" / "legacy-cassan"
        backup_root.parent.mkdir()
        backup_root.symlink_to(outside, target_is_directory=True)
        original_mode = outside.stat().st_mode

        result = self.run_migration("--apply")
        self.assertEqual(result.returncode, 1)
        self.assertTrue((cassan / "asset").is_file())
        self.assertEqual(outside.stat().st_mode, original_mode)
        self.assertEqual(list(outside.iterdir()), [])

    def test_backup_nested_in_source_is_rejected_before_migration(self) -> None:
        cassan = self.home / ".config" / "cassan"
        self.write(cassan / "asset", "must remain")
        nested_state = cassan / "state"
        nested_state.mkdir()
        self.environment["XDG_STATE_HOME"] = str(nested_state)

        result = self.run_migration("--apply")
        self.assertEqual(result.returncode, 2)
        self.assertTrue((cassan / "asset").is_file())
        self.assertFalse((nested_state / "hyprland-dots").exists())

    def test_equal_config_and_state_roots_preserve_unrelated_spicetify_data(self) -> None:
        shared = self.root / "shared-xdg"
        shared.mkdir()
        self.environment["XDG_CONFIG_HOME"] = str(shared)
        self.environment["XDG_STATE_HOME"] = str(shared)
        spicetify = shared / "spicetify"
        self.write(
            spicetify / "config-xpui.ini",
            "[Setting]\ncurrent_theme = Cassan-Nighthowler\ncolor_scheme = Nighthowler\n",
        )
        self.write(spicetify / "Themes" / "Cassan-Nighthowler" / "user.css", "old\n")
        unrelated_theme = spicetify / "Themes" / "UnrelatedUserTheme" / "user.css"
        self.write(unrelated_theme, "keep\n")
        self.write(spicetify / "Backup" / "xpui.spa", "backup\n")
        self.write(spicetify / "Extracted" / "Raw" / "xpui" / "index.html", "old\n")
        spotify_install = self.home / ".local" / "share" / "spotify-launcher" / "install"
        self.write(
            spotify_install / "usr" / "share" / "spotify" / "Apps" / "xpui" / "index.html",
            "patched\n",
        )

        module = load_migration_module()
        roots = module.Roots.from_environ(self.environment)
        actions, reviews = module.build_plan(roots)
        with mock.patch.object(module, "spotify_process_running", return_value=False):
            module.apply_plan(roots, actions, reviews)
        self.assertTrue(unrelated_theme.is_file())
        self.assertFalse((spicetify / "Themes" / "Cassan-Nighthowler").exists())
        self.assertFalse((spicetify / "config-xpui.ini").exists())
        self.assertFalse((spicetify / "Backup").exists())
        self.assertFalse((spicetify / "Extracted").exists())
        backups = sorted((shared / "hyprland-dots" / "legacy-cassan").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "state" / "spicetify" / "Backup").is_dir())
        self.assertTrue((backups[0] / "state" / "spicetify" / "Extracted").is_dir())
        self.assertTrue(
            (backups[0] / "xdg-config" / "spicetify" / "config-xpui.ini").is_file()
        )

    def test_coincident_asset_and_legacy_state_root_is_archived_once(self) -> None:
        shared = self.home / ".config"
        shared.mkdir()
        self.environment["XDG_STATE_HOME"] = str(shared)
        cassan = shared / "cassan"
        self.write(cassan / "assets" / "wallpaper", "old\n")
        self.write(cassan / "manifest.json", "{}\n")

        result = self.run_migration("--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(cassan.exists())
        backups = sorted((shared / "hyprland-dots" / "legacy-cassan").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "home-config" / "cassan" / "manifest.json").is_file())

    def test_running_spotify_blocks_before_creating_a_backup(self) -> None:
        spicetify_config = self.config / "spicetify" / "config-xpui.ini"
        self.write(
            spicetify_config,
            "[Setting]\ncurrent_theme = Cassan-Nighthowler\ncolor_scheme = Nighthowler\n",
        )
        spotify_install = self.home / ".local" / "share" / "spotify-launcher" / "install"
        self.write(spotify_install / "spotify", "client\n")
        module = load_migration_module()
        roots = module.Roots.from_environ(self.environment)
        actions, reviews = module.build_plan(roots)

        with mock.patch.object(module, "spotify_process_running", return_value=True):
            with self.assertRaises(module.MigrationError):
                module.apply_plan(roots, actions, reviews)

        self.assertTrue(spicetify_config.is_file())
        self.assertTrue((spotify_install / "spotify").is_file())
        self.assertEqual(self.backup_directories(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
