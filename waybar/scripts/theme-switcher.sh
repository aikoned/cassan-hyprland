#!/usr/bin/env bash

set -euo pipefail

script_dir=$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/../.." && pwd)
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/hyprland-dots"
theme_root="$cache_dir/themes"
active_theme="$cache_dir/active-theme"
legacy_wallpaper="$cache_dir/current-wallpaper"
lock_file="$cache_dir/theme-switcher.lock"
schedule="$repo_dir/scripts/theme-schedule.py"
after_school=$(realpath "$repo_dir/assets/after_school_stroll_gruvbox.png")
reze=$("$repo_dir/scripts/prepare-private-wallpapers.sh")
reze=$(realpath "$reze")

wallpapers=("$after_school" "$reze")
themes=("after-school" "reze")
labels=("After School Stroll — Gruvbox" "Reze — Cassan Nighthowler")

mkdir -p "$cache_dir" "$theme_root"

lock_switcher() {
  if ! command -v flock >/dev/null 2>&1; then
    printf 'theme switching requires flock from util-linux\n' >&2
    exit 1
  fi
  exec 9>"$lock_file"
  flock 9
  "$schedule" mode >/dev/null
}

atomic_symlink() {
  python3 - "$1" "$2" <<'PY'
import os
import pathlib
import sys
import tempfile

target = sys.argv[1]
destination = pathlib.Path(sys.argv[2])
destination.parent.mkdir(parents=True, exist_ok=True)
if os.path.lexists(destination) and not destination.is_symlink():
    raise RuntimeError(f"refusing to replace non-symlink: {destination}")
temporary_dir = pathlib.Path(
    tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
)
temporary_link = temporary_dir / "link"
try:
    os.symlink(target, temporary_link)
    os.replace(temporary_link, destination)
finally:
    try:
        temporary_link.unlink()
    except FileNotFoundError:
        pass
    temporary_dir.rmdir()
PY
}

ensure_awww() {
  if awww query 9>&- >/dev/null 2>&1; then
    return
  fi

  awww-daemon 9>&- >/dev/null 2>&1 &
  for _ in {1..30}; do
    if awww query 9>&- >/dev/null 2>&1; then
      return
    fi
    sleep 0.1
  done

  notify-send "Theme Switcher" "awww-daemon did not become ready" 9>&- || true
  exit 1
}

current_index() {
  local index
  local selected=""
  local target=""

  if [[ -f "$active_theme/current-theme" ]]; then
    read -r selected < "$active_theme/current-theme"
    for index in "${!themes[@]}"; do
      if [[ "${themes[$index]}" == "$selected" ]]; then
        printf '%s\n' "$index"
        return
      fi
    done
  fi

  selected=$("$schedule" selected)
  for index in "${!themes[@]}"; do
    if [[ "${themes[$index]}" == "$selected" ]]; then
      printf '%s\n' "$index"
      return
    fi
  done

  if [[ -L "$legacy_wallpaper" ]]; then
    target=$(realpath "$legacy_wallpaper" 2>/dev/null || true)
  fi

  for index in "${!wallpapers[@]}"; do
    if [[ "${wallpapers[$index]}" == "$target" ]]; then
      printf '%s\n' "$index"
      return
    fi
  done

  printf '0\n'
}

index_for_slug() {
  local index
  for index in "${!themes[@]}"; do
    if [[ "${themes[$index]}" == "$1" ]]; then
      printf '%s\n' "$index"
      return
    fi
  done
  printf 'unknown wallpaper theme: %s\n' "$1" >&2
  return 1
}

desired_index() {
  if [[ $("$schedule" mode) == auto ]]; then
    index_for_slug "$("$schedule" target)"
  else
    index_for_slug "$("$schedule" selected)"
  fi
}

