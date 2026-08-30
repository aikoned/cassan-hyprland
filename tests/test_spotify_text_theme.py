import configparser
from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "spicetify/Themes/text"
COLOR_MAPPING = {
    "accent": "focus",
    "accent-active": "focus_alt",
    "accent-inactive": "disabled",
    "banner": "focus",
    "border-active": "focus",
    "border-inactive": "border",
    "header": "text",
    "highlight": "panel_alt",
    "main": "background",
    "notification": "focus",
    "notification-error": "urgent",
    "subtext": "text_secondary",
    "text": "text",
}
LABELS = {
    ".Root__globalNav": "Nav",
    ".main-yourLibraryX-entryPoints": "Library",
    ".Root__main-view": "Main",
    ".main-nowPlayingBar-container": "Playing",
    ".Root__right-sidebar:has(aside:not(:empty))": "Sidebar",
}


def rule_blocks(css):
    """Inspect this theme's flat declaration blocks, not a general CSS grammar."""
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        declarations = {}
        for declaration in match[2].split(";"):
            name, separator, value = declaration.partition(":")
            if separator:
                declarations[name.strip()] = re.sub(r"\s*!important\s*$", "", value).strip()
        yield match[1].strip(), declarations


def relative_luminance(color):
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast_ratio(first, second):
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class SpotifyTextThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = re.sub(r"/\*.*?\*/", "", (THEME / "user.css").read_text(encoding="utf-8"), flags=re.S)
        cls.rules = list(rule_blocks(cls.css))
        cls.palettes = {}
        for theme in ("after-school", "reze"):
            with (ROOT / f"themes/{theme}.toml").open("rb") as handle:
                cls.palettes[theme] = tomllib.load(handle)["colors"]

    def declarations_for(self, selector):
        declarations = {}
        for selectors, values in self.rules:
            if selector in [part.strip() for part in selectors.split(",")]:
                declarations.update(values)
        self.assertTrue(declarations, f"missing style rule: {selector}")
        return declarations

    def test_css_is_self_contained_and_uses_a_local_monospace_fallback(self):
        self.assertNotRegex(self.css, r"(?i)@(?:import|font-face)\b")
        self.assertNotRegex(self.css, r"(?i)\burl\s*\(")
        self.assertNotRegex(self.css, r"(?i)(?:https?:)?//")
        self.assertIn("monospace", self.declarations_for(":root")["--text-font-family"])

    def test_five_panel_labels_are_anchored_and_do_not_intercept_clicks(self):
        for selector, label in LABELS.items():
            with self.subTest(label=label):
                panel = self.declarations_for(selector)
                caption = self.declarations_for(f"{selector}::before")
                self.assertEqual(panel.get("position"), "relative")
                self.assertEqual(caption.get("content", "").strip("\"'"), label)
                self.assertEqual(caption.get("position"), "absolute")
                self.assertEqual(caption.get("pointer-events"), "none")
                self.assertIn("top", caption)
                self.assertIn("left", caption)
                self.assertEqual(caption.get("background"), "var(--spice-main)")
                self.assertEqual(caption.get("color"), "var(--spice-header)")

    def test_legacy_pages_label_is_conditional_on_navigation_without_a_library(self):
        pages = [(selectors, values) for selectors, values in self.rules
                 if values.get("content", "").strip("\"'") == "Pages"]
        self.assertEqual(len(pages), 1)
        selector, values = pages[0]
        self.assertIn(".main-yourLibraryX-entryPoints", selector)
        self.assertIn(":has(.main-yourLibraryX-navItems)", selector)
        self.assertIn(":not(:has(.main-yourLibraryX-libraryContainer))", selector)
        self.assertTrue(selector.endswith("::before"))
        self.assertEqual(values.get("pointer-events", "none"), "none")

    def test_spotify_fallback_colors_match_the_after_school_live_mapping(self):
        parser = configparser.ConfigParser(interpolation=None, delimiters=("=",))
        with (THEME / "color.ini").open(encoding="utf-8") as handle:
            parser.read_file(handle)
        self.assertEqual(parser.sections(), ["Spotify"])
        colors = dict(parser["Spotify"])
        self.assertEqual(set(colors), set(COLOR_MAPPING))
        for token, role in COLOR_MAPPING.items():
            with self.subTest(token=token):
                self.assertRegex(colors[token], r"\A[0-9a-fA-F]{6}\Z")
                self.assertEqual(f"#{colors[token]}".lower(), self.palettes["after-school"][role].lower())

    def test_text_and_subtext_contrast_on_main_and_highlight_surfaces(self):
        for theme, colors in self.palettes.items():
            for foreground in ("text", "text_secondary"):
                for background in ("background", "panel_alt"):
                    with self.subTest(theme=theme, foreground=foreground, background=background):
                        self.assertGreaterEqual(contrast_ratio(colors[foreground], colors[background]), 4.5)

    def test_focus_and_control_borders_contrast_on_main_and_highlight_surfaces(self):
        for theme, colors in self.palettes.items():
            for foreground in ("focus", "focus_alt", "border"):
                for background in ("background", "panel_alt"):
                    with self.subTest(theme=theme, foreground=foreground, background=background):
                        self.assertGreaterEqual(contrast_ratio(colors[foreground], colors[background]), 3.0)

    def test_selected_chips_keep_a_distinct_contrasting_surface(self):
        base = self.declarations_for(".encore-dark-theme")
        selected = self.declarations_for(".encore-dark-theme .encore-inverted-light-set")
        self.assertNotEqual(selected.get("--background-base"), base.get("--background-base"))
        self.assertEqual(selected.get("--background-base"), "var(--spice-accent-active)")
        self.assertEqual(selected.get("--text-base"), "var(--spice-main)")
        for theme, colors in self.palettes.items():
            with self.subTest(theme=theme):
                self.assertGreaterEqual(contrast_ratio(colors["background"], colors["focus_alt"]), 4.5)

    def test_pressed_control_color_does_not_override_selected_chip_text(self):
        for selectors, declarations in self.rules:
            if declarations.get("color") != "var(--spice-accent-active)":
                continue
            for selector in selectors.split(","):
                if "[aria-pressed=" in selector or "[aria-checked=" in selector:
                    self.assertTrue(selector.strip().startswith(".player-controls__buttons "))

    def test_css_does_not_target_exact_svg_paths_or_hide_icons(self):
        self.assertNotRegex(self.css, r"\[\s*d\s*[*^$|~]?=")
        for selectors, declarations in self.rules:
            if not re.search(r"\bsvg\b|\bpath\b|icon|control-button|playPauseButton", selectors, re.I):
                continue
            with self.subTest(selectors=selectors):
                self.assertNotEqual(declarations.get("display"), "none")
                self.assertNotIn(declarations.get("visibility"), {"hidden", "collapse"})
                for dimension in ("width", "height", "font-size"):
                    self.assertNotRegex(declarations.get(dimension, ""), r"\A0(?:px|em|rem|%)?\Z")

    def test_theme_does_not_dim_content_or_controls_with_opacity(self):
        self.assertNotRegex(self.css, r"(?i)\bopacity\s*\(")
        for selectors, declarations in self.rules:
            for name in ("opacity", "fill-opacity", "stroke-opacity"):
                if name in declarations:
                    with self.subTest(selectors=selectors, property=name):
                        self.assertRegex(declarations[name], r"\A(?:1(?:\.0+)?|100%)\Z")

    def test_seek_bar_is_scoped_to_the_normal_player_not_the_viewport(self):
        player = self.declarations_for(".main-nowPlayingBar-container")
        seek = self.declarations_for(".main-nowPlayingBar-container .playback-bar")
        self.assertEqual(player.get("position"), "relative")
        self.assertEqual(seek.get("position"), "absolute")
        self.assertEqual(seek.get("width"), "auto")
        self.assertIn("inset", seek)
        for selectors, declarations in self.rules:
            if "progress-bar" not in selectors and "playback-bar" not in selectors:
                continue
            with self.subTest(selectors=selectors):
                self.assertNotEqual(declarations.get("position"), "fixed")
                for value in declarations.values():
                    self.assertNotRegex(value, r"(?i)\d(?:s|l|d)?vw\b")
                if declarations.get("position") == "absolute":
                    self.assertTrue(all(part.strip().startswith(".main-nowPlayingBar-container ")
                                        for part in selectors.split(",")))

    def test_seek_bar_is_anchored_above_the_separate_connect_row(self):
        player_row = self.declarations_for(".main-nowPlayingBar-nowPlayingBar")
        self.assertEqual(player_row.get("position"), "relative")
        for selector in (".main-nowPlayingBar-container .main-nowPlayingBar-center",
                         ".main-nowPlayingBar-container .player-controls"):
            self.assertEqual(self.declarations_for(selector).get("position"), "static")


if __name__ == "__main__":
    unittest.main()
