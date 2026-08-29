#!/usr/bin/env bash

set -euo pipefail

script_dir=$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/../.." && pwd)
wallpaper_dir="$repo_dir/assets"
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/hyprland-dots"
current_wallpaper="$cache_dir/current-wallpaper"

mkdir -p "$cache_dir"

mapfile -t wallpapers < <(
  find "$wallpaper_dir" -type f \
    \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) -print | sort
)

if (( ${#wallpapers[@]} == 0 )); then
  notify-send "Theme Switcher" "No wallpapers found in $wallpaper_dir"
  exit 1
fi

ensure_awww() {
  if awww query >/dev/null 2>&1; then
    return
  fi

  awww-daemon >/dev/null 2>&1 &
  for _ in {1..30}; do
    if awww query >/dev/null 2>&1; then
      return
    fi
    sleep 0.1
  done

  notify-send "Theme Switcher" "awww-daemon did not become ready"
  exit 1
}

current_index() {
  local target=""
  local index

  if [[ -L "$current_wallpaper" ]]; then
    target=$(readlink -f -- "$current_wallpaper" 2>/dev/null || true)
  fi

  for index in "${!wallpapers[@]}"; do
    if [[ "${wallpapers[$index]}" == "$target" ]]; then
      printf '%s\n' "$index"
      return
    fi
  done

  printf '%s\n' 0
}

apply_wallpaper() {
  local wallpaper=$1
  local notify=${2:-yes}
  local positions=(center top bottom left right top-left top-right bottom-left bottom-right)
  local position=${positions[RANDOM % ${#positions[@]}]}

  ensure_awww
  ln -sfn -- "$wallpaper" "$current_wallpaper"
  awww img "$wallpaper" \
    --transition-type grow \
    --transition-fps 60 \
    --transition-duration 2 \
    --transition-pos "$position"

  if [[ "$notify" == yes ]]; then
    notify-send "Theme Switcher" "Applied: $(basename -- "$wallpaper")"
  fi
}

case "${1:-next}" in
  next)
    index=$(( ($(current_index) + 1) % ${#wallpapers[@]} ))
    apply_wallpaper "${wallpapers[$index]}"
    ;;
  random)
    apply_wallpaper "${wallpapers[RANDOM % ${#wallpapers[@]}]}"
    ;;
  restore)
    index=$(current_index)
    apply_wallpaper "${wallpapers[$index]}" no
    ;;
  list)
    selected=$(
      printf '%s\n' "${wallpapers[@]##*/}" |
        wofi --dmenu --prompt "Choose Wallpaper" --insensitive || true
    )
    [[ -n "$selected" ]] || exit 0
    for index in "${!wallpapers[@]}"; do
      if [[ "${wallpapers[$index]##*/}" == "$selected" ]]; then
        apply_wallpaper "${wallpapers[$index]}"
        exit 0
      fi
    done
    ;;
  *)
    printf 'usage: %s {next|random|restore|list}\n' "${0##*/}" >&2
    exit 2
    ;;
esac
