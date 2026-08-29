-- Ignore maximize requests, matching the original rice's default behavior.
hl.window_rule({
  name = "suppress-maximize",
  match = { class = ".*" },
  suppress_event = "maximize",
})

-- Keep the Wofi launcher centered as a normal window.
hl.window_rule({
  name = "float-wofi",
  match = { class = "wofi" },
  float = true,
  center = true,
})
