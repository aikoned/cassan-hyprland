#!/usr/bin/env python3

import argparse
import json
import os
import re
import tempfile
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
THEMES = {
    "after-school": ROOT / "themes/after-school.toml",
    "reze": ROOT / "themes/reze.toml",
}
REQUIRED_COLORS = {
    "background",
    "panel",
    "panel_alt",
    "text",
    "text_secondary",
    "text_muted",
    "disabled",
    "border",
    "focus",
    "focus_alt",
    "blue",
    "purple",
    "green",
    "urgent",
}


def replace_colors(source: str, mapping: dict[str, str]) -> str:
    for name, color in mapping.items():
        pattern = rf"(?m)^@define-color\s+{re.escape(name)}\s+[^;]+;"
        source, count = re.subn(pattern, f"@define-color {name} {color};", source)
        if count != 1:
            raise ValueError(f"expected one CSS definition for {name}, found {count}")
    return source


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.chmod(temporary, 0o644)
    os.replace(temporary, path)


def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
        handle.write(source.read_bytes())
        temporary = Path(handle.name)
    os.chmod(temporary, 0o644)
    os.replace(temporary, destination)


def load_theme(slug: str) -> dict[str, object]:
    with THEMES[slug].open("rb") as handle:
        theme = tomllib.load(handle)
    colors = theme.get("colors")
    if not isinstance(colors, dict):
        raise ValueError(f"{slug} has no color table")
    missing = REQUIRED_COLORS - colors.keys()
    if missing:
        raise ValueError(f"{slug} is missing colors: {sorted(missing)}")
    for name in REQUIRED_COLORS:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(colors[name])):
            raise ValueError(f"{slug}.{name} is not a six-digit hex color")
    return theme


