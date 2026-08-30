import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "waybar/config.jsonc").read_text(encoding="utf-8"))
CSS = (ROOT / "waybar/style.css").read_text(encoding="utf-8")
MODULE = CONFIG["custom/memory-pressure"]


def enabled_modules(names):
    for name in names:
        if name.startswith("group/"):
            yield from enabled_modules(CONFIG[name]["modules"])
        else:
            yield name


def colors(css):
    return dict(re.findall(r"@define-color\s+([\w-]+)\s+(#[0-9a-fA-F]{6});", css))


def luminance(color):
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(first, second):
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class WaybarMemoryTrayTests(unittest.TestCase):
    def test_pressure_replaces_used_ram_in_the_visible_bar(self):
        active = list(enabled_modules(
            CONFIG["modules-left"] + CONFIG["modules-center"] + CONFIG["modules-right"]
        ))
        self.assertEqual(active.count("custom/memory-pressure"), 1)
        self.assertNotIn("memory", active)
        self.assertNotIn("memory", CONFIG)
        self.assertEqual(active.count("tray"), 1)
        self.assertIn("tray", list(enabled_modules(CONFIG["modules-right"])))

    def test_tray_does_not_hide_background_or_passive_applications(self):
        tray = CONFIG["tray"]
        self.assertTrue(tray["show-passive-items"])
        self.assertLessEqual(tray["icon-size"], 18)
        self.assertLessEqual(tray["spacing"], 5)
        self.assertFalse(tray.get("ignore-list"))
        self.assertNotIn(False, tray.get("icons", {}).values())
        self.assertNotIn("drawer", CONFIG["group/system"])

    def test_stream_survives_clicks_without_restarting_history(self):
        self.assertNotIn("interval", MODULE)
        self.assertNotIn("signal", MODULE)
        self.assertFalse(MODULE["exec-on-event"])
        self.assertGreaterEqual(MODULE["restart-interval"], 2)
        self.assertEqual(MODULE["return-type"], "json")
        self.assertEqual(MODULE["format"], "{text}")
        self.assertTrue(MODULE["tooltip"])
        self.assertTrue(MODULE["escape"])
        self.assertIn("python3 -u ", MODULE["exec"])

    def test_bounded_graph_keeps_the_center_title_fixed(self):
        self.assertEqual(MODULE["min-length"], 16)
        self.assertEqual(MODULE["max-length"], 16)
        self.assertTrue(CONFIG["fixed-center"])
        window = CONFIG["hyprland/window"]
        self.assertEqual(window["min-length"], window["max-length"])
        self.assertLessEqual(CONFIG["mpris"]["max-length"], 32)

    def test_graph_opens_the_existing_themed_task_manager(self):
        self.assertEqual(MODULE["on-click"], CONFIG["cpu"]["on-click"])
        self.assertIn("/btop/launch.sh", MODULE["on-click"])
        self.assertIn("kitty --class cassan-btop", MODULE["on-click"])

    def run_probe(self, root, *, pressure=True):
        config_home = root / "config with spaces"
        config_home.mkdir()
        (config_home / "waybar").symlink_to(ROOT / "waybar", target_is_directory=True)
        proc = root / "proc with spaces"
        (proc / "pressure").mkdir(parents=True)
        if pressure:
            (proc / "pressure/memory").write_text(
                "some avg10=0.00 avg60=0.10 avg300=0.40 total=123456\n"
                "full avg10=0.00 avg60=0.01 avg300=0.02 total=12345\n",
                encoding="utf-8",
            )
        (proc / "meminfo").write_text(
            "MemTotal: 16000000 kB\nMemFree: 100000 kB\n"
            "MemAvailable: 2000000 kB\nSwapTotal: 4000000 kB\n"
            "SwapFree: 2000000 kB\n",
            encoding="utf-8",
        )
        (proc / "vmstat").write_text("pswpin 100\npswpout 200\n", encoding="utf-8")
        binaries = root / "bin"
        binaries.mkdir()
        (binaries / "python3").symlink_to(sys.executable)
        env = os.environ | {
            "XDG_CONFIG_HOME": str(config_home),
            "PATH": str(binaries) + os.pathsep + os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        command = MODULE["exec"] + " --once --proc-root " + shlex.quote(str(proc))
        result = subprocess.run(
            ["/bin/sh", "-c", command], env=env, text=True,
            capture_output=True, check=True, timeout=10,
        )
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertFalse(result.stderr)
        return json.loads(result.stdout)

    def test_configured_command_handles_xdg_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.run_probe(Path(directory))
        self.assertEqual(output["class"], "low")
        self.assertTrue(output["text"].startswith("MEM "))
        self.assertEqual(len(output["text"]), MODULE["max-length"])
        self.assertIn("available", output["tooltip"].lower())
        self.assertIn("swap", output["tooltip"].lower())

    def test_unavailable_psi_is_not_shown_as_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            output = self.run_probe(Path(directory), pressure=False)
        self.assertEqual(output["class"], "unknown")
        self.assertTrue(output["text"].startswith("MEM?"))
        self.assertEqual(len(output["text"]), MODULE["max-length"])

    def test_pressure_colors_and_tray_menus_work_in_both_palettes(self):
        fallback = colors(CSS)
        with tempfile.TemporaryDirectory() as directory:
            for theme in ("after-school", "reze"):
                with self.subTest(theme=theme):
                    output = Path(directory) / theme
                    subprocess.run(
                        [sys.executable, str(ROOT / "scripts/render-theme.py"),
                         "--theme", theme, "--output", str(output)],
                        text=True, capture_output=True, check=True, timeout=10,
                    )
                    rendered = (output / "waybar.css").read_text(encoding="utf-8")
                    palette = colors(rendered)
                    for level in ("low", "moderate", "high"):
                        token = "pressure-" + level
                        self.assertEqual(palette[token], fallback[token])
                        self.assertGreaterEqual(contrast(palette[token], palette["background"]), 4.5)
                        self.assertRegex(
                            rendered,
                            rf"#custom-memory-pressure\.{level}\s*\{{\s*color:\s*@{token};",
                        )
                    self.assertRegex(rendered, r"#tray menu\s*\{[^}]*background-color:\s*@background;")
                    self.assertRegex(rendered, r"#tray menu menuitem:hover\s*\{[^}]*color:\s*@focused2;")

    def test_installer_links_the_whole_waybar_directory(self):
        installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
        config_names = installer.split("config_names=(", 1)[1].split(")", 1)[0].split()
        self.assertIn("waybar", config_names)
        self.assertIn('link_path "$repo_dir/$name" "$config_dir/$name"', installer)
        self.assertTrue((ROOT / "waybar/scripts/memory-pressure.py").is_file())
        startup = (ROOT / "hypr/startup.lua").read_text(encoding="utf-8")
        self.assertNotIn("memory-pressure", startup)


if __name__ == "__main__":
    unittest.main(verbosity=2)
