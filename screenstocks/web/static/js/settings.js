/* Settings dialog: General, Colours, Data, Extension (Windows), Updates, About. */
"use strict";

(() => {
  const { t, fmt, esc } = SS;
  const ALL_PAGES = [["general", "settings.tab_general"], ["colors", "settings.tab_colors"], ["data", "settings.tab_data"],
                     ["extension", "settings.tab_extension"], ["updates", "settings.tab_updates"], ["about", "settings.tab_about"]];
  const LOGO = `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="1.5" y="11" width="3.6" height="8" rx="1" fill="#f85149"/>
    <rect x="7.2" y="6" width="3.6" height="11" rx="1" fill="#3fb950"/><rect x="12.9" y="9" width="3.6" height="6" rx="1" fill="#f85149"/>
    <rect x="18.6" y="3" width="3.6" height="10" rx="1" fill="#3fb950"/></svg>`;
  let open = false;

  SS.openSettings = async (page = "general") => {
    if (open) return;
    open = true;
    const [cfg, ext] = await Promise.all([SS.call("settings_get"), SS.call("extension")]);
    const PAGES = ALL_PAGES.filter(([id]) => id !== "extension" || ext.supported);
    const root = document.createElement("div");
    root.className = "sheet-backdrop";
    root.innerHTML = `
      <div class="sheet" role="dialog" aria-modal="true">
        <div class="sheet-head"><h3>${esc(t("settings.title"))}</h3></div>
        <nav class="sheet-nav">${PAGES.map(([id, key]) => `<button data-page="${id}">${esc(t(key))}</button>`).join("")}</nav>
        <div class="sheet-body">${PAGES.map(([id]) => `<section class="sheet-page" data-page="${id}"></section>`).join("")}</div>
        <div class="sheet-foot">
          <div class="form-note">${esc(t("web.set.restart_note"))}</div>
          <button class="btn ghost" data-role="cancel">${esc(t("setup.cancel"))}</button>
          <button class="btn primary" data-role="save">${esc(t("settings.save"))}</button>
        </div>
      </div>`;
    document.body.appendChild(root);
    const q = (sel) => root.querySelector(sel);
    const pageEl = (id) => q(`.sheet-page[data-page="${id}"]`);
    const show = (id) => {
      root.querySelectorAll(".sheet-nav button").forEach((b) => b.classList.toggle("active", b.dataset.page === id));
      root.querySelectorAll(".sheet-page").forEach((p) => p.classList.toggle("active", p.dataset.page === id));
    };
    q(".sheet-nav").onclick = (e) => { const b = e.target.closest("button"); if (b) show(b.dataset.page); };

    const general = buildGeneral(pageEl("general"), cfg);
    const colors = buildColors(pageEl("colors"), cfg);
    buildData(pageEl("data"), cfg);
    if (ext.supported) buildExtension(pageEl("extension"), ext, () => close());
    const updates = buildUpdates(pageEl("updates"), cfg);
    buildAbout(pageEl("about"));
    show(page);

    const close = () => { open = false; colors.closePop(); colors.dispose(); root.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape" && !document.querySelector(".modal-backdrop:not(.hidden)")) close(); };
    document.addEventListener("keydown", onKey);
    q('[data-role="cancel"]').onclick = close;
    root.addEventListener("mousedown", (e) => { if (e.target === root) close(); });
    q('[data-role="save"]').onclick = async () => {
      const res = await SS.call("save_settings", {
        language: general.language(), ui: general.ui(), export_dir: general.exportDir(), enable_mods: general.enableMods(),
        db_path: general.dbPath(), check_updates: updates.checkOnStart(), colors: colors.get(),
      });
      close();
      if (res.warning) {
        await SS.dialog({ title: t("settings.title"), body: t("setup.mods_write_failed", { error: res.warning }),
                          buttons: [{ label: "OK", value: true, kind: "primary" }] });
      }
      if (res.restart && await SS.confirm(t("settings.title"), t("web.set.restart"), t("web.restart_now"))) {
        SS.call("restart");
        return;
      }
      if (res.reload) { location.reload(); return; }    // the language is applied without a restart
      SS.toast(t("web.set.saved"), "ok");
    };
  };

  // ---------------------------------------------------------------- general
  function buildGeneral(el, cfg) {
    el.innerHTML = `
      <div class="form-section"><h4>${esc(t("setup.done.language"))}</h4><div data-role="lang"></div>
        <div class="form-note" style="margin-top:6px">${esc(t("web.set.lang_note"))}</div></div>
      <div class="form-section"><h4>${esc(t("settings.ui"))}</h4><div data-role="ui"></div></div>
      <div class="form-section"><h4>${esc(t("setup.done.export"))}</h4><div data-role="export"></div></div>
      <div class="form-section"><h4>${esc(t("setup.done.db"))}</h4><div data-role="db"></div></div>`;
    const lang = SS.forms.radios(el.querySelector('[data-role="lang"]'), "lang",
      Object.entries(cfg.languages).map(([value, label]) => ({ value, label })), cfg.language);
    const ui = SS.forms.radios(el.querySelector('[data-role="ui"]'), "ui", [
      { value: "web", label: t("web.ui_web"), desc: t("web.ui_web_desc") },
      { value: "classic", label: t("web.ui_classic"), desc: t("web.ui_classic_desc") }], cfg.ui);
    const exp = SS.forms.exportField(el.querySelector('[data-role="export"]'), cfg.export_dir);
    const db = SS.forms.dbField(el.querySelector('[data-role="db"]'), cfg.db_path);
    return { language: lang.get, ui: ui.get, exportDir: exp.get, enableMods: exp.enableMods, dbPath: db.get };
  }

  // ---------------------------------------------------------------- colours
  function buildColors(el, cfg) {
    const colors = { ...cfg.colors };
    let pop = null;
    el.innerHTML = `
      <p class="text">${esc(t("settings.colors_text"))}</p>
      <div class="color-grid" data-role="grid"></div>
      <button class="btn" data-role="reset" style="margin-top:14px">${esc(t("settings.colors_reset"))}</button>`;
    const grid = el.querySelector('[data-role="grid"]');
    const render = () => {
      grid.innerHTML = cfg.stocks.length ? cfg.stocks.map((sid) => {
        const c = colors[sid] || cfg.defaults[sid] || "#8b919a";
        return `<button class="color-item" data-id="${esc(sid)}"><span class="sw" style="background:${c}"></span>${esc(sid)}<span class="hex">${esc(c)}</span></button>`;
      }).join("") : `<div class="form-note">${esc(t("web.set.no_stocks"))}</div>`;
    };
    const closePop = () => { if (pop) { pop.remove(); pop = null; } };
    const setColor = (sid, c) => { colors[sid] = c; render(); };

    grid.onclick = (e) => {
      const item = e.target.closest(".color-item");
      if (!item) return;
      closePop();
      const sid = item.dataset.id, cur = (colors[sid] || "").toLowerCase();
      pop = document.createElement("div");
      pop.className = "color-pop";
      pop.innerHTML = `
        <b>${esc(t("settings.pick_color", { stock: sid }))}</b>
        <div class="swatches">${cfg.palette.map((c) => `<button data-c="${c}" class="${c.toLowerCase() === cur ? "sel" : ""}" style="background:${c}" title="${c}"></button>`).join("")}</div>
        <div class="row"><button class="btn" data-role="custom">${esc(t("web.set.color_custom"))}</button>
          <button class="btn ghost" data-role="default">${esc(t("web.set.color_default"))}</button></div>
        <input type="color" value="${esc(colors[sid] || "#58a6ff")}">`;
      document.body.appendChild(pop);
      const r = item.getBoundingClientRect();
      pop.style.left = `${Math.min(r.left, window.innerWidth - 266)}px`;
      pop.style.top = `${Math.min(r.bottom + 6, window.innerHeight - pop.offsetHeight - 10)}px`;
      const picker = pop.querySelector("input[type=color]");
      pop.querySelector(".swatches").onclick = (ev) => { const b = ev.target.closest("button"); if (b) { setColor(sid, b.dataset.c); closePop(); } };
      pop.querySelector('[data-role="default"]').onclick = () => { setColor(sid, cfg.defaults[sid]); closePop(); };
      pop.querySelector('[data-role="custom"]').onclick = () => picker.click();
      picker.oninput = () => setColor(sid, picker.value);
      picker.onchange = () => { setColor(sid, picker.value); closePop(); };
    };
    const onDown = (e) => { if (pop && !pop.contains(e.target) && !e.target.closest(".color-item")) closePop(); };
    document.addEventListener("mousedown", onDown);
    el.querySelector('[data-role="reset"]').onclick = () => { closePop(); Object.assign(colors, cfg.defaults); render(); };
    render();
    return { get: () => colors, closePop, dispose: () => document.removeEventListener("mousedown", onDown) };
  }

  // ---------------------------------------------------------------- data
  function buildData(el, cfg) {
    el.innerHTML = `
      <p class="text">${esc(t("settings.data_text", { days: cfg.retention_days, s: cfg.bucket_s }))}</p>
      <dl class="kv" data-role="info"></dl>
      <button class="btn" data-role="compact">${esc(t("settings.compact_now"))}</button>
      <div class="status-line" data-role="status"></div>`;
    const info = el.querySelector('[data-role="info"]'), status = el.querySelector('[data-role="status"]');
    const btn = el.querySelector('[data-role="compact"]');
    const showInfo = async () => {
      const d = await SS.call("db_info");
      const rows = [["web.set.db_file", d.path], ["web.set.db_size", `${fmt.num(d.size / 1e6, 1)} MB`],
                    ["web.set.db_prices", fmt.num(d.prices, 0)], ["web.set.db_snaps", fmt.num(d.snapshots, 0)],
                    ["web.set.db_oldest", d.oldest_ms ? fmt.clock(d.oldest_ms, true) : "–"]];
      info.innerHTML = rows.map(([k, v]) => `<dt>${esc(t(k))}</dt><dd>${esc(v)}</dd>`).join("");
    };
    btn.onclick = async () => {
      btn.disabled = true;
      status.className = "status-line warn";
      status.textContent = t("settings.compacting");
      const r = await SS.call("compact_db");
      btn.disabled = false;
      status.className = `status-line ${r.ok ? "up" : "down"}`;
      status.textContent = r.ok
        ? t("settings.compact_done", { prices: fmt.num(r.prices, 0), snaps: fmt.num(r.snaps, 0),
                                       before: fmt.num(r.before / 1e6, 1), after: fmt.num(r.after / 1e6, 1) })
        : t("common.error", { error: r.error });
      showInfo();
    };
    showInfo();
  }

  // ---------------------------------------------------------------- extension
  // Installs / removes right away (not on Save); the page then reloads, which adds or drops the two tabs.
  function buildExtension(el, ext, closeDialog) {
    const line = (cls, text) => `<div class="${cls}">${esc(text)}</div>`;
    let state = ext.installed ? line("ok", t("upg.installed_state", { version: ext.plugin_version || ext.bridge }))
      : line("muted", t("upg.not_installed_state"));
    if (ext.installed && !ext.ours) state += line("warn", t("upg.err.not_ours"));
    if (ext.found && !ext.tested) state += line("warn", t("upg.untested"));
    el.innerHTML = `
      <div class="form-section"><h4>${esc(t("upg.title"))}</h4><p class="form-note">${esc(t("upg.intro"))}</p>
        <div class="notice">${esc(t("upg.what", { bepinex: ext.bepinex, bridge: ext.bridge }))}<br>
          <span class="link" data-url="${esc(ext.page)}">${esc(ext.page)}</span></div></div>
      <div class="form-section"><h4>${esc(t("upg.game_dir"))}</h4>
        <div class="mono">${esc(ext.found ? ext.game_dir : t("upg.no_game"))}</div>
        <button class="btn ghost" data-role="choose" style="margin-top:6px">${esc(t("upg.choose_game"))}</button></div>
      <div class="form-section"><div class="checks">${state}</div></div>
      ${ext.installed && ext.launch_option ? `<div class="form-section" data-role="launch"><h4>${esc(t("upg.launch_title"))}</h4>
        ${ext.launch_set === true ? line("ok", t("upg.launch_ok")) : ext.launch_set === false ? line("warn", t("upg.launch_missing")) : ""}</div>` : ""}
      <div class="ext-actions">
        ${ext.installed ? "" : `<button class="btn primary" data-role="install" ${ext.found ? "" : "disabled"}>${esc(t("upg.install"))}</button>`}
        ${ext.installed && ext.ours ? `<button class="btn danger" data-role="remove">${esc(t("upg.remove"))}</button>` : ""}
      </div>`;
    el.querySelector("[data-url]").onclick = (e) => SS.call("open_url", e.target.dataset.url);
    const launch = el.querySelector('[data-role="launch"]');
    if (launch) launch.appendChild(SS.forms.launchBox(ext));
    const done = (text) => { closeDialog(); SS.toast(text, "ok", 6000); setTimeout(() => location.reload(), 1200); };
    el.querySelector('[data-role="choose"]').onclick = async () => {
      const r = await SS.call("upgrades_choose_game");
      if (r && r.error) SS.toast(SS.forms.extError(r), "err", 6000);
      else if (r && r.ok) buildExtension(el, await SS.call("extension"), closeDialog);
    };
    const install = el.querySelector('[data-role="install"]');
    if (install) {
      install.onclick = async () => {
        if (!(await SS.confirm(t("upg.install"), t("upg.confirm_install", { bepinex: ext.bepinex, bridge: ext.bridge }), t("upg.install")))) return;
        install.disabled = true;
        install.textContent = t("upg.installing");
        if (await SS.forms.installExtension()) done(t("upg.installed"));
        else buildExtension(el, await SS.call("extension"), closeDialog);
      };
    }
    const remove = el.querySelector('[data-role="remove"]');
    if (remove) remove.onclick = async () => { if (await SS.forms.removeExtension()) done(t("upg.removed")); };
  }

  // ---------------------------------------------------------------- updates
  function buildUpdates(el, cfg) {
    el.innerHTML = `
      <div class="form-section"><h4>${esc(t("settings.version", { version: SS.info.version }))}</h4></div>
      <div class="form-section"><label class="switch"><input type="checkbox" data-role="on-start" ${cfg.check_updates ? "checked" : ""}>
        <span class="track"></span><span style="color:var(--fg)">${esc(t("settings.check_on_start"))}</span></label></div>
      <button class="btn" data-role="check">${esc(t("settings.check_now"))}</button>
      <div class="status-line" data-role="status"></div>`;
    const status = el.querySelector('[data-role="status"]'), btn = el.querySelector('[data-role="check"]');
    btn.onclick = async () => {
      btn.disabled = true;
      status.className = "status-line muted";
      status.textContent = t("update.checking");
      const r = await SS.call("check_updates_now");
      btn.disabled = false;
      if (r.state === "failed") { status.className = "status-line down"; status.textContent = t("update.failed", { error: r.error }); }
      else if (r.state === "available") { status.className = "status-line warn"; status.textContent = t("update.available", { version: r.version }); }
      else { status.className = "status-line up"; status.textContent = t("update.up_to_date", { version: r.version }); }
    };
    return { checkOnStart: () => el.querySelector('[data-role="on-start"]').checked };
  }

  // ---------------------------------------------------------------- about
  async function buildAbout(el) {
    const a = await SS.call("about");
    el.innerHTML = `
      <div class="about-head">${LOGO}<div><h4>ScreenStocks Trading Bot</h4>
        <div class="form-note">${esc(t("about.version", { version: a.version }))}</div></div></div>
      <p class="text">${esc(t("about.text"))}</p>
      <p><span class="link" data-url="${esc(a.github)}">${esc(t("about.source"))}</span></p>
      <div class="form-section"><h4>${esc(t("about.libraries"))}</h4>
        <table class="tbl"><thead><tr><th>${esc(t("about.col_name"))}</th><th>${esc(t("about.col_version"))}</th><th>${esc(t("about.col_license"))}</th></tr></thead>
        <tbody>${a.libraries.map((l) => `<tr><td><span class="link" data-url="${esc(l.url)}">${esc(l.name)}</span></td>
          <td class="mono">${esc(l.version || "–")}</td><td>${esc(l.license)}</td></tr>`).join("")}</tbody></table>
        <div class="form-note" style="margin-top:8px">${esc(t("about.runtime", { python: a.python, engine: a.engine }))}</div>
      </div>
      <div class="notice">${esc(t("about.tradingview"))}<br>
        <span class="link" data-url="https://www.tradingview.com/">${esc(t("about.tradingview_link"))}</span></div>`;
    el.onclick = (e) => { const l = e.target.closest("[data-url]"); if (l) SS.call("open_url", l.dataset.url); };
  }
})();
