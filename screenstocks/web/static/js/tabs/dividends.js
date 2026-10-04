/* Dividends tab: ranking of all stocks by dividend yield per invested money. */
"use strict";

(() => {
  const { t, fmt, esc } = SS;
  const S = { el: null, table: null };
  const q = (sel) => S.el.querySelector(sel);

  function mount(el) {
    S.el = el;
    el.innerHTML = `
      <div class="div-tab">
        <section class="panel box div-info"><div class="info" data-role="info"></div><div class="note">${esc(t("div.note"))}</div></section>
        <section class="panel box grow"><div data-role="table" class="grow"></div></section>
      </div>`;
    S.table = SS.ui.table(q('[data-role="table"]'), {
      sortKey: "yield_h", empty: "–",
      rowClass: (r) => (r.own ? "up" : r.buyable ? "" : "muted"),
      columns: [
        { key: "stock", label: t("common.stock"), render: (r) => `<b>${esc(r.stock)}</b>` },
        { key: "price", label: t("common.price"), align: "r", render: (r) => esc(fmt.price(r.price)) },
        { key: "rate", label: t("div.col_rate"), align: "r", render: (r) => esc(fmt.pct(r.rate, false)) },
        { key: "yield_min", label: t("div.col_yield_min"), align: "r", render: (r) => esc(fmt.pct(r.yield_min, false)) },
        { key: "yield_h", label: t("div.col_yield_h"), align: "r", render: (r) => `<b>${esc(fmt.pct(r.yield_h, false))}</b>` },
        { key: "per_mio", label: t("div.col_per_mio"), align: "r", render: (r) => esc(fmt.big(r.per_mio)) },
        { key: "own", label: t("div.col_own"), align: "r", cls: (r) => (r.own ? "up" : ""), render: (r) => (r.own ? esc(fmt.big(r.own)) : "") },
        { key: "available", label: t("col.available"), align: "r", render: (r) => esc(fmt.big(r.available)) },
        { key: "buyable", label: t("div.col_buyable"), align: "r", value: (r) => (r.buyable ? 1 : 0),
          render: (r) => (r.buyable ? '<span class="up">✔</span>' : '<span class="down">✖</span>') },
      ],
    });
  }

  async function refresh() {
    const d = await SS.call("dividend_ranking");
    if (!d || !d.rows) return;
    q('[data-role="info"]').textContent = d.factor
      ? t("div.info_factor", { f: fmt.num(d.factor, 2), n: d.factor_n }) : t("div.info_no_factor");
    S.table.set(d.rows);
  }

  SS.registerTab("dividends", { mount, refresh });
})();
