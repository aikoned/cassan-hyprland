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
  applications/yazi.desktop
  assets/after_school_stroll_gruvbox.png
  assets-profile/bored.jpg
  assets-profile/readin.jpg
  btop/btop.conf
  btop/launch.sh
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
  scripts/prepare-private-wallpapers.sh
  scripts/render-theme.py
  scripts/setup-firefox-theme.py
  scripts/setup-spicetify.sh
  scripts/sync-app-themes.py
  scripts/theme-schedule.py
  scripts/update.sh
  spotify-launcher.conf
  tests/test_migrate_cassan.py
  tests/test_memory_pressure.py
  tests/test_prepare_private_wallpapers.py
  tests/test_setup_firefox_theme.py
  tests/test_setup_spicetify.py
  tests/test_spotify_theme.js
  tests/test_spotify_text_theme.py
  tests/test_sync_app_themes.py
  tests/test_theme_schedule.py
  tests/test_theme_schedule_integration.py
  tests/test_waybar_memory_tray.py
  spicetify/Extensions/hyprland-dots-theme.js
  spicetify/CustomApps/marketplace/manifest.json
  spicetify/CustomApps/marketplace/release.json
  spicetify/Themes/Comfy/color.ini
  spicetify/Themes/Comfy/app.css
  spicetify/Themes/Comfy/release.json
  spicetify/Themes/Comfy/theme.js
  spicetify/Themes/Comfy/theme.script.js
  spicetify/Themes/Comfy/user.css
  spicetify/Themes/text/color.ini
  spicetify/Themes/text/user.css
  swappy/config
  swaync/config.json
  swaync/start.sh
  swaync/style.css
  themes/after-school.toml
  themes/reze.toml
  themes/schedule.toml
  vesktop/settings.json
  vesktop/settings/settings.json
  vesktop/themes/midnight-discord.css
  vesktop/themes/release.json
  waybar/config.jsonc
  waybar/start.sh
  waybar/style.css
  waybar/scripts/bluetooth_status.sh
  waybar/scripts/clipboard_menu.sh
  waybar/scripts/memory-pressure.py
  waybar/scripts/powerprofile.sh
  waybar/scripts/theme-switcher.sh
  wlogout/icons/hibernate.png
  wlogout/icons/lock.png
  wlogout/icons/logout.png
  wlogout/icons/reboot.png
  wlogout/icons/shutdown.png
  wlogout/icons/suspend.png
  wlogout/layout
  wlogout/launch.sh
  wlogout/style.css
  wofi/config
  wofi/gruvbox.css
  wofi/launch.sh
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
  applications
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
  themes
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
done < <(find \
  "$repo_dir/scripts" \
  "$repo_dir/btop" \
  "$repo_dir/waybar" \
  "$repo_dir/swaync" \
  "$repo_dir/wofi" \
  "$repo_dir/wlogout" \
  -type f -name '*.sh' -print)

python3 - "$repo_dir" <<'PY'
import ast
import json
import hashlib
import configparser
import pathlib
import re
import subprocess
import sys
import tempfile

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

root = pathlib.Path(sys.argv[1])
ast.parse((root / "scripts/migrate-cassan.py").read_text(encoding="utf-8"))
ast.parse((root / "scripts/render-theme.py").read_text(encoding="utf-8"))
for script in (root / "scripts").glob("*.py"):
    ast.parse(script.read_text(encoding="utf-8"))
    if script.name == "theme-schedule.py" and not script.stat().st_mode & 0o111:
        raise ValueError(f"script is not executable: {script}")
for script in (root / "waybar/scripts").glob("*.py"):
    ast.parse(script.read_text(encoding="utf-8"))
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
expected_kitty_includes = [
    "colors.conf",
    "current-theme.conf",
    "${XDG_CACHE_HOME}/hyprland-dots/active-theme/kitty.conf",
]
if kitty_includes[:3] != expected_kitty_includes:
    raise ValueError("Kitty must load the generated palette after its fallback colors")
for include in kitty_includes[:2]:
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
    "spotify-launcher.conf",
    "themes/after-school.toml",
    "themes/reze.toml",
    "themes/schedule.toml",
):
    with (root / relative).open("rb") as handle:
        tomllib.load(handle)

with (root / "spotify-launcher.conf").open("rb") as handle:
    spotify_launcher = tomllib.load(handle)
expected_spotify_arguments = [
    "--enable-features=UseOzonePlatform",
    "--ozone-platform=wayland",
]
if spotify_launcher.get("spotify", {}).get("extra_arguments") != expected_spotify_arguments:
    raise ValueError("Spotify launcher must request native Wayland rendering")

