local mod = "SUPER"

local config_home = [["${XDG_CONFIG_HOME:-$HOME/.config}]]
local launcher = config_home .. [[/wofi/launch.sh" --show drun --allow-images]]
local task_manager = "kitty --class cassan-btop -e " .. config_home .. [[/btop/launch.sh"]]

hl.bind(mod .. " + RETURN", hl.dsp.exec_cmd("kitty"))
hl.bind(mod .. " + SPACE", hl.dsp.exec_cmd(launcher))
hl.bind(mod .. " + E", hl.dsp.exec_cmd("kitty --class cassan-yazi -e yazi"))
hl.bind(mod .. " + CTRL + ESCAPE", hl.dsp.exec_cmd(task_manager))
hl.bind(mod .. " + I", hl.dsp.exec_cmd("kitty --hold --class cassan-fastfetch -e fastfetch"))
hl.bind(mod .. " + C", hl.dsp.exec_cmd("kitty --class cassan-cava -e cava"))
hl.bind(mod .. " + B", hl.dsp.exec_cmd("firefox"))
hl.bind(mod .. " + D", hl.dsp.exec_cmd("vesktop"))
hl.bind(mod .. " + M", hl.dsp.exec_cmd("spotify-launcher"))
hl.bind(mod .. " + Q", hl.dsp.window.close())
hl.bind(mod .. " + F", hl.dsp.window.fullscreen({ mode = "fullscreen", action = "toggle" }))
hl.bind(mod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mod .. " + P", hl.dsp.window.pseudo())
hl.bind(mod .. " + T", hl.dsp.layout("togglesplit"))
hl.bind(mod .. " + N", hl.dsp.exec_cmd("swaync-client --toggle-panel --skip-wait"))
hl.bind(mod .. " + ESCAPE", hl.dsp.exec_cmd("hyprlock"))
hl.bind(mod .. " + SHIFT + R", hl.dsp.exec_cmd("hyprctl reload"))
hl.bind(mod .. " + SHIFT + S", hl.dsp.exec_cmd([[grim -g "$(slurp)" - | swappy -f -]]))

hl.bind(mod .. " + W", hl.dsp.exec_cmd(config_home .. [[/waybar/scripts/theme-switcher.sh" next]]))
hl.bind(mod .. " + SHIFT + W", hl.dsp.exec_cmd(config_home .. [[/waybar/scripts/theme-switcher.sh" list]]))
hl.bind(mod .. " + CTRL + W", hl.dsp.exec_cmd(config_home .. [[/waybar/scripts/theme-switcher.sh" auto-toggle]]))
hl.bind(mod .. " + SHIFT + E", hl.dsp.exec_cmd("thunar"))
hl.bind(mod .. " + SHIFT + X", hl.dsp.exec_cmd(config_home .. [[/wlogout/launch.sh"]]))
hl.bind(mod .. " + CTRL + R", hl.dsp.exec_cmd(config_home .. [[/waybar/start.sh" --replace]]))

local directions = {
  H = { focus = "l", resize_x = -20, resize_y = 0 },
  J = { focus = "d", resize_x = 0, resize_y = 20 },
  K = { focus = "u", resize_x = 0, resize_y = -20 },
  L = { focus = "r", resize_x = 20, resize_y = 0 },
}

for key, direction in pairs(directions) do
  hl.bind(mod .. " + " .. key, hl.dsp.focus({ direction = direction.focus }))
  hl.bind(mod .. " + SHIFT + " .. key, hl.dsp.window.swap({ direction = direction.focus }))
  hl.bind(mod .. " + CTRL + " .. key, hl.dsp.window.resize({
    x = direction.resize_x,
    y = direction.resize_y,
    relative = true,
  }))
end

for workspace = 1, 6 do
  hl.bind(mod .. " + " .. workspace, hl.dsp.focus({ workspace = workspace }))
  hl.bind(mod .. " + SHIFT + " .. workspace, hl.dsp.window.move({ workspace = workspace }))
end

hl.bind(mod .. " + S", hl.dsp.workspace.toggle_special("scratch"))
hl.bind(mod .. " + CTRL + S", hl.dsp.window.move({ workspace = "special:scratch" }))

hl.bind(mod .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind(mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })
hl.bind(mod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mod .. " + mouse_up", hl.dsp.focus({ workspace = "e-1" }))

hl.bind(mod .. " + Print", hl.dsp.exec_cmd([[grim "$HOME/Pictures/Screenshots/screenshot-$(date +%s).png"]]))
hl.bind(mod .. " + SHIFT + Print", hl.dsp.exec_cmd([[grim -g "$(slurp)" - | swappy -f -]]))

hl.bind("XF86AudioRaiseVolume", hl.dsp.exec_cmd("wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"), { locked = true, repeating = true })
hl.bind("XF86AudioLowerVolume", hl.dsp.exec_cmd("wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"), { locked = true, repeating = true })
hl.bind("XF86AudioMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"), { locked = true, repeating = true })
hl.bind("XF86AudioMicMute", hl.dsp.exec_cmd("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"), { locked = true, repeating = true })
hl.bind("XF86MonBrightnessUp", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%+"), { locked = true, repeating = true })
hl.bind("XF86MonBrightnessDown", hl.dsp.exec_cmd("brightnessctl -e4 -n2 set 5%-"), { locked = true, repeating = true })
hl.bind("XF86AudioNext", hl.dsp.exec_cmd("playerctl next"), { locked = true })
hl.bind("XF86AudioPause", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPlay", hl.dsp.exec_cmd("playerctl play-pause"), { locked = true })
hl.bind("XF86AudioPrev", hl.dsp.exec_cmd("playerctl previous"), { locked = true })
