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
    },
  };
})();
