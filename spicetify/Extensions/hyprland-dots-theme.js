(() => {
  "use strict";

  const instanceKey = Symbol.for("hyprland-dots.spotify-theme");
  const pollInterval = 2000;
  const requestTimeout = 3000;
  const paletteUrl = new URL("/hyprland-dots/palette.json", window.location.href);
  const colorKeys = [
    "background", "panel", "panel_alt", "text", "text_secondary", "text_muted",
    "disabled", "border", "focus", "focus_alt", "blue", "purple", "green", "urgent",
  ];
  const spiceColors = {
    accent: "focus",
    "accent-active": "focus_alt",
    "accent-inactive": "disabled",
    banner: "focus",
    "border-active": "focus",
    "border-inactive": "border",
    header: "text",
    text: "text",
    subtext: "text_secondary",
    main: "background",
    "main-elevated": "panel",
    "main-transition": "panel",
    highlight: "panel_alt",
    "highlight-elevated": "panel_alt",
    sidebar: "panel",
    player: "background",
    card: "panel",
    shadow: "background",
    "selected-row": "text",
    button: "focus",
    "button-active": "focus_alt",
    "button-disabled": "disabled",
    "tab-active": "panel_alt",
    notification: "focus",
    "notification-error": "urgent",
    misc: "border",
    "play-button": "focus",
    "play-button-active": "focus_alt",
    "progress-fg": "green",
    "progress-bg": "panel_alt",
    heart: "urgent",
    "pagelink-active": "focus_alt",
    "radio-btn-active": "focus",
  };

  function parsePalette(payload) {
    if (!payload || payload.schema !== 1 || !["after-school", "reze"].includes(payload.theme)) {
      return null;
    }
    const colors = payload.colors;
    if (!colors || Array.isArray(colors) || typeof colors !== "object") return null;
    if (Object.keys(colors).length !== colorKeys.length) return null;
    if (!colorKeys.every((key) => Object.hasOwn(colors, key)
        && typeof colors[key] === "string" && /^#[0-9a-f]{6}$/i.test(colors[key]))) {
      return null;
    }
    return Object.entries(spiceColors).flatMap(([name, source]) => {
      const color = colors[source].toLowerCase();
      const rgb = [1, 3, 5].map((offset) => parseInt(color.slice(offset, offset + 2), 16));
      return [[`--spice-${name}`, color], [`--spice-rgb-${name}`, rgb.join(", ")]];
    });
  }

  function applyPalette(variables) {
    if (!variables) return;
    // Comfy defines some colors on body, where inherited :root colors cannot override them.
    for (const element of [document.documentElement, document.body]) {
      if (!element) continue;
      for (const [name, value] of variables) {
        if (element.style.getPropertyValue(name) !== value
            || element.style.getPropertyPriority(name) !== "important") {
          element.style.setProperty(name, value, "important");
        }
      }
    }
  }

  let stopped = false;
  let pollTimer = null;
  let timeoutTimer = null;
  let activeRequest = null;
  let lastPalette = null;

  async function poll() {
    if (stopped) return;
    const controller = new AbortController();
    activeRequest = controller;
    const timeout = window.setTimeout(() => controller.abort(), requestTimeout);
    timeoutTimer = timeout;
    try {
      const response = await fetch(paletteUrl, {
        cache: "no-store",
        credentials: "omit",
        mode: "same-origin",
        redirect: "error",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("Palette is not available");
      const content = await response.text();
      if (content.length > 4096) throw new Error("Palette is too large");
      const variables = parsePalette(JSON.parse(content));
      if (variables && !stopped && !controller.signal.aborted) lastPalette = variables;
    } catch {
      // Keep the last valid palette while Spotify or its generated assets are updating.
    } finally {
      window.clearTimeout(timeout);
      if (timeoutTimer === timeout) timeoutTimer = null;
      if (activeRequest === controller) activeRequest = null;
      if (!stopped) {
        applyPalette(lastPalette);
        pollTimer = window.setTimeout(poll, pollInterval);
      }
    }
  }

  function stop() {
    if (stopped) return;
    stopped = true;
    window.clearTimeout(pollTimer);
    window.clearTimeout(timeoutTimer);
    activeRequest?.abort();
    window.removeEventListener("pagehide", stop);
    if (window[instanceKey]?.stop === stop) delete window[instanceKey];
  }

  window[instanceKey]?.stop();
  window[instanceKey] = { stop };
  window.addEventListener("pagehide", stop, { once: true });
  void poll();
})();
