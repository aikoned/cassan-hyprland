#!/usr/bin/env bash

set -euo pipefail

install_packages=false
install_aur=false
link_shell=false
migrate_cassan=false

usage() {
  cat <<'EOF'
Usage: ./scripts/install.sh [options]

  --packages    Fully update Arch and install official dependencies
  --aur         Install reviewed optional AUR packages with yay or paru
  --with-shell  Back up and link the included .zshrc
  --migrate-cassan
                Archive remnants from the former Cassan setup first
  -h, --help    Show this help
EOF
}

while (( $# > 0 )); do
  case "$1" in
    --packages) install_packages=true ;;
    --aur) install_aur=true ;;
    --with-shell) link_shell=true ;;
    --migrate-cassan) migrate_cassan=true ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

script_dir=$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}"
data_dir="${XDG_DATA_HOME:-$HOME/.local/share}"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/hyprland-dots"
cache_dir="${XDG_CACHE_HOME:-$HOME/.cache}/hyprland-dots"
backup_id=$(date -u +'%Y%m%dT%H%M%SZ')
backup_root="$state_dir/backups"
backup_dir=""

config_names=(
  hypr
  waybar
  kitty
  wofi
  btop
  cava
  fastfetch
  swaync
  swappy
  wlogout
  yazi
  zathura
  gtk-3.0
  gtk-4.0
  qt6ct
  xdg-desktop-portal
)

if [[ ! -r /etc/arch-release ]] || ! command -v pacman >/dev/null 2>&1; then
  printf 'This installer targets Arch Linux and Arch-based systems.\n' >&2
  exit 1
fi

if (( EUID == 0 )); then
  printf 'Run this installer as your desktop user, without sudo.\n' >&2
  exit 1
fi

require_apps_closed() {
  local status app
  local -a query
  for app in spotify vesktop electron-vesktop; do
    query=(pgrep -i -x "$app")
    if [[ "$app" == electron-vesktop ]]; then
      query=(pgrep -f '(^|[[:space:]])/usr/lib/vesktop/app\.asar([[:space:]]|$)')
    fi
    if "${query[@]}" >/dev/null 2>&1; then
      printf 'Close Spotify and Vesktop before installing this update. Nothing was changed.\n' >&2
      exit 1
    else
      status=$?
      if (( status != 1 )); then
        printf 'Could not check running applications; pgrep from procps-ng is required.\n' >&2
        exit 1
      fi
    fi
  done
}

require_apps_closed

read_packages() {
  sed -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$1"
}

# Reject an incomplete checkout before pacman, AUR helpers, backups, or links
# can change the host system.
link_sources=(
  "${config_names[@]}"
  assets
  assets-profile
  applications/yazi.desktop
  spotify-launcher.conf
  scripts
  themes
  vesktop
  spicetify/Extensions/hyprland-dots-theme.js
  spicetify/Themes/Comfy
  spicetify/Themes/marketplace
  spicetify/Themes/text
  spicetify/CustomApps/marketplace
)
if [[ "$link_shell" == true ]]; then
  link_sources+=(.zshrc)
fi
for source in "${link_sources[@]}"; do
  if [[ ! -e "$repo_dir/$source" ]]; then
    printf 'missing install source: %s\n' "$source" >&2
    exit 1
  fi
done

aur_helper=""
if [[ "$install_aur" == true ]]; then
  if command -v paru >/dev/null 2>&1; then
    aur_helper=paru
  elif command -v yay >/dev/null 2>&1; then
    aur_helper=yay
  else
    printf 'Install and review paru or yay before using --aur. Nothing was changed.\n' >&2
    exit 1
  fi
fi

validation_tools_available() {
  command -v python3 >/dev/null 2>&1 &&
    python3 -c 'import tomllib' >/dev/null 2>&1 &&
    command -v rg >/dev/null 2>&1 &&
    command -v zsh >/dev/null 2>&1
}

if validation_tools_available; then
  "$repo_dir/scripts/check.sh"
elif [[ "$install_packages" == false ]]; then
  printf 'Python 3.11+, ripgrep, and zsh are required for pre-install validation.\n' >&2
  exit 1
else
  printf 'Full validation will run after current Python, ripgrep, and zsh are installed.\n'
fi

