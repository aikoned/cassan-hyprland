#!/usr/bin/env bash

set -euo pipefail

spicetify_bin=/usr/bin/spicetify
script_dir=$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd)

exec python3 - "$spicetify_bin" "$script_dir" "$@" <<'PY'
import argparse
import configparser
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys


EXTENSION = "hyprland-dots-theme.js"
SPICETIFY = Path(sys.argv[1])
SCRIPTS = Path(sys.argv[2])


class SetupError(Exception):
    pass


def command(*arguments, capture=False):
    result = subprocess.run(
        [str(SPICETIFY), *map(str, arguments)], check=True,
        text=True, capture_output=capture,
    )
    return result.stdout.strip() if capture else None


def ensure_spotify_closed():
    user = str(os.getuid())
    checks = (
        ["pgrep", "-u", user, "-i", "-x", "spotify"],
        ["pgrep", "-u", user, "-f", r"(^|[ /])spotify-launcher([ ]|$)"],
    )
    for arguments in checks:
        result = subprocess.run(arguments, capture_output=True, check=False)
        if result.returncode == 0:
            raise SetupError("Close Spotify and spotify-launcher before running this setup.")
        if result.returncode != 1:
            raise SetupError("Could not verify that Spotify is closed; check pgrep from procps-ng.")


def read_config(path):
    config = configparser.ConfigParser(interpolation=None, delimiters=("=",))
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            config.read_file(handle)
    return config


def value(config, section, key):
    text = config.get(section, key, fallback="").strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    return text


def configured_path(config, key):
    text = value(config, "Setting", key)
    path = Path(os.path.expandvars(text))
    if not text or not path.is_absolute() or "$" in str(path):
        raise SetupError(
            f"Existing Spicetify {key} must resolve to an absolute path; "
            "the configured path was left unchanged."
        )
    return path


def spotify_version(prefs):
    config = configparser.ConfigParser(interpolation=None, delimiters=("=",), strict=False)
    config.read_string("[prefs]\n" + prefs.read_text(encoding="utf-8"))
    version = value(config, "prefs", "app.last-launched-version")
    if not version:
        raise SetupError("Launch Spotify once, then close it so its preferences record the installed version.")
    return version


class ExtensionScripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.count = 0
        self.theme_stylesheet = False
        self.colors_stylesheet = False

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "link":
            if (attributes.get("href") in {"user.css", "/user.css"}
                    and "stylesheet" in (attributes.get("rel") or "").lower().split()):
                self.theme_stylesheet = True
            if (attributes.get("href") in {"colors.css", "/colors.css"}
                    and "stylesheet" in (attributes.get("rel") or "").lower().split()):
                self.colors_stylesheet = True
        if tag != "script":
            return
        source = attributes.get("src") or ""
        if source in {f"extensions/{EXTENSION}", f"/extensions/{EXTENSION}"}:
            self.count += 1


def deployment_matches(spotify, source):
    extension = spotify / "Apps/xpui/extensions" / EXTENSION
    index = spotify / "Apps/xpui/index.html"
    if extension.is_symlink() or index.is_symlink():
        raise SetupError("Refusing to apply over a symlinked Spotify extension or index.html.")
    if not extension.is_file() or not index.is_file() or extension.read_bytes() != source:
        return False
    scripts = ExtensionScripts()
    scripts.feed(index.read_text(encoding="utf-8"))
    return scripts.count == 1


