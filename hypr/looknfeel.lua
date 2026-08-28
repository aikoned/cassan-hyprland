local theme = require("theme")

hl.config({
  general = {
    gaps_in = theme.geometry.gaps_in,
    gaps_out = theme.geometry.gaps_out,
    border_size = theme.geometry.border,
    col = {
      active_border = theme.roles.focus,
      inactive_border = theme.roles.focus_inactive,
    },
    resize_on_border = true,
    allow_tearing = false,
    layout = "dwindle",
  },

  decoration = {
    rounding = theme.geometry.rounding,
    rounding_power = 2,
    active_opacity = theme.geometry.opacity,
    inactive_opacity = theme.geometry.opacity,
    shadow = {
      enabled = theme.geometry.shadow_enabled,
      range = theme.geometry.shadow_range,
      render_power = 3,
      color = theme.geometry.shadow_color,
    },
    blur = {
      enabled = theme.geometry.blur_enabled,
    },
  },

  animations = {
    enabled = true,
  },

  dwindle = {
    preserve_split = true,
  },

  misc = {
    force_default_wallpaper = 0,
    disable_hyprland_logo = true,
  },

  debug = {
    vfr = true,
  },
})