def render(slug: str, output: Path) -> None:
    theme = load_theme(slug)
    colors = theme["colors"]

    waybar = replace_colors(
        (ROOT / "waybar/style.css").read_text(encoding="utf-8"),
        {
            "background": colors["background"],
            "second-background": colors["panel_alt"],
            "text": colors["text"],
            "borders": colors["border"],
            "focused": colors["focus"],
            "focused2": colors["focus_alt"],
            "color1": colors["blue"],
            "color2": colors["purple"],
            "color3": colors["green"],
            "urgent": colors["urgent"],
        },
    )
    swaync = replace_colors(
        (ROOT / "swaync/style.css").read_text(encoding="utf-8"),
        {
            "bg-primary": colors["background"],
            "bg-secondary": colors["panel"],
            "bg-tertiary": colors["panel_alt"],
            "bg-selected": colors["border"],
            "fg-primary": colors["text"],
            "fg-secondary": colors["text_secondary"],
            "fg-tertiary": colors["text_muted"],
            "fg-disabled": colors["disabled"],
            "accent-green": colors["green"],
            "accent-orange": colors["focus"],
            "accent-red": colors["urgent"],
            "accent-blue": colors["blue"],
            "accent-purple": colors["purple"],
            "border-primary": colors["border"],
            "border-focus": colors["focus_alt"],
        },
    )
    wofi_base = (ROOT / "wofi/style.css").read_text(encoding="utf-8")
    wofi_base, count = re.subn(
        r'(?m)^@import\s+url\(["\']gruvbox\.css["\']\);\s*', "", wofi_base
    )
    if count != 1:
        raise ValueError("Wofi base style must import gruvbox.css exactly once")
    wofi_definitions = "\n".join(
        (
            f"@define-color accent {colors['focus_alt']};",
            f"@define-color txt {colors['text']};",
            f"@define-color bg {colors['background']};",
            f"@define-color bg2 {colors['panel_alt']};",
            f"@define-color accent2 {colors['purple']};",
        )
    )
    wlogout = replace_colors(
        (ROOT / "wlogout/style.css").read_text(encoding="utf-8"),
        {
            "background": colors["panel_alt"],
            "primary": colors["focus_alt"],
            "button-border": colors["focus"],
        },
    )
    hypr = "\n".join(
        (
            "return {",
            f'  background = "rgb({colors["background"][1:]})",',
            f'  background_alt = "rgb({colors["panel_alt"][1:]})",',
            f'  text = "rgb({colors["text"][1:]})",',
            f'  border = "rgb({colors["border"][1:]})",',
            f'  focus = "rgb({colors["focus"][1:]})",',
            f'  focus_alt = "rgb({colors["focus_alt"][1:]})",',
            f'  blue = "rgb({colors["blue"][1:]})",',
            f'  purple = "rgb({colors["purple"][1:]})",',
            f'  green = "rgb({colors["green"][1:]})",',
            f'  urgent = "rgb({colors["urgent"][1:]})",',
            "}",
            "",
        )
    )
    hyprlock = "\n".join(
        (
            f'$border_active = rgb({colors["focus_alt"][1:]})',
            f'$border_inactive = rgb({colors["background"][1:]})',
            f'$text = rgb({colors["text"][1:]})',
            f'$borders = rgb({colors["border"][1:]})',
            f'$focused = rgb({colors["focus"][1:]})',
            f'$focused2 = rgb({colors["focus_alt"][1:]})',
            f'$color1 = rgb({colors["blue"][1:]})',
            f'$color2 = rgb({colors["purple"][1:]})',
            f'$color3 = rgb({colors["green"][1:]})',
            f'$urgent = rgb({colors["urgent"][1:]})',
            "",
        )
    )
    kitty = "\n".join(
        (
            f'foreground {colors["text"]}',
            f'background {colors["background"]}',
            f'selection_foreground {colors["background"]}',
            f'selection_background {colors["text"]}',
            f'cursor {colors["text"]}',
            f'cursor_text_color {colors["background"]}',
            f'url_color {colors["blue"]}',
            f'active_border_color {colors["focus_alt"]}',
            f'inactive_border_color {colors["border"]}',
            f'wayland_titlebar_color {colors["background"]}',
            f'active_tab_foreground {colors["background"]}',
            f'active_tab_background {colors["focus_alt"]}',
            f'inactive_tab_foreground {colors["text_secondary"]}',
            f'inactive_tab_background {colors["panel_alt"]}',
            f'tab_bar_background {colors["background"]}',
            f'mark1_foreground {colors["background"]}',
            f'mark1_background {colors["focus"]}',
            f'mark2_foreground {colors["background"]}',
            f'mark2_background {colors["purple"]}',
            f'mark3_foreground {colors["background"]}',
            f'mark3_background {colors["green"]}',
            f'color0 {colors["background"]}',
            f'color1 {colors["urgent"]}',
            f'color2 {colors["green"]}',
            f'color3 {colors["focus"]}',
            f'color4 {colors["blue"]}',
            f'color5 {colors["purple"]}',
            f'color6 {colors["focus_alt"]}',
            f'color7 {colors["border"]}',
            f'color8 {colors["panel_alt"]}',
            f'color9 {colors["urgent"]}',
            f'color10 {colors["green"]}',
            f'color11 {colors["focus"]}',
            f'color12 {colors["blue"]}',
            f'color13 {colors["purple"]}',
            f'color14 {colors["focus_alt"]}',
            f'color15 {colors["text"]}',
            "",
        )
    )
    btop_colors = {
        "main_bg": colors["background"],
        "main_fg": colors["text"],
        "title": colors["focus_alt"],
        "hi_fg": colors["blue"],
        "selected_bg": colors["border"],
        "selected_fg": colors["text"],
        "inactive_fg": colors["text_muted"],
        "proc_misc": colors["purple"],
        "cpu_box": colors["border"],
        "mem_box": colors["border"],
        "net_box": colors["border"],
        "proc_box": colors["border"],
        "div_line": colors["panel_alt"],
        "temp_start": colors["blue"],
        "temp_mid": colors["focus"],
        "temp_end": colors["urgent"],
        "cpu_start": colors["focus_alt"],
        "cpu_mid": colors["purple"],
        "cpu_end": colors["urgent"],
        "free_start": colors["green"],
        "free_mid": colors["focus_alt"],
        "free_end": colors["blue"],
        "cached_start": colors["blue"],
        "cached_mid": colors["purple"],
        "cached_end": colors["focus"],
        "available_start": colors["green"],
        "available_mid": colors["focus_alt"],
        "available_end": colors["blue"],
        "used_start": colors["focus_alt"],
        "used_mid": colors["focus"],
        "used_end": colors["urgent"],
        "download_start": colors["blue"],
        "download_mid": colors["focus_alt"],
        "download_end": colors["green"],
        "upload_start": colors["purple"],
        "upload_mid": colors["focus"],
        "upload_end": colors["urgent"],
    }
    btop = "\n".join(
        f'theme[{name}]="{color}"' for name, color in btop_colors.items()
    ) + "\n"

    def rgba(name: str, alpha: float) -> str:
        value = colors[name]
        channels = [str(int(value[index:index + 2], 16)) for index in (1, 3, 5)]
        return f'rgba({", ".join(channels)}, {alpha})'

    vesktop_colors = {
        "text-0": colors["background"],
        "text-1": colors["text"],
        "text-2": colors["text"],
        "text-3": colors["text"],
        "text-4": colors["text_secondary"],
        "text-5": colors["text_muted"],
        "bg-1": colors["focus"],
        "bg-2": colors["panel_alt"],
        "bg-3": rgba("panel_alt", 0.9),
        "bg-4": rgba("background", 0.9),
        "bg-floating": rgba("panel_alt", 0.98),
        "hover": rgba("border", 0.2),
        "active": rgba("focus", 0.3),
        "active-2": rgba("focus", 0.4),
        "message-hover": rgba("panel_alt", 0.5),
        "accent-1": colors["blue"],
        "accent-2": colors["focus"],
        "accent-3": colors["focus"],
        "accent-4": colors["focus_alt"],
        "accent-5": colors["border"],
        "accent-new": colors["urgent"],
        "mention": f'linear-gradient(to right, {rgba("focus", 0.1)} 40%, transparent)',
        "mention-hover": f'linear-gradient(to right, {rgba("focus", 0.05)} 40%, transparent)',
        "reply": f'linear-gradient(to right, {rgba("text", 0.1)} 40%, transparent)',
        "reply-hover": f'linear-gradient(to right, {rgba("text", 0.05)} 40%, transparent)',
        "online": colors["green"],
        "dnd": colors["urgent"],
        "idle": colors["focus_alt"],
        "streaming": colors["purple"],
        "offline": colors["text_muted"],
        "border-light": rgba("border", 0.2),
        "border": rgba("focus", 0.3),
        "border-hover": colors["focus"],
        "button-border": rgba("text", 0.1),
    }
    for family, name in (
        ("red", "urgent"), ("green", "green"), ("blue", "blue"),
        ("yellow", "focus_alt"), ("purple", "purple"),
    ):
        for level in range(1, 6):
            vesktop_colors[f"{family}-{level}"] = colors[name]
    vesktop = ":root, body, .theme-dark, .theme-light {\n" + "\n".join(
        f"  --{name}: {value} !important;" for name, value in vesktop_colors.items()
    ) + "\n}\n"

    spotify = {"schema": 1, "theme": slug, "colors": colors}
    cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    firefox = {
        "wallpaper": str(cache_home / "hyprland-dots/active-theme/wallpaper"),
        "special": {
            "background": colors["background"],
            "foreground": colors["text"],
            "cursor": colors["text"],
        },
        "colors": {
            f"color{index}": colors[name]
            for index, name in enumerate((
                "background", "urgent", "green", "focus", "blue", "purple",
                "focus_alt", "text_secondary", "panel_alt", "urgent", "focus",
                "focus_alt", "blue", "focus_alt", "green", "text",
            ))
        },
    }

    atomic_write(output / "waybar.css", waybar)
    atomic_write(output / "swaync.css", swaync)
    atomic_write(output / "wofi.css", f"{wofi_definitions}\n\n{wofi_base}")
    atomic_write(output / "wlogout.css", wlogout)
    atomic_write(output / "hypr.lua", hypr)
    atomic_write(output / "hyprlock.conf", hyprlock)
    atomic_write(output / "kitty.conf", kitty)
    atomic_write(output / "btop/noctalia.theme", btop)
    atomic_write(output / "vesktop.css", vesktop)
    atomic_write(output / "spotify-palette.json", json.dumps(spotify, indent=2) + "\n")
    atomic_write(output / "pywalfox.json", json.dumps(firefox, indent=2) + "\n")
    for icon in sorted((ROOT / "wlogout/icons").glob("*.png")):
        atomic_copy(icon, output / "icons" / icon.name)
    atomic_write(output / "current-theme", f"{slug}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", required=True, choices=sorted(THEMES))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output
    if output is None:
        cache_home = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        output = cache_home / "hyprland-dots/themes" / args.theme
    render(args.theme, output)


if __name__ == "__main__":
    main()
