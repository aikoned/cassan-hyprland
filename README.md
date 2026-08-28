# Cassan

Cassan is a reusable Arch Linux desktop built around Hyprland. The first theme will be called **Cassan Nighthowler**: a rice with violet accents. It should show compact information and prioritize keyboard navigation.

## Current Direction

- Arch Linux with portable defaults and optional hardware profiles
- Hyprland with opaque, lightly framed windows and restrained animation
- Three compact Waybar islands
- Iosevka Nerd Font-style typography
- Shared Nighthowler color tokens across desktop and applications

## Repository map

```text
.zshrc                  shell entry point
assets/nighthowler/     shared visual tokens and redistributable theme assets
btop/                   system monitor
cava/                   audio visualizer
fastfetch/              system-information composition
hypr/                   Hyprland, lock, idle, input, and wallpaper configuration
kitty/                  terminal configuration
spicetify/              optional Spotify integration
swappy/                 screenshot annotation
swaync/                 notifications and quick settings
vesktop/                optional Discord integration
waybar/                 three compact top-bar islands
wlogout/                power and session menu
wofi/                   application launcher
yazi/                   terminal file manager
zathura/                PDF viewer
docs/                   architecture, development, and deployment guidance
hosts/                  optional machine-specific profiles
local/                  ignored local overrides and user-owned assets
packages/               reviewed package manifests
scripts/                validation and future installation helpers
```

## Status

There is intentionally no installer yet. Still a W.I.P.

## Branches

- `main` contains reviewed, known-good releases.
- `develop` contains active work for isolated testing before promotion.
