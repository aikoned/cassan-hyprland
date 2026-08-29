#!/usr/bin/env bash

set -euo pipefail

script_dir=$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)

for command_name in python3 rg zsh; do
  command -v "$command_name" >/dev/null 2>&1 || {
    printf 'required validation command is unavailable: %s\n' "$command_name" >&2
    exit 1
  }
done

zsh -n "$repo_dir/.zshrc"

required_files=(
  .zshrc
  assets/Castle.jpg
  assets-profile/bored.jpg
  assets-profile/readin.jpg
  btop/btop.conf
  btop/themes/noctalia.theme
  cava/config
  cava/themes/noctalia
  fastfetch/config.jsonc
  gtk-3.0/settings.ini
  gtk-4.0/settings.ini
  hypr/animation.lua
  hypr/bind.lua
  hypr/environment.lua
  hypr/gruvbox.conf
  hypr/hypridle.conf
  hypr/hyprland.lua
  hypr/hyprlock.conf
  hypr/input.lua
  hypr/looknfeel.lua
  hypr/monitor.lua
  hypr/rules.lua
  hypr/startup.lua
  hypr/theme.lua
  kitty/colors.conf
  kitty/current-theme.conf
  kitty/kitty.conf
  kitty/themes/noctalia.conf
  packages/aur.txt
  packages/official.txt
  scripts/check.sh
  scripts/install.sh
  scripts/migrate-cassan.py
  scripts/setup-spicetify.sh
  scripts/update.sh
  tests/test_migrate_cassan.py
  spicetify/CustomApps/marketplace/manifest.json
  spicetify/CustomApps/marketplace/release.json
  spicetify/Themes/Comfy/color.ini
  spicetify/Themes/Comfy/app.css
  spicetify/Themes/Comfy/release.json
  spicetify/Themes/Comfy/theme.js
  spicetify/Themes/Comfy/theme.script.js
  spicetify/Themes/Comfy/user.css
  swappy/config
  swaync/config.json
  swaync/start.sh
  swaync/style.css
  vesktop/settings.json
  vesktop/settings/settings.json
  vesktop/themes/midnight-discord.css
  vesktop/themes/release.json
  waybar/config.jsonc
  waybar/style.css
  waybar/scripts/bluetooth_status.sh
  waybar/scripts/clipboard_menu.sh
  waybar/scripts/powerprofile.sh
  waybar/scripts/theme-switcher.sh
  wlogout/icons/hibernate.png
  wlogout/icons/lock.png
  wlogout/icons/logout.png
  wlogout/icons/reboot.png
  wlogout/icons/shutdown.png
  wlogout/icons/suspend.png
  wlogout/layout
  wlogout/style.css
  wofi/config
  wofi/gruvbox.css
  wofi/style.css
  qt6ct/qt6ct.conf
  xdg-desktop-portal/hyprland-portals.conf
  yazi/flavors/noctalia.yazi/flavor.toml
  yazi/theme.toml
  yazi/yazi.toml
  zathura/zathurarc
  zathura/noctaliarc
)

required_dirs=(
  assets
  assets-profile
  btop
  cava
  fastfetch
  gtk-3.0
  gtk-4.0
  hypr
  kitty
  qt6ct
  spicetify
  swappy
  swaync
  vesktop
  waybar
  wlogout
  wofi
  yazi
  zathura
  xdg-desktop-portal
)

for path in "${required_files[@]}"; do
  [[ -f "$repo_dir/$path" ]] || {
    printf 'missing required file: %s\n' "$path" >&2
    exit 1
  }
done

for path in "${required_dirs[@]}"; do
  [[ -d "$repo_dir/$path" ]] || {
    printf 'missing required directory: %s\n' "$path" >&2
    exit 1
  }
done

while IFS= read -r script; do
  bash -n "$script"
  [[ -x "$script" ]] || {
    printf 'script is not executable: %s\n' "${script#"$repo_dir/"}" >&2
    exit 1
  }
done < <(find "$repo_dir/scripts" "$repo_dir/waybar/scripts" "$repo_dir/swaync" -type f -name '*.sh' -print)

python3 - "$repo_dir" <<'PY'
import ast
import json
import hashlib
import configparser
import pathlib
import re
import sys

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

root = pathlib.Path(sys.argv[1])
ast.parse((root / "scripts/migrate-cassan.py").read_text(encoding="utf-8"))
for relative in (
    "waybar/config.jsonc",
    "swaync/config.json",
    "vesktop/settings.json",
    "vesktop/settings/settings.json",
    "vesktop/themes/release.json",
    "spicetify/CustomApps/marketplace/manifest.json",
    "spicetify/CustomApps/marketplace/release.json",
    "spicetify/Themes/Comfy/release.json",
):
    with (root / relative).open(encoding="utf-8") as handle:
        json.load(handle)

for relative in (
    "gtk-3.0/settings.ini",
    "gtk-4.0/settings.ini",
    "qt6ct/qt6ct.conf",
    "xdg-desktop-portal/hyprland-portals.conf",
):
    parser = configparser.ConfigParser(interpolation=None)
    with (root / relative).open(encoding="utf-8") as handle:
        parser.read_file(handle)

