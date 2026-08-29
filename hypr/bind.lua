local mod = "SUPER"

local terminal = "kitty"
local launcher = "wofi --show drun --allow-images"
local file_manager = "kitty --class cassan-yazi yazi"
local task_manager = "kitty --class cassan-btop btop"
local system_info = "kitty --class cassan-fastfetch fastfetch"
local visualizer = "kitty --class cassan-cava cava"
local browser = "firefox"
local chat = "discord"
local music = "spotify-launcher"

-- Core applications and window state.
hl.bind(mod .. " + RETURN", hl.dsp.exec_cmd(terminal))
hl.bind(mod .. " + SPACE", hl.dsp.exec_cmd(launcher))
hl.bind(mod .. " + E", hl.dsp.exec_cmd(file_manager))
hl.bind(mod .. " + CTRL + ESCAPE", hl.dsp.exec_cmd(task_manager))
hl.bind(mod .. " + I", hl.dsp.exec_cmd(system_info))
hl.bind(mod .. " + C", hl.dsp.exec_cmd(visualizer))
hl.bind(mod .. " + B", hl.dsp.exec_cmd(browser))
hl.bind(mod .. " + D", hl.dsp.exec_cmd(chat))
hl.bind(mod .. " + M", hl.dsp.exec_cmd(music))
hl.bind(mod .. " + Q", hl.dsp.window.close())
hl.bind(mod .. " + F", hl.dsp.window.fullscreen({ mode = "fullscreen", action = "toggle" }))
hl.bind(mod .. " + V", hl.dsp.window.float({ action = "toggle" }))
hl.bind(mod .. " + P", hl.dsp.window.pseudo())
hl.bind(mod .. " + T", hl.dsp.layout("togglesplit"))
hl.bind(mod .. " + N", hl.dsp.exec_cmd("swaync-client -t -sw"))
hl.bind(mod .. " + ESCAPE", hl.dsp.exec_cmd("hyprlock"))
hl.bind(mod .. " + SHIFT + R", hl.dsp.exec_cmd("hyprctl reload"))

-- Screenshot an interactively selected region and open it in Swappy.
hl.bind(mod .. " + SHIFT + S", hl.dsp.exec_cmd([[grim -g "$(slurp)" - | swappy -f -]]))

local directions = {
  H = { focus = "left", resize_x = -20, resize_y = 0 },
  J = { focus = "down", resize_x = 0, resize_y = 20 },
  K = { focus = "up", resize_x = 0, resize_y = -20 },
  L = { focus = "right", resize_x = 20, resize_y = 0 },
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

-- Six persistent workspaces match the compact numbered Waybar island.
for workspace = 1, 6 do
  hl.bind(mod .. " + " .. workspace, hl.dsp.focus({ workspace = workspace }))
  hl.bind(mod .. " + SHIFT + " .. workspace, hl.dsp.window.move({ workspace = workspace }))
end

-- Scratchpad for temporary windows.
hl.bind(mod .. " + S", hl.dsp.workspace.toggle_special("scratch"))
hl.bind(mod .. " + CTRL + S", hl.dsp.window.move({ workspace = "special:scratch" }))

-- Mouse remains available when it is the more natural tool.
hl.bind(mod .. " + mouse:272", hl.dsp.window.drag(), { mouse = true })
hl.bind(mod .. " + mouse:273", hl.dsp.window.resize(), { mouse = true })
hl.bind(mod .. " + mouse_down", hl.dsp.focus({ workspace = "e+1" }))
hl.bind(mod .. " + mouse_up", hl.dsp.focus({ workspace = "e-1" }))

-- Laptop media keys work even while the session is locked.
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