desktop = configparser.ConfigParser(interpolation=None)
desktop.optionxform = str
desktop.read(root / "applications/yazi.desktop", encoding="utf-8")
yazi_entry = desktop["Desktop Entry"]
expected_yazi = {
    "TryExec": "kitty",
    "Exec": "kitty --class cassan-yazi -e yazi %f",
    "Terminal": "false",
    "Type": "Application",
}
for key, value in expected_yazi.items():
    if yazi_entry.get(key) != value:
        raise ValueError(f"Yazi desktop entry has an invalid {key}")

theme_files = {
    "after-school": root / "themes/after-school.toml",
    "reze": root / "themes/reze.toml",
}
expected_wallpapers = {
    "after-school": "after_school_stroll_gruvbox.png",
    "reze": "reze.jpg",
}
required_colors = {
    "background", "panel", "panel_alt", "text", "text_secondary",
    "text_muted", "disabled", "border", "focus", "focus_alt", "blue",
    "purple", "green", "urgent",
}

def relative_luminance(value):
    channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    channels = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

def contrast_ratio(first, second):
    lighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)

palettes = {}
for slug, path in theme_files.items():
    with path.open("rb") as handle:
        palette = tomllib.load(handle)
    if palette.get("wallpaper") != expected_wallpapers[slug]:
        raise ValueError(f"{slug} theme has the wrong wallpaper mapping")
    colors = palette.get("colors", {})
    if missing := required_colors - colors.keys():
        raise ValueError(f"{slug} theme is missing colors: {sorted(missing)}")
    for name in required_colors:
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", colors[name]):
            raise ValueError(f"{slug}.{name} is not a six-digit hex color")
    if contrast_ratio(colors["text"], colors["background"]) < 4.5:
        raise ValueError(f"{slug} text contrast is below 4.5:1")
    if contrast_ratio(colors["focus"], colors["background"]) < 3:
        raise ValueError(f"{slug} focus contrast is below 3:1")
    palettes[slug] = palette

image_suffixes = {".jpg", ".jpeg", ".png"}
public_wallpapers = {
    path.name
    for path in (root / "assets").iterdir()
    if path.is_file() and path.suffix.lower() in image_suffixes
}
if public_wallpapers != {"after_school_stroll_gruvbox.png"}:
    raise ValueError(f"unexpected public wallpaper set: {sorted(public_wallpapers)}")

with tempfile.TemporaryDirectory() as temporary:
    output_root = pathlib.Path(temporary)
    for slug, palette in palettes.items():
        output = output_root / slug
        subprocess.run(
            [
                sys.executable,
                str(root / "scripts/render-theme.py"),
                "--theme", slug,
                "--output", str(output),
            ],
            check=True,
        )
        for filename in (
            "btop/noctalia.theme", "current-theme", "hypr.lua", "hyprlock.conf",
            "kitty.conf", "swaync.css", "waybar.css", "wofi.css", "wlogout.css",
            "pywalfox.json", "spotify-palette.json", "vesktop.css",
        ):
            if not (output / filename).is_file():
                raise FileNotFoundError(f"theme renderer omitted {slug}/{filename}")
        if (output / "current-theme").read_text(encoding="utf-8").strip() != slug:
            raise ValueError(f"theme renderer wrote the wrong state for {slug}")
        focus = palette["colors"]["focus"]
        if focus not in (output / "waybar.css").read_text(encoding="utf-8"):
            raise ValueError(f"Waybar output does not contain the {slug} focus color")
        if "@import" in (output / "wofi.css").read_text(encoding="utf-8"):
            raise ValueError("rendered Wofi CSS must be self-contained")
        if focus not in (output / "btop/noctalia.theme").read_text(encoding="utf-8"):
            raise ValueError(f"Btop output does not contain the {slug} focus color")
        if focus not in (output / "kitty.conf").read_text(encoding="utf-8"):
            raise ValueError(f"Kitty output does not contain the {slug} focus color")
        if focus not in (output / "vesktop.css").read_text(encoding="utf-8"):
            raise ValueError(f"Vesktop output does not contain the {slug} focus color")
        spotify_palette = json.loads((output / "spotify-palette.json").read_text(encoding="utf-8"))
        if spotify_palette != {"schema": 1, "theme": slug, "colors": palette["colors"]}:
            raise ValueError(f"Spotify output does not match the {slug} palette")
        firefox_palette = json.loads((output / "pywalfox.json").read_text(encoding="utf-8"))
        if list(firefox_palette.get("colors", {})) != [f"color{i}" for i in range(16)]:
            raise ValueError("Pywalfox colors must remain in numeric insertion order")
        if firefox_palette["colors"]["color10"] != focus:
            raise ValueError(f"Firefox output does not contain the {slug} focus color")
        if not isinstance(firefox_palette.get("wallpaper"), str):
            raise ValueError("Firefox palette must include a wallpaper string")
        for icon in (root / "wlogout/icons").glob("*.png"):
            rendered_icon = output / "icons" / icon.name
            if not rendered_icon.is_file():
                raise FileNotFoundError(
                    f"theme renderer omitted {slug}/icons/{icon.name}"
                )
            if hashlib.sha256(rendered_icon.read_bytes()).digest() != hashlib.sha256(
                icon.read_bytes()
            ).digest():
                raise ValueError(f"rendered Wlogout icon changed: {icon.name}")

