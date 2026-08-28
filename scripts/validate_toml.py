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
    colors = palette.get("colors", {})
    roles = palette.get("roles", {})

    if not colors:
        raise ValueError("Nighthowler palette has no colors")

    invalid = {name: value for name, value in colors.items() if not HEX_COLOR.fullmatch(value)}
    if invalid:
        raise ValueError(f"invalid palette colors: {invalid}")

    unknown_roles = {name: value for name, value in roles.items() if value not in colors}
    if unknown_roles:
        raise ValueError(f"palette roles reference unknown colors: {unknown_roles}")


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
