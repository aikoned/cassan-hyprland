#!/usr/bin/env bash

set -euo pipefail

spicetify_bin=/usr/bin/spicetify

if [[ ! -x "$spicetify_bin" ]]; then
  printf 'Spicetify is not installed. Install the reviewed spicetify-cli AUR package first.\n' >&2
  exit 1
fi

config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
spotify_dir="$HOME/.local/share/spotify-launcher/install/usr/share/spotify"
prefs_file="$config_home/spotify/prefs"

if [[ ! -x "$spotify_dir/spotify" || ! -d "$spotify_dir/Apps" || ! -f "$prefs_file" ]]; then
  cat >&2 <<'EOF'
spotify-launcher has not created the Spotify installation and preferences this
setup expects. Launch spotify-launcher once, let Spotify finish opening, then
close Spotify and run this script again.
EOF
  exit 1
fi

"$spicetify_bin" config spotify_path "$spotify_dir" prefs_path "$prefs_file"

if ! "$spicetify_bin" path >/dev/null 2>&1; then
  printf 'Spicetify rejected the configured Spotify installation paths.\n' >&2
  exit 1
fi

"$spicetify_bin" config \
  current_theme Comfy \
  color_scheme Comfy \
  inject_css 1 \
  inject_theme_js 1 \
  replace_colors 1 \
  overwrite_assets 1
"$spicetify_bin" config custom_apps marketplace
"$spicetify_bin" backup apply

printf 'Applied the Comfy theme and enabled the bundled Marketplace app.\n'
