const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../spicetify/Extensions/hyprland-dots-theme.js"), "utf8",
);
const instanceKey = Symbol.for("hyprland-dots.spotify-theme");
const colorKeys = [
  "background", "panel", "panel_alt", "text", "text_secondary", "text_muted",
  "disabled", "border", "focus", "focus_alt", "blue", "purple", "green", "urgent",
];
const comfyMapping = {
  text: "text", subtext: "text_secondary", main: "background",
  "main-elevated": "panel", "main-transition": "panel", highlight: "panel_alt",
  "highlight-elevated": "panel_alt", sidebar: "panel", player: "background",
  card: "panel", shadow: "background", "selected-row": "text", button: "focus",
  "button-active": "focus_alt", "button-disabled": "disabled", "tab-active": "panel_alt",
  notification: "focus", "notification-error": "urgent", misc: "border",
  "play-button": "focus", "play-button-active": "focus_alt", "progress-fg": "green",
  "progress-bg": "panel_alt", heart: "urgent", "pagelink-active": "focus_alt",
  "radio-btn-active": "focus",
};

function palette(theme = "after-school", offset = 1) {
  return {
    schema: 1,
    theme,
    colors: Object.fromEntries(colorKeys.map((key, index) => [
      key, `#${((index + offset) * 0x0a0b0c).toString(16).padStart(6, "0")}`,
    ])),
  };
}

function realPalette(theme) {
  const contents = fs.readFileSync(path.join(__dirname, `../themes/${theme}.toml`), "utf8");
  const section = contents.split(/^\[colors\]\s*$/m)[1];
  assert.ok(section, `${theme} must have a colors section`);
  const colors = Object.fromEntries([...section.matchAll(/^\s*([a-z_]+)\s*=\s*"(#[0-9a-f]{6})"\s*$/gmi)]
    .map((match) => [match[1], match[2]]));
  assert.deepEqual(Object.keys(colors).sort(), [...colorKeys].sort());
  return { schema: 1, theme, colors };
}

function assertMappedPalette(app, mapping, data) {
  for (const element of [app.document.documentElement, app.document.body]) {
    for (const [name, key] of Object.entries(mapping)) {
      const color = data.colors[key].toLowerCase();
      const rgb = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16)).join(", ");
      assert.equal(element.style.getPropertyValue(`--spice-${name}`), color);
      assert.equal(element.style.getPropertyValue(`--spice-rgb-${name}`), rgb);
      assert.equal(element.style.getPropertyPriority(`--spice-${name}`), "important");
      assert.equal(element.style.getPropertyPriority(`--spice-rgb-${name}`), "important");
    }
  }
}

function style() {
  const values = new Map();
  const writes = [];
  return {
    values,
    writes,
    getPropertyValue: (key) => values.get(key)?.value || "",
    getPropertyPriority: (key) => values.get(key)?.priority || "",
    setProperty(key, value, priority = "") {
      values.set(key, { value, priority });
      writes.push([key, value, priority]);
    },
  };
}

function response(value, ok = true) {
  return { ok, text: async () => JSON.stringify(value) };
}

function harness(fetcher = async () => response(palette()), withBody = true) {
  const timers = new Map();
  let nextTimer = 0;
  const requests = [];
  const listeners = new Map();
  const document = {
    documentElement: { style: style() },
    body: withBody ? { style: style() } : null,
  };
  const window = {
    location: { href: "https://xpui.app.spotify.com/collection/tracks" },
    setTimeout(callback, delay) {
      const id = ++nextTimer;
      timers.set(id, { callback, delay });
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
    addEventListener(event, listener) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(listener);
    },
    removeEventListener: (event, listener) => listeners.get(event)?.delete(listener),
  };
  const context = vm.createContext({
    window,
    document,
    URL,
    AbortController,
    fetch(url, options) {
      requests.push({ url, options });
      return fetcher(url, options, requests.length);
    },
  });
  const run = () => vm.runInContext(source, context, { filename: "hyprland-dots-theme.js" });
  run();
  return {
    timers,
    requests,
    document,
    window,
    listeners,
    run,
    fireTimer(delay) {
      const entry = [...timers].find(([, timer]) => timer.delay === delay);
      assert.ok(entry, `Expected a ${delay}ms timer`);
      timers.delete(entry[0]);
      return entry[1].callback();
    },
    pagehide() {
      for (const callback of [...listeners.get("pagehide") || []]) callback();
    },
  };
}

const settle = () => new Promise((resolve) => setImmediate(resolve));

test("fetches only its same-origin asset without credentials or caching", async () => {
  const app = harness();
  await settle();
  assert.equal(app.requests.length, 1);
  const { url, options } = app.requests[0];
  assert.equal(url.href, "https://xpui.app.spotify.com/hyprland-dots/palette.json");
  assert.equal(options.cache, "no-store");
  assert.equal(options.credentials, "omit");
  assert.equal(options.mode, "same-origin");
  assert.equal(options.redirect, "error");
  assert.equal(options.signal.aborted, false);
  assert.deepEqual([...app.timers.values()].map((timer) => timer.delay), [2000]);
  app.pagehide();
});

