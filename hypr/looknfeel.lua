local theme = require("theme")

hl.config({
  general = {
    gaps_in = 5,
    gaps_out = 10,
    border_size = 2,
    col = {
      active_border = {
        colors = { theme.focus, theme.focus_alt },
        angle = 45,
      },
      inactive_border = theme.background_alt,
    },
    resize_on_border = true,
    allow_tearing = false,
    layout = "dwindle",
  },

  decoration = {
    rounding = 0,
    rounding_power = 2,
    active_opacity = 1.0,
    inactive_opacity = 1.0,
    shadow = {
      enabled = true,
      range = 4,
      render_power = 3,
      color = "rgba(1F1D19ee)",
    },
    blur = {
      enabled = true,
      size = 8,
      passes = 4,
      contrast = 1.0,
      brightness = 1.0,
      noise = 0.015,
      vibrancy = 0.2,
      popups = true,
    },
  },

  animations = { enabled = true },
  dwindle = { preserve_split = true },
  master = { new_status = "master" },
  misc = {
    force_default_wallpaper = -1,
    disable_hyprland_logo = false,
  },
})
