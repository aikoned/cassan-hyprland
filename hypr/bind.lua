local mod = "SUPER"
local terminal = "kitty"
local file_manager = "thunar"
local menu = "wofi --show drun"

hl.bind(mod .. " + SHIFT + Q", hl.dsp.exec_cmd(terminal))
hl.bind(mod .. " + Q", hl.dsp.exec_cmd([[kitty -o confirm_os_window_close=0 -e sh -c "fastfetch; exec $SHELL"]]))
hl.bind(mod .. " + C", hl.dsp.window.close())
hl.bind(mod .. " + M", hl.dsp.exec_cmd("hyprshutdown"))
hl.bind(mod .. " + E", hl.dsp.exec_cmd(file_manager))
hl.bind(mod .. " + SHIFT + E", hl.dsp.exec_cmd("kitty yazi"))
hl.bind(mod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mod .. " + R", hl.dsp.exec_cmd(menu))
hl.bind(mod .. " + P", hl.dsp.window.pseudo())
hl.bind(mod .. " + D", hl.dsp.layout("togglesplit"))
hl.bind(mod .. " + X", hl.dsp.exec_cmd("hyprlock"))
hl.bind(mod .. " + SHIFT + X", hl.dsp.exec_cmd("wlogout"))
hl.bind(mod .. " + T", hl.dsp.exec_cmd([["${XDG_CONFIG_HOME:-$HOME/.config}/waybar/scripts/theme-switcher.sh" next]]))
hl.bind(mod .. " + SHIFT + T", hl.dsp.exec_cmd([["${XDG_CONFIG_HOME:-$HOME/.config}/waybar/scripts/theme-switcher.sh" list]]))
hl.bind(mod .. " + SHIFT + R", hl.dsp.exec_cmd("pkill waybar; waybar"))
hl.bind(mod .. " + Z", hl.dsp.exec_cmd("swaync-client --toggle-panel"))

local directions = {
  H = "l",
  J = "d",
  K = "u",
  L = "r",
}

for key, direction in pairs(directions) do
  hl.bind(mod .. " + " .. key, hl.dsp.focus({ direction = direction }))
  hl.bind(mod .. " + SHIFT + " .. key, hl.dsp.window.swap({ direction = direction }))
end

for workspace = 1, 6 do
  hl.bind(mod .. " + " .. workspace, hl.dsp.focus({ workspace = workspace }))
  hl.bind(mod .. " + SHIFT + " .. workspace, hl.dsp.window.move({ workspace = workspace, follow = false }))
end

hl.bind(mod .. " + S", hl.dsp.workspace.toggle_special("magic"))
hl.bind(mod .. " + SHIFT + S", hl.dsp.window.move({ workspace = "special:magic" }))

hl.bind(mod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mod .. " + mouse_up", hl.dsp.focus({ workspace = "e-1" }))
hl.bind(mod .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind(mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })

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
