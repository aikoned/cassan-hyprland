#!/usr/bin/env bash

set -euo pipefail

config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
style="${XDG_CACHE_HOME:-$HOME/.cache}/hyprland-dots/active-theme/wlogout.css"

if [[ ! -f "$style" ]]; then
  "$config_home/waybar/scripts/theme-switcher.sh" prepare >/dev/null
fi

exec wlogout --css "$style" "$@"