def text_theme_source(config_path, spotify):
    source = SCRIPTS.parent / "spicetify/Themes/text"
    installed = config_path.parent / "Themes/text"
    for name in ("user.css", "color.ini"):
        if (not (source / name).is_file() or not (installed / name).is_file()
                or (source / name).read_bytes() != (installed / name).read_bytes()):
            raise SetupError("The text theme is missing or outdated; run scripts/install.sh before this setup.")
    css = (source / "user.css").read_bytes()
    scheme = read_config(source / "color.ini")
    if not css.strip() or not scheme.has_section("Spotify") or not scheme.items("Spotify"):
        raise SetupError("The text theme needs nonempty user.css and a [Spotify] color scheme.")
    colors = {}
    for name, raw in scheme.items("Spotify"):
        color = re.fullmatch(r"#?([0-9a-fA-F]{6})", raw.strip())
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name) or color is None:
            raise SetupError("The text theme's [Spotify] colors must be six-digit hexadecimal values.")
        colors[name] = color.group(1).lower()
    for name in ("user.css", "colors.css", "spicetify-config.json"):
        deployed = spotify / "Apps/xpui" / name
        if deployed.is_symlink():
            raise SetupError(f"Refusing to apply over symlinked Spotify {name}.")
        if deployed.exists() and not deployed.is_file():
            raise SetupError(f"Refusing to apply over non-regular Spotify {name}.")
    return css, colors


def palette_matches(css, colors):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    root = re.fullmatch(r"\s*:root\s*\{([^{}]*)\}\s*", css, flags=re.DOTALL)
    if root is None:
        return False
    declarations = {}
    for raw in root.group(1).split(";"):
        if not raw.strip():
            continue
        declaration = re.fullmatch(r"\s*(--spice-[a-zA-Z0-9_-]+)\s*:\s*(.*?)\s*", raw, flags=re.DOTALL)
        if declaration is None or declaration.group(1) in declarations:
            return False
        declarations[declaration.group(1)] = declaration.group(2)
    for name, expected in colors.items():
        color = re.fullmatch(r"#([0-9a-fA-F]{6})", declarations.get(f"--spice-{name}", ""))
        if color is None or color.group(1).lower() != expected:
            return False
        rgb = re.fullmatch(r"([0-9]{1,3})\s*,\s*([0-9]{1,3})\s*,\s*([0-9]{1,3})", declarations.get(f"--spice-rgb-{name}", ""))
        expected_rgb = tuple(int(expected[index:index + 2], 16) for index in (0, 2, 4))
        if rgb is None or tuple(map(int, rgb.groups())) != expected_rgb:
            return False
    return True


def text_theme_deployed(spotify, source):
    xpui = spotify / "Apps/xpui"
    css = xpui / "user.css"
    colors = xpui / "colors.css"
    metadata = xpui / "spicetify-config.json"
    if any(path.is_symlink() or not path.is_file() for path in (css, colors, metadata)):
        return False
    source_css, source_colors = source
    if css.read_bytes() != source_css or not palette_matches(colors.read_text(encoding="utf-8"), source_colors):
        return False
    try:
        current = json.loads(metadata.read_text(encoding="utf-8"))
    except ValueError:
        return False
    if not isinstance(current, dict) or current.get("theme_name") != "text" or current.get("scheme_name") != "Spotify":
        return False
    markup = ExtensionScripts()
    markup.feed((xpui / "index.html").read_text(encoding="utf-8"))
    return markup.theme_stylesheet and markup.colors_stylesheet


