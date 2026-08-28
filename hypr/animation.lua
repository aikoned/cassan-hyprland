local theme = require("theme")

hl.curve("cassanSmooth", {
  type = "bezier",
  points = { { 0.25, 0.10 }, { 0.25, 1.00 } },
})

-- Short, non-looping transitions preserve the polished feel without keeping
-- the compositor busy when the desktop is idle.
hl.animation({ leaf = "global", enabled = true, speed = theme.animation.normal_ds, bezier = "cassanSmooth" })
hl.animation({ leaf = "windowsIn", enabled = true, speed = theme.animation.normal_ds, bezier = "cassanSmooth", style = "popin 98%" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = theme.animation.fast_ds, bezier = "cassanSmooth", style = "popin 98%" })
hl.animation({ leaf = "layersIn", enabled = true, speed = theme.animation.normal_ds, bezier = "cassanSmooth", style = "fade" })
hl.animation({ leaf = "layersOut", enabled = true, speed = theme.animation.fast_ds, bezier = "cassanSmooth", style = "fade" })
hl.animation({ leaf = "fadeIn", enabled = true, speed = theme.animation.normal_ds, bezier = "cassanSmooth" })
hl.animation({ leaf = "fadeOut", enabled = true, speed = theme.animation.fast_ds, bezier = "cassanSmooth" })
hl.animation({ leaf = "workspaces", enabled = true, speed = theme.animation.slow_ds, bezier = "cassanSmooth", style = "fade" })
hl.animation({ leaf = "border", enabled = false })