if [[ "$install_packages" == true ]]; then
  mapfile -t official_packages < <(read_packages "$repo_dir/packages/official.txt")
  sudo pacman -Syu --needed "${official_packages[@]}"
fi

if [[ "$install_aur" == true ]]; then
  mapfile -t aur_packages < <(read_packages "$repo_dir/packages/aur.txt")
  "$aur_helper" -S --needed "${aur_packages[@]}"
fi

verify_installed_packages() {
  local manifest=$1
  local label=$2
  local package
  local -a missing=()

  while IFS= read -r package; do
    if ! pacman -Q -- "$package" >/dev/null 2>&1; then
      missing+=("$package")
    fi
  done < <(read_packages "$manifest")

  if (( ${#missing[@]} > 0 )); then
    printf '%s package verification failed; missing:' "$label" >&2
    printf ' %s' "${missing[@]}" >&2
    printf '\n' >&2
    exit 1
  fi
}

if [[ "$install_packages" == true ]]; then
  verify_installed_packages "$repo_dir/packages/official.txt" "Official"
fi
if [[ "$install_aur" == true ]]; then
  verify_installed_packages "$repo_dir/packages/aur.txt" "AUR"
fi

# This second pass is intentional: on a minimal Arch install, Python and
# ripgrep may only have become available in the package transaction above.
"$repo_dir/scripts/check.sh"

"$repo_dir/scripts/prepare-private-wallpapers.sh" >/dev/null

set_dark_preferences() {
  local failed=false

  if ! command -v gsettings >/dev/null 2>&1; then
    printf 'warning: gsettings is unavailable; Firefox may retain a light toolbar\n' >&2
    return
  fi
  gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark' || failed=true
  gsettings set org.gnome.desktop.interface gtk-theme 'Adwaita-dark' || failed=true
  if [[ "$failed" == true ]]; then
    printf 'warning: the desktop dark preference could not be saved in this session\n' >&2
  fi
}

set_dark_preferences

if [[ "$migrate_cassan" == true ]]; then
  python3 "$repo_dir/scripts/migrate-cassan.py" --apply
fi

mkdir -p "$config_dir" "$data_dir/applications" "$state_dir" "$cache_dir"
mkdir -p "$HOME/Pictures/Screenshots"

ensure_backup_dir() {
  if [[ -z "$backup_dir" ]]; then
    mkdir -p "$backup_root"
    backup_dir=$(mktemp -d "$backup_root/${backup_id}.XXXXXX")
  fi
}

link_path() {
  local source=$1
  local destination=$2
  local backup_relative=$3

  if [[ ! -e "$source" ]]; then
    printf 'refusing to create a broken link; source is missing: %s\n' "$source" >&2
    exit 1
  fi

  if [[ -L "$destination" ]] && [[ "$(readlink -f -- "$destination")" == "$(readlink -f -- "$source")" ]]; then
    printf 'already linked: %s\n' "$destination"
    return
  fi

  if [[ -e "$destination" || -L "$destination" ]]; then
    ensure_backup_dir
    mkdir -p "$backup_dir/$(dirname -- "$backup_relative")"
    mv -- "$destination" "$backup_dir/$backup_relative"
    printf 'backed up: %s -> %s\n' "$destination" "$backup_dir/$backup_relative"
  fi

  mkdir -p "$(dirname -- "$destination")"
  ln -s -- "$source" "$destination"
  printf 'linked: %s -> %s\n' "$destination" "$source"
}

ensure_real_directory() {
  local destination=$1
  local backup_relative=$2

  if [[ -d "$destination" && ! -L "$destination" ]]; then
    return
  fi
  if [[ -e "$destination" || -L "$destination" ]]; then
    ensure_backup_dir
    mkdir -p "$backup_dir/$(dirname -- "$backup_relative")"
    mv -- "$destination" "$backup_dir/$backup_relative"
    printf 'backed up: %s -> %s\n' "$destination" "$backup_dir/$backup_relative"
  fi
  mkdir -p "$destination"
}

ensure_real_directory "$config_dir/spicetify" "config/spicetify"
ensure_real_directory "$config_dir/spicetify/Themes" "config/spicetify/Themes"
ensure_real_directory "$config_dir/spicetify/CustomApps" "config/spicetify/CustomApps"
if [[ -e "$config_dir/spicetify/Extensions" || -L "$config_dir/spicetify/Extensions" ]]; then
  if [[ ! -d "$config_dir/spicetify/Extensions" ]]; then
    printf 'Spicetify Extensions must be a directory; existing path was left unchanged.\n' >&2
    exit 1
  fi
else
  mkdir -p "$config_dir/spicetify/Extensions"
fi

python3 "$repo_dir/scripts/sync-app-themes.py" --install-vesktop

for name in "${config_names[@]}"; do
  link_path "$repo_dir/$name" "$config_dir/$name" "config/$name"
done

link_path \
  "$repo_dir/spotify-launcher.conf" \
  "$config_dir/spotify-launcher.conf" \
  "config/spotify-launcher.conf"

link_path \
  "$repo_dir/applications/yazi.desktop" \
  "$data_dir/applications/yazi.desktop" \
  "data/applications/yazi.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$data_dir/applications" || \
    printf 'warning: the desktop application cache could not be refreshed\n' >&2
fi

link_path \
  "$repo_dir/spicetify/Themes/Comfy" \
  "$config_dir/spicetify/Themes/Comfy" \
  "config/spicetify/Themes/Comfy"
link_path \
  "$repo_dir/spicetify/Themes/marketplace" \
  "$config_dir/spicetify/Themes/marketplace" \
  "config/spicetify/Themes/marketplace"
link_path \
  "$repo_dir/spicetify/Themes/text" \
  "$config_dir/spicetify/Themes/text" \
  "config/spicetify/Themes/text"
link_path \
  "$repo_dir/spicetify/CustomApps/marketplace" \
  "$config_dir/spicetify/CustomApps/marketplace" \
  "config/spicetify/CustomApps/marketplace"
link_path \
  "$repo_dir/spicetify/Extensions/hyprland-dots-theme.js" \
  "$config_dir/spicetify/Extensions/hyprland-dots-theme.js" \
  "config/spicetify/Extensions/hyprland-dots-theme.js"

link_path "$repo_dir/assets" "$config_dir/hyprland-dots/assets" "config/hyprland-dots-assets"
link_path "$repo_dir/assets-profile" "$config_dir/hyprland-dots/assets-profile" "config/hyprland-dots-assets-profile"
link_path "$repo_dir/scripts" "$config_dir/hyprland-dots/scripts" "config/hyprland-dots-scripts"

if [[ "$link_shell" == true ]]; then
  link_path "$repo_dir/.zshrc" "$HOME/.zshrc" "home/.zshrc"
fi

"$repo_dir/waybar/scripts/theme-switcher.sh" prepare

app_setup_incomplete=false
if ! python3 "$repo_dir/scripts/setup-firefox-theme.py"; then
  printf 'warning: Firefox needs ./scripts/setup-firefox-theme.py after resolving the error above.\n' >&2
  app_setup_incomplete=true
fi

if [[ -x /usr/bin/spicetify && ( -f "$config_dir/spicetify/config-xpui.ini" || -f "$config_dir/spotify/prefs" ) ]]; then
  if ! "$repo_dir/scripts/setup-spicetify.sh"; then
    printf 'warning: Spotify text theming needs ./scripts/setup-spicetify.sh.\n' >&2
    app_setup_incomplete=true
  fi
else
  printf 'Spotify: after its first launch, close it and run ./scripts/setup-spicetify.sh.\n'
fi

if ! python3 "$repo_dir/scripts/sync-app-themes.py" --verbose; then
  app_setup_incomplete=true
fi

"$repo_dir/scripts/check.sh"

if [[ -n "$backup_dir" && -d "$backup_dir" ]]; then
  printf '\nBackups: %s\n' "$backup_dir"
fi
printf '\nAutomatic wallpaper switching: 08:00–20:00 After School, 20:00–08:00 Reze, local time.\n'
printf 'Click AUTO/MAN in Waybar or press Super+Ctrl+W to toggle; manual wallpaper choices pause it.\n'
if [[ "$app_setup_incomplete" == true ]]; then
  printf '\nDesktop files are installed, but app theme setup needs attention; see the warnings above.\n' >&2
  exit 1
fi
printf '\nInstallation complete. Log out and start a new Hyprland session.\n'
