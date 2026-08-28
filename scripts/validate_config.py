#!/usr/bin/env python3
"""Validate Cassan's portable desktop configuration contracts."""

from __future__ import annotations

import configparser
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from validate_toml import load as load_toml


REPO_DIR = Path(__file__).resolve().parent.parent
WAYBAR_CONFIG = REPO_DIR / "waybar" / "config.jsonc"
HYPR_ENTRYPOINT = REPO_DIR / "hypr" / "hyprland.lua"
KITTY_CONFIG = REPO_DIR / "kitty" / "kitty.conf"
WOFI_CONFIG = REPO_DIR / "wofi" / "config"
SWAYNC_CONFIG = REPO_DIR / "swaync" / "config.json"
YAZI_CONFIG = REPO_DIR / "yazi" / "yazi.toml"
YAZI_THEME = REPO_DIR / "yazi" / "theme.toml"
FASTFETCH_CONFIG = REPO_DIR / "fastfetch" / "config.jsonc"
CAVA_CONFIG = REPO_DIR / "cava" / "config"
CAVA_THEME = REPO_DIR / "cava" / "themes" / "nighthowler"

EXPECTED_WAYBAR_CLUSTERS = {
    "modules-left": ["custom/cassan", "hyprland/workspaces", "mpris"],
    "modules-center": ["hyprland/window"],
    "modules-right": [
        "cpu",
        "memory",
        "clock",
        "network",
        "bluetooth",
        "pulseaudio",
        "backlight",
        "battery",
        "tray",
        "custom/notification",
    ],
}

EXPECTED_HYPR_MODULES = (
    "environment",
    "monitor",
    "looknfeel",
    "input",
    "animation",
    "rules",
    "startup",
    "bind",
)

EXPECTED_WOFI_SETTINGS = {
    "show": "drun",
    "prompt": "Launch",
    "width": "34%",
    "lines": "7",
    "columns": "1",
    "location": "center",
    "layer": "overlay",
    "orientation": "vertical",
    "halign": "fill",
    "content_halign": "fill",
    "valign": "start",
    "dynamic_lines": "true",
    "allow_images": "true",
    "image_size": "32",
    "allow_markup": "false",
    "hide_scroll": "true",
    "matching": "fuzzy",
    "insensitive": "true",
    "parse_search": "true",
    "filter_rate": "100",
    "sort_order": "default",
    "no_custom_entry": "true",
    "close_on_focus_loss": "true",
    "single_click": "true",
    "term": "kitty",
    "key_up": "Ctrl-k,Up",
    "key_down": "Ctrl-j,Down",
    "key_submit": "Return,KP_Enter",
    "key_exit": "Escape",
    "key_expand": "Alt-l",
    "drun-display_generic": "false",
    "drun-ignore_metadata": "false",
}

EXPECTED_SWAYNC_WIDGETS = [
    "buttons-grid#quick-settings",
    "mpris",
    "volume",
    "slider#backlight",
    "dnd",
    "title",
    "notifications",
]

EXPECTED_SWAYNC_WIDGET_CONFIGS = set(EXPECTED_SWAYNC_WIDGETS)

EXPECTED_SWAYNC_TOP_LEVEL_KEYS = {
    "$schema",
    "ignore-gtk-theme",
    "cssPriority",
    "positionX",
    "positionY",
    "layer",
    "control-center-layer",
    "layer-shell",
    "layer-shell-cover-screen",
    "control-center-exclusive-zone",
    "control-center-margin-top",
    "control-center-margin-bottom",
    "control-center-margin-right",
    "control-center-margin-left",
    "fit-to-screen",
    "control-center-width",
    "notification-window-width",
    "notification-window-height",
    "notification-2fa-action",
    "notification-inline-replies",
    "timeout",
    "timeout-low",
    "timeout-critical",
    "relative-timestamps",
    "keyboard-shortcuts",
    "notification-grouping",
    "image-visibility",
    "transition-time",
    "hide-on-clear",
    "hide-on-action",
    "text-empty",
    "script-fail-notify",
    "widgets",
    "widget-config",
}

