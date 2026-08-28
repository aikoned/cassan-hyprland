#!/usr/bin/env python3

"""Validate Cassan's foundational TOML files using only Python's standard library."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


REPO = Path(__file__).resolve().parents[1]
PALETTE_PATH = REPO / "assets" / "nighthowler" / "palette.toml"
HOSTS_PATH = REPO / "hosts"
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{8}$|^#[0-9A-Fa-f]{6}$")
SAFE_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_THEME_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REQUIRED_ROLES = {
    "background",
    "panel",
    "panel_alternate",
    "text",
    "text_secondary",
    "text_muted",
    "focus",
    "focus_inactive",
    "warm_accent",
    "urgent",
}


def parse_scalar(value: str):
    if value in {"true", "false"}:
        return value == "true"
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError) as error:
        raise ValueError(f"unsupported TOML value: {value}") from error


def load_simple_toml(path: Path) -> dict:
    """Parse the small TOML subset used here when Python is older than 3.11."""

    document: dict = {}
    section = document

    for line_number, source_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip()
            if not name or "." in name:
                raise ValueError(f"{path}:{line_number}: unsupported section name")
            section = document.setdefault(name, {})
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected key = value")
        key, raw_value = (part.strip() for part in line.split("=", 1))
        if not key or key in section:
            raise ValueError(f"{path}:{line_number}: invalid or duplicate key")
        section[key] = parse_scalar(raw_value)

    return document


def load(path: Path) -> dict:
    if tomllib is None:
        return load_simple_toml(path)
    with path.open("rb") as source:
        return tomllib.load(source)


def validate_palette() -> None:
    palette = load(PALETTE_PATH)
    slug = palette.get("slug")
    colors = palette.get("colors", {})
    roles = palette.get("roles", {})
    typography = palette.get("typography", {})
    geometry = palette.get("geometry", {})
    animation = palette.get("animation", {})
    wallpaper = palette.get("wallpaper", {})
    layout = palette.get("layout", {})

    if not colors:
        raise ValueError("Nighthowler palette has no colors")
    if not isinstance(slug, str) or not SAFE_THEME_SLUG.fullmatch(slug):
        raise ValueError("theme slug must contain only lowercase letters, numbers, and hyphens")

    invalid = {
        name: value
        for name, value in colors.items()
        if not isinstance(value, str) or not HEX_COLOR.fullmatch(value)
    }
    if invalid:
        raise ValueError(f"invalid palette colors: {invalid}")

    missing_roles = REQUIRED_ROLES.difference(roles)
    if missing_roles:
        raise ValueError(f"palette is missing semantic roles: {sorted(missing_roles)}")

    unknown_roles = {name: value for name, value in roles.items() if value not in colors}
    if unknown_roles:
        raise ValueError(f"palette roles reference unknown colors: {unknown_roles}")

    if not typography.get("desktop_font") or not typography.get("terminal_font"):
        raise ValueError("palette must define desktop and terminal fonts")

    positive_geometry = {
        "border_px",
        "gap_inner_px",
        "gap_outer_px",
        "bar_height_px",
        "bar_margin_px",
        "panel_padding_px",
        "shadow_blur_px",
    }
    invalid_geometry = {
        key: geometry.get(key)
        for key in positive_geometry
        if not isinstance(geometry.get(key), int) or geometry[key] <= 0
    }
    if invalid_geometry:
        raise ValueError(f"invalid positive geometry values: {invalid_geometry}")
    if not isinstance(geometry.get("rounding_px"), int) or geometry["rounding_px"] < 0:
        raise ValueError("rounding_px must be a non-negative integer")
    if geometry.get("blur_enabled") is not False:
        raise ValueError("Nighthowler's base visual contract keeps blur disabled")

    durations = {
        name: value
        for name, value in animation.items()
        if name.startswith("duration_") and (not isinstance(value, int) or value <= 0)
    }
    if durations:
        raise ValueError(f"invalid animation durations: {durations}")
    if animation.get("overshoot") is not False:
        raise ValueError("Nighthowler animations must not overshoot")

    if wallpaper.get("asset_policy") not in {"bundled-private", "user-supplied"}:
        raise ValueError("wallpaper asset policy must be bundled-private or user-supplied")
    wallpaper_filename = str(wallpaper.get("filename", ""))
    if not SAFE_ASSET_NAME.fullmatch(wallpaper_filename):
        raise ValueError("wallpaper filename must be a safe relative filename")
    if wallpaper.get("redistributable") is not False:
        raise ValueError("unverified wallpaper assets must remain non-redistributable")
    if wallpaper.get("asset_policy") == "bundled-private":
        wallpaper_path = REPO / "assets" / slug / wallpaper_filename
        if not wallpaper_path.is_file():
            raise ValueError(f"bundled wallpaper is missing: {wallpaper_path}")
    if wallpaper.get("fit") != "cover" or wallpaper.get("position") != "center":
        raise ValueError("wallpaper must use centered cover placement")

    if layout.get("bar_islands") != 3:
        raise ValueError("Nighthowler must define three bar islands")
    if layout.get("subject_safe_area") != "center":
        raise ValueError("Nighthowler must preserve a center subject safe area")


def validate_host(path: Path) -> None:
    host = load(path)
    expected_hostname = path.parent.name
    hostname = host.get("hostname")

    if hostname != expected_hostname:
        raise ValueError(
            f"{path}: hostname must match its profile directory ({expected_hostname})"
        )
    if host.get("hardware_status") not in {"pending", "confirmed"}:
        raise ValueError(f"{path}: hardware_status must be pending or confirmed")


def validate_hosts() -> None:
    if not HOSTS_PATH.is_dir():
        return

    for path in sorted(HOSTS_PATH.glob("*/host.toml")):
        validate_host(path)


def main() -> int:
    try:
        validate_palette()
        validate_hosts()
    except (OSError, ValueError) as error:
        print(f"validation failed: {error}", file=sys.stderr)
        return 1

    print("TOML validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
