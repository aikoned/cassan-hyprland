#!/usr/bin/env bash

set -euo pipefail

if [[ ! -r /etc/arch-release ]] || ! command -v pacman >/dev/null 2>&1; then
  printf 'This updater targets Arch Linux and Arch-based systems.\n' >&2
  exit 1
fi

sudo pacman -Syu

if command -v paru >/dev/null 2>&1; then
  paru -Sua
elif command -v yay >/dev/null 2>&1; then
  yay -Sua
fi

script_dir=$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd)
"$script_dir/check.sh"

printf 'System packages and local compatibility checks are up to date.\n'
