/* App shell: header, tab navigation, update notice, settings, status bar, refresh loop. */
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const { t, fmt } = SS;

  // Tabs in the order of the classic interface. Tab modules register themselves via SS.registerTab;
  // tabs not built yet show a placeholder with the phase they arrive in.
  const TAB_ORDER = [
    ["market", "tab.market", 1], ["compare", "tab.compare", 4], ["portfolio", "tab.portfolio", 3],
    ["dividends", "tab.dividends", 3], ["journal", "tab.journal", 3], ["stats", "tab.stats", 4],
    ["news", "tab.news", 4], ["automation", "tab.automation", 2],
  ];
  const modules = SS.modules;   // filled by the tab scripts via SS.registerTab (core.js)
  let active = "market";
  let lastTick = null;

  function buildTabs() {
    const nav = $("tabs"), views = $("views");
    for (const [id, key, phase] of TAB_ORDER) {
      const b = document.createElement("button");
      b.dataset.tab = id;
      b.setAttribute("role", "tab");
      b.textContent = t(key).trim();
      b.onclick = () => activate(id);
      nav.appendChild(b);
      const view = document.createElement("section");
      view.className = "view";
      view.id = `view-${id}`;
      views.appendChild(view);
      if (modules[id]) modules[id].mount(view);
      else {
        view.innerHTML = `<div class="placeholder"><div><h2>${SS.esc(t(key).trim())}</h2>
          <div>${SS.esc(t("web.placeholder", { phase }))}</div></div></div>`;
      }
    }
    activate(active);
  }

  function activate(id) {
    if (modules[active] && modules[active].hide && active !== id) modules[active].hide();
    active = id;
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === id));
    document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${id}`));
    const m = modules[id];
    if (m && m.show) m.show();
    if (m && m.refresh && lastTick) m.refresh(lastTick);
  }

  // ---------------------------------------------------------------- header
  function renderHeader(d) {
    const state = $("kpi-state");
    state.classList.toggle("live", !!d.live);
    $("state-text").textContent = d.live ? "LIVE" : (d.market_found ? t("web.paused") : t("web.no_market"));
    $("kpi-net").textContent = fmt.big(d.net);
    $("kpi-cash").textContent = fmt.big(d.cash);
    $("kpi-level").textContent = d.level ?? "–";
    for (const [id, cd] of [["kpi-buy", d.buy_cd], ["kpi-short", d.short_cd]]) {
      const el = $(id);
      if (cd === null || cd === undefined) { el.textContent = "–"; el.className = ""; continue; }
      el.textContent = cd <= 0 ? t("common.ready") : fmt.duration(cd);
      el.className = cd <= 0 ? "ready" : "";
    }
  }

  function renderStatus(d) {
    const c = d.counts || {};
    const parts = [
      `${t("web.source")}: ${d.source}`,
      `DB: ${d.db} – ${fmt.num(c.prices, 0)} / ${fmt.num(c.snapshots, 0)} / ${fmt.num(c.news, 0)}`,
      `${t("web.game")} ${d.game_version || "–"}`,
      `v${SS.info.version}`,
    ];
    $("statusbar").innerHTML = parts.map((p) => `<span>${SS.esc(p)}</span>`).join("")
      + (d.read_errors ? `<span class="err">${SS.esc(t("status.read_errors", { n: d.read_errors, error: d.last_error }).replace(/^[\s|]+/, ""))}</span>` : "");
  }

  // ---------------------------------------------------------------- updates
  let updateDismissed = null;
  function renderUpdate(u) {
    const bar = $("update-bar");
    if (!u || !u.version || updateDismissed === u.version) { bar.classList.add("hidden"); return; }
    bar.classList.remove("hidden");
    const install = $("update-install");
    install.classList.toggle("hidden", !u.installer);
    if (u.state === "downloading") {
      $("update-text").textContent = `${t("update.downloading")} ${u.progress || 0} %`;
      install.disabled = true;
    } else if (u.state === "installing") {
      $("update-text").textContent = t("web.installing");
      install.disabled = true;
    } else if (u.state === "failed") {
      $("update-text").textContent = t("update.failed", { error: u.error || "" });
      install.disabled = false;
    } else {
      $("update-text").textContent = t("update.banner", { version: u.version, current: SS.info.version });
      install.disabled = false;
    }
  }

  function bindUpdate() {
    $("update-page").onclick = () => lastTick && lastTick.update && SS.call("open_url", lastTick.update.page);
    $("update-later").onclick = () => { updateDismissed = lastTick && lastTick.update && lastTick.update.version; $("update-bar").classList.add("hidden"); };
    $("update-install").onclick = async () => {
      const u = lastTick && lastTick.update;
      if (!u) return;
      if (await SS.confirm(t("update.title"), t("update.confirm", { version: u.version }), t("update.install"))) {
        SS.call("install_update");
      }
    };
  }

  // ---------------------------------------------------------------- settings (phase 0: interface choice)
  async function openSettings() {
    const body = document.createElement("div");
    body.innerHTML = `
      <div>${SS.esc(t("web.settings_intro"))}</div>
      <div class="choice">
        <label><input type="radio" name="ui" value="web"> <b>${SS.esc(t("web.ui_web"))}</b><small>${SS.esc(t("web.ui_web_desc"))}</small></label>
        <label><input type="radio" name="ui" value="classic"> <b>${SS.esc(t("web.ui_classic"))}</b><small>${SS.esc(t("web.ui_classic_desc"))}</small></label>
      </div>
      <div class="muted">${SS.esc(t("web.settings_more"))}</div>`;
    body.querySelector(`input[value="${SS.info.ui || "web"}"]`).checked = true;
    const ok = await SS.dialog({
      title: t("settings.title"), body,
      buttons: [{ label: t("setup.cancel"), value: false, kind: "ghost" }, { label: t("settings.save"), value: true, kind: "primary" }],
    });
    if (!ok) return;
    const mode = body.querySelector("input[name=ui]:checked").value;
    if (mode === SS.info.ui) return;
    await SS.call("set_ui", mode);
    SS.info.ui = mode;
    if (await SS.confirm(t("settings.title"), t("setup.restart"), t("web.restart_now"))) SS.call("restart");
  }

  // ---------------------------------------------------------------- loop
  async function tick() {
    try {
      const d = await SS.call("tick");
      lastTick = d;
      renderHeader(d);
      renderStatus(d);
      renderUpdate(d.update);
      const m = modules[active];
      if (m && m.refresh) await m.refresh(d);
    } catch (err) {
      console.error(err);
    }
    setTimeout(tick, 1000);
  }

  SS.ready().then(async () => {
    const info = await SS.call("init");
    SS.info = info;
    SS.lang = info.lang === "de" ? "de" : "en";
    SS.texts = info.texts || {};
    document.documentElement.lang = SS.lang;
    SS.applyTexts();
    $("btn-settings").title = t("settings.title");
    $("btn-settings").onclick = openSettings;
    bindUpdate();
    buildTabs();
    tick();
  });
})();
