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
WAYBAR_STYLE = REPO_DIR / "waybar" / "style.css"
GTK_THEME_PATHS = (
    REPO_DIR / "waybar" / "theme.css",
    REPO_DIR / "wofi" / "theme.css",
    REPO_DIR / "wofi" / "style.css",
    REPO_DIR / "swaync" / "theme.css",
)
HYPR_ENTRYPOINT = REPO_DIR / "hypr" / "hyprland.lua"
HYPR_STARTUP = REPO_DIR / "hypr" / "startup.lua"
HYPR_BINDINGS = REPO_DIR / "hypr" / "bind.lua"
HYPRLOCK_CONFIG = REPO_DIR / "hypr" / "hyprlock.conf"
HYPRIDLE_CONFIG = REPO_DIR / "hypr" / "hypridle.conf"
KITTY_CONFIG = REPO_DIR / "kitty" / "kitty.conf"
WOFI_CONFIG = REPO_DIR / "wofi" / "config"
WOFI_STYLE = REPO_DIR / "wofi" / "style.css"
NETWORKMANAGER_DMENU_CONFIG = REPO_DIR / "networkmanager-dmenu" / "config.ini"
SWAYNC_CONFIG = REPO_DIR / "swaync" / "config.json"
YAZI_CONFIG = REPO_DIR / "yazi" / "yazi.toml"
YAZI_THEME = REPO_DIR / "yazi" / "theme.toml"
FASTFETCH_CONFIG = REPO_DIR / "fastfetch" / "config.jsonc"
CAVA_CONFIG = REPO_DIR / "cava" / "config"
CAVA_THEME = REPO_DIR / "cava" / "themes" / "nighthowler"
SWAYNC_STYLE = REPO_DIR / "swaync" / "style.css"
BTOP_CONFIG = REPO_DIR / "btop" / "btop.conf"
BTOP_THEME = REPO_DIR / "btop" / "themes" / "nighthowler.theme"
FIREFOX_CHROME_THEME = REPO_DIR / "firefox" / "cassan-nighthowler.css"
FIREFOX_CONTENT_THEME = REPO_DIR / "firefox" / "cassan-nighthowler-content.css"
VESKTOP_THEME = REPO_DIR / "vesktop" / "Cassan-Nighthowler.theme.css"
SPICETIFY_COLORS = REPO_DIR / "spicetify" / "Cassan-Nighthowler" / "color.ini"
SPICETIFY_STYLE = REPO_DIR / "spicetify" / "Cassan-Nighthowler" / "user.css"

