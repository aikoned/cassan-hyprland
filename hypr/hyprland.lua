-- Cassan Hyprland entry point.
--
-- Keep concerns in separate modules so theme, hardware, and behavior can evolve
-- independently. Modules execute in this order when required.

require("environment")
require("monitor")
require("looknfeel")
require("input")
require("animation")
require("rules")
require("startup")
require("bind")
