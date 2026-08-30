-- Portable fallback. Replace this with the output from `hyprctl monitors all`
-- if you want fixed positions, refresh rates, or per-monitor scaling.
hl.monitor({
  output = "",
  mode = "preferred",
  position = "auto",
  scale = 1,
})
