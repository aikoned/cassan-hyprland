import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LEGACY_WALLPAPER = "sw" + "ww"
HOME_ERROR = "machine-specific /home path found"
WALLPAPER_ERROR = "obsolete " + LEGACY_WALLPAPER + " command found"


class RuntimeDataValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if any(shutil.which(command) is None for command in ("bash", "git", "rg")):
            raise unittest.SkipTest("validator fixtures require bash, git, and rg")
        source = (ROOT / "scripts/check.sh").read_text(encoding="utf-8")
        blocks = re.findall(r"(?ms)^if rg\b.*?^fi$", source)
        cls.scans = {}
        for marker in (HOME_ERROR, WALLPAPER_ERROR):
            matches = [block for block in blocks if marker in block]
            if len(matches) != 1:
                raise AssertionError(f"expected one actual validator scan for {marker!r}")
            cls.scans[marker] = matches[0]
        cls.ignore_bytes = (ROOT / ".gitignore").read_bytes()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="runtime-data-validation-")
        self.base = Path(self.temporary.name)
        self.outside = self.base / "outside working directory"
        self.outside.mkdir()
        self.environment = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_") and key != "RIPGREP_CONFIG_PATH"
        }
        self.environment.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self, is_git):
        root = self.base / ("git clone with spaces" if is_git else "archive copy with spaces")
        root.mkdir()
        for component in ("hypr", "waybar", "swaync", "wofi", "kitty", "fastfetch", "vesktop",
                          "spicetify", "wlogout", "zathura"):
            (root / component).mkdir()
        (root / ".zshrc").write_text("# shell fixture\n", encoding="utf-8")
        (root / ".gitignore").write_bytes(self.ignore_bytes)
        if is_git:
            subprocess.run(["git", "-c", "init.templateDir=", "init", "--quiet", str(root)],
                           env=self.environment, cwd=self.outside, check=True, capture_output=True)
        runtime = {
            root / "vesktop/sessionData/chromium.log": b"cached profile path: /home/fixture-user/.config/vesktop\n",
            root / "vesktop/sessionData/Cache/old-session.txt":
                ("cached command: " + LEGACY_WALLPAPER + "-daemon\n").encode(),
            root / "vesktop/sessionData/Cache/private-bytes": b"\x00\xff\x01private fixture bytes\n",
        }
        for path, content in runtime.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return root, runtime

    def scan(self, marker, root, runtime, *, outside):
        try:
            result = subprocess.run(
                ["bash", "-c", 'set -euo pipefail\nrepo_dir="$1"\n' + self.scans[marker],
                 "validator-scan", str(root)],
                cwd=self.outside if outside else root,
                env=self.environment, capture_output=True, text=True, check=False, timeout=10,
            )
        finally:
            for path, original in runtime.items():
                self.assertEqual(path.read_bytes(), original, f"runtime data changed: {path.name}")
        return result

    def assert_runtime_scan_clean(self, marker):
        for is_git in (False, True):
            root, runtime = self.fixture(is_git)
            for outside in (False, True):
                with self.subTest(is_git=is_git, outside=outside):
                    result = self.scan(marker, root, runtime, outside=outside)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertEqual(result.stderr, "")

    def test_cached_home_paths_are_ignored_across_repository_and_cwd_variants(self):
        self.assert_runtime_scan_clean(HOME_ERROR)

    def test_cached_legacy_commands_are_ignored_across_repository_and_cwd_variants(self):
        self.assert_runtime_scan_clean(WALLPAPER_ERROR)

    def test_real_machine_specific_app_configuration_still_fails(self):
        for is_git in (False, True):
            root, runtime = self.fixture(is_git)
            shipped = root / "vesktop/settings.json"
            shipped.write_text('{"fixture_path":"/home/shipped-user/theme.css"}\n', encoding="utf-8")
            for outside in (False, True):
                with self.subTest(is_git=is_git, outside=outside):
                    result = self.scan(HOME_ERROR, root, runtime, outside=outside)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn(HOME_ERROR, result.stderr)
                    self.assertIn(str(shipped), result.stdout)
                    self.assertNotIn("sessionData", result.stdout)

    def test_similarly_named_shipped_directory_is_not_blanket_excluded(self):
        for is_git in (False, True):
            root, runtime = self.fixture(is_git)
            shipped = root / "vesktop/sessionData-template/example.conf"
            shipped.parent.mkdir()
            shipped.write_text("path=/home/shipped-user\ncommand=" + LEGACY_WALLPAPER + "\n", encoding="utf-8")
            for outside in (False, True):
                for marker in self.scans:
                    with self.subTest(is_git=is_git, outside=outside, scan=marker):
                        result = self.scan(marker, root, runtime, outside=outside)
                        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                        self.assertIn(marker, result.stderr)
                        self.assertIn(str(shipped), result.stdout)
                        self.assertNotIn("sessionData/", result.stdout)

    def test_actual_gitignore_excludes_runtime_data_but_not_app_settings(self):
        root, runtime = self.fixture(True)
        (root / "vesktop/settings.json").write_text("{}\n", encoding="utf-8")
        paths = [path.relative_to(root).as_posix() for path in runtime]
        request = ("\0".join([*paths, "vesktop/settings.json"]) + "\0").encode()
        for outside in (False, True):
            with self.subTest(outside=outside):
                result = subprocess.run(
                    ["git", "-C", str(root), "check-ignore", "--stdin", "-z"], input=request,
                    cwd=self.outside if outside else root, env=self.environment,
                    capture_output=True, check=False, timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(set(result.stdout.decode().rstrip("\0").split("\0")), set(paths))
                for path, original in runtime.items():
                    self.assertEqual(path.read_bytes(), original)

    def test_real_legacy_wallpaper_command_still_fails(self):
        for is_git in (False, True):
            root, runtime = self.fixture(is_git)
            shipped = root / "vesktop/start.sh"
            shipped.write_text("#!/bin/sh\n" + LEGACY_WALLPAPER + " img example.png\n", encoding="utf-8")
            for outside in (False, True):
                with self.subTest(is_git=is_git, outside=outside):
                    result = self.scan(WALLPAPER_ERROR, root, runtime, outside=outside)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn(WALLPAPER_ERROR, result.stderr)
                    self.assertIn(str(shipped), result.stdout)
                    self.assertNotIn("sessionData", result.stdout)


if __name__ == "__main__":
    unittest.main()
