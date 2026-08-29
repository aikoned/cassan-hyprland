-- Keep global rules conservative. Application-specific integration should be
-- added only after confirming each application's live class with hyprctl.
hl.window_rule({
  name = "float-modal-dialogs",
  match = { modal = true },
  float = true,
  center = true,
})

-- A normal Wofi window can lose focus when the user clicks elsewhere, allowing
-- close_on_focus_loss to dismiss the launcher instead of trapping the click in
-- a full-screen layer-shell surface.
hl.window_rule({
  name = "float-cassan-launcher",
  match = { class = "wofi" },
  float = true,
  center = true,
  opacity = "1.0 override 1.0 override",
})

-- Resource monitors need substantially more room than a half-width terminal.
-- Keep them useful even if a second instance is launched accidentally.
hl.window_rule({
  name = "float-cassan-task-manager",
  match = { class = "cassan-btop" },
  float = true,
  center = true,
  size = { "(monitor_w*0.82)", "(monitor_h*0.80)" },
})
