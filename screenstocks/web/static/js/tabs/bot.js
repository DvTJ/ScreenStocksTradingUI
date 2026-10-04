/* Bot tab: switch, level, settings (simple / medium / advanced), results, positions, journal, history test. */
"use strict";

(() => {
  const { t, fmt, esc, cls } = SS;
  const S = { el: null, data: null, settings: null, shown: {}, busy: false, stockSig: "", logSig: "", kpis: null, pos: null };
  const PARAMS = ["tau_s", "entry_z", "exit_z", "min_edge_pct", "stop_pct", "max_hold_s", "confirm_s", "max_loss_pct", "jump_pct", "news_s"];
  const STEP = { tau_s: 10, entry_z: 0.1, exit_z: 0.1, min_edge_pct: 0.5, stop_pct: 1, max_hold_s: 10, confirm_s: 1, max_loss_pct: 0.5, jump_pct: 1, news_s: 5 };
  const RANGES = ["15m", "30m", "1h", "3h", "6h", "24h", "all"];
  const LEVELS = ["simple", "medium", "advanced"], CAUTIONS = ["prudent", "balanced", "aggressive"];
  const q = (sel) => S.el.querySelector(sel);
  const f = (name) => q(`[data-f="${name}"]`);
  const money = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + fmt.num(v, 0));
  const plain = (v) => String(+(+v).toFixed(4)).replace(".", SS.commaLang() ? "," : ".");
  const parse = (s) => { const v = parseFloat(String(s).replace(/\s/g, "").replace(",", ".")); return Number.isFinite(v) ? v : null; };
  const options = (keys, label) => keys.map((k) => `<option value="${k}">${esc(label(k))}</option>`).join("");

  // ------------------------------------------------------------------ layout
  function mount(el) {
    S.el = el;
    const info = (k) => `<span class="info" tabindex="0" role="note" data-tip="${esc(t(`bot.d.${k}`))}">i</span>`;
    const adv = (k, step) => `<label>${esc(t(`bot.p.${k}`))} ${info(k)}</label>
      <input class="in num" type="text" inputmode="decimal" data-f="${k}" data-step="${step}"><span class="tag" data-tag="${k}"></span>`;
    el.innerHTML = `
      <div class="bot" data-level="simple">
        <div class="panel bot-top">
          <label class="switch big"><input type="checkbox" data-f="enabled"><span class="track"></span>${esc(t("bot.enable"))}</label>
          <label class="switch"><input type="checkbox" data-f="paper"><span class="track"></span>${esc(t("bot.paper"))} ${info("paper")}</label>
          <span class="badge warn">${esc(t("bot.experimental_badge"))}</span>
          <div class="lvl"><label>${esc(t("bot.level"))}</label>
            <select class="in" data-f="level">${options(LEVELS, (k) => t(`bot.level.${k}`))}</select></div>
          <span class="badge neutral" data-role="state"></span>
          <span class="spacer"></span>
          <button class="btn ghost" data-role="export">${esc(t("bot.export"))}</button>
          <button class="btn ghost" data-role="import">${esc(t("bot.import"))}</button>
        </div>

        <section class="panel card">
          <div class="bset">
            <div class="field wide"><label>${esc(t("bot.trade_pct"))} ${info("trade_pct")}</label><input class="in num" type="number" min="1" max="100" data-f="trade_pct"></div>
            <div class="field only-medium"><label>${esc(t("bot.caution"))} ${info("caution")}</label>
              <select class="in" data-f="caution">${options(CAUTIONS, (k) => t(`bot.caution.${k}`))}</select></div>
            <div class="field only-medium"><label>${esc(t("bot.max_positions"))} ${info("max_positions")}</label><input class="in num" type="number" min="1" max="10" data-f="max_positions"></div>
            <label class="switch only-medium"><input type="checkbox" data-f="shorts"><span class="track"></span>${esc(t("bot.shorts"))} ${info("shorts")}</label>
            <label class="switch only-medium"><input type="checkbox" data-f="trade_events"><span class="track"></span>${esc(t("bot.trade_events"))} ${info("trade_events")}</label>
          </div>
          <details class="bot-adv only-advanced" data-role="adv"><summary>${esc(t("bot.advanced").replace(/^[▸▾]\s*/, ""))}</summary>
            <div class="padv">${PARAMS.map((k) => adv(k, STEP[k])).join("")}
              <label>${esc(t("bot.p.recalib_min"))} ${info("recalib_min")}</label><input class="in num" type="text" inputmode="numeric" data-f="recalib_min"><span></span>
              <label>${esc(t("bot.p.loss_limit_pct"))} ${info("loss_limit_pct")}</label><input class="in num" type="text" inputmode="decimal" data-f="loss_limit_pct"><span></span></div>
            <button class="btn ghost" data-role="reset">${esc(t("bot.reset_auto"))}</button>
            <div style="margin-top:12px"><label>${esc(t("bot.stocks_traded"))}</label></div>
            <div class="stock-checks" data-role="stocks"></div>
          </details>
        </section>

        <div data-role="kpis"></div>
        <div class="bot-trades-bar"><span class="spacer"></span><button class="btn ghost danger" data-role="clear">${esc(t("bot.clear"))}</button><button class="btn ghost" data-role="trades-detail">${esc(t("bot.trades_detail"))}</button></div>
        <div class="bot-note hidden" data-role="none"></div>

        <div class="bot-grid">
          <section class="panel box"><h2>${esc(t("bot.positions"))}</h2><div data-role="positions" class="grow"></div></section>
          <section class="panel box"><h2>${esc(t("bot.log"))}</h2><div class="bot-log" data-role="log"></div></section>
          <section class="panel box wide"><h2>${esc(t("bot.thinking"))}<span class="think-status" data-role="think-status"></span><span class="spacer"></span>
            <button class="btn ghost" data-role="think-copy">${esc(t("bot.copy"))}</button>
            <button class="btn ghost" data-role="think-export">${esc(t("bot.export_results"))}</button></h2>
            <div class="bot-log" data-role="thoughts"></div></section>
        </div>

        <section class="panel card">
          <div class="bot-test">
            <div class="field"><label>${esc(t("bot.test"))}</label>
              <select class="in" data-role="range">${options(RANGES, (k) => (k === "all" ? t("common.all") : k))}</select></div>
            <div class="field cap"><label>${esc(t("bot.test.capital"))}</label><input class="in num" type="text" inputmode="decimal" data-role="capital"></div>
            <label class="switch"><input type="checkbox" data-role="usecash" checked><span class="track"></span>${esc(t("bot.test.use_cash"))}</label>
            <button class="btn primary" data-role="run">${esc(t("bot.test"))}</button>
            <button class="btn ghost" data-role="detail" disabled>${esc(t("bot.test.detail"))}</button>
          </div>
          <div class="bot-test-result" data-role="result"></div>
        </section>
      </div>`;
    q('[data-role="range"]').value = "all";
    S.kpis = SS.ui.kpis(q('[data-role="kpis"]'), [
      { key: "gain", label: t("bot.results.gain") }, { key: "n", label: t("bot.results.trades") },
      { key: "win", label: t("journal.hit_rate") }, { key: "best", label: t("journal.best") }, { key: "worst", label: t("journal.worst") },
    ]);
    S.pos = SS.ui.table(q('[data-role="positions"]'), {
      sortKey: "stock", sortDesc: false, empty: "–", rowClass: (r) => cls(r.gain),
      columns: [
        { key: "stock", label: t("common.stock"), render: (r) => `<b>${esc(r.stock)}</b>` },
        { key: "side", label: t("bot.col_side"), render: (r) => esc(r.side_text) },
        { key: "entry", label: t("bot.col_entry"), align: "r", render: (r) => esc(fmt.price(r.entry)) },
        { key: "target", label: t("bot.col_target"), align: "r", render: (r) => esc(fmt.price(r.target)) },
        { key: "gain", label: t("bot.col_gain"), align: "r", cls: (r) => cls(r.gain), render: (r) => esc(fmt.pct(r.gain)) },
      ],
    });

    // every control saves on change; text fields on Enter / leaving the field
    el.querySelectorAll("[data-f]").forEach((c) => c.addEventListener("change", () => onChange(c)));
    el.querySelectorAll("[data-f][data-step]").forEach((c) => c.addEventListener("keydown", (e) => {
      if (e.key === "Enter") c.blur();
      if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        const v = parse(c.value) ?? 0;
        c.value = plain(v + (e.key === "ArrowUp" ? 1 : -1) * +c.dataset.step);
        save();
      }
    }));
    q('[data-role="reset"]').onclick = async () => { await SS.call("bot_reset_auto"); refreshNow(true); };
    q('[data-role="export"]').onclick = () => fileAction("bot_export_setup");
    q('[data-role="import"]').onclick = async () => { await fileAction("bot_import_setup"); refreshNow(true); };
    q('[data-role="usecash"]').onchange = syncCapital;
    q('[data-role="think-copy"]').onclick = async () => {
      const text = [...q('[data-role="thoughts"]').querySelectorAll(".item")].map((i) => i.innerText.replace(/\n+/g, " ")).join("\n");
      try { await navigator.clipboard.writeText(text); }
      catch { const a = document.createElement("textarea"); a.value = text; document.body.appendChild(a); a.select(); document.execCommand("copy"); a.remove(); }
      SS.toast(t("bot.copied"), "ok");
    };
    q('[data-role="think-export"]').onclick = () => fileAction("bot_export_report");
    q('[data-role="run"]').onclick = runTest;
    q('[data-role="detail"]').onclick = showDetail;
    q('[data-role="trades-detail"]').onclick = showTrades;
    q('[data-role="clear"]').onclick = async () => {
      const ok = await SS.dialog({ title: t("bot.clear"), body: t("bot.clear_ask"), buttons: [
        { label: t("setup.cancel"), value: false, kind: "ghost" }, { label: t("bot.clear"), value: true, kind: "primary" }] });
      if (!ok) return;
      const res = await SS.call("bot_clear_history");
      if (res && res.ok) { SS.toast(res.message, "ok"); S.logSig = ""; S.thinkSig = ""; refreshNow(true); }
    };
  }

  const reveal = (res) => (res.path ? { label: t("bot.open_folder"), run: () => SS.call("reveal_file", res.path) } : null);

  async function fileAction(name) {
    const res = await SS.call(name);
    if (!res || res.cancelled) return;
    if (res.error) SS.toast(res.error, "err", 6000);
    else SS.toast(res.message, "ok", 15000, reveal(res));
  }

  // ---------------------------------------------------------------- settings form
  function values() {
    const overrides = { ...(S.settings ? S.settings.overrides : {}) };
    for (const k of PARAMS) {                       // a field that no longer shows what we put there was edited
      const v = parse(f(k).value);
      if (v !== null && v !== S.shown[k] && (v > 0 || k === "exit_z")) overrides[k] = v;
    }
    return {
      enabled: f("enabled").checked, paper: f("paper").checked, level: f("level").value, trade_pct: parse(f("trade_pct").value) ?? S.settings.trade_pct,
      caution: f("caution").value, max_positions: parse(f("max_positions").value) ?? S.settings.max_positions,
      shorts: f("shorts").checked, trade_events: f("trade_events").checked, recalib_min: parse(f("recalib_min").value) ?? S.settings.recalib_min,
      loss_limit_pct: parse(f("loss_limit_pct").value) ?? S.settings.loss_limit_pct,
      excluded: [...S.el.querySelectorAll("[data-stock]")].filter((c) => !c.checked).map((c) => c.dataset.stock),
      overrides,
    };
  }

  function onChange(c) {
    if (c.dataset.f === "caution" && S.data) f("max_positions").value = S.data.presets[c.value];   // the preset's positions
    save();
  }

  async function save() {
    if (!S.settings) return;
    S.busy = true;
    try {
      const res = await SS.call("bot_save", values());
      if (res && res.ok) { S.settings = res.settings; fill(true); }
    } finally { S.busy = false; }
    refreshNow();
  }

  /** Put the stored settings into the controls (a control being edited is left alone unless forced). */
  function fill(force = false) {
    const s = S.settings, d = S.data;
    if (!s) return;
    const set = (name, v) => {
      const c = f(name);
      if (!force && document.activeElement === c) return;
      if (c.type === "checkbox") c.checked = !!v; else c.value = v;
    };
    set("enabled", s.enabled); set("paper", s.paper); set("level", s.level); set("trade_pct", s.trade_pct); set("caution", s.caution);
    set("max_positions", s.max_positions); set("shorts", s.shorts); set("trade_events", s.trade_events); set("recalib_min", s.recalib_min); set("loss_limit_pct", s.loss_limit_pct);
    q(".bot").dataset.level = s.level;
    for (const k of PARAMS) {
      const manual = k in s.overrides;
      const tag = q(`[data-tag="${k}"]`);
      tag.textContent = t(manual ? "bot.manual" : "bot.auto");
      tag.classList.toggle("manual", manual);
      const shown = manual ? s.overrides[k] : d && d.auto[k];
      if (shown != null && (force || document.activeElement !== f(k))) {
        S.shown[k] = +(+shown).toFixed(4);
        f(k).value = plain(shown);
      }
    }
  }

  function syncStocks(d) {
    const sig = d.stocks.join(",") + "|" + d.settings.excluded.join(",");
    if (sig === S.stockSig) return;
    S.stockSig = sig;
    q('[data-role="stocks"]').innerHTML = d.stocks.map((sid) =>
      `<label class="check"><input type="checkbox" data-stock="${esc(sid)}" ${d.settings.excluded.includes(sid) ? "" : "checked"}>${esc(sid)}</label>`).join("");
    q('[data-role="stocks"]').querySelectorAll("input").forEach((c) => c.addEventListener("change", save));
  }

  // ---------------------------------------------------------------- history test
  function syncCapital() {
    const on = q('[data-role="usecash"]').checked, inp = q('[data-role="capital"]');
    inp.disabled = on;
    if (on && S.data && S.data.cash != null) inp.value = fmt.num(S.data.cash, 0);
  }

  async function runTest() {
    await SS.call("bot_test_start", q('[data-role="range"]').value, q('[data-role="capital"]').value, q('[data-role="usecash"]').checked);
    refreshNow();
  }

  async function showTrades() {
    const d = await SS.call("bot_trades");
    if (!d || !d.trades) return;
    const body = document.createElement("div");
    body.className = "bot-detail";
    const per = Object.entries(d.per_stock).map(([sid, v]) => `<span><b>${esc(sid)}</b> ${v.n}× <span class="${cls(v.profit)}">${esc(money(v.profit))}</span></span>`).join("");
    const head = [d.paper ? t("bot.trades.practice") : "", d.since ? t("bot.trades.since", { time: fmt.clock(d.since, true), cash: fmt.num(d.cash0, 0) }) : ""].filter(Boolean);
    body.innerHTML = `<div class="head"><button class="btn ghost" data-role="csv">${esc(t("bot.trades.export_csv"))}</button>
        <button class="btn ghost" data-role="json">${esc(t("bot.export_results"))}</button></div>
      <div class="row"><span class="muted">${esc(head.join(" · "))}</span></div>
      <div class="row"><b>${esc(t("bot.trades.summary", { n: d.n, win: Math.round(d.win_rate), profit: money(d.profit) }))}</b></div>
      <div class="row"><span class="muted">${esc(t("bot.detail.per_stock"))}:</span>${per || "–"}</div><div data-role="trades"></div>`;
    const done = (res) => { if (res && !res.cancelled) SS.toast(res.error || res.message, res.error ? "err" : "ok", 15000, res.error ? null : reveal(res)); };
    body.querySelector('[data-role="csv"]').onclick = async () => done(await SS.call("bot_export_trades"));
    body.querySelector('[data-role="json"]').onclick = async () => done(await SS.call("bot_export_report"));
    const reason = (x) => t(x.reason === "target" && x.pnl < 0 ? "bot.reason.target_loss" : `bot.reason.${x.reason}`);
    const tbl = SS.ui.table(body.querySelector('[data-role="trades"]'), {
      sortKey: "time_ms", empty: t("bot.results.none"), rowClass: (r) => cls(r.pnl),
      columns: [
        { key: "time_ms", label: t("bot.col_at"), render: (r) => `<span class="mono">${esc(fmt.clock(r.time_ms, true))}</span>` },
        { key: "stock_id", label: t("common.stock"), render: (r) => `<b>${esc(r.stock_id)}</b>` },
        { key: "side", label: t("bot.col_side"), render: (r) => esc(t(`side.${r.side}`)) },
        { key: "ret", label: t("bot.col_return"), align: "r", cls: (r) => cls(r.ret), render: (r) => esc(fmt.pct(r.ret)) },
        { key: "money", label: t("bot.col_stake"), align: "r", render: (r) => esc(fmt.num(r.money, 0)) },
        { key: "pnl", label: t("bot.col_profit"), align: "r", cls: (r) => cls(r.pnl), render: (r) => esc(money(r.pnl)) },
        { key: "entry", label: t("bot.col_entry"), align: "r", render: (r) => esc(fmt.price(r.entry)) },
        { key: "exit", label: t("bot.col_exit"), align: "r", render: (r) => esc(fmt.price(r.exit)) },
        { key: "held_s", label: t("bot.col_held"), align: "r", render: (r) => esc(r.held_s ?? "–") },
        { key: "reason", label: t("bot.col_reason"), render: (r) => esc(reason(r)), value: (r) => reason(r) },
        { key: "del", label: "", render: (r) => `<button class="btn ghost danger" data-del="${r.time_ms}" title="${esc(t("bot.delete_trade"))}">✕</button>`, value: () => 0 },
      ],
    });
    tbl.set(d.trades);
    body.querySelector('[data-role="trades"]').onclick = async (e) => {
      const b = e.target.closest("[data-del]");
      if (!b) return;
      await SS.call("bot_delete_trade", +b.dataset.del);
      const n = await SS.call("bot_trades");
      if (n && n.trades) tbl.set(n.trades);
    };
    const modal = document.querySelector(".modal");
    modal.classList.add("wide");
    await SS.dialog({ title: t("bot.trades.title"), body, buttons: [{ label: "OK", value: true, kind: "primary" }] });
    modal.classList.remove("wide");
  }

  async function showDetail() {
    const d = await SS.call("bot_test_detail");
    if (!d || !d.trades) return;
    const body = document.createElement("div");
    body.className = "bot-detail";
    const per = Object.entries(d.per_stock).map(([sid, v]) => `<span><b>${esc(sid)}</b> ${v.n}× <span class="${cls(v.profit)}">${esc(money(v.profit))}</span></span>`).join("");
    const periods = d.periods.map((p) => `<span>${esc(t("bot.detail.period", {
      period: p.seconds < 3600 ? `${p.seconds / 60} min` : `${p.seconds / 3600} h`, n: p.n,
      win: p.win_rate == null ? "–" : Math.round(p.win_rate), profit: money(p.profit) }))}</span>`).join("");
    body.innerHTML = `<div class="head"><button class="btn ghost" data-role="export-report">${esc(t("bot.export_results"))}</button></div>
      <div class="row"><span class="muted">${esc(t("bot.detail.per_stock"))}:</span>${per || "–"}</div>
      <div class="row">${periods}</div><div data-role="trades"></div>`;
    body.querySelector('[data-role="export-report"]').onclick = async () => {
      const res = await SS.call("bot_export_report");
      if (res && !res.cancelled) SS.toast(res.error || res.message, res.error ? "err" : "ok", 15000, res.error ? null : reveal(res));
    };
    const reason = (x) => t(x.reason === "target" && x.pnl < 0 ? "bot.reason.target_loss" : `bot.reason.${x.reason}`);
    SS.ui.table(body.querySelector('[data-role="trades"]'), {
      sortKey: "exit_time_ms", empty: "–", rowClass: (r) => cls(r.pnl),
      columns: [
        { key: "exit_time_ms", label: t("bot.col_at"), render: (r) => `<span class="mono">${esc(fmt.clock(r.exit_time_ms, true))}</span>` },
        { key: "stock_id", label: t("common.stock"), render: (r) => `<b>${esc(r.stock_id)}</b>` },
        { key: "side", label: t("bot.col_side"), render: (r) => esc(t(`side.${r.side}`)) },
        { key: "ret", label: t("bot.col_return"), align: "r", cls: (r) => cls(r.ret), render: (r) => esc(fmt.pct(r.ret)) },
        { key: "stake", label: t("bot.col_stake"), align: "r", render: (r) => esc(fmt.num(r.stake, 0)) },
        { key: "pnl", label: t("bot.col_profit"), align: "r", cls: (r) => cls(r.pnl), render: (r) => esc(money(r.pnl)) },
        { key: "reason", label: t("bot.col_reason"), render: (r) => esc(reason(r)), value: (r) => reason(r) },
      ],
    }).set(d.trades);
    const modal = document.querySelector(".modal");
    modal.classList.add("wide");
    await SS.dialog({ title: t("bot.detail.title"), body, buttons: [{ label: "OK", value: true, kind: "primary" }] });
    modal.classList.remove("wide");
  }

  // ---------------------------------------------------------------- refresh
  function renderThoughts(list, status) {
    const age = status && status.last_ms ? Math.max(0, Math.round((status.now_ms - status.last_ms) / 1000)) : null;
    const el = q('[data-role="think-status"]');
    el.className = `think-status ${age !== null && age <= 10 ? "alive" : "stale"}`;
    el.textContent = age !== null && age <= 10 ? `● ${t("bot.think_alive", { s: age, n: status.watching })}`
      : `● ${t("bot.think_stale", { s: age ?? "–" })}`;
    list = [...list].sort((a, b) => b.time - a.time);          // newest first
    const sig = list.length ? `${list[0].time}:${list.length}` : "";
    if (sig === S.thinkSig) return;
    S.thinkSig = sig;
    const box = q('[data-role="thoughts"]');
    box.innerHTML = list.map((x) =>
      `<div class="item${x.code.startsWith("enter_") ? " decision" : ""}${x.code.startsWith("event") ? " link" : ""}" data-code="${esc(x.code)}"><span class="t">${esc(fmt.clock(x.time, true))}</span><span title="${esc(x.msg)}">${esc(x.msg)}</span></div>`).join("")
      || `<div class="muted">–</div>`;
    box.onclick = (e) => { const it = e.target.closest(".item.link"); if (it && !String(window.getSelection()).length) SS.goto("automation"); };
  }

  function renderLog(journal) {
    const sig = journal.length ? `${journal[0].id}:${journal.length}` : "";
    if (sig === S.logSig) return;
    S.logSig = sig;
    q('[data-role="log"]').innerHTML = journal.map((x) =>
      `<div class="item"><span class="t">${esc(fmt.clock(x.time, true))}</span><span title="${esc(x.msg)}">${esc(x.msg)}</span></div>`).join("")
      || `<div class="muted">–</div>`;
  }

  async function refresh() {
    const d = await SS.call("bot");
    if (!d || !d.settings) return;
    S.data = d;
    if (!S.busy) { S.settings = d.settings; fill(false); }
    syncStocks(d);
    const badge = q('[data-role="state"]');
    badge.textContent = d.state.text;
    badge.className = "badge " + (d.state.tone === "ok" ? "ok" : d.state.tone === "warn" ? "" : "neutral");

    const r = d.results, k = S.kpis;
    k.set("gain", r.n ? money(r.gain) : "–", r.n ? cls(r.gain) : "");
    k.set("n", r.n ? String(r.n) : "–");
    k.set("win", r.n ? fmt.pct(r.win_rate, false) : "–");
    k.set("best", r.best ? fmt.pct(r.best.ret) : "–", r.best ? cls(r.best.ret) : "", r.best ? r.best.sid : null);
    k.set("worst", r.worst ? fmt.pct(r.worst.ret) : "–", r.worst ? cls(r.worst.ret) : "", r.worst ? r.worst.sid : null);
    const none = q('[data-role="none"]');
    none.textContent = r.none;
    none.classList.toggle("hidden", r.n > 0);

    S.pos.set(d.positions);
    renderLog(d.journal);
    renderThoughts(d.thoughts || [], d.think_status);

    const test = d.test, run = q('[data-role="run"]');
    run.disabled = test.state === "running";
    q('[data-role="detail"]').disabled = !test.has_detail;
    q('[data-role="result"]').textContent = test.state === "running" ? t("bot.running") : test.text;
    syncCapital();
  }
  const refreshNow = (force = false) => refresh().then(() => force && fill(true)).catch((e) => console.error(e));

  async function warnOnce() {
    if (await SS.call("bot_experimental", false)) return;
    await SS.dialog({ title: t("bot.experimental_title"), body: t("bot.experimental_text"),
      buttons: [{ label: "OK", value: true, kind: "primary" }] });
    SS.call("bot_experimental", true);
  }

  SS.registerTab("bot", { mount, refresh, show: () => { refreshNow(); warnOnce(); } });
})();