gtk = configparser.ConfigParser(interpolation=None)
gtk.read(root / "gtk-3.0/settings.ini", encoding="utf-8")
if gtk.get("Settings", "gtk-theme-name") != "Adwaita-dark":
    raise ValueError("GTK must select the installed dark theme")

gtk4 = configparser.ConfigParser(interpolation=None)
gtk4.read(root / "gtk-4.0/settings.ini", encoding="utf-8")
if gtk4.get("Settings", "gtk-application-prefer-dark-theme") != "1":
    raise ValueError("GTK 4 applications must prefer their dark theme variant")

qt = configparser.ConfigParser(interpolation=None)
qt.read(root / "qt6ct/qt6ct.conf", encoding="utf-8")
if qt.get("Appearance", "color_scheme_path") != "/usr/share/qt6ct/colors/darker.conf":
    raise ValueError("qt6ct must select its installed dark color scheme")
if qt.get("Appearance", "custom_palette").lower() != "true":
    raise ValueError("qt6ct custom palette must be enabled")

portals = configparser.ConfigParser(interpolation=None)
portals.read(root / "xdg-desktop-portal/hyprland-portals.conf", encoding="utf-8")
if portals.get("preferred", "default") != "hyprland;gtk":
    raise ValueError("Hyprland portal configuration must retain the GTK fallback")

swappy = configparser.ConfigParser(interpolation=None)
swappy.read(root / "swappy/config", encoding="utf-8")
if swappy.get("Default", "save_dir") != "$HOME/Pictures/Screenshots":
    raise ValueError("Swappy save_dir must use its supported environment expansion")

kitty_includes = [
    line.split(maxsplit=1)[1]
    for line in (root / "kitty/kitty.conf").read_text(encoding="utf-8").splitlines()
    if line.strip().startswith("include ")
]
if kitty_includes[:2] != ["colors.conf", "current-theme.conf"]:
    raise ValueError("Kitty must load the reference rice's active theme after its base colors")
for include in kitty_includes:
    if not (root / "kitty" / include).is_file():
        raise FileNotFoundError(f"Kitty include is missing: {include}")

# wlogout deliberately uses a stream of adjacent JSON objects, not a JSON
# array. Validate that exact format and the fields wlogout requires.
layout = (root / "wlogout/layout").read_text(encoding="utf-8")
decoder = json.JSONDecoder()
position = 0
buttons = []
while True:
    while position < len(layout) and layout[position].isspace():
        position += 1
    if position == len(layout):
        break
    button, position = decoder.raw_decode(layout, position)
    if not isinstance(button, dict):
        raise ValueError("each wlogout layout entry must be an object")
    missing = {"label", "action", "text", "keybind"} - button.keys()
    if missing:
        raise ValueError(f"wlogout entry is missing: {sorted(missing)}")
    buttons.append(button)
if not buttons:
    raise ValueError("wlogout layout has no buttons")
labels = [button["label"] for button in buttons]
if len(labels) != len(set(labels)):
    raise ValueError("wlogout layout labels must be unique")

if tomllib is None:
    raise RuntimeError("Python 3.11+ is required for TOML validation")
for relative in (
    "yazi/yazi.toml",
    "yazi/theme.toml",
    "yazi/flavors/noctalia.yazi/flavor.toml",
):
    with (root / relative).open("rb") as handle:
        tomllib.load(handle)

# Selected local themes must exist, and Vesktop must only enable bundled CSS.
btop = (root / "btop/btop.conf").read_text(encoding="utf-8")
btop_theme = next(
    line.split("=", 1)[1].strip().strip('"')
    for line in btop.splitlines()
    if line.strip().startswith("color_theme =")
)
if not (root / "btop/themes" / f"{btop_theme}.theme").is_file():
    raise FileNotFoundError(f"selected btop theme is missing: {btop_theme}")

cava = (root / "cava/config").read_text(encoding="utf-8")
cava_theme = next(
    line.split("=", 1)[1].strip().strip('"\'')
    for line in cava.splitlines()
    if line.strip().startswith("theme =")
)
if not (root / "cava/themes" / cava_theme).is_file():
    raise FileNotFoundError(f"selected Cava theme is missing: {cava_theme}")

vesktop = json.loads((root / "vesktop/settings/settings.json").read_text(encoding="utf-8"))
for theme in vesktop.get("enabledThemes", []):
    if not (root / "vesktop/themes" / theme).is_file():
        raise FileNotFoundError(f"enabled Vesktop theme is missing: {theme}")

vesktop_theme_dir = root / "vesktop/themes"
vesktop_release = json.loads((vesktop_theme_dir / "release.json").read_text(encoding="utf-8"))
for name, expected in vesktop_release["files"].items():
    actual = hashlib.sha256((vesktop_theme_dir / name).read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"Vesktop theme file checksum mismatch: {name}")
for name in (
    "midnight-discord.css",
    "vendor/system24/system24.css",
    "vendor/system24/midnight.css",
):
    content = (vesktop_theme_dir / name).read_text(encoding="utf-8")
    if re.search(r"url\(\s*['\"]?https?://", content):
        raise ValueError(f"enabled Vesktop theme has a mutable remote asset: {name}")

