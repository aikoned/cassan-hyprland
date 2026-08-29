local home = assert(os.getenv("HOME"), "HOME must be set")

-- Hyprlang imports environment variables as config variables. Defining the
-- XDG defaults here keeps hyprlock and every spawned application on the same
-- paths even when the variables were not exported by the display manager.
hl.env("XDG_CONFIG_HOME", os.getenv("XDG_CONFIG_HOME") or (home .. "/.config"))
hl.env("XDG_CACHE_HOME", os.getenv("XDG_CACHE_HOME") or (home .. "/.cache"))
hl.env("XDG_STATE_HOME", os.getenv("XDG_STATE_HOME") or (home .. "/.local/state"))

hl.env("XCURSOR_SIZE", "24")
hl.env("HYPRCURSOR_SIZE", "24")
hl.env("XDG_CURRENT_DESKTOP", "Hyprland")
hl.env("XDG_SESSION_TYPE", "wayland")
hl.env("XDG_SESSION_DESKTOP", "Hyprland")
hl.env("ELECTRON_OZONE_PLATFORM_HINT", "auto")
hl.env("ELECTRON_ENABLE_NATIVE_WINDOW_OPEN", "1")
hl.env("QT_QPA_PLATFORMTHEME", "qt6ct")
hl.env("QT_QPA_PLATFORM", "wayland;xcb")