test("maps every Comfy color on both root and body without altering layout styles", async () => {
  const data = palette();
  const app = harness(async () => response(data));
  app.document.body.style.setProperty("--comfy-font", "monospace");
  app.document.body.style.setProperty("display", "flex");
  await settle();
  const colorIni = fs.readFileSync(path.join(__dirname, "../spicetify/Themes/Comfy/color.ini"), "utf8");
  const comfyKeys = colorIni.split("[Comfy]")[1].split("[")[0].trim().split("\n")
    .map((line) => line.split("=")[0].trim());
  assert.deepEqual(Object.keys(comfyMapping).sort(), comfyKeys.sort());
  assertMappedPalette(app, comfyMapping, data);
  assert.equal(app.document.body.style.getPropertyValue("display"), "flex");
  assert.equal(app.document.body.style.getPropertyValue("--comfy-font"), "monospace");
  app.pagehide();
});

test("maps every text color and live-switches real palettes on root and body without layout changes", async () => {
  const textMapping = {
    accent: "focus", "accent-active": "focus_alt", "accent-inactive": "disabled",
    banner: "focus", "border-active": "focus", "border-inactive": "border", header: "text",
    highlight: "panel_alt", main: "background", notification: "focus",
    "notification-error": "urgent", subtext: "text_secondary", text: "text",
  };
  const colorIni = fs.readFileSync(path.join(__dirname, "../spicetify/Themes/text/color.ini"), "utf8");
  const textKeys = colorIni.split("[Spotify]")[1].split("[")[0].trim().split("\n")
    .map((line) => line.split("=")[0].trim());
  assert.deepEqual(Object.keys(textMapping).sort(), textKeys.sort());
  const first = realPalette("after-school");
  const second = realPalette("reze");
  assert.notEqual(first.colors.background, second.colors.background);
  assert.notEqual(first.colors.focus, second.colors.focus);
  const app = harness(async (_url, _options, count) => response(count === 1 ? first : second));
  for (const element of [app.document.documentElement, app.document.body]) {
    element.style.setProperty("display", "grid");
    element.style.setProperty("border-radius", "0px");
    element.style.setProperty("--font-family", "monospace");
  }
  await settle();
  const mapping = { ...comfyMapping, ...textMapping };
  assertMappedPalette(app, mapping, first);
  await app.fireTimer(2000);
  assertMappedPalette(app, mapping, second);
  for (const element of [app.document.documentElement, app.document.body]) {
    assert.equal(element.style.getPropertyValue("display"), "grid");
    assert.equal(element.style.getPropertyValue("border-radius"), "0px");
    assert.equal(element.style.getPropertyValue("--font-family"), "monospace");
    const writes = element.style.writes.length;
    await app.fireTimer(2000);
    assert.equal(element.style.writes.length, writes);
  }
  app.pagehide();
});

test("changes a running palette and skips redundant style writes", async () => {
  const first = palette();
  const second = palette("reze", 2);
  const app = harness(async (_url, _options, count) => response(count < 3 ? first : second));
  await settle();
  const initialWrites = app.document.body.style.writes.length;
  await app.fireTimer(2000);
  assert.equal(app.document.body.style.writes.length, initialWrites);
  await app.fireTimer(2000);
  assert.equal(app.document.body.style.getPropertyValue("--spice-main"), second.colors.background);
  assert.equal(app.document.body.style.writes.length, initialWrites * 2);
  app.pagehide();
});

test("accepts the renderer's uppercase hex colors and normalizes their CSS values", async () => {
  const data = palette("reze");
  data.colors = Object.fromEntries(Object.entries(data.colors).map(([key, value]) => [key, value.toUpperCase()]));
  const app = harness(async () => response(data));
  await settle();
  assert.equal(app.document.body.style.getPropertyValue("--spice-main"), data.colors.background.toLowerCase());
  assert.equal(app.document.body.style.getPropertyValue("--spice-rgb-main"), "10, 11, 12");
  app.pagehide();
});

test("reapplies managed variables when a body is replaced or its inline colors change", async () => {
  const data = palette();
  const app = harness(async () => response(data), false);
  await settle();
  assert.equal(app.document.documentElement.style.getPropertyValue("--spice-main"), data.colors.background);
  app.document.body = { style: style() };
  await app.fireTimer(2000);
  assert.equal(app.document.body.style.getPropertyValue("--spice-main"), data.colors.background);
  app.document.body.style.setProperty("--spice-main", "#ffffff", "important");
  await app.fireTimer(2000);
  assert.equal(app.document.body.style.getPropertyValue("--spice-main"), data.colors.background);
  app.pagehide();
});

