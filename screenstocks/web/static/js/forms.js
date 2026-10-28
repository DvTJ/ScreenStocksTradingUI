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
      if (!r.market_ok) {
        html += r.mod_support === true ? line("ok", "setup.game.modsupport_on")
          : r.mod_support === false ? line("bad", "setup.game.modsupport_off") : line("warn", "setup.game.modsupport_unknown");
        if (r.mod_support !== true) html += line("steps", "setup.game.modsupport_steps", { path: r.settings_file });
      }
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

  // ---------------------------------------------------------------- game extension (Upgrades, Leaderboard)

  /** Text of an {error, detail} answer of the extension calls. */
  forms.extError = (r) => {
    const key = `upg.err.${r && r.error}`;
    const text = SS.texts[key] !== undefined ? t(key) : t("upg.err.failed");
    return r && r.detail ? `${text} (${r.detail})` : text;
  };

  forms.copy = async (text) => {
    try { await navigator.clipboard.writeText(text); }
    catch { const a = document.createElement("textarea"); a.value = text; document.body.appendChild(a); a.select(); document.execCommand("copy"); a.remove(); }
    SS.toast(t("bot.copied"), "ok");
  };

  /** The Steam launch option the extension needs on macOS and under Proton: what to do, the line, a copy button. */
  forms.launchBox = (ext, intro) => {
    const box = document.createElement("div");
    box.className = "ext-launch";
    box.innerHTML = `<p>${esc(intro || t(ext.build === "macos" ? "upg.launch_macos" : "upg.launch_wine"))}</p>
      <div class="ext-launch-line"><code class="mono">${esc(ext.launch_option)}</code>
        <button class="btn ghost small">${esc(t("upg.copy"))}</button></div>`;
    box.querySelector("button").onclick = () => forms.copy(ext.launch_option);
    return box;
  };

  /** Install the extension; while the game runs, ask to close it and try again (or leave it for later).
      Resolves true once it is installed. */
  forms.installExtension = async () => {
    for (;;) {
      const r = await SS.call("upgrades_install");
      if (r && r.ok) {
        const ext = await SS.call("extension");
        if (ext.launch_option && ext.launch_set !== true) {
          await SS.dialog({ title: t("upg.launch_title"), body: forms.launchBox(ext),
                            buttons: [{ label: "OK", value: true, kind: "primary" }] });
        }
        return true;
      }
      if (r && r.error === "game_running") {
        const again = await SS.dialog({ title: t("upg.install"), body: t("upg.close_game"), buttons: [
          { label: t("upg.later"), value: false, kind: "ghost" }, { label: t("upg.retry"), value: true, kind: "primary" }] });
        if (again) continue;
        return false;
      }
      await SS.dialog({ title: t("upg.install"), body: forms.extError(r), buttons: [{ label: "OK", value: true, kind: "primary" }] });
      return false;
    }
  };

  /** Remove the extension (the game has to be closed). Resolves true once it is gone. */
  forms.removeExtension = async () => {
    if (!(await SS.confirm(t("upg.remove"), t("upg.confirm_remove"), t("upg.remove"), "danger"))) return false;
    const r = await SS.call("upgrades_remove");
    if (r && r.ok) {
      if (r.launch_option) {
        await SS.dialog({ title: t("upg.remove"), buttons: [{ label: "OK", value: true, kind: "primary" }],
                          body: forms.launchBox(r, t(r.build === "macos" ? "upg.removed_launch_macos" : "upg.removed_launch")) });
      }
      return true;
    }
    await SS.dialog({ title: t("upg.remove"), body: forms.extError(r), buttons: [{ label: "OK", value: true, kind: "primary" }] });
    return false;
  };
})();