switcher = (root / "waybar/scripts/theme-switcher.sh").read_text(encoding="utf-8")
apply_body = switcher.split("apply_index() {", 1)[1].split("\n}", 1)[0]
if apply_body.index("awww img") > apply_body.index('publish_selection "$index"'):
    raise ValueError("theme state must only publish after awww accepts the wallpaper")
if "flock 9" not in switcher:
    raise ValueError("theme switching must serialize concurrent changes")
if 'atomic_symlink "${wallpapers[$index]}"' in switcher:
    raise ValueError("wallpaper and palette state must share one active-theme pointer")

installer = (root / "scripts/install.sh").read_text(encoding="utf-8")
private_preflight = installer.index(
    '"$repo_dir/scripts/prepare-private-wallpapers.sh" >/dev/null'
)
migration = installer.index(
    'python3 "$repo_dir/scripts/migrate-cassan.py" --apply'
)
first_link = installer.index('for name in "${config_names[@]}"; do')
if not private_preflight < migration < first_link:
    raise ValueError(
        "private wallpaper verification must precede migration and config links"
    )

waybar = json.loads((root / "waybar/config.jsonc").read_text(encoding="utf-8"))
if waybar.get("fixed-center") is not True:
    raise ValueError("Waybar must keep the focused-window title at the display center")
mpris = waybar.get("mpris", {})
if (
    mpris.get("dynamic-len"),
    mpris.get("artist-len"),
    mpris.get("title-len"),
    mpris.get("max-length"),
) != (22, 22, 22, 32):
    raise ValueError("Waybar MPRIS text limits are too wide for the laptop layout")
window = waybar.get("hyprland/window", {})
if (window.get("min-length"), window.get("max-length")) != (12, 12):
    raise ValueError("Waybar window title must have a stable bounded width")
theme_mode = waybar.get("custom/theme-mode", {})
if theme_mode.get("return-type") != "json" or "auto-toggle" not in theme_mode.get("on-click", ""):
    raise ValueError("Waybar must expose the automatic wallpaper toggle")

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
    "cliphist", "desktop-file-utils", "ffmpegthumbnailer", "firefox",
    "gsettings-desktop-schemas", "gnome-themes-extra", "gvfs", "gvfs-mtp",
    "hypridle", "hyprland",
    "hyprlock", "hyprpolkitagent", "hyprshutdown", "kitty", "networkmanager",
    "libgepub", "libgsf", "libopenraw", "otf-font-awesome", "pipewire-pulse",
    "poppler-glib", "power-profiles-daemon", "procps-ng", "python-pipx", "qt6-wayland", "qt6ct",
    "spotify-launcher", "swaync", "thunar", "thunar-archive-plugin",
    "thunar-volman", "tumbler", "util-linux", "waybar", "wl-clipboard", "wofi",
    "xdg-desktop-portal-gtk", "xdg-desktop-portal-hyprland", "xarchiver",
}
required_aur = {"spicetify-cli", "vesktop", "wlogout"}
if missing := required_official - official:
    raise ValueError(f"official package manifest is missing: {sorted(missing)}")
if missing := required_aur - aur:
    raise ValueError(f"AUR package manifest is missing: {sorted(missing)}")
PY

python3 "$repo_dir/tests/test_migrate_cassan.py"
python3 "$repo_dir/tests/test_memory_pressure.py"
python3 "$repo_dir/tests/test_prepare_private_wallpapers.py"
python3 "$repo_dir/tests/test_setup_firefox_theme.py"
python3 "$repo_dir/tests/test_setup_spicetify.py"
python3 "$repo_dir/tests/test_spotify_text_theme.py"
python3 "$repo_dir/tests/test_sync_app_themes.py"
python3 "$repo_dir/tests/test_theme_schedule.py"
python3 "$repo_dir/tests/test_theme_schedule_integration.py"
python3 "$repo_dir/tests/test_waybar_memory_tray.py"

if command -v node >/dev/null 2>&1; then
  node --test "$repo_dir/tests/test_spotify_theme.js"
else
  printf 'Node is unavailable; Spotify extension unit tests skipped on this host.\n'
fi

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