def main():
    parser = argparse.ArgumentParser(
        prog="setup-spicetify.sh",
        description="Set up Spotify's text theme and live wallpaper colors while Spotify is closed; never starts or restarts Spotify.",
    )
    parser.add_argument(
        "--live-theme-only", action="store_true",
        help="add wallpaper colors to an existing Spicetify setup without changing its theme or custom apps",
    )
    arguments = parser.parse_args(sys.argv[3:])
    if not SPICETIFY.is_file() or not os.access(SPICETIFY, os.X_OK):
        raise SetupError("Spicetify is not installed. Install the reviewed spicetify-cli AUR package first.")
    ensure_spotify_closed()

    home = Path.home()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    expected_config = config_home / "spicetify/config-xpui.ini"
    override = os.environ.get("SPICETIFY_CONFIG")
    if override and Path(override).resolve() != expected_config.parent.resolve():
        raise SetupError("This rice manages XDG_CONFIG_HOME/spicetify; unset a different SPICETIFY_CONFIG first.")
    first_setup = not expected_config.is_file()
    if arguments.live_theme_only and not expected_config.is_file():
        raise SetupError("No existing Spicetify configuration; run setup-spicetify.sh without --live-theme-only first.")

    config_path = Path(command("--config", capture=True))
    if not config_path.is_absolute() or config_path.resolve() != expected_config.resolve():
        raise SetupError("Spicetify returned an unexpected configuration path; no settings were changed.")
    config = read_config(config_path)
    defaults = {
        "spotify_path": home / ".local/share/spotify-launcher/install/usr/share/spotify",
        "prefs_path": config_home / "spotify/prefs",
    }
    path_updates = []
    paths = {}
    for key, default in defaults.items():
        if value(config, "Setting", key):
            paths[key] = configured_path(config, key)
        else:
            paths[key] = default
            path_updates.extend((key, default))
    spotify = paths["spotify_path"]
    prefs = paths["prefs_path"]
    if (not (spotify / "spotify").is_file() or not os.access(spotify / "spotify", os.X_OK)
            or not (spotify / "Apps").is_dir() or not prefs.is_file()):
        raise SetupError("Spotify installation/preferences are missing. Launch spotify-launcher once, close Spotify, and retry.")

    source = SCRIPTS.parent / "spicetify/Extensions" / EXTENSION
    installed = config_path.parent / "Extensions" / EXTENSION
    if not source.is_file() or not installed.is_file() or source.read_bytes() != installed.read_bytes():
        raise SetupError("The live-theme extension is missing or outdated; run scripts/install.sh before this setup.")
    source_bytes = source.read_bytes()
    theme = None if arguments.live_theme_only else text_theme_source(config_path, spotify)
    current_version = spotify_version(prefs)
    cli_version = command("--version", capture=True)
    if not re.fullmatch(r"v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", cli_version):
        raise SetupError(f"Unrecognized Spicetify version: {cli_version!r}")
    backup_version = value(config, "Backup", "version")
    backup_cli = value(config, "Backup", "with")
    stock = any(path.is_file() and path.suffix == ".spa" for path in (spotify / "Apps").iterdir())
    extensions = value(config, "AdditionalOptions", "extensions").split("|")
    registered = EXTENSION in {entry.strip() for entry in extensions}
    deployed = deployment_matches(spotify, source_bytes)

    if stock:
        actions = ("backup", "apply")
    elif not backup_version or backup_version != current_version:
        raise SetupError(
            "Spotify has no stock archives and its backup version does not match. "
            "Reinstall/update Spotify with spotify-launcher, launch it once, close it, then retry; "
            "the old backup was not restored."
        )
    elif backup_cli != cli_version:
        actions = ("restore", "backup", "apply")
    else:
        actions = ("apply",)

    apply_needed = not (
        arguments.live_theme_only and registered and deployed and not stock
        and backup_cli == cli_version and not path_updates
    )
    if apply_needed:
        ensure_spotify_closed()
        if not arguments.live_theme_only:
            command(
                "config", "current_theme", "text", "color_scheme", "Spotify",
                "inject_css", "1", "inject_theme_js", "0", "replace_colors", "1", "overwrite_assets", "0",
            )
            if first_setup:
                command("config", "custom_apps", "marketplace")
        if not registered:
            command("config", "extensions", EXTENSION)
        if path_updates:
            command("config", *path_updates)
        command("--no-restart", *actions)
        if not deployment_matches(spotify, source_bytes):
            raise SetupError("Spicetify did not install and inject the live-theme extension; Spotify remains closed.")
        if theme is not None and not text_theme_deployed(spotify, theme):
            raise SetupError("Spicetify did not deploy the requested text theme and Spotify color scheme; Spotify remains closed.")

    subprocess.run([sys.executable, str(SCRIPTS / "sync-app-themes.py")], check=True)
    if arguments.live_theme_only:
        print("Spotify live colors ready; existing theme, custom apps and other extensions preserved.")
    else:
        print("Applied the text theme and installed live wallpaper colors.")
    print("Spotify was not started or restarted. Open it when you are ready.")


try:
    main()
except (SetupError, OSError, ValueError, configparser.Error, subprocess.SubprocessError) as error:
    print(f"Spotify theme setup failed: {error}", file=sys.stderr)
    raise SystemExit(1)
PY
