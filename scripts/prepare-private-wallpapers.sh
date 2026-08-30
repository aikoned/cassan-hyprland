#!/usr/bin/env bash

set -euo pipefail
umask 077

wallpaper_dir="${XDG_DATA_HOME:-$HOME/.local/share}/hyprland-dots/wallpapers"
destination="$wallpaper_dir/reze.jpg"
expected=b795a1231176884c2b144ddf38ffbc436505df03592fa2d4010df26100867277
legacy_config="${XDG_CONFIG_HOME:-$HOME/.config}/cassan/assets/nighthowler/wallpaper.jpg"
legacy_repo="$HOME/cassan-hyprland/assets/nighthowler/wallpaper.jpg"
backup_root="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland-dots/legacy-cassan"

checksum() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

if [[ -L "$destination" ]]; then
  printf 'refusing to use a symlink as the private wallpaper: %s\n' "$destination" >&2
  exit 1
fi

if [[ -f "$destination" ]]; then
  if [[ "$(checksum "$destination")" != "$expected" ]]; then
    printf 'refusing to replace a different file at %s\n' "$destination" >&2
    exit 1
  fi
  chmod 600 "$destination"
  printf '%s\n' "$destination"
  exit 0
fi

if [[ -e "$destination" ]]; then
  printf 'refusing to replace a non-file at %s\n' "$destination" >&2
  exit 1
fi

source_wallpaper=""
for candidate in "$legacy_repo" "$legacy_config"; do
  if [[ -f "$candidate" ]] && [[ "$(checksum "$candidate")" == "$expected" ]]; then
    source_wallpaper=$candidate
    break
  fi
done

if [[ -z "$source_wallpaper" && -d "$backup_root" ]]; then
  while IFS= read -r candidate; do
    if [[ "$(checksum "$candidate")" == "$expected" ]]; then
      source_wallpaper=$candidate
      break
    fi
  done < <(
    find "$backup_root" -type f \
      -path '*/home-config/cassan/assets/nighthowler/wallpaper.jpg' -print | sort -r
  )
fi

if [[ -z "$source_wallpaper" ]]; then
  printf 'The private Reze wallpaper was not found.\n' >&2
  printf 'Keep the old file at %s or place your verified copy at %s, then rerun.\n' \
    "$legacy_repo" "$destination" >&2
  exit 1
fi

mkdir -p "$wallpaper_dir"
temporary=$(mktemp "$wallpaper_dir/.reze.jpg.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT
cp -- "$source_wallpaper" "$temporary"

if [[ "$(checksum "$temporary")" != "$expected" ]]; then
  printf 'the private Reze wallpaper failed checksum verification\n' >&2
  exit 1
fi

chmod 600 "$temporary"
mv -- "$temporary" "$destination"
trap - EXIT
printf '%s\n' "$destination"
