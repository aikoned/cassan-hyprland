import configparser
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/setup-spicetify.sh"
EXTENSION = "hyprland-dots-theme.js"
VERSION = "1.2.97.270"
CLI_VERSION = "2.44.0"

FAKE_SPICETIFY = r'''
import configparser
import json
import os
from pathlib import Path
import shutil
import sys

arguments = sys.argv[1:]
with open(os.environ["TEST_CALLS"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(arguments) + "\n")
config_path = Path(os.environ["XDG_CONFIG_HOME"]) / "spicetify/config-xpui.ini"
if arguments == ["--config"]:
    print(os.environ.get("TEST_CONFIG_PATH", str(config_path)))
    raise SystemExit(0)
if arguments == ["--version"]:
    print(os.environ.get("TEST_CLI_VERSION", "2.44.0"))
    raise SystemExit(0)
if os.environ.get("TEST_FAIL") == "config" and arguments[0] == "config":
    raise SystemExit(40)
config = configparser.ConfigParser(interpolation=None)
if config_path.exists():
    config.read(config_path)
for section in ("Setting", "AdditionalOptions", "Backup", "Preprocesses"):
    if not config.has_section(section):
        config.add_section(section)

def save():
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        config.write(handle)

if arguments[0] == "config":
    for key, value in zip(arguments[1::2], arguments[2::2]):
        if key in {"extensions", "custom_apps"}:
            entries = set(filter(None, config.get("AdditionalOptions", key, fallback="").split("|")))
            entries.add(value)
            config.set("AdditionalOptions", key, "|".join(sorted(entries)))
        else:
            config.set("Setting", key, value)
    save()
    raise SystemExit(0)

if arguments[0] != "--no-restart":
    raise SystemExit("Mutating commands must explicitly disable restart")
if os.environ.get("TEST_FAIL") == "apply":
    raise SystemExit(41)
spotify = Path(os.path.expandvars(config.get("Setting", "spotify_path")))
assert str(spotify).startswith(os.environ["TEST_ROOT"] + os.sep)
apps = spotify / "Apps"
current_version = os.environ.get("TEST_SPOTIFY_VERSION", "1.2.97.270")
for action in arguments[1:]:
    if action == "restore":
        if config.get("Backup", "version", fallback="") != current_version:
            raise SystemExit("Unsafe old backup restore")
        shutil.rmtree(apps)
        apps.mkdir()
        (apps / "xpui.spa").write_bytes(b"stock archive")
    elif action == "backup":
        if not list(apps.glob("*.spa")):
            raise SystemExit("Cannot backup an applied-only installation")
        config.set("Backup", "version", current_version)
        config.set("Backup", "with", os.environ.get("TEST_CLI_VERSION", "2.44.0"))
        save()
    elif action == "apply":
        if config.get("Backup", "version") != current_version:
            raise SystemExit("Backup version mismatch")
        if config.get("Backup", "with") != os.environ.get("TEST_CLI_VERSION", "2.44.0"):
            raise SystemExit("Preprocessing version mismatch")
        for archive in apps.glob("*.spa"):
            archive.unlink()
        target = apps / "xpui/extensions/hyprland-dots-theme.js"
        target.parent.mkdir(parents=True, exist_ok=True)
        if os.environ.get("TEST_FAIL") != "missing-file":
            data = (config_path.parent / "Extensions/hyprland-dots-theme.js").read_bytes()
            if os.environ.get("TEST_FAIL") == "wrong-file":
                data = b"outdated extension"
            target.write_bytes(data)
        index = apps / "xpui/index.html"
        injected = "<script defer src='extensions/hyprland-dots-theme.js'></script>"
        if os.environ.get("TEST_FAIL") == "missing-injection":
            injected = "<!-- " + injected + " -->"
        if os.environ.get("TEST_FAIL") == "duplicate-injection":
            injected += injected
        stylesheet = "<link rel='stylesheet' href='user.css'>"
        if os.environ.get("TEST_FAIL") == "missing-theme-link":
            stylesheet = "<!-- " + stylesheet + " -->"
        colorsheet = "<link rel='stylesheet' class='userCSS' href='colors.css'>"
        if os.environ.get("TEST_FAIL") == "missing-colors-link":
            colorsheet = "<!-- " + colorsheet + " -->"
        if os.environ.get("TEST_FAIL") == "wrong-colors-link-rel":
            colorsheet = "<link rel='preload' href='colors.css'>"
        if os.environ.get("TEST_COLOR_FORMAT") == "spaced-reversed":
            colorsheet = "<link href='/colors.css' rel='STYLESHEET'>"
        stylesheet += colorsheet
        index.write_text("<html><head>" + stylesheet + "</head><body>" + injected + "</body></html>", encoding="utf-8")
        if config.get("Setting", "current_theme", fallback="") == "text":
            css = apps / "xpui/user.css"
            if os.environ.get("TEST_FAIL") == "missing-theme-css":
                css.unlink(missing_ok=True)
            else:
                data = (config_path.parent / "Themes/text/user.css").read_bytes()
                if os.environ.get("TEST_FAIL") == "wrong-theme-css":
                    data = b"/* old Comfy style */"
                css.write_bytes(data)
            scheme = configparser.ConfigParser(interpolation=None)
            scheme.read(config_path.parent / "Themes/text/color.ini")
            colors = {"sidebar": "121212", **dict(scheme.items("Spotify"))}
            declarations = []
            for name, raw in colors.items():
                color = raw.strip().lstrip("#").lower()
                rgb = ",".join(str(int(color[index:index + 2], 16)) for index in (0, 2, 4))
                for variable, value in ((f"--spice-{name}", "#" + color), (f"--spice-rgb-{name}", rgb)):
                    if variable == os.environ.get("TEST_COLOR_NAME", "--spice-text"):
                        if os.environ.get("TEST_FAIL") == "missing-color-variable":
                            continue
                        if os.environ.get("TEST_FAIL") == "wrong-color-variable":
                            value = "0,0,0" if variable.startswith("--spice-rgb-") else "#000000"
                        if os.environ.get("TEST_FAIL") == "wrong-color-value-format":
                            value = f"rgb({value})" if variable.startswith("--spice-rgb-") else value.lstrip("#")
                        if os.environ.get("TEST_FAIL") == "commented-color-variable":
                            declarations.append(f"/* {variable}: {value}; */")
                            continue
                        if os.environ.get("TEST_FAIL") == "duplicate-color-variable":
                            declarations.append(f"{variable}: {value};")
                    if os.environ.get("TEST_COLOR_FORMAT") == "spaced-reversed":
                        value = value.replace(",", " , \n\t")
                        declarations.append(f"\t{variable}\t: \n{value}\t ;")
                    else:
                        declarations.append(f"    {variable}: {value};")
            if os.environ.get("TEST_COLOR_FORMAT") == "spaced-reversed":
                declarations.reverse()
            palette = ":root {\n" + "\n".join(declarations) + "\n}\n"
            if os.environ.get("TEST_FAIL") == "wrong-color-scope":
                palette = palette.replace(":root", "body", 1)
            colors_css = apps / "xpui/colors.css"
            if os.environ.get("TEST_FAIL") == "missing-theme-colors":
                colors_css.unlink(missing_ok=True)
            elif os.environ.get("TEST_FAIL") == "directory-theme-colors":
                colors_css.mkdir()
            elif os.environ.get("TEST_FAIL") == "symlink-theme-colors":
                referent = Path(os.environ["TEST_ROOT"]) / "palette-referent.css"
                referent.write_text(palette, encoding="utf-8")
                colors_css.symlink_to(referent)
            elif os.environ.get("TEST_FAIL") != "stale-theme-colors":
                colors_css.write_text(palette, encoding="utf-8")
            theme_name = "Comfy" if os.environ.get("TEST_FAIL") == "wrong-theme-marker" else "text"
            (apps / "xpui/spicetify-config.json").write_text(json.dumps({
                "theme_name": theme_name,
                "scheme_name": config.get("Setting", "color_scheme"),
            }), encoding="utf-8")
    else:
        raise SystemExit("Unexpected command: " + action)
'''