theme_is_complete() {
  local path=$1
  local required

  for required in \
    current-theme \
    btop/noctalia.theme \
    hypr.lua \
    hyprlock.conf \
    kitty.conf \
    pywalfox.json \
    spotify-palette.json \
    swaync.css \
    vesktop.css \
    waybar.css \
    wofi.css \
    wlogout.css \
    wallpaper \
    icons/lock.png \
    icons/logout.png \
    icons/suspend.png \
    icons/hibernate.png \
    icons/reboot.png \
    icons/shutdown.png; do
    [[ -f "$path/$required" ]] || return 1
  done
}

render_theme() {
  local index=$1
  local slug=${themes[$index]}
  local generation

  generation=$(mktemp -d "$theme_root/.${slug}.XXXXXX") || return 1
  if ! python3 "$repo_dir/scripts/render-theme.py" \
    --theme "$slug" \
    --output "$generation"; then
    rm -rf -- "$generation"
    return 1
  fi
  if ! ln -s -- "${wallpapers[$index]}" "$generation/wallpaper"; then
    rm -rf -- "$generation"
    return 1
  fi
  if ! theme_is_complete "$generation"; then
    rm -rf -- "$generation"
    return 1
  fi
  atomic_symlink "$generation" "$theme_root/$slug"
}

ensure_theme() {
  local index=$1
  local theme_link="$theme_root/${themes[$index]}"

  if [[ ! -L "$theme_link" ]] || ! theme_is_complete "$theme_link"; then
    render_theme "$index"
  fi
}

activate_index() {
  local index=$1
  local theme_target

  ensure_theme "$index" || return 1
  theme_target=$(realpath "$theme_root/${themes[$index]}") || return 1
  atomic_symlink "$theme_target" "$active_theme"
}

publish_selection() {
  local index=$1
  local state_action=${2:-remember}
  local previous_theme=""

  if [[ -L "$active_theme" ]]; then
    previous_theme=$(readlink "$active_theme")
  fi
  activate_index "$index" || return 1
  if ! "$schedule" "$state_action" "${themes[$index]}"; then
    if [[ -n "$previous_theme" ]]; then
      atomic_symlink "$previous_theme" "$active_theme"
    elif [[ -L "$active_theme" ]]; then
      unlink "$active_theme"
    fi
    printf 'Could not save the wallpaper selection; restored the previous theme pointer.\n' >&2
    return 1
  fi
}

cleanup_generations() {
  local generation
  local resolved
  local retained
  local target
  local -a keep=()

  for target in "$theme_root/after-school" "$theme_root/reze" "$active_theme"; do
    if [[ -L "$target" ]]; then
      resolved=$(realpath "$target" 2>/dev/null || true)
      if [[ -n "$resolved" ]]; then
        keep+=("$resolved")
      fi
    fi
  done

  shopt -s nullglob
  for generation in "$theme_root"/.after-school.* "$theme_root"/.reze.*; do
    [[ -d "$generation" && ! -L "$generation" ]] || continue
    resolved=$(realpath "$generation")
    retained=false
    for target in "${keep[@]}"; do
      if [[ "$resolved" == "$target" ]]; then
        retained=true
        break
      fi
    done
    if [[ "$retained" == false ]]; then
      rm -rf -- "$generation"
    fi
  done
  shopt -u nullglob
}

prepare_themes() {
  local index
  local selected

  selected=$(desired_index)

  for index in "${!themes[@]}"; do
    render_theme "$index"
  done
  publish_selection "$selected"
  cleanup_generations
  sync_app_themes
}

sync_app_themes() {
  if ! python3 "$repo_dir/scripts/sync-app-themes.py" 9>&-; then
    printf 'Some application colors could not be updated; see the warnings above.\n' >&2
  fi
}

reload_desktop() {
  hyprctl reload 9>&- >/dev/null 2>&1 || true
  pkill -SIGUSR2 -x waybar 9>&- >/dev/null 2>&1 || true
  pkill -SIGUSR2 -x btop 9>&- >/dev/null 2>&1 || true
  pkill -SIGUSR1 -x kitty 9>&- >/dev/null 2>&1 || true
  swaync-client -rs 9>&- >/dev/null 2>&1 || true
}

