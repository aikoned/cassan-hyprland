#!/usr/bin/env python3
"""Validate Cassan's strict JSON and modular Lua configuration."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_DIR = Path(__file__).resolve().parent.parent
WAYBAR_CONFIG = REPO_DIR / "waybar" / "config.jsonc"
HYPR_ENTRYPOINT = REPO_DIR / "hypr" / "hyprland.lua"

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
        compile_lua(lua_files)
    except ValidationError as exc:
        print(f"configuration validation failed: {exc}", file=sys.stderr)
        return 1

    print("Waybar structure and Hyprland module validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
