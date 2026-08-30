#!/usr/bin/env bash

set -euo pipefail

config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/hyprland-dots/active-theme"

if [[ ! -f "$cache_dir/waybar.css" ]]; then
  "$config_home/waybar/scripts/theme-switcher.sh" prepare >/dev/null
fi

if [[ "${1:-}" == --replace ]]; then
  pkill -x waybar >/dev/null 2>&1 || true
elif (( $# > 0 )); then
  printf 'usage: %s [--replace]\n' "${0##*/}" >&2
  exit 2
fi

exec waybar \
  --config "$config_home/waybar/config.jsonc" \
  --style "$cache_dir/waybar.css"