EXPECTED_WAYBAR_CLUSTERS = {
    "modules-left": ["custom/cassan", "hyprland/workspaces", "mpris"],
    "modules-center": ["hyprland/window"],
    "modules-right": [
        "cpu",
        "memory",
        "pulseaudio",
        "battery",
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
    "normal_window": "true",
    "layer": "top",
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
    "󰤨": ("/usr/bin/nmcli radio wifi", "/usr/bin/nmcli radio wifi"),
    "": ("/usr/bin/bluetoothctl power", "/usr/bin/bluetoothctl show"),
    "󰍬": (
        "/usr/bin/wpctl set-mute @DEFAULT_AUDIO_SOURCE@",
        "/usr/bin/wpctl get-volume @DEFAULT_AUDIO_SOURCE@",
    ),
    "󰕾": (
        "/usr/bin/wpctl set-mute @DEFAULT_AUDIO_SINK@",
        "/usr/bin/wpctl get-volume @DEFAULT_AUDIO_SINK@",
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

EXPECTED_HYPRIDLE_GENERAL = {
    "lock_cmd": "pidof hyprlock || hyprlock",
    "before_sleep_cmd": "loginctl lock-session",
    "after_sleep_cmd": "hyprctl dispatch 'hl.dsp.dpms({ action = \"enable\" })'",
    "ignore_dbus_inhibit": "false",
    "ignore_systemd_inhibit": "false",
    "ignore_wayland_inhibit": "false",
    "inhibit_sleep": "3",
}

EXPECTED_HYPRIDLE_LISTENERS = [
    {
        "timeout": "300",
        "on-timeout": "loginctl lock-session",
        "ignore_inhibit": "false",
    },
    {
        "timeout": "330",
        "on-timeout": "hyprctl dispatch 'hl.dsp.dpms({ action = \"disable\" })'",
        "on-resume": "hyprctl dispatch 'hl.dsp.dpms({ action = \"enable\" })'",
        "ignore_inhibit": "false",
    },
]

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
    """Validate the continuous Waybar surface and its module contract."""
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
            "waybar/config.jsonc must define exactly three positioning zones ("
            + "; ".join(details)
            + ")"
        )

    for key, expected in EXPECTED_WAYBAR_CLUSTERS.items():
        actual = config[key]
        if actual != expected:
            raise ValidationError(
                f"waybar/config.jsonc {key} must be {expected!r}; found {actual!r}"
            )

    for margin in ("margin-top", "margin-right", "margin-bottom", "margin-left"):
        if config.get(margin, 0) != 0:
            raise ValidationError(
                "waybar/config.jsonc must have no outer margins so the bar spans the monitor"
            )
    if "width" in config:
        raise ValidationError(
            "waybar/config.jsonc must not set a fixed width on the full-width bar"
        )

    removed_modules = {"clock", "network", "bluetooth", "backlight", "tray"}
    configured_removed = sorted(removed_modules.intersection(config))
    if configured_removed:
        raise ValidationError(
            "waybar/config.jsonc must not retain removed bar modules: "
            + ", ".join(configured_removed)
        )

    expected_actions = {
        "cpu": {"on-click": "kitty --class cassan-btop btop"},
        "memory": {"on-click": "kitty --class cassan-btop btop"},
        "pulseaudio": {
            "on-click": "wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle",
            "on-click-right": "pavucontrol",
        },
        "custom/notification": {
            "on-click": "swaync-client -t -sw",
            "on-click-right": "swaync-client -d -sw",
        },
    }
    for module, actions in expected_actions.items():
        settings = config.get(module)
        if not isinstance(settings, dict):
            raise ValidationError(f"waybar/config.jsonc must configure {module}")
        for action, expected in actions.items():
            if settings.get(action) != expected:
                raise ValidationError(
                    f"waybar {module}.{action} must remain functional"
                )

    style = read_text(WAYBAR_STYLE)
    continuous_surface = re.compile(
        r"window#waybar\s*\{[^}]*background:\s*@cassan-panel;"
        r"[^}]*border-bottom:\s*2px solid @cassan-focus-inactive;",
        re.DOTALL,
    )
    if not continuous_surface.search(style):
        raise ValidationError(
            "waybar/style.css must draw one continuous panel on the Waybar window"
        )
    island_selectors = {".modules-left", ".modules-center", ".modules-right"}
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", style, re.DOTALL):
        selectors = {selector.strip() for selector in rule.group(1).split(",")}
        if not selectors.intersection(island_selectors):
            continue
        declarations = rule.group(2)
        background_values = re.findall(
            r"background(?:-color)?:\s*([^;]+)", declarations
        )
        nontransparent_background = any(
            value.strip() != "transparent" for value in background_values
        )
        separate_border = re.search(r"(?:^|;)\s*border(?:-[^:]+)?:", declarations)
        radius_values = re.findall(r"border-radius:\s*([^;]+)", declarations)
        rounded = any(value.strip() not in ("0", "0px") for value in radius_values)
        if nontransparent_background or separate_border or rounded:
            raise ValidationError(
                "waybar/style.css must not recreate separate module islands"
            )
    for module in removed_modules:
        if f"#{module}" in style:
            raise ValidationError(
                f"waybar/style.css must not retain styling for removed module {module}"
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


def parse_hypr_blocks(path: Path) -> list[tuple[str, dict[str, list[str]]]]:
    """Parse Cassan's flat Hyprlock/Hypridle block subset without executing it."""
    blocks: list[tuple[str, dict[str, list[str]]]] = []
    block_name = None
    settings: dict[str, list[str]] = {}

    for line_number, source_line in enumerate(read_text(path).splitlines(), 1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue

        if block_name is None:
            match = re.fullmatch(r"([A-Za-z][A-Za-z0-9_-]*)\s*\{", line)
            if not match:
                raise ValidationError(
                    f"{path.relative_to(REPO_DIR)}:{line_number}: expected a block"
                )
            block_name = match.group(1)
            settings = {}
            continue

        if line == "}":
            blocks.append((block_name, settings))
            block_name = None
            settings = {}
            continue

        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*\s*\{", line):
            raise ValidationError(
                f"{path.relative_to(REPO_DIR)}:{line_number}: nested blocks are not supported"
            )
        if "=" not in line:
            raise ValidationError(
                f"{path.relative_to(REPO_DIR)}:{line_number}: expected key = value"
            )
        key, value = (part.strip() for part in line.split("=", 1))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key):
            raise ValidationError(
                f"{path.relative_to(REPO_DIR)}:{line_number}: invalid key {key!r}"
            )
        settings.setdefault(key, []).append(value)

    if block_name is not None:
        raise ValidationError(
            f"{path.relative_to(REPO_DIR)}: unterminated {block_name!r} block"
        )
    return blocks


def single_value_block(
    path: Path, block_name: str, settings: dict[str, list[str]]
) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, candidates in settings.items():
        if len(candidates) != 1:
            raise ValidationError(
                f"{path.relative_to(REPO_DIR)} {block_name}.{key} must occur once"
            )
        values[key] = candidates[0]
    return values


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

    style = read_text(WOFI_STYLE)
    if "@import" in style:
        raise ValidationError(
            "wofi/style.css must be self-contained because Wofi loses relative import paths"
        )
    if "@define-color cassan-panel #151B1D;" not in style:
        raise ValidationError(
            "wofi/style.css must include its generated Nighthowler palette"
        )
    opaque_surface_contracts = (
        re.compile(
            r"window,\s*#window\s*\{[^}]*background-color:\s*@cassan-panel;"
            r"[^}]*opacity:\s*1;",
            re.DOTALL,
        ),
        re.compile(
            r"#outer-box\s*\{[^}]*background-color:\s*@cassan-panel;"
            r"[^}]*opacity:\s*1;",
            re.DOTALL,
        ),
        re.compile(
            r"#scroll,\s*#scroll viewport,\s*#inner-box\s*\{"
            r"[^}]*background-color:\s*@cassan-panel;[^}]*opacity:\s*1;",
            re.DOTALL,
        ),
    )
    if any(not contract.search(style) for contract in opaque_surface_contracts):
        raise ValidationError(
            "wofi/style.css must keep every Wofi 1.5 launcher surface opaque"
        )

    rules = read_text(REPO_DIR / "hypr" / "rules.lua")
    for contract in (
        'match = { class = "wofi" }',
        'opacity = "1.0 override 1.0 override"',
    ):
        if contract not in rules:
            raise ValidationError(
                "hypr/rules.lua must float the opaque normal Wofi window"
            )

    task_manager_contract = (
        'name = "float-cassan-task-manager"',
        'match = { class = "cassan-btop" }',
        'size = { "(monitor_w*0.82)", "(monitor_h*0.80)" }',
    )
    if any(contract not in rules for contract in task_manager_contract):
        raise ValidationError(
            "hypr/rules.lua must keep the btop task manager large and floating"
        )


def validate_networkmanager_dmenu() -> None:
    source = read_text(NETWORKMANAGER_DMENU_CONFIG)
    reject_machine_paths(source, "networkmanager-dmenu/config.ini")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(source)
    except configparser.Error as exc:
        raise ValidationError(
            f"networkmanager-dmenu/config.ini is invalid INI: {exc}"
        ) from exc

    expected = {
        "dmenu": {
            "dmenu_command": "wofi",
            "compact": "True",
            "list_saved": "True",
            "highlight": "True",
            "prompt": "Networks",
        },
        "editor": {
            "gui_if_available": "True",
            "gui": "nm-connection-editor",
            "terminal": "kitty",
        },
        "nmdm": {
            "rescan_delay": "5",
            "show_notifications": "True",
            "notification_timeout": "5",
        },
    }
    if set(parser.sections()) != set(expected):
        raise ValidationError(
            "networkmanager-dmenu/config.ini must define dmenu, editor, and nmdm"
        )
    for section, settings in expected.items():
        for key, value in settings.items():
            if parser.get(section, key, fallback=None) != value:
                raise ValidationError(
                    f"networkmanager-dmenu {section}.{key} must be {value!r}"
                )


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
        if "sh -c" in command or "sh -c" in update_command:
            raise ValidationError(
                f"SwayNC quick setting {label!r} must not add a nested shell layer"
            )
        if not update_command.endswith("; /usr/bin/sleep 0.05"):
            raise ValidationError(
                f"SwayNC quick setting {label!r} must preserve the 0.12.6 output-drain window"
            )
    if set(labels) != set(SWAYNC_TOGGLE_CONTRACTS):
        raise ValidationError("SwayNC quick-setting labels must be unique")

    backlight = widget_config["slider#backlight"]
    if backlight.get("cmd_getter") != "brightnessctl -m | cut -d, -f4 | tr -d '%'":
        raise ValidationError("SwayNC brightness getter must use portable brightnessctl detection")
    if backlight.get("cmd_setter") != "brightnessctl set $value%":
        raise ValidationError("SwayNC brightness setter must use brightnessctl")

    style = read_text(SWAYNC_STYLE)
    for active_selector in ("button.toggle:checked", "button.toggle.active"):
        if active_selector not in style:
            raise ValidationError(
                "SwayNC must visually distinguish active toggles across supported versions"
            )


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


def validate_btop() -> None:
    config = read_text(BTOP_CONFIG)
    reject_machine_paths(config, "btop/btop.conf")
    required_config = {
        'color_theme = "nighthowler"',
        "theme_background = true",
        "truecolor = true",
        "vim_keys = true",
        'shown_boxes = "cpu mem net proc"',
        "save_config_on_exit = false",
    }
    missing_config = sorted(required_config - set(config.splitlines()))
    if missing_config:
        raise ValidationError(
            "btop/btop.conf is missing Cassan task-manager defaults: "
            + ", ".join(missing_config)
        )

    theme = read_text(BTOP_THEME)
    reject_machine_paths(theme, "btop/themes/nighthowler.theme")
    required_theme_keys = {
        "main_bg",
        "main_fg",
        "selected_bg",
        "selected_fg",
        "cpu_box",
        "mem_box",
        "net_box",
        "proc_box",
    }
    found_theme_keys = set(re.findall(r"^theme\[([a-z_]+)\]=\"#[0-9A-Fa-f]{6}\"$", theme, re.MULTILINE))
    if not required_theme_keys <= found_theme_keys:
        raise ValidationError("btop Nighthowler theme is incomplete")
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


def validate_hyprlock() -> None:
    """Validate portable and security-sensitive lock-screen invariants.

    Exact generated styling is checked by render_theme.py --check. Keeping this
    validator focused on invariants avoids duplicating palette and geometry data.
    """
    source = read_text(HYPRLOCK_CONFIG)
    reject_machine_paths(source, "hypr/hyprlock.conf")
    if "aikon" in source.lower():
        raise ValidationError("Hyprlock must discover the current user instead of naming aikon")
    if "path = screenshot" in source:
        raise ValidationError("Hyprlock must not expose the live desktop as its background")

    blocks = parse_hypr_blocks(HYPRLOCK_CONFIG)
    names = [name for name, _ in blocks]
    expected_names = [
        "general",
        "animations",
        "background",
        "shape",
        "label",
        "label",
        "label",
        "label",
        "input-field",
        "label",
    ]
    if names != expected_names:
        raise ValidationError(
            f"hypr/hyprlock.conf widgets must be {expected_names!r}; found {names!r}"
        )

    general = single_value_block(HYPRLOCK_CONFIG, "general", blocks[0][1])
    required_general = {
        "hide_cursor": "true",
        "ignore_empty_input": "true",
        "immediate_render": "true",
    }
    for key, expected in required_general.items():
        if general.get(key) != expected:
            raise ValidationError(
                f"Hyprlock general.{key} must be {expected!r}; found {general.get(key)!r}"
            )
    if "grace" in general:
        raise ValidationError("Hyprlock must not weaken authentication with a grace period")
    try:
        fail_timeout = int(general.get("fail_timeout", ""))
    except ValueError as exc:
        raise ValidationError("Hyprlock general.fail_timeout must be an integer") from exc
    if not 500 <= fail_timeout <= 3000:
        raise ValidationError("Hyprlock failure feedback must clear within 0.5–3 seconds")

    animations = blocks[1][1]
    animation_names = [
        value.split(",", 1)[0].strip() for value in animations.get("animation", [])
    ]
    if animations.get("enabled") != ["true"] or animation_names != [
        "fadeIn",
        "fadeOut",
        "inputFieldColors",
        "inputFieldDots",
    ]:
        raise ValidationError("Hyprlock must retain its restrained animation contract")

    background = single_value_block(HYPRLOCK_CONFIG, "background", blocks[2][1])
    wallpaper = background.get("path", "")
    if not wallpaper.startswith("~/.config/cassan/assets/") or not wallpaper.lower().endswith(
        (".jpg", ".jpeg", ".png", ".webp")
    ):
        raise ValidationError("Hyprlock must load a portable Cassan wallpaper asset")
    if any(
        background.get(key) != expected
        for key, expected in {
            "monitor": "",
            "blur_passes": "0",
            "noise": "0.0",
            "vibrancy": "0.0",
            "vibrancy_darkness": "0.0",
        }.items()
    ):
        raise ValidationError("Hyprlock background must use the unblurred Nighthowler wallpaper")

    shape = single_value_block(HYPRLOCK_CONFIG, "shape", blocks[3][1])
    if (
        shape.get("monitor") != ""
        or shape.get("halign") != "right"
        or shape.get("valign") != "center"
        or shape.get("zindex") != "1"
        or not re.fullmatch(r"rgba\([0-9A-Fa-f]{6}FF\)", shape.get("color", ""))
    ):
        raise ValidationError("Hyprlock must keep one opaque right-side authentication panel")

    label_blocks = [
        single_value_block(HYPRLOCK_CONFIG, "label", settings)
        for name, settings in blocks
        if name == "label"
    ]
    texts = [label.get("text", "") for label in label_blocks]
    if (
        "CASSAN // LOCKED" not in texts
        or "$TIME" not in texts
        or not any(text.startswith("cmd[update:") and " date " in text for text in texts)
        or not any("$USER" in text for text in texts)
        or not any("ESC TO CLEAR" in text for text in texts)
    ):
        raise ValidationError("Hyprlock labels must remain dynamic and machine-independent")
    for label in label_blocks:
        if label.get("monitor") != "" or label.get("halign") != "right":
            raise ValidationError("Hyprlock labels must work on every monitor from the right rail")
        if label.get("zindex") != "2":
            raise ValidationError("Hyprlock labels must render above the authentication panel")

    input_field = single_value_block(HYPRLOCK_CONFIG, "input-field", blocks[8][1])
    if (
        input_field.get("monitor") != ""
        or input_field.get("halign") != "right"
        or input_field.get("valign") != "center"
        or input_field.get("zindex") != "2"
        or input_field.get("hide_input") != "false"
        or "PASSWORD" not in input_field.get("placeholder_text", "")
        or "$ATTEMPTS" not in input_field.get("fail_text", "")
    ):
        raise ValidationError("Hyprlock password field violates the Nighthowler auth contract")

    for name, settings in blocks[2:]:
        if settings.get("monitor") != [""]:
            raise ValidationError(f"Hyprlock {name} hardcodes a monitor")


def validate_hypridle() -> None:
    source = read_text(HYPRIDLE_CONFIG)
    reject_machine_paths(source, "hypr/hypridle.conf")
    for forbidden in (
        "systemctl suspend",
        "systemctl hibernate",
        "systemctl poweroff",
        "brightnessctl",
        "intel_backlight",
        "amdgpu_bl",
        "acpi_video",
    ):
        if forbidden in source:
            raise ValidationError(
                f"hypr/hypridle.conf contains unverified hardware behavior: {forbidden}"
            )

    blocks = parse_hypr_blocks(HYPRIDLE_CONFIG)
    if [name for name, _ in blocks] != ["general", "listener", "listener"]:
        raise ValidationError("Hypridle must contain one general block and two listeners")
    general = single_value_block(HYPRIDLE_CONFIG, "general", blocks[0][1])
    listeners = [
        single_value_block(HYPRIDLE_CONFIG, "listener", settings)
        for _, settings in blocks[1:]
    ]
    if general != EXPECTED_HYPRIDLE_GENERAL:
        raise ValidationError("Hypridle general settings violate the lock-before-sleep contract")
    if listeners != EXPECTED_HYPRIDLE_LISTENERS:
        raise ValidationError("Hypridle must lock at 300 seconds and power displays off at 330")

    startup = read_text(HYPR_STARTUP)
    for command in ("hyprpaper", "waybar", "swaync", "hypridle"):
        invocation = f'hl.exec_cmd("{command}")'
        if startup.count(invocation) != 1:
            raise ValidationError(f"hypr/startup.lua must launch {command} exactly once")
    if "hypridle.service" in startup:
        raise ValidationError("Cassan must not launch Hypridle both directly and as a service")
    polkit = 'hl.exec_cmd("systemctl --user start hyprpolkitagent")'
    if startup.count(polkit) != 1:
        raise ValidationError(
            "hypr/startup.lua must start the graphical authentication agent once"
        )


def validate_style_import(path: Path) -> None:
    source = read_text(path)
    reject_machine_paths(source, str(path.relative_to(REPO_DIR)))
    if not source.startswith('@import url("theme.css");\n'):
        raise ValidationError(
            f"{path.relative_to(REPO_DIR)} must import its generated theme first"
        )


def validate_gtk_themes() -> None:
    """Keep generated colors within GTK CSS's supported color syntax."""
    eight_digit_hex = re.compile(r"#[0-9A-Fa-f]{8}(?![0-9A-Fa-f])")
    expected_transparent = (
        "@define-color cassan-color-transparent rgba(0, 0, 0, 0);"
    )

    for path in GTK_THEME_PATHS:
        source = read_text(path)
        if eight_digit_hex.search(source):
            raise ValidationError(
                f"{path.relative_to(REPO_DIR)} contains GTK-incompatible "
                "eight-digit hex color syntax"
            )
        if expected_transparent not in source.splitlines():
            raise ValidationError(
                f"{path.relative_to(REPO_DIR)} must render transparency as rgba()"
            )


def validate_application_themes() -> None:
    """Keep optional app themes local, generated, and intentionally narrow."""
    firefox_chrome = read_text(FIREFOX_CHROME_THEME)
    firefox_content = read_text(FIREFOX_CONTENT_THEME)
    vesktop = read_text(VESKTOP_THEME)
    spicetify_style = read_text(SPICETIFY_STYLE)

    if "#navigator-toolbox" not in firefox_chrome or "#urlbar-background" not in firefox_chrome:
        raise ValidationError("Firefox chrome theme must cover the toolbar and address field")
    unsafe_firefox_rules = ("display: none", "visibility: hidden", "#identity-box")
    if any(rule in firefox_chrome for rule in unsafe_firefox_rules):
        raise ValidationError("Firefox chrome theme must not hide navigation or identity controls")
    expected_content_scope = (
        '@-moz-document url("about:home"), url("about:newtab"), url("about:blank")'
    )
    if expected_content_scope not in firefox_content:
        raise ValidationError("Firefox content theme must remain limited to built-in new-tab pages")
    if "url-prefix(" in firefox_content or 'domain("' in firefox_content:
        raise ValidationError("Firefox content theme must not style ordinary websites")

    if not vesktop.startswith("/**\n * @name Cassan Nighthowler\n"):
        raise ValidationError("Vesktop theme must begin with local Vencord metadata")
    for remote_token in ("@import", "http://", "https://"):
        if remote_token in vesktop:
            raise ValidationError("Vesktop theme must not load remote styles or assets")
    for opaque_token in ("background: transparent", "background-color: transparent", "opacity:"):
        if opaque_token in vesktop:
            raise ValidationError("Vesktop theme must keep its application surfaces opaque")

    colors = configparser.ConfigParser(interpolation=None, strict=True)
    colors.optionxform = str
    try:
        colors.read_string(read_text(SPICETIFY_COLORS), source=str(SPICETIFY_COLORS))
    except configparser.Error as exc:
        raise ValidationError(f"invalid Spicetify color.ini: {exc}") from exc
    if colors.sections() != ["Nighthowler"]:
        raise ValidationError("Spicetify colors must define exactly [Nighthowler]")
    expected_color_keys = {
        "text",
        "subtext",
        "main",
        "main-elevated",
        "main-transition",
        "highlight",
        "highlight-elevated",
        "sidebar",
        "player",
        "card",
        "shadow",
        "selected-row",
        "button",
        "button-active",
        "button-disabled",
        "tab-active",
        "notification",
        "notification-error",
        "misc",
        "play-button",
        "play-button-active",
        "progress-fg",
        "progress-bg",
        "heart",
        "pagelink-active",
        "radio-btn-active",
    }
    actual_color_keys = set(colors["Nighthowler"])
    if actual_color_keys != expected_color_keys:
        raise ValidationError("Spicetify color scheme violates its generated key contract")
    for name, value in colors["Nighthowler"].items():
        if not re.fullmatch(r"[0-9a-f]{6}", value.strip()):
            raise ValidationError(f"Spicetify color {name} must be six lowercase hex digits")
    if "@import" in spicetify_style or "http://" in spicetify_style or "https://" in spicetify_style:
        raise ValidationError("Spicetify theme must not load remote styles or assets")


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

    bindings = read_text(HYPR_BINDINGS)
    for command in (
        '"firefox"',
        '"vesktop"',
        '[[/usr/bin/spotify-launcher --no-exec && /usr/bin/env -u SPICETIFY_CONFIG '
        '-u SPICETIFY_STATE "$HOME/.spicetify/spicetify" --no-restart auto && '
        '/usr/bin/spotify-launcher --skip-update]]',
        '"kitty --class cassan-btop btop"',
        '"kitty --hold --class cassan-fastfetch fastfetch"',
        '"kitty --class cassan-cava cava"',
    ):
        if bindings.count(command) != 1:
            raise ValidationError(
                f"hypr/bind.lua must define the optional app command {command} once"
            )
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
        validate_networkmanager_dmenu()
        validate_swaync()
        validate_yazi()
        validate_fastfetch()
        validate_cava()
        validate_btop()
        validate_hyprlock()
        validate_hypridle()
        validate_gtk_themes()
        validate_application_themes()
        validate_style_import(REPO_DIR / "swaync" / "style.css")
        compile_lua(lua_files)
    except ValidationError as exc:
        print(f"configuration validation failed: {exc}", file=sys.stderr)
        return 1

    print("Desktop configuration contracts passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
