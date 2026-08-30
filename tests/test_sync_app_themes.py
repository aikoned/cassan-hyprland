import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/sync-app-themes.py"
SPEC = importlib.util.spec_from_file_location("sync_app_themes", SCRIPT)
sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync
SPEC.loader.exec_module(sync)


class AppThemeSyncTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="app-theme-sync-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.config = self.root / "config"
        self.cache = self.root / "cache"
        self.state = self.root / "state/hyprland-dots"
        self.data = self.root / "data"
        self.template = self.root / "template/vesktop"
        self.environment = {
            "XDG_CONFIG_HOME": str(self.config),
            "XDG_CACHE_HOME": str(self.cache),
            "XDG_STATE_HOME": str(self.state.parent),
            "XDG_DATA_HOME": str(self.data),
        }
        environment_patch = mock.patch.dict(os.environ, self.environment)
        environment_patch.start()
        self.addCleanup(environment_patch.stop)
        command_patch = mock.patch.object(sync.subprocess, "run", side_effect=self.closed_vesktop)
        self.commands = command_patch.start()
        self.addCleanup(command_patch.stop)

    @staticmethod
    def closed_vesktop(command, **kwargs):
        if command[0] != "pgrep":
            raise AssertionError(f"unexpected external command: {command}")
        return subprocess.CompletedProcess(command, 1, b"", b"")

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return path

    @staticmethod
    def palette(theme="after-school", color="#123456"):
        return {
            "schema": 1,
            "theme": theme,
            "colors": {key: color for key in sorted(sync.COLOR_KEYS)},
        }

    def palette_bytes(self, theme="after-school", color="#123456"):
        return (json.dumps(self.palette(theme, color), indent=2) + "\n").encode()

    def runtime(self, quick_css="", settings=None):
        root = self.config / "vesktop"
        settings = {"useQuickCss": True, "customOption": {"keep": 42}} if settings is None else settings
        self.write(root / "settings/settings.json", json.dumps(settings))
        self.write(root / "settings/quickCss.css", quick_css)
        return root

    def spotify(self, root=None, *, patched=True):
        root = root or self.home / ".local/share/spotify-launcher/install/usr/share/spotify"
        xpui = root / "Apps/xpui"
        xpui.mkdir(parents=True, exist_ok=True)
        if patched:
            self.write(xpui / "helper/spicetifyWrapper.js", "// Spicetify marker\n")
        return xpui

    def firefox(self, **overrides):
        wrapper = self.data / "hyprland-dots/firefox/native-host.sh"
        self.write(wrapper, "#!/bin/sh\nexit 0\n")
        wrapper.chmod(0o700)
        manifest = {
            "name": "pywalfox",
            "type": "stdio",
            "path": str(wrapper),
            "allowed_extensions": ["pywalfox@frewacom.org"],
        }
        manifest.update(overrides)
        return self.write(
            self.home / ".mozilla/native-messaging-hosts/pywalfox.json",
            json.dumps(manifest),
        )

    def generation(self, name, theme, color):
        generation = self.cache / f"hyprland-dots/generations/{name}"
        self.write(generation / "vesktop.css", f":root {{ --focus: {color}; }}\n")
        self.write(generation / "spotify-palette.json", self.palette_bytes(theme, color))
        return generation

    def test_quick_css_keeps_custom_rules_and_inode_across_palette_changes(self):
        prefix = "/* my CSS stays verbatim */\n.custom { display: flex; }\n\n"
        suffix = "\n.footer { opacity: 0.7; }\n"
        original = prefix + sync.BEGIN + "\n:root { --old: red; }\n" + sync.END + suffix
        root = self.runtime(original)
        css = root / "settings/quickCss.css"
        settings = root / "settings/settings.json"
        inode = css.stat().st_ino
        settings_before = settings.read_bytes()
        for palette in (":root { --focus: #aabbcc; }\n", ":root { --focus: #112233; }\n"):
            with self.subTest(palette=palette):
                previous = css.read_bytes()
                self.assertTrue(sync.sync_vesktop(self.config, self.state, palette))
                expected = prefix + sync.BEGIN + "\n" + palette.rstrip() + "\n" + sync.END + suffix
                self.assertEqual(css.read_text(), expected)
                self.assertEqual(css.stat().st_ino, inode)
                self.assertEqual(settings.read_bytes(), settings_before)
                self.assertEqual((self.state / "app-theme-backups/quickCss.previous.css").read_bytes(), previous)
        before = css.stat().st_mtime_ns
        self.assertTrue(sync.sync_vesktop(self.config, self.state, palette))
        self.assertEqual(css.stat().st_mtime_ns, before)

    def test_quick_css_preserves_in_place_editor_save_during_backup(self):
        original = ".custom { color: red; }\n"
        edited = ".custom { color: blue; }\n.new { display: flex; }\n"
        root = self.runtime(original)
        css = root / "settings/quickCss.css"
        inode = css.stat().st_ino
        atomic_write = sync.atomic_write

        def save_during_backup(path, content, mode=0o600):
            atomic_write(path, content, mode)
            css.write_text(edited)

        with mock.patch.object(sync, "atomic_write", side_effect=save_during_backup):
            with self.assertRaisesRegex(ValueError, "changed during theme sync"):
                sync.sync_vesktop(self.config, self.state, ":root { --focus: #123456; }")
        self.assertEqual(css.read_text(), edited)
        self.assertEqual(css.stat().st_ino, inode)
        self.assertEqual((self.state / "app-theme-backups/quickCss.previous.css").read_text(), original)

    def test_quick_css_preserves_editor_inode_replacement_during_backup(self):
        original = ".custom { color: red; }\n"
        for edited in (original, ".new { color: blue; }\n"):
            with self.subTest(edited=edited):
                root = self.runtime(original)
                css = root / "settings/quickCss.css"
                inode = css.stat().st_ino
                replacement = self.write(self.root / "editor-save.css", edited)
                atomic_write = sync.atomic_write

                def replace_during_backup(path, content, mode=0o600):
                    atomic_write(path, content, mode)
                    os.replace(replacement, css)

                with css.open() as original_handle:
                    with mock.patch.object(sync, "atomic_write", side_effect=replace_during_backup):
                        with self.assertRaisesRegex(ValueError, "changed during theme sync"):
                            sync.sync_vesktop(self.config, self.state, ":root { --focus: #123456; }")
                    self.assertEqual(original_handle.read(), original)
                self.assertEqual(css.read_text(), edited)
                self.assertNotEqual(css.stat().st_ino, inode)
                self.assertEqual((self.state / "app-theme-backups/quickCss.previous.css").read_text(), original)

    def test_quick_css_refuses_symlink_or_nonregular_replacement_during_backup(self):
        original = ".custom { color: red; }\n"
        unrelated = self.write(self.root / "unrelated.css", "do not change")
        for kind in ("symlink", "directory", "fifo"):
            with self.subTest(kind=kind):
                root = self.runtime(original)
                css = root / "settings/quickCss.css"
                atomic_write = sync.atomic_write

                def replace_during_backup(path, content, mode=0o600):
                    atomic_write(path, content, mode)
                    css.unlink()
                    if kind == "symlink":
                        css.symlink_to(unrelated)
                    elif kind == "directory":
                        css.mkdir()
                    else:
                        os.mkfifo(css)

                with css.open() as original_handle:
                    with mock.patch.object(sync, "atomic_write", side_effect=replace_during_backup):
                        with self.assertRaisesRegex(ValueError, "changed during theme sync"):
                            sync.sync_vesktop(self.config, self.state, ":root { --focus: #123456; }")
                    self.assertEqual(original_handle.read(), original)
                self.assertEqual(unrelated.read_text(), "do not change")
                if kind == "directory":
                    self.assertTrue(css.is_dir())
                    css.rmdir()
                else:
                    self.assertTrue(css.is_symlink() if kind == "symlink" else stat.S_ISFIFO(css.lstat().st_mode))
                    css.unlink()

    def test_quick_css_appends_one_managed_block_without_changing_custom_text(self):
        for custom in ("", "/* user */", "/* user */\n", "/* user */\n\n"):
            with self.subTest(custom=custom):
                result = sync.merge_quick_css(custom, ":root { --focus: #123456; }\n")
                self.assertTrue(result.startswith(custom))
                self.assertEqual(result.count(sync.BEGIN), 1)
                self.assertEqual(result.count(sync.END), 1)
                self.assertEqual(sync.merge_quick_css(result, ":root { --focus: #123456; }\n"), result)

    def test_missing_vesktop_is_skipped_without_creating_runtime(self):
        self.assertFalse(sync.sync_vesktop(self.config, self.state, ":root {}"))
        self.assertFalse(self.config.exists())
        self.assertFalse(self.state.exists())

    def test_malformed_quick_css_is_preserved(self):
        root = self.runtime()
        css = root / "settings/quickCss.css"
        for content in (
            sync.BEGIN,
            sync.END,
            sync.END + sync.BEGIN,
            sync.BEGIN + sync.END + sync.BEGIN + sync.END,
            b"invalid UTF-8: \xff",
        ):
            with self.subTest(content=content):
                self.write(css, content)
                original = css.read_bytes()
                inode = css.stat().st_ino
                with self.assertRaises(ValueError):
                    sync.sync_vesktop(self.config, self.state, ":root {}")
                self.assertEqual(css.read_bytes(), original)
                self.assertEqual(css.stat().st_ino, inode)
        self.assertFalse(self.state.exists())

    def test_symlinked_quick_css_and_runtime_directories_are_refused(self):
        root = self.runtime()
        css = root / "settings/quickCss.css"
        unrelated = self.write(self.root / "unrelated.css", "do not change")
        css.unlink()
        css.symlink_to(unrelated)
        with self.assertRaises(ValueError):
            sync.sync_vesktop(self.config, self.state, ":root {}")
        self.assertEqual(unrelated.read_text(), "do not change")
        css.unlink()
        settings = root / "settings"
        moved = root / "custom-settings"
        settings.rename(moved)
        settings.symlink_to(moved)
        with self.assertRaises(ValueError):
            sync.sync_vesktop(self.config, self.state, ":root {}")
        settings.unlink()
        relocated = self.root / "custom-runtime"
        root.rename(relocated)
        root.symlink_to(relocated)
        with self.assertRaises(ValueError):
            sync.sync_vesktop(self.config, self.state, ":root {}")
        self.assertFalse(self.state.exists())

    def test_exact_managed_vesktop_symlink_becomes_private_runtime_copy(self):
        settings = {"useQuickCss": False, "enabledThemes": ["custom.css"], "plugins": {"keep": True}}
        settings_source = self.write(self.template / "settings/settings.json", json.dumps(settings))
        original_settings = settings_source.read_bytes()
        self.write(self.template / "settings/quickCss.css", ".custom { color: red; }\n")
        self.write(self.template / "settings.json", '{"windowBounds":{"width":1024}}')
        self.write(self.template / "sessionData/runtime.db", b"private runtime data\0\xff")
        destination = self.config / "vesktop"
        destination.parent.mkdir(parents=True)
        destination.symlink_to(self.template)
        sync.prepare_vesktop(self.config, self.state, self.template)
        self.assertFalse(destination.is_symlink())
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
        updated = json.loads((destination / "settings/settings.json").read_text())
        self.assertEqual(updated, {**settings, "useQuickCss": True})
        for name in ("settings/quickCss.css", "settings.json", "sessionData/runtime.db"):
            self.assertEqual((destination / name).read_bytes(), (self.template / name).read_bytes())
        self.assertEqual(settings_source.read_bytes(), original_settings)
        saved = list((self.state / "app-theme-backups").glob("vesktop-*/vesktop"))
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0].is_symlink())
        self.assertEqual(os.readlink(saved[0]), str(self.template))
        self.assertEqual(list(self.config.glob(".vesktop-stage-*")), [])
        settings_path = destination / "settings/settings.json"
        before = settings_path.stat().st_mtime_ns
        sync.prepare_vesktop(self.config, self.state, self.template)
        self.assertEqual(settings_path.stat().st_mtime_ns, before)

    def test_existing_vesktop_runtime_settings_are_merged_not_replaced(self):
        root = self.runtime("/* user */", {"useQuickCss": False, "custom": {"value": 7}})
        preferences = self.write(root / "settings.json", '{"windowBounds":{"x":18}}')
        sync.prepare_vesktop(self.config, self.state, self.template)
        self.assertEqual(json.loads((root / "settings/settings.json").read_text()), {
            "useQuickCss": True, "custom": {"value": 7},
        })
        self.assertEqual((root / "settings/quickCss.css").read_text(), "/* user */")
        self.assertEqual(preferences.read_text(), '{"windowBounds":{"x":18}}')
        copies = list((self.state / "app-theme-backups").glob("vesktop-*/settings.json"))
        self.assertEqual(len(copies), 1)
        self.assertFalse(json.loads(copies[0].read_text())["useQuickCss"])

    def test_running_vesktop_and_indeterminate_process_check_are_refused(self):
        self.runtime("/* user */")
        for results in ((0,), (2,), (1, 0), (1, 2)):
            with self.subTest(results=results):
                self.commands.side_effect = [subprocess.CompletedProcess([], code) for code in results]
                with self.assertRaises(ValueError):
                    sync.prepare_vesktop(self.config, self.state, self.template)
                self.assertEqual((self.config / "vesktop/settings/quickCss.css").read_text(), "/* user */")
                self.assertFalse(self.state.exists())

    def test_custom_vesktop_symlink_is_never_materialized(self):
        custom = self.root / "custom-vesktop"
        self.write(custom / "settings/settings.json", '{"useQuickCss":false}')
        self.config.mkdir()
        destination = self.config / "vesktop"
        destination.symlink_to(custom)
        with self.assertRaisesRegex(ValueError, "custom Vesktop symlink"):
            sync.prepare_vesktop(self.config, self.state, self.template)
        self.assertTrue(destination.is_symlink())
        self.assertEqual((custom / "settings/settings.json").read_text(), '{"useQuickCss":false}')
        self.assertFalse(self.state.exists())

    def test_failed_vesktop_materialization_restores_original_symlink(self):
        self.write(self.template / "settings/settings.json", '{"useQuickCss":true}')
        self.config.mkdir()
        destination = self.config / "vesktop"
        destination.symlink_to(self.template)
        with mock.patch.object(sync.os, "replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                sync.prepare_vesktop(self.config, self.state, self.template)
        self.assertTrue(destination.is_symlink())
        self.assertEqual(os.readlink(destination), str(self.template))
        self.assertEqual(list(self.config.glob(".vesktop-stage-*")), [])

    def test_malformed_and_symlinked_vesktop_settings_are_preserved(self):
        root = self.runtime()
        settings = root / "settings/settings.json"
        for content in ("{invalid", "[]", "null", "false", "42", '"text"', b"\xff"):
            with self.subTest(content=content):
                self.write(settings, content)
                before = settings.read_bytes()
                with self.assertRaises(ValueError):
                    sync.prepare_vesktop(self.config, self.state, self.template)
                self.assertEqual(settings.read_bytes(), before)
        target = self.write(self.root / "custom-settings.json", '{"useQuickCss":false}')
        settings.unlink()
        settings.symlink_to(target)
        with self.assertRaises(ValueError):
            sync.prepare_vesktop(self.config, self.state, self.template)
        self.assertEqual(target.read_text(), '{"useQuickCss":false}')
        self.assertFalse(self.state.exists())

    def test_nonregular_vesktop_settings_are_rejected_before_reading(self):
        root = self.runtime()
        settings = root / "settings/settings.json"
        settings.unlink()
        for kind in ("directory", "fifo"):
            if kind == "directory":
                settings.mkdir()
            else:
                os.mkfifo(settings)
            with self.subTest(kind=kind):
                with mock.patch.object(Path, "read_text", side_effect=AssertionError("must reject before reading")):
                    with self.assertRaises(ValueError):
                        sync.prepare_vesktop(self.config, self.state, self.template)
            if kind == "directory":
                settings.rmdir()
            else:
                settings.unlink()
        self.assertFalse(self.state.exists())

    def test_spotify_palette_validation_is_strict(self):
        valid = self.palette_bytes()
        self.assertEqual(sync.validate_spotify_palette(valid), self.palette())
        self.assertEqual(sync.validate_spotify_palette(valid + b" " * (4096 - len(valid))), self.palette())
        invalid = [b"not JSON", b"\xff", valid + b" " * (4097 - len(valid))]
        invalid.extend(json.dumps(value).encode() for value in ([], None, True, 1, "palette"))
        for key, values in (
            ("schema", (True, False, 1.0, "1", 0, 2, None)),
            ("theme", ([], {}, True, None, "unknown")),
            ("colors", ([], None, {}, {**self.palette()["colors"], "extra": "#ffffff"})),
        ):
            invalid.extend(json.dumps({**self.palette(), key: value}).encode() for value in values)
        invalid.append(json.dumps({**self.palette(), "extra": True}).encode())
        for key in ("schema", "theme", "colors"):
            invalid.append(json.dumps({name: value for name, value in self.palette().items() if name != key}).encode())
        for color in (None, 123, "#abc", "#12345678", "#gggggg", "red", "#123456\n"):
            palette = self.palette()
            palette["colors"]["focus"] = color
            invalid.append(json.dumps(palette).encode())
        for content in invalid:
            with self.subTest(content=content[:100]):
                with self.assertRaises(ValueError):
                    sync.validate_spotify_palette(content)

    def test_spotify_not_installed_or_not_spicetify_patched_is_skipped(self):
        self.assertFalse(sync.sync_spotify(self.config, self.home, self.palette_bytes()))
        self.assertFalse(self.home.exists())
        xpui = self.spotify(patched=False)
        self.assertFalse(sync.sync_spotify(self.config, self.home, self.palette_bytes()))
        self.write(xpui / "spicetifyWrapper.js", "wrong marker location")
        self.assertFalse(sync.sync_spotify(self.config, self.home, self.palette_bytes()))
        self.assertFalse((xpui / "hyprland-dots").exists())

    def test_spotify_palette_publish_update_and_idempotency(self):
        xpui = self.spotify()
        destination = xpui / "hyprland-dots/palette.json"
        for content in (self.palette_bytes(), self.palette_bytes("reze", "#abcdef")):
            with self.subTest(content=content[:80]):
                self.assertTrue(sync.sync_spotify(self.config, self.home, content))
                self.assertEqual(destination.read_bytes(), content)
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o644)
                before = (destination.stat().st_ino, destination.stat().st_mtime_ns)
                self.assertTrue(sync.sync_spotify(self.config, self.home, content))
                self.assertEqual((destination.stat().st_ino, destination.stat().st_mtime_ns), before)

    def test_spotify_configured_install_path_is_used(self):
        spotify = self.root / "custom Spotify installation"
        xpui = self.spotify(spotify)
        settings = self.write(self.config / "spicetify/config-xpui.ini", f"[Setting]\nspotify_path = {spotify}\n")
        before = settings.read_bytes()
        self.assertTrue(sync.sync_spotify(self.config, self.home, self.palette_bytes()))
        self.assertEqual((xpui / "hyprland-dots/palette.json").read_bytes(), self.palette_bytes())
        self.assertEqual(settings.read_bytes(), before)
        self.assertFalse(self.home.exists())

    def test_spotify_quoted_configured_path_with_spaces_is_used(self):
        spotify = self.root / "custom Spotify installation"
        xpui = self.spotify(spotify)
        for quote in ("'", '"'):
            with self.subTest(quote=quote):
                settings = self.write(
                    self.config / "spicetify/config-xpui.ini",
                    f"[Setting]\nspotify_path = {quote}{spotify}{quote}\n",
                )
                before = settings.read_bytes()
                self.assertTrue(sync.sync_spotify(self.config, self.home, self.palette_bytes()))
                self.assertEqual((xpui / "hyprland-dots/palette.json").read_bytes(), self.palette_bytes())
                self.assertEqual(settings.read_bytes(), before)
        self.assertFalse(self.home.exists())

    def test_spotify_relative_configured_path_is_refused(self):
        for relative in ("relative Spotify", "./spotify", "../spotify", '"relative Spotify"'):
            with self.subTest(relative=relative):
                settings = self.write(
                    self.config / "spicetify/config-xpui.ini",
                    f"[Setting]\nspotify_path = {relative}\n",
                )
                before = settings.read_bytes()
                with self.assertRaisesRegex(ValueError, "absolute path"):
                    sync.sync_spotify(self.config, self.home, self.palette_bytes())
                self.assertEqual(settings.read_bytes(), before)
        self.assertFalse(self.home.exists())

    def test_spotify_custom_directory_and_palette_symlinks_are_refused(self):
        xpui = self.spotify()
        managed = xpui / "hyprland-dots"
        other = self.root / "unrelated-spotify"
        other.mkdir()
        managed.symlink_to(other)
        with self.assertRaises(ValueError):
            sync.sync_spotify(self.config, self.home, self.palette_bytes())
        self.assertEqual(list(other.iterdir()), [])
        managed.unlink()
        managed.mkdir()
        for dangling in (False, True):
            with self.subTest(dangling=dangling):
                target = other / f"palette-{dangling}.json"
                if not dangling:
                    target.write_bytes(self.palette_bytes())
                destination = managed / "palette.json"
                destination.symlink_to(target)
                with self.assertRaises(ValueError):
                    sync.sync_spotify(self.config, self.home, self.palette_bytes())
                self.assertTrue(destination.is_symlink())
                if dangling:
                    self.assertFalse(target.exists())
                else:
                    self.assertEqual(target.read_bytes(), self.palette_bytes())
                destination.unlink()

    def test_foreign_spotify_palette_and_invalid_incoming_palette_are_preserved(self):
        xpui = self.spotify()
        destination = self.write(xpui / "hyprland-dots/palette.json", '{"unrelated":true}')
        before = destination.read_bytes()
        with self.assertRaises(ValueError):
            sync.sync_spotify(self.config, self.home, self.palette_bytes())
        self.assertEqual(destination.read_bytes(), before)
        destination.write_bytes(self.palette_bytes())
        with self.assertRaises(ValueError):
            sync.sync_spotify(self.config, self.home, b"[]")
        self.assertEqual(destination.read_bytes(), self.palette_bytes())

    def test_nonregular_spotify_palette_is_rejected_before_reading(self):
        destination = self.spotify() / "hyprland-dots/palette.json"
        destination.parent.mkdir()
        for kind in ("directory", "fifo"):
            if kind == "directory":
                destination.mkdir()
            else:
                os.mkfifo(destination)
            with self.subTest(kind=kind):
                with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("must reject before reading")):
                    with self.assertRaises(ValueError):
                        sync.sync_spotify(self.config, self.home, self.palette_bytes())
            if kind == "directory":
                destination.rmdir()
            else:
                destination.unlink()

    def test_atomic_write_failure_and_nonregular_destinations_are_safe(self):
        destination = self.write(self.root / "palette.json", "original")
        with mock.patch.object(sync.os, "replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                sync.atomic_write(destination, b"replacement")
        self.assertEqual(destination.read_text(), "original")
        self.assertEqual(list(self.root.iterdir()), [destination])
        destination.unlink()
        for kind in ("symlink", "directory", "fifo"):
            if kind == "symlink":
                destination.symlink_to(self.root / "nonexistent-target")
            elif kind == "directory":
                destination.mkdir()
            else:
                os.mkfifo(destination)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                sync.atomic_write(destination, b"replacement")
            if kind == "directory":
                destination.rmdir()
            else:
                destination.unlink()

    def test_custom_firefox_manifests_are_skipped_without_commands(self):
        self.assertFalse(sync.update_firefox(self.cache, self.home))
        for values in (
            {"name": "custom"}, {"type": "file"},
            {"path": "/some/custom/native-host"},
            {"allowed_extensions": ["pywalfox@frewacom.org", "another-addon"]},
            {"allowed_extensions": "pywalfox@frewacom.org"},
        ):
            with self.subTest(values=values):
                manifest = self.firefox(**values)
                before = manifest.read_bytes()
                self.assertFalse(sync.update_firefox(self.cache, self.home))
                self.assertEqual(manifest.read_bytes(), before)
        self.commands.assert_not_called()

    def test_malformed_and_symlinked_firefox_manifests_do_not_trigger_updates(self):
        manifest = self.firefox()
        for content in ("[]", "null", "42", "false"):
            manifest.write_text(content)
            self.assertFalse(sync.update_firefox(self.cache, self.home))
        manifest.write_text("{broken")
        self.assertFalse(sync.update_firefox(self.cache, self.home))
        manifest = self.firefox()
        other = self.root / "external-native-host.json"
        manifest.rename(other)
        manifest.symlink_to(other)
        self.assertFalse(sync.update_firefox(self.cache, self.home))
        self.commands.assert_not_called()

    def test_firefox_update_requires_managed_host_and_uses_private_cache(self):
        manifest = self.firefox()
        original = manifest.read_bytes()
        self.commands.side_effect = None
        self.commands.return_value = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(sync.shutil, "which", side_effect=AssertionError("must not discover PATH executables")):
            self.assertTrue(sync.update_firefox(self.cache, self.home))
        args, kwargs = self.commands.call_args
        wrapper = self.data / "hyprland-dots/firefox/native-host.sh"
        self.assertEqual(args[0], [str(wrapper), "--update"])
        self.assertEqual(kwargs["env"]["XDG_CACHE_HOME"], str(self.cache / "hyprland-dots/firefox"))
        self.assertTrue(kwargs["check"])
        self.assertEqual(manifest.read_bytes(), original)

    def test_firefox_missing_nonexecutable_and_symlinked_wrappers_are_skipped(self):
        self.firefox()
        wrapper = self.data / "hyprland-dots/firefox/native-host.sh"
        wrapper.chmod(0o600)
        self.assertFalse(sync.update_firefox(self.cache, self.home))
        wrapper.unlink()
        self.assertFalse(sync.update_firefox(self.cache, self.home))
        target = self.write(self.root / "custom-native-host.sh", "#!/bin/sh\n")
        target.chmod(0o700)
        wrapper.symlink_to(target)
        self.assertFalse(sync.update_firefox(self.cache, self.home))
        self.commands.assert_not_called()

    def test_sync_uses_one_active_generation_even_when_pointer_changes(self):
        first = self.generation("first", "after-school", "#123456")
        second = self.generation("second", "reze", "#abcdef")
        active = self.cache / "hyprland-dots/active-theme"
        active.symlink_to(first)
        args = argparse.Namespace(install_vesktop=False, verbose=False)

        def vesktop(config, state, palette):
            self.assertEqual(palette, (first / "vesktop.css").read_text())
            active.unlink()
            active.symlink_to(second)
            return True

        with mock.patch.object(sync, "sync_vesktop", side_effect=vesktop):
            with mock.patch.object(sync, "sync_spotify", return_value=True) as spotify:
                with mock.patch.object(sync, "update_firefox", return_value=False):
                    self.assertEqual(sync.sync_apps(args, self.home, self.config, self.cache, self.state), 0)
        spotify.assert_called_once_with(self.config, self.home, (first / "spotify-palette.json").read_bytes())
        self.assertEqual(active.resolve(), second.resolve())

    def test_missing_generation_skips_all_app_operations(self):
        args = argparse.Namespace(install_vesktop=False, verbose=False)
        with mock.patch.object(sync, "sync_vesktop") as vesktop:
            with mock.patch.object(sync, "sync_spotify") as spotify:
                with mock.patch.object(sync, "update_firefox") as firefox:
                    self.assertEqual(sync.sync_apps(args, self.home, self.config, self.cache, self.state), 0)
        vesktop.assert_not_called()
        spotify.assert_not_called()
        firefox.assert_not_called()
        self.assertFalse(self.home.exists())
        self.assertFalse(self.cache.exists())

    def test_install_vesktop_only_materializes_without_syncing_apps(self):
        generation = self.generation("first", "after-school", "#123456")
        (self.cache / "hyprland-dots/active-theme").symlink_to(generation)
        args = argparse.Namespace(install_vesktop=True, verbose=False)
        with mock.patch.object(sync, "prepare_vesktop") as prepare:
            with mock.patch.object(sync, "sync_vesktop") as vesktop:
                with mock.patch.object(sync, "sync_spotify") as spotify:
                    with mock.patch.object(sync, "update_firefox") as firefox:
                        self.assertEqual(sync.sync_apps(args, self.home, self.config, self.cache, self.state), 0)
        prepare.assert_called_once_with(self.config, self.state)
        vesktop.assert_not_called()
        spotify.assert_not_called()
        firefox.assert_not_called()

    def test_one_app_failure_does_not_skip_other_apps(self):
        generation = self.generation("first", "after-school", "#123456")
        (self.cache / "hyprland-dots/active-theme").symlink_to(generation)
        args = argparse.Namespace(install_vesktop=False, verbose=True)
        errors = io.StringIO()
        with mock.patch.object(sync, "sync_vesktop", side_effect=ValueError("custom CSS needs attention")):
            with mock.patch.object(sync, "sync_spotify", return_value=True) as spotify:
                with mock.patch.object(sync, "update_firefox", return_value=False) as firefox:
                    with contextlib.redirect_stderr(errors), contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(sync.sync_apps(args, self.home, self.config, self.cache, self.state), 1)
        spotify.assert_called_once()
        firefox.assert_called_once()
        self.assertIn("Vesktop", errors.getvalue())

    def test_main_serializes_invocations_with_its_own_lock(self):
        first_inside = threading.Event()
        release_first = threading.Event()
        second_inside = threading.Event()
        second_lock_attempt = threading.Event()
        results = []
        errors = []
        calls = []
        lock_calls = []
        original_flock = sync.fcntl.flock

        def flock(descriptor, operation):
            lock_calls.append(operation)
            if len(lock_calls) == 2:
                second_lock_attempt.set()
            return original_flock(descriptor, operation)

        def operation(*args):
            calls.append(args)
            if len(calls) == 1:
                first_inside.set()
                if not release_first.wait(5):
                    raise AssertionError("timed out releasing first sync")
            else:
                second_inside.set()
            return 0

        def run():
            try:
                results.append(sync.main())
            except BaseException as error:
                errors.append(error)

        with mock.patch.object(Path, "home", return_value=self.home):
            with mock.patch.object(sync.sys, "argv", [str(SCRIPT)]):
                with mock.patch.object(sync, "sync_apps", side_effect=operation):
                    with mock.patch.object(sync.fcntl, "flock", side_effect=flock):
                        threads = [threading.Thread(target=run, daemon=True) for _ in range(2)]
                        try:
                            threads[0].start()
                            self.assertTrue(first_inside.wait(3))
                            threads[1].start()
                            self.assertTrue(second_lock_attempt.wait(3))
                            self.assertFalse(second_inside.wait(0.05))
                        finally:
                            release_first.set()
                            for thread in threads:
                                if thread.ident is not None:
                                    thread.join(3)
                        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(results, [0, 0])
        self.assertTrue(second_inside.is_set())
        lock = self.state / "app-theme-sync.lock"
        self.assertTrue(lock.is_file())
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)

    def test_sync_lock_rejects_symlinks_and_nonregular_files(self):
        self.state.mkdir(parents=True)
        lock = self.state / "app-theme-sync.lock"
        unrelated = self.write(self.root / "unrelated-lock", "keep")
        lock.symlink_to(unrelated)
        with self.assertRaises(OSError):
            with sync.sync_lock(self.state):
                self.fail("entered a symlinked lock")
        self.assertEqual(unrelated.read_text(), "keep")
        lock.unlink()
        os.mkfifo(lock)
        with self.assertRaises(ValueError):
            with sync.sync_lock(self.state):
                self.fail("entered a nonregular lock")
        self.assertTrue(stat.S_ISFIFO(lock.stat().st_mode))


if __name__ == "__main__":
    unittest.main()