SWAYNC_TOGGLE_CONTRACTS = {
    "󰤨": ("nmcli radio wifi", "nmcli radio wifi"),
    "": ("bluetoothctl power", "bluetoothctl show"),
    "󰍬": (
        "wpctl set-mute @DEFAULT_AUDIO_SOURCE@",
        "wpctl get-volume @DEFAULT_AUDIO_SOURCE@",
    ),
    "󰕾": (
        "wpctl set-mute @DEFAULT_AUDIO_SINK@",
        "wpctl get-volume @DEFAULT_AUDIO_SINK@",
    ),
}

DEPRECATED_SWAYNC_KEYS = {
    "notification-icon-size",
    "image-size",
    "image-radius",
    "icon-size",
    "right-click-command",
}

EXPECTED_YAZI_CONFIG = {
    "mgr": {
        "ratio": [1, 4, 3],
        "sort_by": "natural",
        "sort_sensitive": False,
        "sort_reverse": False,
        "sort_dir_first": True,
        "sort_translit": False,
        "sort_fallback": "natural",
        "linemode": "size",
        "show_hidden": False,
        "show_symlink": True,
        "scrolloff": 5,
        "mouse_events": ["click", "scroll"],
    },
    "preview": {
        "wrap": "no",
        "tab_size": 2,
        "max_width": 1200,
        "max_height": 1200,
        "image_delay": 30,
        "image_filter": "triangle",
        "image_quality": 75,
    },
}

EXPECTED_YAZI_THEME_SECTIONS = [
    "app",
    "mgr",
    "tabs",
    "mode",
    "indicator",
    "status",
    "which",
    "confirm",
    "spot",
    "notify",
    "pick",
    "input",
    "cmp",
    "tasks",
    "help",
]

EXPECTED_FASTFETCH_MODULES = [
    "title",
    "separator",
    "os",
    "host",
    "kernel",
    "packages",
    "shell",
    "wm",
    "terminal",
    "terminalfont",
    "cpu",
    "gpu",
    "memory",
    "battery",
    "uptime",
    "media",
    "break",
    "colors",
]

EXPECTED_CAVA_CONFIG = {
    "general": {
        "framerate": "30",
        "autosens": "1",
        "sensitivity": "100",
        "scaling": "linear",
        "bars": "0",
        "bar_width": "2",
        "bar_spacing": "1",
        "center_align": "1",
        "max_height": "92",
        "lower_cutoff_freq": "50",
        "higher_cutoff_freq": "10000",
        "sleep_timer": "3",
    },
    "input": {"method": "pipewire", "source": "auto"},
    "output": {
        "method": "noncurses",
        "orientation": "bottom",
        "channels": "stereo",
        "mono_option": "average",
        "reverse": "0",
        "xaxis": "none",
        "synchronized_sync": "0",
        "show_idle_bar_heads": "0",
    },
    "color": {"theme": "'nighthowler'"},
    "smoothing": {"monstercat": "0", "waves": "0", "noise_reduction": "77"},
}

REQUIRE_RE = re.compile(
    r"\brequire\s*(?:\(\s*)?(['\"])([A-Za-z0-9_./-]+)\1\s*\)?"
)


class ValidationError(ValueError):
    """Raised when a configuration violates the repository contract."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting duplicate keys."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def reject_non_finite_number(value: str) -> None:
    """Reject NaN and infinities, which are not part of strict JSON."""
    raise ValidationError(f"non-finite JSON number is not allowed: {value}")


def load_strict_json(path: Path) -> Any:
    """Load strict JSON, including duplicate-key and finite-number checks."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"cannot read {path.relative_to(REPO_DIR)}: {exc}") from exc

    try:
        return json.loads(
            source,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite_number,
        )
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValidationError(
            f"{path.relative_to(REPO_DIR)} is not strict JSON: {exc}"
        ) from exc


def validate_waybar() -> None:
    """Validate the Waybar document and its three intentional islands."""
    config = load_strict_json(WAYBAR_CONFIG)
    if not isinstance(config, dict):
        raise ValidationError("waybar/config.jsonc must contain one JSON object")

    cluster_keys = {key for key in config if key.startswith("modules-")}
    expected_keys = set(EXPECTED_WAYBAR_CLUSTERS)
    if cluster_keys != expected_keys:
        missing = sorted(expected_keys - cluster_keys)
        unexpected = sorted(cluster_keys - expected_keys)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected {', '.join(unexpected)}")
        raise ValidationError(
            "waybar/config.jsonc must define exactly three module clusters ("
            + "; ".join(details)
            + ")"
        )

    for key, expected in EXPECTED_WAYBAR_CLUSTERS.items():
        actual = config[key]
        if actual != expected:
            raise ValidationError(
                f"waybar/config.jsonc {key} must be {expected!r}; found {actual!r}"
            )


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"cannot read {path.relative_to(REPO_DIR)}: {exc}") from exc


