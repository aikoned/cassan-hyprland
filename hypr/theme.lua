local fallback = {
  background = "rgb(2C2A24)",
  background_alt = "rgb(3A372F)",
  text = "rgb(DDD5C4)",
  border = "rgb(A0907A)",
  focus = "rgb(D08B57)",
  focus_alt = "rgb(BFAA80)",
  blue = "rgb(7699A3)",
  purple = "rgb(8D7AAE)",
  green = "rgb(78997A)",
  urgent = "rgb(B05A5A)",
}

local cache_home = os.getenv("XDG_CACHE_HOME")
if not cache_home then
  local home = os.getenv("HOME")
  if home then
    cache_home = home .. "/.cache"
  end
end

if cache_home then
  local loader = loadfile(cache_home .. "/hyprland-dots/active-theme/hypr.lua")
  if loader then
    local ok, theme = pcall(loader)
    if ok and type(theme) == "table" then
      return theme
    end
  end
end

return fallback
