/* Automation tab: master switch, rule form + table, announced-event trading, log. */
"use strict";

(() => {
  const { t, fmt, esc, cls } = SS;
  const S = { el: null, data: null, editId: null, previewTimer: null, sigRules: "", sigEvents: "", sigLog: "", eventsInit: false };
  const q = (sel) => S.el.querySelector(sel);
  const PUMP = ["pump_buy_pct", "pump_drop_pct", "pump_start_share", "pump_safety_s", "pump_short_pct", "pump_cover_pct", "pump_cover_max_s"];
  const CRASH = ["crash_minutes", "crash_short_pct", "crash_rise_pct", "crash_safety_s", "crash_rebuy_pct"];

  // ------------------------------------------------------------------ layout
  function mount(el) {
    S.el = el;
    const param = (k) => `<label for="ev-${k}">${esc(t(`event.p.${k}`))}</label><input class="in num" id="ev-${k}" data-param="${k}">`;
    el.innerHTML = `
      <div class="auto">
        <div class="panel auto-top">
          <label class="switch big"><input type="checkbox" data-role="master"><span class="track"></span>${esc(t("auto.master"))}</label>
          <span class="badge" data-role="engine"></span>
          <span class="hint">${esc(t("web.auto.engine_hint"))}</span>
        </div>

        <div class="auto-left">
          <section class="panel card">
            <h2><span data-role="form-title">${esc(t("web.auto.new_rule"))}</span><span class="editing-tag" data-role="editing"></span></h2>
            <div class="rform">
              <div class="field"><label>${esc(t("common.stock"))}</label><select class="in" data-f="stock_id"></select></div>
              <div class="field"><label>${esc(t("auto.type"))}</label><select class="in" data-f="kind"></select></div>
              <div class="field"><label>${esc(t("auto.side"))}</label><select class="in" data-f="side"></select></div>
              <div class="field"><label>${esc(t("auto.trigger"))}</label>
                <div class="pair"><input class="in num" data-f="value" placeholder="0"><select class="in" data-f="mode"></select></div></div>
              <div class="field"><label>${esc(t("auto.amount_pct"))}</label><input class="in num" type="number" min="1" max="100" data-f="percent" value="100"></div>
              <div class="field"><label>${esc(t("auto.confirm_after"))}</label><input class="in num" type="number" min="0" data-f="confirm_s" value="0"></div>
            </div>
            <div class="rform-actions">
              <label class="switch"><input type="checkbox" data-f="repeat"><span class="track"></span>↻ ${esc(t("auto.repeat"))}</label>
              <span class="spacer"></span>
              <button class="btn ghost" data-role="use-price">${esc(t("auto.use_price"))}</button>
              <button class="btn ghost hidden" data-role="cancel">${esc(t("auto.cancel_edit"))}</button>
              <button class="btn primary" data-role="save">${esc(t("auto.add"))}</button>
            </div>
            <div class="rhelp" data-role="help"></div>
          </section>

          <section class="panel card rules-card">
            <h2>${esc(t("auto.rules"))}</h2>
            <div class="tbl-wrap"><table class="tbl">
              <thead><tr>
                <th>#</th><th>${esc(t("common.stock"))}</th><th>${esc(t("auto.type"))}</th><th>${esc(t("auto.side"))}</th>
                <th>${esc(t("auto.trigger"))}</th><th class="r">${esc(t("auto.col_amount"))}</th><th class="r">${esc(t("common.price"))}</th>
                <th class="r">${esc(t("auto.col_distance"))}</th><th class="r">${esc(t("auto.col_confirm"))}</th>
                <th class="r">${esc(t("auto.col_repeat"))}</th><th>${esc(t("common.status"))}</th><th></th>
              </tr></thead>
              <tbody data-role="rules"></tbody>
            </table></div>
          </section>
        </div>

        <div class="auto-right">
          <section class="panel card">
            <h2>${esc(t("event.title"))}</h2>
            <div class="ev-switches">
              <label class="switch"><input type="checkbox" data-ev="pumps"><span class="track"></span>${esc(t("event.switch_pumps"))}</label>
              <label class="switch"><input type="checkbox" data-ev="crashes"><span class="track"></span>${esc(t("event.switch_crashes"))}</label>
            </div>
            <details class="params"><summary>${esc(t("web.auto.params"))}</summary>
              <div class="pgrid"><h4>${esc(t("event.pump_params"))}</h4>${PUMP.map(param).join("")}
                <h4>${esc(t("event.crash_params"))}</h4>${CRASH.map(param).join("")}</div>
              <div class="ev-help">${esc(t("event.help"))}</div>
            </details>
            <div class="ev-list" data-role="events"></div>
          </section>
          <section class="panel card log-card">
            <h2>${esc(t("auto.log"))}</h2>
            <div class="log-list" data-role="log"></div>
          </section>
        </div>
      </div>`;

    q('[data-role="master"]').onchange = async (e) => { await SS.call("set_master", e.target.checked); refreshNow(); };
    el.querySelectorAll("[data-ev]").forEach((cb) => (cb.onchange = saveEvents));
    el.querySelectorAll("[data-param]").forEach((inp) => (inp.onchange = saveEvents));
    el.querySelectorAll("[data-f]").forEach((inp) => {
      inp.addEventListener("input", onFormChange);
      inp.addEventListener("change", onFormChange);
    });
    q('[data-role="save"]').onclick = saveRule;
    q('[data-role="cancel"]').onclick = cancelEdit;
    q('[data-role="use-price"]').onclick = usePrice;
    q('[data-role="rules"]').onclick = onRuleAction;
  }

  const f = (name) => q(`[data-f="${name}"]`);
  /** Number for an input field: no thousands separator, decimal comma in German. */
  const plain = (v, digits = 4) => String(+(+v).toFixed(digits)).replace(".", SS.lang === "de" ? "," : ".");

  function fillSelect(sel, options, keep) {
    const cur = keep ?? sel.value;
    const html = Object.entries(options).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join("");
    if (sel.dataset.sig !== html) { sel.innerHTML = html; sel.dataset.sig = html; }
    if (cur && options[cur] !== undefined) sel.value = cur;
  }

  // ------------------------------------------------------------------ form
  function formValues() {
    return {
      stock_id: f("stock_id").value, kind: f("kind").value, side: f("side").value, mode: f("mode").value,
      value: f("value").value, percent: f("percent").value, confirm_s: f("confirm_s").value, repeat: f("repeat").checked,
    };
  }

  function syncFormControls() {
    const d = S.data; if (!d) return;
    const kind = f("kind").value, exit = d.exit_kinds.includes(kind);
    f("side").disabled = !exit;
    const mode = f("mode");
    if (kind === "trailing_stop") { fillSelect(mode, { pct: d.modes.trail }, "pct"); mode.disabled = true; }
    else if (exit) { fillSelect(mode, { pct: d.modes.pct, price: d.modes.price }); mode.disabled = false; }
    else { fillSelect(mode, { price: d.modes.price }, "price"); mode.disabled = true; }
  }

  function onFormChange() {
    syncFormControls();
    clearTimeout(S.previewTimer);
    S.previewTimer = setTimeout(updatePreview, 200);
  }

  async function updatePreview() {
    const p = await SS.call("rule_preview", formValues());
    q('[data-role="help"]').innerHTML = p.help.map((l, i) => `<div class="${i === 1 && l.includes("⚠") ? "warn" : ""}">${esc(l)}</div>`).join("");
  }

  function usePrice() {
    const price = S.data && S.data.prices[f("stock_id").value];
    if (price == null) return;
    if (!f("mode").disabled) f("mode").value = "price";
    f("value").value = plain(price, price >= 100 ? 2 : 4);
    onFormChange();
  }

  async function saveRule() {
    const form = formValues();
    const p = await SS.call("rule_preview", form);
    if (p.would_fire && !(await SS.confirm(t("auto.rule_title"), p.would_fire_text, S.editId ? t("auto.save") : t("auto.add")))) return;
    const res = await SS.call("save_rule", form, S.editId);
    SS.toast(res.text, res.ok ? "ok" : "err");
    if (res.ok) { cancelEdit(); refreshNow(); }
  }

  async function startEdit(id) {
    const r = await SS.call("rule_form", id);
    if (!r) return;
    S.editId = id;
    f("stock_id").value = r.stock_id; f("kind").value = r.kind; f("side").value = r.side;
    syncFormControls();
    if (!f("mode").disabled) f("mode").value = r.mode;
    f("value").value = r.value; f("percent").value = r.percent; f("confirm_s").value = r.confirm_s; f("repeat").checked = r.repeat;
    q('[data-role="form-title"]').textContent = t("web.auto.edit_rule", { id });
    q('[data-role="save"]').textContent = t("auto.save");
    q('[data-role="cancel"]').classList.remove("hidden");
    onFormChange();
    q('[data-role="form-title"]').scrollIntoView({ block: "nearest" });
  }

  function cancelEdit() {
    S.editId = null;
    q('[data-role="form-title"]').textContent = t("web.auto.new_rule");
    q('[data-role="save"]').textContent = t("auto.add");
    q('[data-role="cancel"]').classList.add("hidden");
  }

  // ------------------------------------------------------------------ rules table
  function renderRules(rules) {
    const sig = JSON.stringify(rules);
    if (sig === S.sigRules) return;
    S.sigRules = sig;
    const body = q('[data-role="rules"]');
    if (!rules.length) { body.innerHTML = `<tr><td colspan="12" class="empty-row">${esc(t("web.auto.no_rules"))}</td></tr>`; return; }
    body.innerHTML = rules.map((r) => `
      <tr class="${r.enabled ? "" : "off"} ${r.armed ? "armed" : ""}">
        <td class="mono">${r.id}</td><td><b>${esc(r.stock)}</b></td><td>${esc(r.kind_text)}</td><td>${esc(r.side_text)}</td>
        <td>${esc(r.trigger_text)}</td><td class="r mono">${esc(fmt.num(r.percent, 0))}%</td>
        <td class="r mono">${esc(fmt.price(r.price))}</td><td class="r mono ${cls(r.distance)}">${esc(fmt.pct(r.distance))}</td>
        <td class="r">${r.confirm_s ? esc(fmt.num(r.confirm_s, 0)) + " s" : "–"}</td>
        <td class="r">${r.repeat ? "↻ " + r.runs + "×" : "1×"}</td>
        <td class="wrap">${esc(r.status)}</td>
        <td><div class="row-actions">
          <button class="ibtn ${r.repeat ? "on" : ""}" data-act="repeat" data-id="${r.id}" title="${esc(t("auto.toggle_repeat"))}">↻</button>
          <button class="ibtn" data-act="edit" data-id="${r.id}" title="${esc(t("auto.edit"))}">✎</button>
          <button class="ibtn ${r.enabled ? "on" : ""}" data-act="toggle" data-id="${r.id}" title="${esc(t("auto.toggle"))}">⏻</button>
          <button class="ibtn danger" data-act="delete" data-id="${r.id}" title="${esc(t("auto.delete"))}">✕</button>
        </div></td>
      </tr>`).join("");
  }

  async function onRuleAction(e) {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const id = +btn.dataset.id, act = btn.dataset.act;
    if (act === "edit") return startEdit(id);
    if (act === "repeat") await SS.call("toggle_repeat", id);
    if (act === "toggle") await SS.call("toggle_rule", id);
    if (act === "delete") {
      if (!(await SS.confirm(t("auto.delete_title"), t("auto.delete_text", { id }), t("auto.delete"), "danger"))) return;
      await SS.call("delete_rule", id);
      if (S.editId === id) cancelEdit();
    }
    refreshNow();
  }

  // ------------------------------------------------------------------ events
  function fillEventSettings(s) {
    for (const k of ["pumps", "crashes"]) q(`[data-ev="${k}"]`).checked = !!s[k];
    for (const k of [...PUMP, ...CRASH]) {
      const inp = q(`[data-param="${k}"]`);
      if (document.activeElement !== inp) inp.value = plain(s[k], 2);
    }
  }

  async function saveEvents() {
    const values = {};
    for (const k of ["pumps", "crashes"]) values[k] = q(`[data-ev="${k}"]`).checked;
    for (const k of [...PUMP, ...CRASH]) values[k] = q(`[data-param="${k}"]`).value;
    const saved = await SS.call("save_events", values);
    fillEventSettings(saved);
    refreshNow();
  }

  function renderEvents(events, now) {
    const sig = JSON.stringify(events.map((e) => [e.id, e.phase_text, e.future]));
    const list = q('[data-role="events"]');
    if (sig !== S.sigEvents) {
      S.sigEvents = sig;
      list.innerHTML = events.length ? events.map((e) => `
        <div class="ev ${esc(e.direction)} ${e.future ? "" : "past"}" data-at="${e.at}">
          <span class="dotc"></span>
          <div class="main"><b>${esc(e.stock)}</b>${esc(e.direction_text)} → ${esc(fmt.price(e.target))}
            <div class="sub">${esc(fmt.clock(e.at, true))}</div></div>
          <div><div class="cd"></div><div class="phase">${esc(e.phase_text)}</div></div>
        </div>`).join("") : `<div class="muted">${esc(t("web.auto.no_events"))}</div>`;
    }
    list.querySelectorAll(".ev").forEach((row) => {
      const at = +row.dataset.at;
      row.querySelector(".cd").textContent = at >= now ? t("news.in", { countdown: fmt.duration((at - now) / 1000) }) : "";
    });
  }

  // ------------------------------------------------------------------ log
  function renderLog(log) {
    const sig = log.length ? `${log[0].id}:${log.length}` : "";
    if (sig === S.sigLog) return;
    S.sigLog = sig;
    q('[data-role="log"]').innerHTML = log.map((x) => `
      <div class="log-item"><span class="t">${esc(fmt.clock(x.time, true))}</span><span class="rid">${x.rule ? "#" + x.rule : ""}</span>
        <b>${esc(x.stock || "")}</b><span class="msg" title="${esc(x.msg)}">${esc(x.msg)}</span></div>`).join("");
  }

  // ------------------------------------------------------------------ refresh
  async function refresh() {
    const d = await SS.call("automation");
    if (!d || !d.rules) return;
    S.data = d;
    q('[data-role="master"]').checked = d.master;
    const badge = q('[data-role="engine"]');
    badge.textContent = t("engine.label", { state: t(`engine.${d.engine}`) });
    badge.className = "badge " + (d.engine === "active" ? "ok" : "");
    fillSelect(f("stock_id"), Object.fromEntries(d.stocks.map((s) => [s, s])));
    fillSelect(f("kind"), d.kinds);
    fillSelect(f("side"), d.sides);
    if (!S.eventsInit) { fillEventSettings(d.event_settings); S.eventsInit = true; onFormChange(); }
    else for (const k of ["pumps", "crashes"]) q(`[data-ev="${k}"]`).checked = !!d.event_settings[k];
    renderRules(d.rules);
    renderEvents(d.events, d.now);
    renderLog(d.log);
  }
  const refreshNow = () => refresh().catch((e) => console.error(e));

  SS.registerTab("automation", { mount, refresh, show: refreshNow });
})();
