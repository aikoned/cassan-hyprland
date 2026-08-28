#!/usr/bin/env bash

set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)

required_paths=(
  ".zshrc"
  "assets/nighthowler/palette.toml"
  "packages/official.txt"
  "scripts/validate_toml.py"
)

for path in "${required_paths[@]}"; do
  if [[ ! -f "$repo_dir/$path" ]]; then
    echo "missing required file: $path" >&2
    exit 1
  fi
done

if command -v python3 >/dev/null 2>&1; then
  python3 "$repo_dir/scripts/validate_toml.py"
else
  echo "warning: python3 unavailable; skipped TOML validation" >&2
fi

git -C "$repo_dir" diff --check
git -C "$repo_dir" diff --cached --check

echo "Cassan repository checks passed."
