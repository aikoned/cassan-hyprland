#!/usr/bin/env bash

set -o pipefail

selection=$(
  cliphist list |
    "${XDG_CONFIG_HOME:-$HOME/.config}/wofi/launch.sh" \
      --dmenu --width 700 --height 400 || true
)
[[ -n "$selection" ]] || exit 0
printf '%s\n' "$selection" | cliphist decode | wl-copy