FAKE_PGREP = r'''
import json
import os
import sys
with open(os.environ["TEST_PGREPS"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\n")
if os.environ.get("TEST_PGREP_ERROR"):
    raise SystemExit(2)
if os.environ.get("TEST_RUNNING") == "spotify" and "-x" in sys.argv:
    raise SystemExit(0)
if os.environ.get("TEST_RUNNING") == "launcher" and "-f" in sys.argv:
    raise SystemExit(0)
raise SystemExit(1)
'''

FAKE_SYNC = r'''
import json
import os
import sys
with open(os.environ["TEST_SYNCS"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\n")
raise SystemExit(1 if os.environ.get("TEST_SYNC_FAIL") else 0)
'''


class SetupSpicetifyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="spicetify-setup-test-")
        self.root = Path(self.temporary.name)
        self.home = self.root / "home with 'quote"
        self.config_home = self.root / "configuration with space"
        self.config_file = self.config_home / "spicetify/config-xpui.ini"
        self.repository = self.root / "repository with space"
        self.script = self.repository / "scripts/setup-spicetify.sh"
        self.bin = self.root / "fake bin"
        self.package = self.bin / "package-spicetify"
        self.calls_file = self.root / "calls.jsonl"
        self.pgreps_file = self.root / "pgreps.jsonl"
        self.syncs_file = self.root / "syncs.jsonl"
        self.spotify = self.home / ".local/share/spotify-launcher/install/usr/share/spotify"
        self.prefs = self.config_home / "spotify/prefs"
        self.bin.mkdir()
        self.script.parent.mkdir(parents=True)
        self.write_executable(self.package, FAKE_SPICETIFY)
        self.write_executable(self.bin / "pgrep", FAKE_PGREP)
        (self.bin / "python3").symlink_to(sys.executable)
        self.script.write_text(SCRIPT.read_text(encoding="utf-8").replace(
            "spicetify_bin=/usr/bin/spicetify",
            "spicetify_bin=" + shlex.quote(str(self.package)),
        ), encoding="utf-8")
        (self.script.parent / "sync-app-themes.py").write_text(FAKE_SYNC, encoding="utf-8")
        self.source = self.repository / "spicetify/Extensions" / EXTENSION
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"// current test extension\n")
        self.installed = self.config_file.parent / "Extensions" / EXTENSION
        self.installed.parent.mkdir(parents=True)
        self.installed.symlink_to(self.source)
        self.theme_source = self.repository / "spicetify/Themes/text"
        self.theme_source.mkdir(parents=True)
        (self.theme_source / "user.css").write_bytes(b"/* text theme fixture */\n:root { --font-family: monospace; }\n")
        (self.theme_source / "color.ini").write_bytes((ROOT / "spicetify/Themes/text/color.ini").read_bytes())
        self.installed_theme = self.config_file.parent / "Themes/text"
        self.installed_theme.parent.mkdir(parents=True)
        self.installed_theme.symlink_to(self.theme_source)
        self.create_installation(self.spotify, self.prefs)
        self.environment = os.environ.copy()
        for key in ("SPICETIFY_CONFIG", "SPICETIFY_STATE"):
            self.environment.pop(key, None)
        self.environment.update({
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.config_home),
            "PATH": str(self.bin) + os.pathsep + self.environment.get("PATH", "/usr/bin:/bin"),
            "TEST_ROOT": str(self.root),
            "TEST_CALLS": str(self.calls_file),
            "TEST_PGREPS": str(self.pgreps_file),
            "TEST_SYNCS": str(self.syncs_file),
        })

    def tearDown(self):
        self.temporary.cleanup()

    def write_executable(self, path, source):
        path.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")
        path.chmod(0o700)

    def create_installation(self, spotify, prefs, stock=True):
        (spotify / "Apps").mkdir(parents=True, exist_ok=True)
        self.write_executable(spotify / "spotify", "raise SystemExit('must not run Spotify')\n")
        if stock:
            (spotify / "Apps/xpui.spa").write_bytes(b"stock archive")
        prefs.parent.mkdir(parents=True, exist_ok=True)
        prefs.write_text(f'app.last-launched-version="{VERSION}"\n', encoding="utf-8")

    def write_config(self, spotify=None, prefs=None, extensions="existing.js", custom_apps="lyrics-plus"):
        self.config_file.write_text(
            f"[Setting]\nspotify_path = {spotify or self.spotify}\nprefs_path = {prefs or self.prefs}\n"
            "current_theme = UserTheme\ncolor_scheme = UserScheme\ninject_css = 0\n"
            "inject_theme_js = 0\nreplace_colors = 0\noverwrite_assets = 0\n"
            "spotify_launch_flags = --ozone-platform=wayland\n"
            f"[AdditionalOptions]\nextensions = {extensions}\ncustom_apps = {custom_apps}\n"
            "experimental_features = 0\n[Preprocesses]\nexpose_apis = 1\n"
            f"[Backup]\nversion = {VERSION}\nwith = {CLI_VERSION}\n"
            "[Patch]\ncustom = untouched\n",
            encoding="utf-8",
        )

    def config(self):
        result = configparser.ConfigParser(interpolation=None)
        result.read(self.config_file)
        return result

    def calls(self, path=None):
        path = path or self.calls_file
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def run_setup(self, *arguments, **environment):
        result = subprocess.run(
            ["bash", str(self.script), *arguments],
            env={**self.environment, **environment}, capture_output=True, text=True, timeout=15,
        )
        for call in self.calls():
            self.assertNotIn("restart", call)
            self.assertNotIn("auto", call)
            self.assertNotIn("--remote-debugging-port", " ".join(call))
        return result

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("not started or restarted", result.stdout)

    def test_default_installs_text_and_extension_without_replacing_existing_custom_apps(self):
        self.write_config()
        result = self.run_setup()
        self.assert_success(result)
        config = self.config()
        self.assertEqual(config.get("Setting", "current_theme"), "text")
        self.assertEqual(config.get("Setting", "color_scheme"), "Spotify")
        for name in ("inject_css", "replace_colors"):
            self.assertEqual(config.get("Setting", name), "1")
        for name in ("inject_theme_js", "overwrite_assets"):
            self.assertEqual(config.get("Setting", name), "0")
        self.assertEqual(set(config.get("AdditionalOptions", "extensions").split("|")), {"existing.js", EXTENSION})
        self.assertEqual(config.get("AdditionalOptions", "custom_apps"), "lyrics-plus")
        self.assertFalse(any(call[:2] == ["config", "custom_apps"] for call in self.calls()))
        self.assertIn(["--no-restart", "backup", "apply"], self.calls())
        self.assertEqual(self.calls(self.syncs_file), [[]])

    def test_default_supports_a_fresh_spicetify_configuration(self):
        result = self.run_setup()
        self.assert_success(result)
        self.assertEqual(self.config().get("Setting", "spotify_path"), str(self.spotify))
        self.assertEqual(self.config().get("Setting", "current_theme"), "text")
        self.assertEqual(self.config().get("AdditionalOptions", "custom_apps"), "marketplace")
        self.assertIn(["--no-restart", "backup", "apply"], self.calls())

    def test_default_migrates_comfy_and_preserves_custom_absolute_paths_and_extensions(self):
        other_spotify = self.root / "custom Spotify location"
        other_prefs = self.root / "custom preferences/prefs"
        self.create_installation(other_spotify, other_prefs)
        self.write_config(other_spotify, other_prefs, extensions="first.js|last.js", custom_apps="lyrics-plus|marketplace")
        config = self.config()
        config.set("Setting", "current_theme", "Comfy")
        config.set("Setting", "color_scheme", "Comfy")
        config.set("Setting", "overwrite_assets", "1")
        config.set("Setting", "inject_theme_js", "1")
        with self.config_file.open("w", encoding="utf-8") as handle:
            config.write(handle)
        self.assert_success(self.run_setup("--live-theme-only"))
        before = len(self.calls())
        self.assert_success(self.run_setup())
        after = self.config()
        self.assertEqual(after.get("Setting", "current_theme"), "text")
        self.assertEqual(after.get("Setting", "color_scheme"), "Spotify")
        self.assertEqual(after.get("Setting", "spotify_path"), str(other_spotify))
        self.assertEqual(after.get("Setting", "prefs_path"), str(other_prefs))
        self.assertEqual(after.get("AdditionalOptions", "custom_apps"), "lyrics-plus|marketplace")
        self.assertEqual(set(after.get("AdditionalOptions", "extensions").split("|")), {"first.js", "last.js", EXTENSION})
        self.assertEqual(after.get("Setting", "spotify_launch_flags"), "--ozone-platform=wayland")
        self.assertEqual(after.get("Patch", "custom"), "untouched")
        migration_calls = self.calls()[before:]
        self.assertIn(["--no-restart", "apply"], migration_calls)
        self.assertFalse(any(call[:2] in (["config", "spotify_path"], ["config", "prefs_path"], ["config", "custom_apps"])
                             for call in migration_calls))
        self.assertEqual((other_spotify / "Apps/xpui/user.css").read_bytes(), (self.theme_source / "user.css").read_bytes())

    def test_default_reapplies_changed_text_css_even_with_current_extension(self):
        self.write_config()
        self.assert_success(self.run_setup())
        replacement = b"/* updated text layout */\n:root { --font-size: 12px; }\n"
        (self.theme_source / "user.css").write_bytes(replacement)
        before = len(self.calls())
        self.assert_success(self.run_setup())
        self.assertIn(["--no-restart", "apply"], self.calls()[before:])
        self.assertEqual((self.spotify / "Apps/xpui/user.css").read_bytes(), replacement)

    def test_default_does_not_override_nonempty_invalid_paths(self):
        self.write_config(spotify=self.root / "missing Spotify")
        original = self.config_file.read_bytes()
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installation/preferences are missing", result.stderr)
        self.assertEqual(self.config_file.read_bytes(), original)
        self.assertFalse(any(call[0] == "config" for call in self.calls()))

    def test_default_requires_the_installed_text_theme_before_mutation(self):
        self.write_config()
        original = self.config_file.read_bytes()
        self.installed_theme.unlink()
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("text theme is missing", result.stderr)
        self.assertEqual(self.config_file.read_bytes(), original)
        self.assertFalse(any(call[0] == "config" for call in self.calls()))
        self.assert_success(self.run_setup("--live-theme-only"))

    def test_default_requires_complete_source_css_and_spotify_color_scheme(self):
        self.write_config()
        original = self.config_file.read_bytes()
        (self.theme_source / "color.ini").write_text("[WrongScheme]\ntext = FFFFFF\n")
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("[Spotify] color scheme", result.stderr)
        self.assertEqual(self.config_file.read_bytes(), original)
        (self.theme_source / "user.css").unlink()
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("text theme is missing", result.stderr)
        self.assertEqual(self.config_file.read_bytes(), original)

    def test_default_verifies_deployed_css_theme_metadata_and_stylesheet_link(self):
        self.write_config()
        for failure in ("missing-theme-css", "wrong-theme-css", "wrong-theme-marker", "missing-theme-link"):
            with self.subTest(failure=failure):
                result = self.run_setup(TEST_FAIL=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("did not deploy the requested text theme", result.stderr)
                self.assertEqual(self.calls(self.syncs_file), [])

    def test_default_requires_palette_file_and_real_stylesheet_link(self):
        self.write_config()
        for failure in ("missing-theme-colors", "missing-colors-link", "wrong-colors-link-rel", "wrong-color-scope"):
            with self.subTest(failure=failure):
                result = self.run_setup(TEST_FAIL=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("did not deploy the requested text theme", result.stderr)
                self.assertEqual(self.calls(self.syncs_file), [])

    def test_default_requires_hex_and_rgb_for_every_current_theme_color(self):
        self.write_config()
        scheme = configparser.ConfigParser(interpolation=None)
        scheme.read(self.theme_source / "color.ini")
        for name in scheme["Spotify"]:
            for prefix in ("--spice-", "--spice-rgb-"):
                with self.subTest(variable=prefix + name):
                    result = self.run_setup(TEST_FAIL="missing-color-variable", TEST_COLOR_NAME=prefix + name)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("did not deploy the requested text theme", result.stderr)
                    self.assertEqual(self.calls(self.syncs_file), [])

    def test_default_rejects_wrong_commented_duplicate_or_malformed_colors(self):
        self.write_config()
        for failure in ("wrong-color-variable", "wrong-color-value-format", "commented-color-variable", "duplicate-color-variable"):
            for variable in ("--spice-text", "--spice-rgb-text"):
                with self.subTest(failure=failure, variable=variable):
                    result = self.run_setup(TEST_FAIL=failure, TEST_COLOR_NAME=variable)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("did not deploy the requested text theme", result.stderr)
                    self.assertEqual(self.calls(self.syncs_file), [])

    def test_default_accepts_unordered_colors_whitespace_and_extra_upstream_defaults(self):
        self.write_config()
        self.assert_success(self.run_setup(TEST_COLOR_FORMAT="spaced-reversed"))
        self.assertEqual(self.calls(self.syncs_file), [[]])

    def test_default_verifies_updated_source_palette_instead_of_accepting_stale_colors(self):
        self.write_config()
        self.assert_success(self.run_setup())
        scheme = configparser.ConfigParser(interpolation=None)
        scheme.read(self.theme_source / "color.ini")
        scheme.set("Spotify", "text", "123456")
        with (self.theme_source / "color.ini").open("w", encoding="utf-8") as handle:
            scheme.write(handle)
        result = self.run_setup(TEST_FAIL="stale-theme-colors")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not deploy the requested text theme", result.stderr)
        self.assertEqual(self.calls(self.syncs_file), [[]])
        self.assert_success(self.run_setup())
        colors = (self.spotify / "Apps/xpui/colors.css").read_text(encoding="utf-8")
        self.assertIn("--spice-text: #123456;", colors)
        self.assertIn("--spice-rgb-text: 18,52,86;", colors)
        self.assertEqual(self.calls(self.syncs_file), [[], []])

    def test_default_rejects_non_regular_or_symlinked_palette_after_apply(self):
        self.write_config()
        palette = self.spotify / "Apps/xpui/colors.css"
        for failure in ("directory-theme-colors", "symlink-theme-colors"):
            with self.subTest(failure=failure):
                result = self.run_setup(TEST_FAIL=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("did not deploy the requested text theme", result.stderr)
                self.assertEqual(self.calls(self.syncs_file), [])
                if palette.is_symlink():
                    palette.unlink()
                else:
                    palette.rmdir()

    def test_default_rejects_symlinked_or_non_regular_palette_before_mutation(self):
        self.write_config()
        original = self.config_file.read_bytes()
        palette = self.spotify / "Apps/xpui/colors.css"
        palette.parent.mkdir(parents=True)
        unrelated = self.root / "unrelated-colors.css"
        unrelated.write_bytes(b"keep me")
        palette.symlink_to(unrelated)
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlinked Spotify colors.css", result.stderr)
        self.assertEqual(unrelated.read_bytes(), b"keep me")
        self.assertEqual(self.config_file.read_bytes(), original)
        self.assertEqual(self.calls(), [["--config"]])
        palette.unlink()
        palette.mkdir()
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-regular Spotify colors.css", result.stderr)
        self.assertEqual(self.config_file.read_bytes(), original)
        self.assertEqual(self.calls(), [["--config"], ["--config"]])

    def test_default_rejects_invalid_source_palette_before_mutation(self):
        self.write_config()
        original = self.config_file.read_bytes()
        (self.theme_source / "color.ini").write_text("[Spotify]\ntext = not-a-color\n", encoding="utf-8")
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("six-digit hexadecimal", result.stderr)
        self.assertEqual(self.config_file.read_bytes(), original)
        self.assertEqual(self.calls(), [["--config"]])

    def test_default_does_not_overwrite_symlinked_deployed_theme_css(self):
        self.write_config()
        target = self.spotify / "Apps/xpui/user.css"
        target.parent.mkdir(parents=True)
        unrelated = self.root / "unrelated.css"
        unrelated.write_bytes(b"keep me")
        target.symlink_to(unrelated)
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlinked Spotify user.css", result.stderr)
        self.assertEqual(unrelated.read_bytes(), b"keep me")
        self.assertFalse(any(call[0] == "config" for call in self.calls()))

    def test_installer_uses_default_setup_to_migrate_existing_themes(self):
        installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
        self.assertIn('if ! "$repo_dir/scripts/setup-spicetify.sh"; then', installer)
        self.assertNotIn("--live-theme-only", installer)

    def test_live_only_uses_existing_paths_and_preserves_all_non_extension_choices(self):
        other_spotify = self.root / "custom Spotify location"
        other_prefs = self.root / "custom preferences/prefs"
        self.create_installation(other_spotify, other_prefs)
        self.write_config(other_spotify, other_prefs, extensions="first.js|last.js")
        before = self.config()
        result = self.run_setup("--live-theme-only")
        self.assert_success(result)
        after = self.config()
        for section in before.sections():
            for key, original in before[section].items():
                if (section, key) != ("AdditionalOptions", "extensions"):
                    self.assertEqual(after.get(section, key), original, f"{section}.{key}")
        self.assertEqual(set(after.get("AdditionalOptions", "extensions").split("|")), {"first.js", "last.js", EXTENSION})
        config_calls = [call for call in self.calls() if call[0] == "config"]
        self.assertEqual(config_calls, [["config", "extensions", EXTENSION]])
        self.assertTrue((other_spotify / "Apps/xpui/extensions" / EXTENSION).is_file())
        self.assertFalse((self.spotify / "Apps/xpui").exists())

    def test_live_only_repeat_does_not_reapply_or_rewrite_config(self):
        self.write_config()
        self.assert_success(self.run_setup("--live-theme-only"))
        config_before = self.config_file.read_bytes()
        timestamp = self.config_file.stat().st_mtime_ns
        before = len(self.calls())
        self.assert_success(self.run_setup("--live-theme-only"))
        self.assertEqual(self.calls()[before:], [["--config"], ["--version"]])
        self.assertEqual(self.config_file.read_bytes(), config_before)
        self.assertEqual(self.config_file.stat().st_mtime_ns, timestamp)
        self.assertEqual(len(self.calls(self.syncs_file)), 2)

    def test_live_only_initializes_blank_paths_without_resetting_user_choices(self):
        self.write_config(extensions="first.js|last.js")
        before = self.config()
        before.set("Setting", "spotify_path", "")
        before.remove_option("Setting", "prefs_path")
        before.remove_section("Backup")
        with self.config_file.open("w", encoding="utf-8") as handle:
            before.write(handle)
        result = self.run_setup("--live-theme-only")
        self.assert_success(result)
        after = self.config()
        self.assertEqual(after.get("Setting", "spotify_path"), str(self.spotify))
        self.assertEqual(after.get("Setting", "prefs_path"), str(self.prefs))
        for section in before.sections():
            for key, original in before[section].items():
                if (section, key) not in {
                    ("Setting", "spotify_path"), ("AdditionalOptions", "extensions"),
                }:
                    self.assertEqual(after.get(section, key), original, f"{section}.{key}")
        self.assertEqual(set(after.get("AdditionalOptions", "extensions").split("|")), {"first.js", "last.js", EXTENSION})
        config_calls = [call for call in self.calls() if call[0] == "config"]
        self.assertEqual(config_calls, [
            ["config", "extensions", EXTENSION],
            ["config", "spotify_path", str(self.spotify), "prefs_path", str(self.prefs)],
        ])
        self.assertEqual(self.calls()[-1], ["--no-restart", "backup", "apply"])

    def test_live_only_initializing_one_missing_path_forces_apply_without_replacing_the_other(self):
        self.write_config()
        self.assert_success(self.run_setup("--live-theme-only"))
        for key, expected in (("spotify_path", self.spotify), ("prefs_path", self.prefs)):
            with self.subTest(key=key):
                config = self.config()
                config.remove_option("Setting", key)
                with self.config_file.open("w", encoding="utf-8") as handle:
                    config.write(handle)
                before = len(self.calls())
                result = self.run_setup("--live-theme-only")
                self.assert_success(result)
                self.assertEqual(self.calls()[before:], [
                    ["--config"], ["--version"],
                    ["config", key, str(expected)], ["--no-restart", "apply"],
                ])
                self.assertEqual(self.config().get("Setting", "spotify_path"), str(self.spotify))
                self.assertEqual(self.config().get("Setting", "prefs_path"), str(self.prefs))

    def test_blank_path_initialization_does_not_overwrite_a_nonempty_invalid_path(self):
        self.write_config()
        config = self.config()
        config.set("Setting", "spotify_path", "")
        config.set("Setting", "prefs_path", str(self.root / "missing prefs"))
        with self.config_file.open("w", encoding="utf-8") as handle:
            config.write(handle)
        original = self.config_file.read_bytes()
        result = self.run_setup("--live-theme-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installation/preferences are missing", result.stderr)
        self.assertEqual(self.config_file.read_bytes(), original)
        self.assertEqual(self.calls(), [["--config"]])

    def test_blank_paths_are_not_written_until_backup_state_is_validated(self):
        self.write_config()
        config = self.config()
        config.set("Setting", "spotify_path", "")
        config.set("Setting", "prefs_path", "")
        config.set("Backup", "version", "old-version")
        with self.config_file.open("w", encoding="utf-8") as handle:
            config.write(handle)
        original = self.config_file.read_bytes()
        (self.spotify / "Apps/xpui.spa").unlink()
        result = self.run_setup("--live-theme-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("old backup was not restored", result.stderr)
        self.assertEqual(self.config_file.read_bytes(), original)
        self.assertFalse(any(call[0] == "config" for call in self.calls()))

    def test_updated_extension_reapplies_from_matching_backup_without_rebackup(self):
        self.write_config()
        self.assert_success(self.run_setup("--live-theme-only"))
        self.source.write_bytes(b"// updated test extension\n")
        before = len(self.calls())
        self.assert_success(self.run_setup("--live-theme-only"))
        self.assertEqual(self.calls()[before:], [["--config"], ["--version"], ["--no-restart", "apply"]])

    def test_changed_cli_refreshes_preprocessing_using_matching_spotify_backup(self):
        self.write_config()
        self.assert_success(self.run_setup("--live-theme-only"))
        before = len(self.calls())
        result = self.run_setup("--live-theme-only", TEST_CLI_VERSION="2.45.0")
        self.assert_success(result)
        self.assertIn(["--no-restart", "restore", "backup", "apply"], self.calls()[before:])
        self.assertEqual(self.config().get("Backup", "with"), "2.45.0")

    def test_mismatched_applied_only_backup_is_not_restored_or_reconfigured(self):
        self.write_config()
        (self.spotify / "Apps/xpui.spa").unlink()
        self.prefs.write_text('app.last-launched-version="1.2.98.1"\n')
        before = self.config_file.read_bytes()
        result = self.run_setup("--live-theme-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("old backup was not restored", result.stderr)
        self.assertEqual(self.config_file.read_bytes(), before)
        self.assertEqual(self.calls(), [["--config"], ["--version"]])
        self.assertEqual(self.calls(self.syncs_file), [])

    def test_running_spotify_or_launcher_stops_before_cli_mutation(self):
        for process in ("spotify", "launcher"):
            with self.subTest(process=process):
                result = self.run_setup(TEST_RUNNING=process)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Close Spotify", result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertEqual(self.calls(self.syncs_file), [])

    def test_process_check_failure_is_not_treated_as_closed(self):
        result = self.run_setup(TEST_PGREP_ERROR="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not verify", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_live_only_requires_existing_config_and_valid_explicit_paths(self):
        result = self.run_setup("--live-theme-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No existing Spicetify", result.stderr)
        self.assertEqual(self.calls(), [])
        self.write_config()
        original = self.config_file.read_text()
        self.config_file.write_text(original.replace(str(self.spotify), "relative/spotify"))
        result = self.run_setup("--live-theme-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("absolute path", result.stderr)
        self.assertFalse(any(call[0] == "config" for call in self.calls()))

    def test_missing_extension_or_spotify_installation_does_not_change_config(self):
        self.write_config()
        original = self.config_file.read_bytes()
        self.installed.unlink()
        result = self.run_setup("--live-theme-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("extension is missing", result.stderr)
        self.assertEqual(self.config_file.read_bytes(), original)
        self.installed.symlink_to(self.source)
        self.prefs.unlink()
        result = self.run_setup("--live-theme-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installation/preferences are missing", result.stderr)
        self.assertEqual(self.config_file.read_bytes(), original)

    def test_missing_package_binary_fails_without_running_the_cli(self):
        self.package.chmod(0o600)
        result = self.run_setup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Spicetify is not installed", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_failure_stops_before_sync_and_never_starts_spotify(self):
        self.write_config()
        for failure in ("config", "apply"):
            with self.subTest(failure=failure):
                result = self.run_setup("--live-theme-only", TEST_FAIL=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("setup failed", result.stderr)
                self.assertEqual(self.calls(self.syncs_file), [])

    def test_deployment_is_verified_including_real_script_injection(self):
        self.write_config()
        for failure in ("missing-file", "wrong-file", "missing-injection", "duplicate-injection"):
            with self.subTest(failure=failure):
                result = self.run_setup("--live-theme-only", TEST_FAIL=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("did not install and inject", result.stderr)
                self.assertEqual(self.calls(self.syncs_file), [])

    def test_sync_failure_is_reported_after_successful_extension_installation(self):
        self.write_config()
        result = self.run_setup("--live-theme-only", TEST_SYNC_FAIL="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("setup failed", result.stderr)
        self.assertEqual(self.calls(self.syncs_file), [[]])
        self.assertTrue((self.spotify / "Apps/xpui/extensions" / EXTENSION).is_file())

    def test_unexpected_config_override_is_not_modified(self):
        self.write_config()
        before = self.config_file.read_bytes()
        result = self.run_setup("--live-theme-only", SPICETIFY_CONFIG=str(self.root / "another profile"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unset a different SPICETIFY_CONFIG", result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.config_file.read_bytes(), before)

    def test_symlinked_deployment_is_not_overwritten(self):
        self.write_config()
        target = self.spotify / "Apps/xpui/extensions" / EXTENSION
        target.parent.mkdir(parents=True)
        unrelated = self.root / "unrelated.js"
        unrelated.write_bytes(b"keep me")
        target.symlink_to(unrelated)
        result = self.run_setup("--live-theme-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlinked Spotify extension", result.stderr)
        self.assertEqual(unrelated.read_bytes(), b"keep me")
        self.assertFalse(any(call[0] == "config" for call in self.calls()))

    def test_help_and_unknown_arguments_do_not_invoke_package_tools(self):
        self.assertEqual(self.run_setup("--help").returncode, 0)
        self.assertNotEqual(self.run_setup("--unsupported").returncode, 0)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
