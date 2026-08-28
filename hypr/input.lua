hl.config({
  input = {
    kb_layout = "us",
    kb_variant = "",
    kb_model = "",
    kb_options = "",
    kb_rules = "",
    follow_mouse = 1,
    sensitivity = 0,
    touchpad = {
      disable_while_typing = true,
      natural_scroll = false,
      tap_to_click = true,
      tap_and_drag = true,
    },
  },
})

-- A restrained laptop gesture that mirrors the numbered workspace bindings.
hl.gesture({
  fingers = 3,
  direction = "horizontal",
  action = "workspace",
})
