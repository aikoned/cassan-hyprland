#!/usr/bin/env python3

import argparse
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

    atomic_write(output / "waybar.css", waybar)
    atomic_write(output / "swaync.css", swaync)
    atomic_write(output / "wofi.css", f"{wofi_definitions}\n\n{wofi_base}")
    atomic_write(output / "wlogout.css", wlogout)
    atomic_write(output / "hypr.lua", hypr)
    atomic_write(output / "hyprlock.conf", hyprlock)
    atomic_write(output / "kitty.conf", kitty)
    atomic_write(output / "btop/noctalia.theme", btop)
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
