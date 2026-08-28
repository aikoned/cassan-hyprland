-- Keep global rules conservative. Application-specific integration should be
-- added only after confirming each application's live class with hyprctl.
hl.window_rule({
  name = "float-modal-dialogs",
  match = { modal = true },
  float = true,
  center = true,
})
