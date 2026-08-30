#!/usr/bin/env bash

set -euo pipefail

config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
theme_dir="${XDG_CACHE_HOME:-$HOME/.cache}/hyprland-dots/active-theme/btop"

if [[ ! -f "$theme_dir/noctalia.theme" ]]; then
  "$config_home/waybar/scripts/theme-switcher.sh" prepare >/dev/null
fi

exec btop --themes-dir "$theme_dir" "$@"
