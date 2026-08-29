#!/usr/bin/env bash

set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)

required_paths=(
  ".zshrc"
  "assets/nighthowler/palette.toml"
  "btop/btop.conf"
  "btop/themes/nighthowler.theme"
  "cava/config"
  "cava/themes/nighthowler"
  "fastfetch/config.jsonc"
  "firefox/cassan-nighthowler.css"
  "firefox/cassan-nighthowler-content.css"
  "hypr/animation.lua"
  "hypr/bind.lua"
  "hypr/environment.lua"
  "hypr/hyprland.lua"
  "hypr/hypridle.conf"
  "hypr/hyprlock.conf"
  "hypr/hyprpaper.conf"
  "hypr/input.lua"
  "hypr/looknfeel.lua"
  "hypr/monitor.lua"
  "hypr/rules.lua"
  "hypr/startup.lua"
  "hypr/theme.lua"
  "kitty/kitty.conf"
  "kitty/theme.conf"
  "packages/aur.txt"
  "packages/official.txt"
  "scripts/app_themes.py"
  "scripts/cassan.py"
  "scripts/render_theme.py"
  "scripts/test_app_themes.py"
  "scripts/test_cassan.py"
  "scripts/validate_config.py"
  "scripts/validate_toml.py"
  "swaync/config.json"
  "swaync/style.css"
  "swaync/theme.css"
  "spicetify/Cassan-Nighthowler/color.ini"
  "spicetify/Cassan-Nighthowler/user.css"
  "vesktop/Cassan-Nighthowler.theme.css"
  "waybar/config.jsonc"
  "waybar/style.css"
  "waybar/theme.css"
  "wofi/config"
  "wofi/style.css"
  "wofi/style.template.css"
  "wofi/theme.css"
  "networkmanager-dmenu/config.ini"
  "yazi/theme.toml"
  "yazi/yazi.toml"
)

for path in "${required_paths[@]}"; do
  if [[ ! -f "$repo_dir/$path" ]]; then
    echo "missing required file: $path" >&2
    exit 1
  fi
done

for path in "${required_paths[@]}"; do
  if LC_ALL=C grep -nE '[[:blank:]]+$' "$repo_dir/$path" >/dev/null; then
    echo "trailing whitespace found in: $path" >&2
    LC_ALL=C grep -nE '[[:blank:]]+$' "$repo_dir/$path" >&2
    exit 1
  fi
done

tracked_preview_paths=$(git -C "$repo_dir" ls-files -- 'preview/**' 'scripts/preview.sh')
if [[ -n "$tracked_preview_paths" ]]; then
  echo "preview-only files must not be tracked:" >&2
  printf '%s\n' "$tracked_preview_paths" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required for Cassan configuration validation" >&2
  exit 1
fi

python3 "$repo_dir/scripts/validate_toml.py"
python3 "$repo_dir/scripts/validate_config.py"
python3 "$repo_dir/scripts/render_theme.py" --check
python3 -B "$repo_dir/scripts/test_app_themes.py"
python3 -B "$repo_dir/scripts/test_cassan.py"

git -C "$repo_dir" diff --check
git -C "$repo_dir" diff --cached --check

echo "Cassan repository checks passed."