marketplace_dir = root / "spicetify/CustomApps/marketplace"
release = json.loads((marketplace_dir / "release.json").read_text(encoding="utf-8"))
for name, expected in release["files"].items():
    actual = hashlib.sha256((marketplace_dir / name).read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"Marketplace release file checksum mismatch: {name}")

comfy_dir = root / "spicetify/Themes/Comfy"
comfy_release = json.loads((comfy_dir / "release.json").read_text(encoding="utf-8"))
for name, expected in comfy_release["files"].items():
    actual = hashlib.sha256((comfy_dir / name).read_bytes()).hexdigest()
    if actual != expected:
        raise ValueError(f"Comfy theme file checksum mismatch: {name}")
expected_user_css = (comfy_dir / "app.css").read_text(encoding="utf-8")
expected_user_css = expected_user_css.replace(
    "https://i.imgur.com/nzAfcIL.png", "comfy-vendor/upgrade.png"
).replace(
    "https://media0.giphy.com/media/lVHOm4nZ0yfFXI8cgd/giphy.gif?cid=790b7611hvc1po0u3gn3yrlgmhu5gqhjv9cve7hp84f9aoox&ep=v1_gifs_search&rid=giphy.gif",
    "comfy-vendor/kitty.gif",
)
if (comfy_dir / "user.css").read_text(encoding="utf-8") != expected_user_css:
    raise ValueError("Comfy CSS entry point is not the verified local derivation")

expected_theme_js = (comfy_dir / "theme.script.js").read_text(encoding="utf-8")
expected_theme_js = expected_theme_js.replace(
    "https://raw.githubusercontent.com/Comfy-Themes/Spicetify/main/Comfy/color.ini",
    "comfy-vendor/color.ini",
).replace(
    "https://raw.githubusercontent.com/Tetrax-10/Nord-Spotify/master/assets/font/font-url.png",
    "comfy-vendor/font-url.png",
).replace(
    "https://github.com/Comfy-Themes/Spicetify/blob/main/images/settings/column-bar.png?raw=true",
    "comfy-vendor/column-bar.png",
)
if (comfy_dir / "theme.js").read_text(encoding="utf-8") != expected_theme_js:
    raise ValueError("Comfy JavaScript entry point is not the verified local derivation")

def manifest_entries(relative):
    entries = []
    for line in (root / relative).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            entries.append(line)
    if len(entries) != len(set(entries)):
        raise ValueError(f"duplicate package in {relative}")
    return set(entries)

official = manifest_entries("packages/official.txt")
aur = manifest_entries("packages/aur.txt")
required_official = {
    "adwaita-icon-theme", "awww", "bluez", "blueman", "brightnessctl",
    "cliphist", "ffmpegthumbnailer", "gnome-themes-extra", "gvfs", "gvfs-mtp",
    "hypridle", "hyprland",
    "hyprlock", "hyprpolkitagent", "hyprshutdown", "kitty", "networkmanager",
    "libgepub", "libgsf", "libopenraw", "otf-font-awesome", "pipewire-pulse",
    "poppler-glib", "power-profiles-daemon", "qt6-wayland", "qt6ct",
    "spotify-launcher", "swaync", "thunar", "thunar-archive-plugin",
    "thunar-volman", "tumbler", "waybar", "wl-clipboard", "wofi",
    "xdg-desktop-portal-gtk", "xdg-desktop-portal-hyprland", "xarchiver",
}
required_aur = {"spicetify-cli", "vesktop", "wlogout"}
if missing := required_official - official:
    raise ValueError(f"official package manifest is missing: {sorted(missing)}")
if missing := required_aur - aur:
    raise ValueError(f"AUR package manifest is missing: {sorted(missing)}")
PY

python3 "$repo_dir/tests/test_migrate_cassan.py"

if rg -n '/home/[^/$ ]+' \
  "$repo_dir/hypr" \
  "$repo_dir/waybar" \
  "$repo_dir/swaync" \
  "$repo_dir/wofi" \
  "$repo_dir/kitty" \
  "$repo_dir/fastfetch" \
  "$repo_dir/vesktop" \
  "$repo_dir/spicetify" \
  "$repo_dir/wlogout" \
  "$repo_dir/zathura" \
  "$repo_dir/.zshrc"; then
  printf 'machine-specific /home path found\n' >&2
  exit 1
fi

if rg -n '\bswww(-daemon)?\b' "$repo_dir" \
  -g '!README.md' -g '!UPDATING.md' -g '!scripts/check.sh'; then
  printf 'obsolete swww command found; current Arch uses awww\n' >&2
  exit 1
fi

if rg -n '\.spicetify' "$repo_dir/.zshrc"; then
  printf 'the shell PATH must not prefer the retired Cassan Spicetify binary\n' >&2
  exit 1
fi

rg -q '^spicetify_bin=/usr/bin/spicetify$' "$repo_dir/scripts/setup-spicetify.sh" || {
  printf 'Spicetify setup must use the reviewed AUR package binary\n' >&2
  exit 1
}

printf 'Rice compatibility checks passed.\n'
