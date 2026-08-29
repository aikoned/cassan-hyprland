#!/usr/bin/env bash

set -euo pipefail

if ! command -v powerprofilesctl >/dev/null 2>&1; then
  printf '󰾅\n'
  exit 0
fi

current_profile() {
  powerprofilesctl get 2>/dev/null || printf 'unavailable\n'
}

display_profile() {
  case "$(current_profile)" in
    power-saver) printf '󰾆\n' ;;
    balanced) printf '󰾅\n' ;;
    performance) printf '󰓅\n' ;;
    *) printf '󰾅\n' ;;
  esac
}

toggle_profile() {
  case "$(current_profile)" in
    power-saver) powerprofilesctl set balanced ;;
    balanced)
      if powerprofilesctl list | grep -q 'performance:'; then
        powerprofilesctl set performance
      else
        powerprofilesctl set power-saver
      fi
      ;;
    performance) powerprofilesctl set power-saver ;;
    unavailable) return 0 ;;
    *) powerprofilesctl set balanced ;;
  esac
}

case "${1:-display}" in
  display) display_profile ;;
  toggle)
    toggle_profile
    display_profile
    ;;
  *)
    printf 'usage: %s {display|toggle}\n' "${0##*/}" >&2
    exit 2
    ;;
esac
