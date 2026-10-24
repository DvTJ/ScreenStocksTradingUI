/* Test data for opening the UI in a normal browser (index.html?mock) - never loaded by the app. */
"use strict";

(() => {
  const start = Date.now();
  const texts = {
    "tab.market": "Market", "tab.compare": "Compare", "tab.portfolio": "Portfolio", "tab.dividends": "Dividends",
    "tab.journal": "Journal", "tab.stats": "Statistics", "tab.news": "News", "tab.automation": "Automation",
    "common.net_worth": "Net worth", "common.cash": "Cash", "common.level": "Level", "common.ready": "ready",
    "hdr.buy_cd": "Buy cooldown", "hdr.short_cd": "Short cooldown", "settings.title": "Settings", "settings.save": "Save",
    "setup.cancel": "Cancel", "setup.restart": "Restart now?", "update.open_page": "View release",
    "update.install": "Install now", "update.later": "Later", "update.title": "Update",
    "update.banner": "New version {version} available (installed: {current})",
    "update.confirm": "Download and install version {version}?", "update.downloading": "Downloading update …",
    "web.placeholder": "Coming in phase {phase} of the new interface.", "web.paused": "PAUSED",
    "web.no_market": "NO DATA", "web.source": "Source", "web.game": "game", "web.installing": "Starting installer …",
    "web.settings_intro": "Choose the interface:", "web.ui_web": "New interface", "web.ui_web_desc": "Web based",
    "web.ui_classic": "Classic interface", "web.ui_classic_desc": "Tkinter", "web.settings_more": "More settings in phase 5.",
    "web.restart_now": "Restart",
  };
  // market tab: one stock with a smooth fake price per second, a trade marker, a price line and an event
  const off = -new Date().getTimezoneOffset() * 60;
  const price = (s) => 100 + 5 * Math.sin(s / 300) + Math.sin(s / 17);
  const points = (fromS, toS) => {
    const out = [];
    for (let s = Math.floor(fromS) + 1; s <= toS; s++) out.push({ time: s + off, value: price(s) });
    return out;
  };
  const nowS = () => Math.floor(Date.now() / 1000);
  const overlays = () => ({
    markers: [{ time: nowS() - 600 + off, kind: "buy", price: price(nowS() - 600), letter: "B", text: "Buy" }],
    news: [{ time: nowS() - 900 + off, kind: "high", price: price(nowS() - 900) }],
    lines: [{ price: 99, kind: "avg_buy", title: "Avg buy" }, { price: 108, kind: "event", title: "Event" }],
    events: [{ direction: "up", target: 108, at: start + 30 * 60_000 }],
    offset: off,
  });
  window.pywebview = {
    api: {
      init: async () => ({ lang: "en", texts, version: "2.0.0-dev", colors: {}, frozen: false, ui: "web" }),
      tick: async () => ({
        live: true, market_found: true, server_now: Date.now(), net: 21.3e9, cash: 14.7e9, level: 10, sequence: 1,
        buy_cd: 42 - ((Date.now() - start) / 1000) % 60, short_cd: -1, engine: "active", game_version: "1.0.12",
        read_errors: 0, last_error: "", source: "C:\\…\\mods\\export", db: "screenstocks.db",
        counts: { prices: 123456, snapshots: 4567, news: 321 },
        update: { version: "2.0.1", page: "https://github.com/", installer: true, state: "available" },
      }),
      set_ui: async () => {}, restart: async () => {}, open_url: async () => {}, install_update: async () => {},
      log_client_error: async () => {},
      market: async () => ({
        rows: [{ id: "AAA", name: "Alpha", color: "#58a6ff", price: price(nowS()), d1: 0.1, d5: 0.4, d15: -0.2, d60: 1.2,
                 spark: [99, 100, 101, 100.5], base: 100, cap: 200, rate: 0.001, avail: 1e6, maxvol: 5e4, unlocked: true,
                 owned: 1000, avg: 99, shorted: 0, avg_short: 0, pl: 1000 * (price(nowS()) - 99), div: 120 }],
        factor: 1, factor_n: 0, live: true, trade: null, log: [],
      }),
      series: async () => ({ data: points(nowS() - 3600, nowS()), ...overlays(), last_ms: nowS() * 1000, bucket_ms: 1 }),
      series_overlays: async () => overlays(),
      updates: async (_sid, sinceMs) => ({ data: points(sinceMs / 1000, nowS()), last_ms: Math.max(sinceMs, nowS() * 1000) }),
      series_detail: async () => ({ data: [], bucket_ms: 1 }),
    },
  };
})();