def reject_machine_paths(source: str, label: str) -> None:
    for prefix in ("/home/", "/Users/"):
        if prefix in source:
            raise ValidationError(f"{label} contains a machine-specific path: {prefix}")


def parse_directives(path: Path) -> dict[str, str]:
    directives: dict[str, str] = {}
    for line_number, source_line in enumerate(read_text(path).splitlines(), 1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ValidationError(
                f"{path.relative_to(REPO_DIR)}:{line_number}: expected directive and value"
            )
        key, value = parts
        if key in directives:
            raise ValidationError(
                f"{path.relative_to(REPO_DIR)}:{line_number}: duplicate directive {key!r}"
            )
        directives[key] = value
    return directives


def validate_kitty() -> None:
    source = read_text(KITTY_CONFIG)
    reject_machine_paths(source, "kitty/kitty.conf")
    directives = parse_directives(KITTY_CONFIG)

    required = {
        "include": "theme.conf",
        "shell": ".",
        "shell_integration": "enabled",
        "background_opacity": "1.0",
        "dynamic_background_opacity": "no",
        "background_blur": "0",
        "copy_on_select": "no",
        "enable_audio_bell": "no",
    }
    for key, expected in required.items():
        actual = directives.get(key)
        if actual != expected:
            raise ValidationError(
                f"kitty/kitty.conf {key} must be {expected!r}; found {actual!r}"
            )

    forbidden = {
        "allow_remote_control",
        "input_delay",
        "linux_display_server",
        "repaint_delay",
        "remote_control_password",
        "sync_to_monitor",
    }
    present = sorted(forbidden.intersection(directives))
    if present:
        raise ValidationError(
            "kitty/kitty.conf must retain portable upstream defaults for: "
            + ", ".join(present)
        )


def parse_assignments(path: Path) -> dict[str, str]:
    settings: dict[str, str] = {}
    for line_number, source_line in enumerate(read_text(path).splitlines(), 1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValidationError(
                f"{path.relative_to(REPO_DIR)}:{line_number}: expected key=value"
            )
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or key in settings:
            raise ValidationError(
                f"{path.relative_to(REPO_DIR)}:{line_number}: empty or duplicate key"
            )
        settings[key] = value
    return settings


def validate_wofi() -> None:
    source = read_text(WOFI_CONFIG)
    reject_machine_paths(source, "wofi/config")
    settings = parse_assignments(WOFI_CONFIG)
    if settings != EXPECTED_WOFI_SETTINGS:
        missing = sorted(set(EXPECTED_WOFI_SETTINGS) - set(settings))
        unexpected = sorted(set(settings) - set(EXPECTED_WOFI_SETTINGS))
        changed = sorted(
            key
            for key in set(settings).intersection(EXPECTED_WOFI_SETTINGS)
            if settings[key] != EXPECTED_WOFI_SETTINGS[key]
        )
        details = []
        if missing:
            details.append(f"missing {missing}")
        if unexpected:
            details.append(f"unexpected {unexpected}")
        if changed:
            details.append(f"changed {changed}")
        raise ValidationError("wofi/config violates its portable launcher contract: " + "; ".join(details))


def nested_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from nested_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_keys(child)


def validate_swaync() -> None:
    config = load_strict_json(SWAYNC_CONFIG)
    if not isinstance(config, dict):
        raise ValidationError("swaync/config.json must contain one JSON object")

    source = read_text(SWAYNC_CONFIG)
    reject_machine_paths(source, "swaync/config.json")
    for hardware_name in ("intel_backlight", "amdgpu_bl", "acpi_video"):
        if hardware_name in source:
            raise ValidationError(
                f"swaync/config.json hardcodes a backlight device: {hardware_name}"
            )

    deprecated = sorted(DEPRECATED_SWAYNC_KEYS.intersection(nested_keys(config)))
    if deprecated:
        raise ValidationError(
            "swaync/config.json uses deprecated or unsupported fields: "
            + ", ".join(deprecated)
        )

    expected_top_level = {
        "$schema": "/etc/xdg/swaync/configSchema.json",
        "ignore-gtk-theme": True,
        "cssPriority": "user",
        "positionX": "right",
        "positionY": "top",
        "layer": "overlay",
        "control-center-layer": "overlay",
        "layer-shell": True,
        "layer-shell-cover-screen": True,
        "control-center-exclusive-zone": True,
        "control-center-margin-top": 10,
        "control-center-margin-bottom": 10,
        "control-center-margin-right": 10,
        "control-center-margin-left": 10,
        "fit-to-screen": True,
        "control-center-width": 420,
        "notification-window-width": 400,
        "notification-window-height": -1,
        "notification-2fa-action": False,
        "notification-inline-replies": False,
        "timeout": 6,
        "timeout-low": 4,
        "timeout-critical": 0,
        "relative-timestamps": True,
        "notification-grouping": True,
        "image-visibility": "when-available",
        "transition-time": 120,
        "keyboard-shortcuts": True,
        "hide-on-clear": False,
        "hide-on-action": True,
        "text-empty": "No notifications",
        "script-fail-notify": False,
    }
    if set(config) != EXPECTED_SWAYNC_TOP_LEVEL_KEYS:
        missing = sorted(EXPECTED_SWAYNC_TOP_LEVEL_KEYS - set(config))
        unexpected = sorted(set(config) - EXPECTED_SWAYNC_TOP_LEVEL_KEYS)
        raise ValidationError(
            "swaync/config.json top-level fields do not match the 0.12.6 contract: "
            f"missing {missing}; unexpected {unexpected}"
        )
    for key, expected in expected_top_level.items():
        actual = config.get(key)
        if actual != expected:
            raise ValidationError(
                f"swaync/config.json {key} must be {expected!r}; found {actual!r}"
            )

    if "control-center-height" in config:
        raise ValidationError(
            "swaync/config.json must stay responsive instead of setting control-center-height"
        )
    if "scripts" in config or "notification-visibility" in config:
        raise ValidationError(
            "swaync/config.json must not run scripts for incoming notifications"
        )
    if config.get("widgets") != EXPECTED_SWAYNC_WIDGETS:
        raise ValidationError(
            f"swaync/config.json widgets must be {EXPECTED_SWAYNC_WIDGETS!r}"
        )

    widget_config = config.get("widget-config")
    if not isinstance(widget_config, dict):
        raise ValidationError("swaync/config.json widget-config must be an object")
    if set(widget_config) != EXPECTED_SWAYNC_WIDGET_CONFIGS:
        raise ValidationError(
            "swaync/config.json widget-config keys must match the widget stack"
        )

    quick_settings = widget_config["buttons-grid#quick-settings"]
    if quick_settings.get("buttons-per-row") != 4:
        raise ValidationError("SwayNC quick settings must use one row of four buttons")
    actions = quick_settings.get("actions")
    if not isinstance(actions, list) or len(actions) != len(SWAYNC_TOGGLE_CONTRACTS):
        raise ValidationError("SwayNC quick settings must define four toggle actions")

    labels = []
    for action in actions:
        if not isinstance(action, dict):
            raise ValidationError("each SwayNC quick setting must be an object")
        label = action.get("label")
        labels.append(label)
        contract = SWAYNC_TOGGLE_CONTRACTS.get(label)
        if contract is None:
            raise ValidationError(f"unexpected SwayNC quick-setting label: {label!r}")
        if action.get("type") != "toggle":
            raise ValidationError(f"SwayNC quick setting {label!r} must be a toggle")
        if not isinstance(action.get("active"), bool):
            raise ValidationError(
                f"SwayNC quick setting {label!r} must define a boolean active fallback"
            )
        command = action.get("command", "")
        update_command = action.get("update-command", "")
        if "SWAYNC_TOGGLE_STATE" not in command:
            raise ValidationError(f"SwayNC quick setting {label!r} ignores its toggle state")
        if contract[0] not in command or contract[1] not in update_command:
            raise ValidationError(f"SwayNC quick setting {label!r} violates its command contract")
    if set(labels) != set(SWAYNC_TOGGLE_CONTRACTS):
        raise ValidationError("SwayNC quick-setting labels must be unique")

    backlight = widget_config["slider#backlight"]
    if backlight.get("cmd_getter") != "brightnessctl -m | cut -d, -f4 | tr -d '%'":
        raise ValidationError("SwayNC brightness getter must use portable brightnessctl detection")
    if backlight.get("cmd_setter") != "brightnessctl set $value%":
        raise ValidationError("SwayNC brightness setter must use brightnessctl")


def validate_yazi() -> None:
    source = read_text(YAZI_CONFIG)
    reject_machine_paths(source, "yazi/yazi.toml")
    if not source.startswith("#:schema https://yazi-rs.github.io/schemas/yazi.json\n"):
        raise ValidationError("yazi/yazi.toml must declare Yazi's current schema first")

    try:
        config = load_toml(YAZI_CONFIG)
    except (OSError, ValueError) as exc:
        raise ValidationError(f"yazi/yazi.toml is invalid TOML: {exc}") from exc
    if config != EXPECTED_YAZI_CONFIG:
        raise ValidationError("yazi/yazi.toml violates its portable three-pane contract")

    theme = read_text(YAZI_THEME)
    reject_machine_paths(theme, "yazi/theme.toml")
    if not theme.startswith("#:schema https://yazi-rs.github.io/schemas/theme.json\n"):
        raise ValidationError("yazi/theme.toml must declare Yazi's current theme schema first")
    sections = re.findall(r"^\[([a-z]+)\]$", theme, flags=re.MULTILINE)
    if sections != EXPECTED_YAZI_THEME_SECTIONS:
        raise ValidationError(
            "yazi/theme.toml must style only the maintained Nighthowler UI sections; "
            f"found {sections!r}"
        )
    if "[filetype]" in theme or "[completion]" in theme:
        raise ValidationError(
            "yazi/theme.toml must retain Yazi's maintained file icons and current cmp section"
        )


def fastfetch_module_type(module: Any) -> str:
    if isinstance(module, str):
        return module
    if not isinstance(module, dict) or not isinstance(module.get("type"), str):
        raise ValidationError("each Fastfetch module must be a string or typed object")
    if not isinstance(module.get("key"), str) or not module["key"].strip():
        raise ValidationError(f"Fastfetch module {module['type']!r} must have a visible key")
    return module["type"]


def validate_fastfetch() -> None:
    config = load_strict_json(FASTFETCH_CONFIG)
    if not isinstance(config, dict):
        raise ValidationError("fastfetch/config.jsonc must contain one JSON object")

    source = read_text(FASTFETCH_CONFIG)
    reject_machine_paths(source, "fastfetch/config.jsonc")
    if "aikon" in source.lower():
        raise ValidationError("Fastfetch must detect the user's hostname instead of naming aikon")
    if set(config) != {"$schema", "logo", "display", "modules"}:
        raise ValidationError("Fastfetch must contain exactly schema, logo, display, and modules")
    if config["$schema"] != (
        "https://raw.githubusercontent.com/fastfetch-cli/fastfetch/2.67.1/"
        "doc/json_schema.json"
    ):
        raise ValidationError("Fastfetch must pin the Arch stable 2.67.1 schema")

    logo = config.get("logo")
    expected_logo = {
        "type": "builtin",
        "source": "arch",
        "color": {"1": "#A173C9", "2": "#F2D7DF"},
        "padding": {"top": 1, "left": 1, "right": 3},
        "printRemaining": True,
        "position": "left",
    }
    if logo != expected_logo:
        raise ValidationError("Fastfetch logo must use the themed built-in Arch Linux ASCII art")

    modules = config.get("modules")
    if not isinstance(modules, list):
        raise ValidationError("Fastfetch modules must be an ordered list")
    module_types = [fastfetch_module_type(module) for module in modules]
    if module_types != EXPECTED_FASTFETCH_MODULES:
        raise ValidationError(
            f"Fastfetch modules must be {EXPECTED_FASTFETCH_MODULES!r}; found {module_types!r}"
        )
    if any(module_type in {"command", "custom"} for module_type in module_types):
        raise ValidationError("Fastfetch must not execute custom commands")


def load_ini(path: Path) -> dict[str, dict[str, str]]:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read_string(read_text(path))
    except configparser.Error as exc:
        raise ValidationError(f"{path.relative_to(REPO_DIR)} is invalid INI: {exc}") from exc
    return {section: dict(parser.items(section)) for section in parser.sections()}


def validate_cava() -> None:
    source = read_text(CAVA_CONFIG)
    reject_machine_paths(source, "cava/config")
    config = load_ini(CAVA_CONFIG)
    if config != EXPECTED_CAVA_CONFIG:
        raise ValidationError("cava/config violates its portable low-overhead PipeWire contract")

    theme_source = read_text(CAVA_THEME)
    reject_machine_paths(theme_source, "cava/themes/nighthowler")
    theme = load_ini(CAVA_THEME)
    if set(theme) != {"color"}:
        raise ValidationError("Cava's Nighthowler theme must contain only its color section")
    color = theme["color"]
    if color.get("gradient") != "1" or "gradient_count" in color:
        raise ValidationError("Cava must use its documented implicit gradient color count")
    gradient_keys = [f"gradient_color_{index}" for index in range(1, 7)]
    if set(color) != {"background", "foreground", "gradient", *gradient_keys}:
        raise ValidationError("Cava's Nighthowler theme must define exactly six gradient stops")
    for key in ("background", "foreground", *gradient_keys):
        value = color[key].strip("'\"")
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
            raise ValidationError(f"Cava theme {key} is not a six-digit hex color")


def validate_style_import(path: Path) -> None:
    source = read_text(path)
    reject_machine_paths(source, str(path.relative_to(REPO_DIR)))
    if not source.startswith('@import url("theme.css");\n'):
        raise ValidationError(
            f"{path.relative_to(REPO_DIR)} must import its generated theme first"
        )


def lua_requires(source: str) -> list[str]:
    """Extract simple require calls in source order, ignoring line comments."""
    modules: list[str] = []
    for line in source.splitlines():
        code = line.split("--", 1)[0]
        modules.extend(match.group(2) for match in REQUIRE_RE.finditer(code))
    return modules


def validate_hypr() -> list[Path]:
    """Validate Hyprland's module imports and return Lua files to compile."""
    try:
        source = HYPR_ENTRYPOINT.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"cannot read hypr/hyprland.lua: {exc}") from exc

    required = lua_requires(source)
    if required != list(EXPECTED_HYPR_MODULES):
        raise ValidationError(
            "hypr/hyprland.lua must require modules in this exact order: "
            + ", ".join(EXPECTED_HYPR_MODULES)
            + f"; found: {', '.join(required) or '(none)'}"
        )

    lua_files = [HYPR_ENTRYPOINT]
    for module in EXPECTED_HYPR_MODULES:
        module_path = REPO_DIR / "hypr" / f"{module}.lua"
        if not module_path.is_file():
            raise ValidationError(
                f"required Hyprland module is missing: hypr/{module}.lua"
            )
        lua_files.append(module_path)

    theme_path = REPO_DIR / "hypr" / "theme.lua"
    if not theme_path.is_file():
        raise ValidationError("required generated theme is missing: hypr/theme.lua")
    lua_files.append(theme_path)
    return lua_files


def compile_lua(lua_files: list[Path]) -> None:
    """Syntax-check Lua sources when a compiler is installed."""
    luac = shutil.which("luac")
    if luac is None:
        print("Lua syntax check skipped (luac unavailable).")
        return

    for path in lua_files:
        result = subprocess.run(
            [luac, "-p", str(path)],
            cwd=REPO_DIR,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            relative = path.relative_to(REPO_DIR)
            raise ValidationError(f"Lua syntax check failed for {relative}: {detail}")


def main() -> int:
    try:
        validate_waybar()
        lua_files = validate_hypr()
        validate_kitty()
        validate_wofi()
        validate_swaync()
        validate_yazi()
        validate_fastfetch()
        validate_cava()
        validate_style_import(REPO_DIR / "wofi" / "style.css")
        validate_style_import(REPO_DIR / "swaync" / "style.css")
        compile_lua(lua_files)
    except ValidationError as exc:
        print(f"configuration validation failed: {exc}", file=sys.stderr)
        return 1

    print("Desktop configuration contracts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
