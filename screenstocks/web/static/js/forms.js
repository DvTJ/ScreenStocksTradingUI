/* Form pieces shared by the settings dialog and the setup wizard: export folder and database file. */
"use strict";

(() => {
  const { t, esc } = SS;
  const forms = (SS.forms = {});

  /** Export folder with Browse / Detect and the checks of the classic wizard. Returns {get, enableMods, check}. */
  forms.exportField = (el, value) => {
    el.innerHTML = `
      <div class="path-row">
        <input class="in" data-role="path" spellcheck="false">
        <button class="btn" data-role="browse">${esc(t("setup.game.browse"))}</button>
        <button class="btn" data-role="detect">${esc(t("setup.game.detect"))}</button>
      </div>
      <div class="checks" data-role="checks"></div>`;
    const input = el.querySelector('[data-role="path"]'), checks = el.querySelector('[data-role="checks"]');
    let enable = true, last = null;
    input.value = value || "";

    async function check() {
      const path = input.value.trim();
      const r = await SS.call("check_export", path);
      last = r;
      const line = (cls, key, vars) => `<div class="${cls}">${esc(t(key, vars))}</div>`;
      let html = r.dir_ok ? line("ok", "setup.game.dir_ok") : line("bad", "setup.game.dir_missing");
      if (r.dir_ok) html += r.market_ok ? line("ok", "setup.game.market_ok") : line("warn", "setup.game.market_missing");
      if (!r.mods) {
        if (r.dir_ok) html += line("warn", "setup.game.mods_missing");
      } else {
        const ok = r.mods.export && r.mods.commands;
        html += line(ok ? "ok" : "warn", "setup.game.mods_flags", { export: r.mods.export, commands: r.mods.commands });
        if (!ok) html += `<label class="check"><input type="checkbox" data-role="enable" ${enable ? "checked" : ""}>${esc(t("setup.game.enable_mods"))}</label>`;
      }
      checks.innerHTML = html;
      const box = checks.querySelector('[data-role="enable"]');
      if (box) box.onchange = () => { enable = box.checked; };
      return r;
    }
    input.addEventListener("change", check);
    el.querySelector('[data-role="browse"]').onclick = async () => {
      const path = await SS.call("browse_export", input.value.trim());
      if (path) { input.value = path; check(); }
    };
    el.querySelector('[data-role="detect"]').onclick = async () => {
      const path = await SS.call("detect_export");
      if (path) { input.value = path; check(); } else SS.toast(t("setup.game.detect_failed"), "warn", 5000);
    };
    check();
    return { get: () => input.value.trim(), enableMods: () => enable, check, dirOk: () => !!(last && last.dir_ok) };
  };

  /** Database file with Browse and a note whether it exists. Returns {get}. */
  forms.dbField = (el, value) => {
    el.innerHTML = `
      <div class="path-row">
        <input class="in" data-role="path" spellcheck="false">
        <button class="btn" data-role="browse">${esc(t("setup.game.browse"))}</button>
      </div>
      <div class="checks" data-role="checks"></div>`;
    const input = el.querySelector('[data-role="path"]'), checks = el.querySelector('[data-role="checks"]');
    input.value = value || "";
    async function check() {
      const exists = await SS.call("db_exists", input.value.trim());
      checks.innerHTML = exists ? `<div class="ok">${esc(t("setup.data.exists"))}</div>` : `<div class="muted">${esc(t("setup.data.new"))}</div>`;
    }
    input.addEventListener("change", check);
    el.querySelector('[data-role="browse"]').onclick = async () => {
      const path = await SS.call("browse_db", input.value.trim());
      if (path) { input.value = path; check(); }
    };
    check();
    return { get: () => input.value.trim() };
  };

  /** Radio group: options [{value, label, desc}] -> {get} */
  forms.radios = (el, name, options, value, onChange) => {
    el.className = "radios";
    el.innerHTML = options.map((o) => `<label><input type="radio" name="${name}" value="${esc(o.value)}" ${o.value === value ? "checked" : ""}>
      <span>${esc(o.label)}${o.desc ? `<br><small>${esc(o.desc)}</small>` : ""}</span></label>`).join("");
    if (onChange) el.onchange = (e) => onChange(e.target.value);
    return { get: () => (el.querySelector("input:checked") || {}).value };
  };
})();
