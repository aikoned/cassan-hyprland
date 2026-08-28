-- Cassan owns these processes here. Do not also enable duplicate user services.
hl.on("hyprland.start", function()
  hl.exec_cmd("hyprpaper")
  hl.exec_cmd("waybar")
  hl.exec_cmd("swaync")
end)