if rg -n '\bpseudotile[[:space:]]*=' "$repo_dir/hypr" -g '*.lua'; then
  printf 'obsolete dwindle.pseudotile config key found; use the window.pseudo dispatcher\n' >&2
  exit 1
fi

rg -q '^[[:space:]]*scale = 1,$' "$repo_dir/hypr/monitor.lua" || {
  printf 'the monitor fallback must use the requested 1x display scale\n' >&2
  exit 1
}

rg -Fq 'hl.bind(mod .. " + P", hl.dsp.window.pseudo())' "$repo_dir/hypr/bind.lua" || {
  printf 'the Super+P pseudotile dispatcher binding is missing\n' >&2
  exit 1
}

for binding in \
  'hl.bind(mod .. " + RETURN", hl.dsp.exec_cmd("kitty"))' \
  'hl.bind(mod .. " + SPACE", hl.dsp.exec_cmd(launcher))' \
  'hl.bind(mod .. " + E", hl.dsp.exec_cmd("kitty --class cassan-yazi -e yazi"))' \
  'hl.bind(mod .. " + CTRL + ESCAPE", hl.dsp.exec_cmd(task_manager))' \
  'hl.bind(mod .. " + CTRL + W", hl.dsp.exec_cmd(config_home .. [[/waybar/scripts/theme-switcher.sh" auto-toggle]]))' \
  'hl.bind(mod .. " + Q", hl.dsp.window.close())' \
  'hl.bind(mod .. " + SHIFT + S", hl.dsp.exec_cmd([[grim -g "$(slurp)" - | swappy -f -]]))' \
  'hl.bind(mod .. " + CTRL + S", hl.dsp.window.move({ workspace = "special:scratch" }))'; do
  rg -Fq "$binding" "$repo_dir/hypr/bind.lua" || {
    printf 'restored Cassan binding is missing: %s\n' "$binding" >&2
    exit 1
  }
done

rg -Fq '"$repo_dir/waybar/scripts/theme-switcher.sh" prepare' "$repo_dir/scripts/install.sh" || {
  printf 'installer must prepare the selected wallpaper and theme\n' >&2
  exit 1
}

rg -Fq 'applications/yazi.desktop' "$repo_dir/scripts/install.sh" || {
  printf 'installer must link the Yazi desktop entry\n' >&2
  exit 1
}

for active_consumer in \
  'hypr/theme.lua:/hyprland-dots/active-theme/hypr.lua' \
  'hypr/hyprlock.conf:hyprland-dots/active-theme/wallpaper' \
  'kitty/kitty.conf:hyprland-dots/active-theme/kitty.conf' \
  'btop/launch.sh:hyprland-dots/active-theme/btop' \
  'waybar/start.sh:hyprland-dots/active-theme' \
  'swaync/start.sh:hyprland-dots/active-theme/swaync.css' \
  'wofi/launch.sh:hyprland-dots/active-theme/wofi.css' \
  'wlogout/launch.sh:hyprland-dots/active-theme/wlogout.css'; do
  consumer=${active_consumer%%:*}
  expected=${active_consumer#*:}
  rg -Fq "$expected" "$repo_dir/$consumer" || {
    printf 'dynamic theme consumer is not using the active palette: %s\n' "$consumer" >&2
    exit 1
  }
done

if [[ $(rg -F -c 'kitty --class cassan-btop -e \"${XDG_CONFIG_HOME:-$HOME/.config}/btop/launch.sh\"' \
  "$repo_dir/waybar/config.jsonc") -ne 2 ]]; then
  printf 'Waybar CPU and memory-pressure clicks must both use the themed Btop launcher\n' >&2
  exit 1
fi

rg -Fq 'awww-daemon 9>&- >/dev/null 2>&1 &' \
  "$repo_dir/waybar/scripts/theme-switcher.sh" || {
  printf 'awww-daemon must not inherit the theme-switcher flock descriptor\n' >&2
  exit 1
}

for mapping in \
  'wallpapers=("$after_school" "$reze")' \
  'themes=("after-school" "reze")'; do
  rg -Fq "$mapping" "$repo_dir/waybar/scripts/theme-switcher.sh" || {
    printf 'two-wallpaper theme mapping is missing: %s\n' "$mapping" >&2
    exit 1
  }
done

if rg -n '\.spicetify' "$repo_dir/.zshrc"; then
  printf 'the shell PATH must not prefer the retired Cassan Spicetify binary\n' >&2
  exit 1
fi

rg -q '^spicetify_bin=/usr/bin/spicetify$' "$repo_dir/scripts/setup-spicetify.sh" || {
  printf 'Spicetify setup must use the reviewed AUR package binary\n' >&2
  exit 1
}

printf 'Rice compatibility checks passed.\n'
