/* Setup wizard (first start / --setup): language -> game export folder -> database -> summary.
   Same steps and checks as the classic wizard; afterwards the app opens in the same window. */
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const { t, esc } = SS;
  const STEPS = ["language", "game", "data", "done"];
  const S = { step: 0, values: {}, languages: {}, field: null };

  function render() {
    const name = STEPS[S.step];
    $("steps").innerHTML = STEPS.map((_, i) => `<i class="${i <= S.step ? "on" : ""}"></i>`).join("");
    $("step-label").textContent = t("setup.step", { n: S.step + 1, total: STEPS.length });
    $("btn-cancel").textContent = t("setup.cancel");
    $("btn-back").textContent = t("setup.back").replace(/^<\s*/, "← ");
    $("btn-back").disabled = S.step === 0;
    $("btn-next").textContent = S.step === STEPS.length - 1 ? t("setup.finish") : t("setup.next").replace(/\s*>$/, " →");
    document.title = t("setup.title");
    const body = $("wizard-body");
    const heading = (h, text) => `<h2>${esc(t(h))}</h2><p class="text">${esc(t(text))}</p>`;
    S.field = null;
    if (name === "language") {
      body.innerHTML = heading("setup.lang.heading", "setup.lang.text") + `<div data-role="lang"></div>`;
      SS.forms.radios(body.querySelector('[data-role="lang"]'), "lang",
        Object.entries(S.languages).map(([value, label]) => ({ value, label })), S.values.language, setLanguage);
      body.querySelector('[data-role="lang"]').classList.add("stack");
    } else if (name === "game") {
      body.innerHTML = heading("setup.game.heading", "setup.game.text") + `<div data-role="export"></div>`;
      S.field = SS.forms.exportField(body.querySelector('[data-role="export"]'), S.values.export_dir);
    } else if (name === "data") {
      body.innerHTML = heading("setup.data.heading", "setup.data.text")
        + `<div class="form-section"><h4>${esc(t("setup.data.file"))}</h4><div data-role="db"></div></div>`;
      S.field = SS.forms.dbField(body.querySelector('[data-role="db"]'), S.values.db_path);
    } else {
      const rows = [["setup.done.language", S.languages[S.values.language] || S.values.language],
                    ["setup.done.export", S.values.export_dir], ["setup.done.db", S.values.db_path]];
      body.innerHTML = heading("setup.done.heading", "setup.done.text")
        + `<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(t(k))}</dt><dd class="mono">${esc(v)}</dd>`).join("")}</dl>`
        + `<div class="form-note warn">${esc(t("setup.done.note"))}</div>`;
    }
  }

  /** Remember what the current page shows before leaving it. */
  function collect() {
    const name = STEPS[S.step];
    if (name === "game" && S.field) { S.values.export_dir = S.field.get(); S.values.enable_mods = S.field.enableMods(); }
    if (name === "data" && S.field) S.values.db_path = S.field.get();
  }

  async function setLanguage(lang) {
    S.values.language = lang;
    SS.texts = await SS.call("wizard_language", lang);
    SS.lang = SS.LANGS[lang] ? lang : "en";
    document.documentElement.lang = SS.lang;
    render();
  }

  async function next() {
    const name = STEPS[S.step];
    collect();
    if (name === "game") {
      const r = await S.field.check();
      if (!r.dir_ok && !(await SS.confirm(t("setup.title"), t("setup.game.continue_anyway"), t("setup.next").replace(/\s*>$/, "")))) return;
    }
    if (S.step < STEPS.length - 1) { S.step += 1; render(); return; }
    $("btn-next").disabled = true;
    const res = await SS.call("wizard_finish", S.values);
    if (res.warning) {
      await SS.dialog({ title: t("setup.title"), body: t("setup.mods_write_failed", { error: res.warning }),
                        buttons: [{ label: "OK", value: true, kind: "primary" }] });
    }
    const opened = await SS.call("wizard_open");   // starts recording and loads the app into this window
    if (opened && opened.error) {
      await SS.dialog({ title: t("setup.title"), body: opened.error, buttons: [{ label: "OK", value: true, kind: "primary" }] });
      $("btn-next").disabled = false;
    }
  }

  SS.ready().then(async () => {
    const st = await SS.call("wizard_state");
    SS.texts = st.texts;
    SS.lang = SS.LANGS[st.lang] ? st.lang : "en";
    SS.info = { version: st.version };
    document.documentElement.lang = SS.lang;
    S.languages = st.languages;
    S.values = { language: st.lang, export_dir: st.export_dir, db_path: st.db_path, enable_mods: true };
    $("btn-next").onclick = next;
    $("btn-back").onclick = () => { collect(); if (S.step) { S.step -= 1; render(); } };
    $("btn-cancel").onclick = () => SS.call("wizard_cancel");
    render();
  });
})();
