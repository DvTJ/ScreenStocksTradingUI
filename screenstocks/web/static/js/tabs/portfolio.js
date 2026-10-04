/* Portfolio tab: KPIs, net worth/cash chart, positions, position changes, dividend payouts. */
"use strict";

(() => {
  const { t, fmt, esc, cls } = SS;
  const S = { el: null, range: null, kpis: null, chart: null, pos: null, chg: null, pay: null, lastChart: 0, busy: false };
  const CHART_INTERVAL_MS = 10_000;          // the chart holds thousands of points - reload it less often
  const q = (sel) => S.el.querySelector(sel);
  const money = (v) => esc(fmt.big(v));

  function mount(el) {
    S.el = el;
    el.innerHTML = `
      <div class="pf">
        <div data-role="kpis"></div>
        <div class="toolbar"><div data-role="range"></div></div>
        <section class="panel pf-chart" data-role="chart"></section>
        <div class="pf-bottom">
          <section class="panel box"><h2>${esc(t("pf.positions"))}</h2><div data-role="pos" class="grow"></div></section>
          <section class="panel box"><h2>${esc(t("pf.changes"))}</h2><div data-role="chg" class="grow"></div></section>
          <section class="panel box"><h2>${esc(t("pf.dividends"))}</h2><div data-role="pay" class="grow"></div></section>
        </div>
      </div>`;
    S.kpis = SS.ui.kpis(q('[data-role="kpis"]'), [
      { key: "net", label: t("common.net_worth") }, { key: "cash", label: t("common.cash") },
      { key: "invested", label: t("pf.invested") }, { key: "delta", label: t("pf.delta") },
      { key: "pl", label: t("pf.open_pl") }, { key: "div", label: t("pf.div_min") },
      { key: "received", label: t("pf.div_received") },
    ]);
    S.range = SS.ui.rangeBar(q('[data-role="range"]'), "1h", () => { S.chart.resetZoom(); refreshAll(); });
    S.chart = SS.ui.lineChart(q('[data-role="chart"]'), {
      series: [{ key: "net", label: t("common.net_worth"), color: "#58a6ff", area: true }, { key: "cash", label: t("common.cash"), color: "#3fb950" }],
      priceFormat: fmt.big,
    });
    S.pos = SS.ui.table(q('[data-role="pos"]'), {
      sortKey: "value", empty: "–", rowClass: (r) => cls((r.pl || 0) + (r.short_pl || 0)),
      columns: [
        { key: "stock", label: t("common.stock"), render: (r) => `<b>${esc(r.stock)}</b>` },
        { key: "owned", label: t("common.owned"), align: "r", render: (r) => (r.owned ? money(r.owned) : "") },
        { key: "avg", label: t("common.avg_buy"), align: "r", render: (r) => (r.owned ? esc(fmt.price(r.avg)) : "") },
        { key: "price", label: t("common.price"), align: "r", render: (r) => esc(fmt.price(r.price)) },
        { key: "value", label: t("pf.value"), align: "r", render: (r) => (r.owned ? money(r.value) : "") },
        { key: "pl", label: t("common.pl"), align: "r", cls: (r) => cls(r.pl), render: (r) => (r.pl != null ? money(r.pl) : "") },
        { key: "plp", label: t("pf.pl_pct"), align: "r", cls: (r) => cls(r.plp), render: (r) => (r.owned ? esc(fmt.pct(r.plp)) : "") },
        { key: "short", label: t("common.short"), align: "r", render: (r) => (r.short ? money(r.short) : "") },
        { key: "avg_short", label: t("common.avg_short"), align: "r", render: (r) => (r.short ? esc(fmt.price(r.avg_short)) : "") },
        { key: "short_pl", label: t("pf.short_pl"), align: "r", cls: (r) => cls(r.short_pl), render: (r) => (r.short_pl != null ? money(r.short_pl) : "") },
        { key: "div", label: t("col.div_min"), align: "r", render: (r) => (r.div ? money(r.div) : "") },
      ],
    });
    S.chg = SS.ui.table(q('[data-role="chg"]'), {
      sortKey: "time", empty: "–",
      columns: [
        { key: "time", label: t("common.time"), render: (r) => `<span class="mono">${esc(fmt.clock(r.time, true))}</span>` },
        { key: "stock", label: t("common.stock"), render: (r) => `<b>${esc(r.stock)}</b>` },
        { key: "owned", label: t("common.owned"), align: "r", render: (r) => money(r.owned) },
        { key: "avg", label: t("common.avg_buy"), align: "r", render: (r) => esc(fmt.price(r.avg)) },
        { key: "short", label: t("common.short"), align: "r", render: (r) => money(r.short) },
      ],
    });
    S.pay = SS.ui.table(q('[data-role="pay"]'), {
      sortKey: "time", empty: "–",
      columns: [
        { key: "time", label: t("common.time"), render: (r) => `<span class="mono">${esc(fmt.clock(r.time, true))}</span>` },
        { key: "amount", label: t("pf.div_amount"), align: "r", cls: () => "up", render: (r) => money(r.amount) },
        { key: "factor", label: t("pf.div_factor_col"), align: "r", render: (r) => "×" + esc(fmt.num(r.factor, 2)) },
      ],
    });
  }

  async function refreshChart() {
    const c = await SS.call("portfolio_chart", S.range.get());
    S.chart.setData({ net: c.net, cash: c.cash }, c.offset);
    S.lastChart = Date.now();
  }

  async function refresh() {
    if (S.busy) return;                       // the 1 s tick must not stack calls while the chart loads
    S.busy = true;
    try { await load(); } finally { S.busy = false; }
  }

  async function load() {
    const d = await SS.call("portfolio", S.range.get());
    if (!d || d.positions === undefined) return;
    S.kpis.set("net", fmt.big(d.net));
    S.kpis.set("cash", fmt.big(d.cash));
    S.kpis.set("invested", fmt.big(d.invested));
    S.kpis.set("delta", d.delta != null ? `${fmt.big(d.delta)}` : "–", cls(d.delta), d.delta_pct != null ? fmt.pct(d.delta_pct) : null);
    S.kpis.set("pl", d.open_pl != null ? fmt.big(d.open_pl) : "–", cls(d.open_pl));
    const factor = d.factor ? t("pf.div_factor", { f: fmt.num(d.factor, 2), n: d.factor_n }) : t("pf.div_factor_unknown");
    S.kpis.set("div", d.div_min ? fmt.big(d.div_min) : "–", d.div_min ? "up" : "",
      (d.div_min ? t("pf.div_hour", { v: fmt.big(d.div_min * 60) }) + " · " : "") + factor);
    S.kpis.set("received", d.received ? fmt.big(d.received) : "–", d.received ? "up" : "");
    S.pos.set(d.positions);
    S.chg.set(d.changes);
    S.pay.set(d.payouts);
    if (Date.now() - S.lastChart > CHART_INTERVAL_MS) await refreshChart();
  }
  const refreshAll = () => { S.lastChart = 0; return refresh().catch((e) => console.error(e)); };

  SS.registerTab("portfolio", { mount, refresh, show: () => { S.lastChart = 0; } });
})();
