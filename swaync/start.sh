#!/usr/bin/env bash

set -euo pipefail

case "${1:-}" in
  "") ;;
  --prepare-only) ;;
  *)
    printf 'usage: %s [--prepare-only]\n' "${0##*/}" >&2
    exit 2
    ;;
esac

config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/hyprland-dots/swaync"
source_config="$config_home/swaync/config.json"
source_style="$config_home/swaync/style.css"
runtime_config="$cache_dir/config.json"
backlight_root="${HYPRLAND_DOTS_BACKLIGHT_ROOT:-/sys/class/backlight}"

mkdir -p "$cache_dir"

best_device=""
best_max=-1
shopt -s nullglob
for device_path in "$backlight_root"/*; do
  [[ -d "$device_path" ]] || continue
  max_brightness=0
  if [[ -r "$device_path/max_brightness" ]]; then
    read -r max_brightness < "$device_path/max_brightness" || max_brightness=0
  fi
  [[ "$max_brightness" =~ ^[0-9]+$ ]] || max_brightness=0
  if (( max_brightness > best_max )); then
    best_max=$max_brightness
    best_device=${device_path##*/}
  fi
done
shopt -u nullglob

temporary_config=$(mktemp "$cache_dir/config.json.XXXXXX")
trap 'rm -f -- "$temporary_config"' EXIT

if [[ -n "$best_device" ]]; then
  jq --arg device "$best_device" \
    '.["widget-config"].backlight.device = $device' \
    "$source_config" > "$temporary_config"
else
  jq \
    '.widgets |= map(select(. != "backlight")) | .["widget-config"] |= del(.backlight)' \
    "$source_config" > "$temporary_config"
fi

mv -- "$temporary_config" "$runtime_config"
trap - EXIT

if [[ "${1:-}" == --prepare-only ]]; then
  printf '%s\n' "$runtime_config"
  exit 0
fi

exec swaync --replace --config "$runtime_config" --style "$source_style"