test("rejects invalid schemas and CSS payloads without losing the last valid palette", async () => {
  const data = palette();
  const malformed = [
    null, [], {}, { ...data, schema: 2 }, { ...data, theme: "unmanaged" },
    { ...data, colors: [] }, { ...data, colors: null },
    { ...data, colors: { ...data.colors, background: "red" } },
    { ...data, colors: { ...data.colors, background: "#abc" } },
    { ...data, colors: { ...data.colors, background: "#112233; background:url(https://example.com)" } },
    { ...data, colors: { ...data.colors, background: 112233 } },
    { ...data, colors: { ...data.colors, background: "#112233\n" } },
    { ...data, colors: { ...data.colors, extra: "#ffffff" } },
    { ...data, colors: Object.fromEntries(Object.entries(data.colors).slice(1)) },
  ];
  const app = harness(async (_url, _options, count) => response(count === 1 ? data : malformed[count - 2]));
  await settle();
  const initialWrites = app.document.body.style.writes.length;
  for (const invalid of malformed) {
    await app.fireTimer(2000);
    assert.equal(app.document.body.style.writes.length, initialWrites, JSON.stringify(invalid));
  }
  assert.equal(app.document.body.style.getPropertyValue("--spice-main"), data.colors.background);
  app.pagehide();
});

test("missing, partial, oversized and failed reads are retried without style changes", async () => {
  const failures = [
    async () => response({}, false),
    async () => ({ ok: true, text: async () => "{\"schema\":" }),
    async () => ({ ok: true, text: async () => " ".repeat(4097) }),
    async () => { throw new Error("unavailable"); },
    async () => ({ ok: true, text: async () => { throw new Error("interrupted"); } }),
  ];
  const app = harness(async (_url, _options, count) => {
    if (count === 1 || count > failures.length + 1) return response(palette());
    return failures[count - 2]();
  });
  await settle();
  const initialWrites = app.document.body.style.writes.length;
  for (const failure of failures) {
    await app.fireTimer(2000);
    assert.equal(app.document.body.style.writes.length, initialWrites, failure.toString());
    assert.deepEqual([...app.timers.values()].map((timer) => timer.delay), [2000]);
  }
  await app.fireTimer(2000);
  assert.equal(app.document.body.style.writes.length, initialWrites);
  app.pagehide();
});

test("a slow request cannot overlap the next poll and is aborted after its deadline", async () => {
  let active = 0;
  let maxActive = 0;
  const app = harness((_url, { signal }) => new Promise((_resolve, reject) => {
    active += 1;
    maxActive = Math.max(active, maxActive);
    signal.addEventListener("abort", () => {
      active -= 1;
      reject(new Error("aborted"));
    });
  }));
  assert.deepEqual([...app.timers.values()].map((timer) => timer.delay), [3000]);
  assert.equal(app.requests.length, 1);
  app.fireTimer(3000);
  await settle();
  assert.equal(app.requests[0].options.signal.aborted, true);
  assert.equal(active, 0);
  assert.deepEqual([...app.timers.values()].map((timer) => timer.delay), [2000]);
  void app.fireTimer(2000);
  assert.equal(app.requests.length, 2);
  assert.equal(maxActive, 1);
  app.pagehide();
  await settle();
  assert.equal(active, 0);
  assert.equal(app.timers.size, 0);
});

test("unloading cancels requests and prevents a late response from updating styles", async () => {
  let finish;
  const app = harness(() => new Promise((resolve) => { finish = resolve; }));
  app.pagehide();
  assert.equal(app.requests[0].options.signal.aborted, true);
  assert.equal(app.timers.size, 0);
  finish(response(palette()));
  await settle();
  assert.equal(app.document.body.style.writes.length, 0);
  assert.equal(app.timers.size, 0);
  assert.equal(app.window[instanceKey], undefined);
});

test("ignores an expired request even if its response arrives after cancellation", async () => {
  let finish;
  const app = harness(() => new Promise((resolve) => { finish = resolve; }));
  app.fireTimer(3000);
  finish(response(palette()));
  await settle();
  assert.equal(app.document.body.style.writes.length, 0);
  assert.deepEqual([...app.timers.values()].map((timer) => timer.delay), [2000]);
  app.pagehide();
});

test("reinjection replaces the previous instance without duplicate polls", async () => {
  const app = harness();
  await settle();
  const first = app.window[instanceKey];
  app.run();
  await settle();
  assert.notEqual(app.window[instanceKey], first);
  assert.equal(app.requests.length, 2);
  assert.equal(app.listeners.get("pagehide").size, 1);
  assert.deepEqual([...app.timers.values()].map((timer) => timer.delay), [2000]);
  app.pagehide();
  assert.equal(app.timers.size, 0);
});
