import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/setup-firefox-theme.py"
SPEC = importlib.util.spec_from_file_location("setup_firefox_theme", SCRIPT)
setup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = setup
SPEC.loader.exec_module(setup)


class FirefoxThemeSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="firefox-setup-test-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "home with 'quote"
        self.paths = setup.Paths.for_user(self.home, {})
        self.binary = self.root / "custom pipx bin/pywalfox"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.binary.chmod(0o700)
        self.profile = self.home / ".mozilla/firefox/test.default"
        self.profile.mkdir(parents=True)
        for name in ("user.js", "prefs.js", "chrome/userChrome.css"):
            target = self.profile / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"original {name}\n", encoding="utf-8")
        self.profile_before = self.profile_snapshot()
        self.installs = []

    def tearDown(self):
        self.temporary.cleanup()

    def profile_snapshot(self):
        return {str(path.relative_to(self.profile)): path.read_bytes()
                for path in self.profile.rglob("*") if path.is_file()}

    def write_palette(self):
        self.paths.palette_source.parent.mkdir(parents=True, exist_ok=True)
        self.paths.palette_source.write_text(json.dumps({
            "wallpaper": "",
            "colors": {f"color{i}": "#123456" for i in range(16)},
        }), encoding="utf-8")

    def native_install(self, args, **kwargs):
        self.assertEqual(args, [self.binary, "install", "--executable", self.paths.wrapper])
        self.assertFalse(setup.lexists(self.paths.manifest))
        self.installs.append(args)
        self.paths.manifest.write_text(json.dumps({
            "name": "pywalfox",
            "description": "Upstream native host",
            "path": str(self.paths.wrapper),
            "type": "stdio",
            "allowed_extensions": [setup.ADDON_ID],
        }), encoding="utf-8")
        return "installed"

    def configure(self, command=None):
        with contextlib.redirect_stdout(io.StringIO()):
            with setup.setup_lock(self.paths):
                with mock.patch.object(setup, "run_command", side_effect=command or self.native_install):
                    setup.setup_host(self.paths, self.binary)

    def test_fresh_setup_and_check_preserve_profiles(self):
        self.write_palette()
        self.configure()
        self.assertEqual(setup.check_host(self.paths, self.binary), [])
        self.assertEqual(self.paths.wrapper.stat().st_mode & 0o777, 0o700)
        self.assertEqual(os.readlink(self.paths.palette), str(self.paths.palette_source))
        self.assertEqual(self.profile_snapshot(), self.profile_before)
        self.assertFalse(self.paths.backups.exists())
        self.assertEqual(len(self.installs), 1)

    def test_repeat_is_idempotent(self):
        self.write_palette()
        self.configure()
        before = {path: path.lstat().st_mtime_ns
                  for path in (self.paths.wrapper, self.paths.palette, self.paths.manifest)}
        self.configure()
        self.assertEqual(before, {path: path.lstat().st_mtime_ns for path in before})
        self.assertEqual(len(self.installs), 1)
        self.assertFalse(self.paths.backups.exists())

    def test_existing_files_are_backed_up(self):
        old_files = {
            self.paths.wrapper: ("native-host.sh", b"old wrapper\n"),
            self.paths.palette: ("colors.json", b"old palette\n"),
            self.paths.manifest: ("pywalfox.json", b'{"name":"other"}\n'),
        }
        for path, (_, content) in old_files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.configure()
        backups = list(self.paths.backups.iterdir())
        self.assertEqual(len(backups), 1)
        for name, content in old_files.values():
            self.assertEqual((backups[0] / name).read_bytes(), content)
        self.assertEqual(self.profile_snapshot(), self.profile_before)

    def test_manifest_symlink_does_not_overwrite_its_referent(self):
        for dangling in (False, True):
            with self.subTest(dangling=dangling):
                referent = self.root / f"unrelated-{dangling}.json"
                if not dangling:
                    referent.write_text("untouched", encoding="utf-8")
                self.paths.manifest.parent.mkdir(parents=True, exist_ok=True)
                self.paths.manifest.unlink(missing_ok=True)
                self.paths.manifest.symlink_to(referent)
                self.configure()
                self.assertFalse(self.paths.manifest.is_symlink())
                if dangling:
                    self.assertFalse(referent.exists())
                else:
                    self.assertEqual(referent.read_text(encoding="utf-8"), "untouched")
                self.assertTrue(any(
                    (backup / "pywalfox.json").is_symlink()
                    and os.readlink(backup / "pywalfox.json") == str(referent)
                    for backup in self.paths.backups.iterdir()
                ))

    def test_install_failure_restores_original_files(self):
        original = {}
        for path in (self.paths.wrapper, self.paths.palette, self.paths.manifest):
            path.parent.mkdir(parents=True, exist_ok=True)
            original[path] = f"original {path.name}".encode()
            path.write_bytes(original[path])

        def failure(args, **kwargs):
            self.paths.manifest.write_text("partial upstream manifest", encoding="utf-8")
            raise setup.SetupError("simulated upstream failure")

        with self.assertRaisesRegex(setup.SetupError, "previous files restored"):
            self.configure(failure)
        for path, content in original.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(self.profile_snapshot(), self.profile_before)

    def test_new_install_failure_removes_only_new_leaves(self):
        def failure(args, **kwargs):
            raise setup.SetupError("simulated upstream failure")

        with self.assertRaises(setup.SetupError):
            self.configure(failure)
        self.assertFalse(setup.lexists(self.paths.wrapper))
        self.assertFalse(setup.lexists(self.paths.palette))
        self.assertFalse(setup.lexists(self.paths.manifest))
        self.assertEqual(self.profile_snapshot(), self.profile_before)

    def test_failed_install_restores_original_manifest_symlink(self):
        referent = self.root / "existing-host.json"
        referent.write_text("existing native host", encoding="utf-8")
        self.paths.manifest.parent.mkdir(parents=True)
        self.paths.manifest.symlink_to(referent)

        def failure(args, **kwargs):
            self.assertFalse(setup.lexists(self.paths.manifest))
            self.paths.manifest.write_text("partial replacement", encoding="utf-8")
            raise setup.SetupError("simulated upstream failure")

        with self.assertRaises(setup.SetupError):
            self.configure(failure)
        self.assertTrue(self.paths.manifest.is_symlink())
        self.assertEqual(os.readlink(self.paths.manifest), str(referent))
        self.assertEqual(referent.read_text(encoding="utf-8"), "existing native host")

    def test_rejects_directories_at_managed_file_paths(self):
        self.paths.manifest.mkdir(parents=True)
        with self.assertRaisesRegex(setup.SetupError, "non-file"):
            self.configure()
        self.assertTrue(self.paths.manifest.is_dir())
        self.assertEqual(self.installs, [])

    def test_check_does_not_write_or_install(self):
        before = sorted(str(path) for path in self.root.rglob("*"))
        with mock.patch.object(setup.sys, "platform", "linux"):
            with mock.patch.object(setup.os, "geteuid", return_value=1000):
                with mock.patch.object(setup.Paths, "for_user", return_value=self.paths):
                    with mock.patch.object(setup, "pywalfox_binary", return_value=self.binary) as binary:
                        with contextlib.redirect_stderr(io.StringIO()):
                            self.assertEqual(setup.main(["--check"]), 1)
                        binary.assert_called_once_with(install=False)
        self.assertEqual(before, sorted(str(path) for path in self.root.rglob("*")))

    def test_readiness_checks_reject_fifo_files_without_reading_them(self):
        self.write_palette()
        self.configure()
        for path, check, expected in (
            (self.paths.manifest, lambda: setup.manifest_matches(self.paths), False),
            (self.paths.wrapper, lambda: setup.wrapper_matches(self.paths, self.binary), False),
            (self.paths.palette_source, lambda: bool(setup.palette_errors(self.paths)), True),
        ):
            with self.subTest(path=path):
                content = path.read_bytes()
                mode = path.stat().st_mode & 0o777
                path.unlink()
                os.mkfifo(path)
                with mock.patch.object(Path, "read_text", side_effect=AssertionError("must reject FIFO before reading")):
                    self.assertEqual(check(), expected)
                path.unlink()
                path.write_bytes(content)
                path.chmod(mode)

    def test_successful_check_does_not_claim_live_browser_delivery(self):
        self.write_palette()
        self.configure()
        output = io.StringIO()
        with mock.patch.object(setup.sys, "platform", "linux"):
            with mock.patch.object(setup.os, "geteuid", return_value=1000):
                with mock.patch.object(setup.Paths, "for_user", return_value=self.paths):
                    with mock.patch.object(setup, "pywalfox_binary", return_value=self.binary):
                        with contextlib.redirect_stdout(output):
                            self.assertEqual(setup.main(["--check"]), 0)
        self.assertIn("live delivery are not checked", output.getvalue())
        self.assertIn("CSS modifications are disabled", output.getvalue())

    def test_existing_different_pywalfox_version_is_not_replaced(self):
        with mock.patch.object(setup.shutil, "which", return_value="/usr/bin/pipx"):
            with mock.patch.object(setup, "run_command", side_effect=[str(self.binary.parent), "v2.7.4"]) as run:
                with self.assertRaisesRegex(setup.SetupError, "left unchanged"):
                    setup.pywalfox_binary(install=True)
        self.assertEqual(run.call_args_list, [
            mock.call(["/usr/bin/pipx", "environment", "--value", "PIPX_BIN_DIR"]),
            mock.call([self.binary, "--version"]),
        ])

    def test_pipx_install_is_pinned_and_uses_resolved_bin_dir(self):
        self.binary.unlink()
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if args[1:] == ["environment", "--value", "PIPX_BIN_DIR"]:
                return str(self.binary.parent)
            if args[1:] == ["install", "pywalfox==2.9.0"]:
                self.binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                self.binary.chmod(0o700)
                return "installed"
            if args == [self.binary, "--version"]:
                return "v2.9.0"
            self.fail(f"unexpected command: {args}")

        with mock.patch.object(setup.shutil, "which", return_value="/usr/bin/pipx"):
            with mock.patch.object(setup, "run_command", side_effect=run):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(setup.pywalfox_binary(install=True), self.binary)
        self.assertEqual(calls[1], ["/usr/bin/pipx", "install", "pywalfox==2.9.0"])

    def test_wrapper_quotes_paths_and_does_not_forward_firefox_arguments(self):
        self.configure()
        subprocess.run(["/bin/sh", "-n", str(self.paths.wrapper)], check=True)
        self.binary.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$XDG_CACHE_HOME\" \"$#\" \"$@\"\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [str(self.paths.wrapper), str(self.paths.manifest), setup.ADDON_ID],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.splitlines(), [
            str(self.paths.cache), "3", "start", "--profile-path",
            str(self.paths.cache / "profile-access-disabled"),
        ])
        self.assertFalse((self.paths.cache / "profile-access-disabled").exists())
        self.assertEqual(self.profile_snapshot(), self.profile_before)

    def test_wrapper_update_uses_pinned_binary_and_private_cache_without_profiles(self):
        self.configure()
        self.binary.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$XDG_CACHE_HOME\" \"$#\" \"$@\"\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [str(self.paths.wrapper), "--update", "ignored-extra-argument"],
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.splitlines(), [str(self.paths.cache), "1", "update"])
        self.assertFalse((self.paths.cache / "profile-access-disabled").exists())
        self.assertEqual(self.profile_snapshot(), self.profile_before)

    def test_palette_check_detects_lexicographic_color_order(self):
        self.write_palette()
        self.configure()
        data = json.loads(self.paths.palette.read_text(encoding="utf-8"))
        self.paths.palette_source.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        self.assertIn("numeric insertion order", setup.palette_errors(self.paths)[0])

    def test_relative_xdg_path_is_rejected(self):
        with self.assertRaisesRegex(setup.SetupError, "absolute path"):
            setup.Paths.for_user(self.home, {"XDG_CACHE_HOME": "relative/cache"})

    def test_root_is_rejected_before_any_setup(self):
        with mock.patch.object(setup.sys, "platform", "linux"):
            with mock.patch.object(setup.os, "geteuid", return_value=0):
                with mock.patch.object(setup, "pywalfox_binary") as binary:
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(setup.main([]), 1)
                    binary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