apply_index() {
  local index=$1
  local notify=${2:-yes}
  local state_action=${3:-remember}
  local positions=(center top bottom left right top-left top-right bottom-left bottom-right)
  local position=${positions[RANDOM % ${#positions[@]}]}
  local previous_wallpaper=""

  ensure_theme "$index"
  if [[ -e "$active_theme" && ! -L "$active_theme" ]]; then
    printf 'refusing to replace non-symlink: %s\n' "$active_theme" >&2
    return 1
  fi
  if [[ -f "$active_theme/wallpaper" ]]; then
    previous_wallpaper=$(realpath "$active_theme/wallpaper")
  fi
  ensure_awww
  awww img "${wallpapers[$index]}" \
    --transition-type grow \
    --transition-fps 60 \
    --transition-duration 2 \
    --transition-pos "$position" 9>&-
  if ! publish_selection "$index" "$state_action"; then
    if [[ -n "$previous_wallpaper" ]]; then
      awww img "$previous_wallpaper" --transition-type none 9>&- >/dev/null 2>&1 || true
    fi
    return 1
  fi
  cleanup_generations
  sync_app_themes
  reload_desktop

  if [[ "$notify" == yes ]]; then
    notify-send "Theme Switcher" "Applied: ${labels[$index]}" 9>&- || true
  fi
}

case "${1:-next}" in
  prepare)
    lock_switcher
    prepare_themes
    ;;
  next)
    lock_switcher
    index=$(( ($(current_index) + 1) % ${#wallpapers[@]} ))
    apply_index "$index" yes manual
    ;;
  random)
    lock_switcher
    current=$(current_index)
    index=$((RANDOM % ${#wallpapers[@]}))
    if (( ${#wallpapers[@]} > 1 && index == current )); then
      index=$(( (index + 1) % ${#wallpapers[@]} ))
    fi
    apply_index "$index" yes manual
    ;;
  restore)
    lock_switcher
    apply_index "$(desired_index)" no
    ;;
  scheduled)
    lock_switcher
    [[ $("$schedule" mode) == auto ]] || exit 0
    index=$(desired_index)
    if [[ $(current_index) != "$index" ]] || ! theme_is_complete "$active_theme"; then
      apply_index "$index" no
    fi
    ;;
  auto-on|auto-off|auto-toggle)
    lock_switcher
    mode=$("$schedule" mode)
    if [[ "$1" == auto-off || ( "$1" == auto-toggle && "$mode" == auto ) ]]; then
      index=$(current_index)
      "$schedule" manual "${themes[$index]}"
      notify-send "Theme Schedule" "Automatic switching off; keeping ${labels[$index]}" 9>&- || true
    else
      index=$(index_for_slug "$("$schedule" target)")
      if [[ $(current_index) != "$index" ]] || ! theme_is_complete "$active_theme"; then
        apply_index "$index" no automatic
      else
        "$schedule" automatic "${themes[$index]}"
      fi
      notify-send "Theme Schedule" "Automatic day/night switching on" 9>&- || true
    fi
    ;;
  set)
    [[ $# == 2 ]] || { printf 'set requires after-school or reze\n' >&2; exit 2; }
    lock_switcher
    index=$(index_for_slug "$2")
    apply_index "$index" yes manual
    ;;
  list)
    selected=$(
      printf '%s\n' "${labels[@]}" |
        "${XDG_CONFIG_HOME:-$HOME/.config}/wofi/launch.sh" \
          --dmenu --prompt "Choose Wallpaper" --insensitive || true
    )
    [[ -n "$selected" ]] || exit 0
    for index in "${!labels[@]}"; do
      if [[ "${labels[$index]}" == "$selected" ]]; then
        lock_switcher
        apply_index "$index" yes manual
        exit 0
      fi
    done
    ;;
  *)
    printf 'usage: %s {prepare|next|random|restore|list|set THEME|auto-on|auto-off|auto-toggle|scheduled}\n' "${0##*/}" >&2
    exit 2
    ;;
esac
