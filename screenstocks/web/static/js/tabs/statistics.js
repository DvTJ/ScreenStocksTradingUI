/* Statistics tab: price behaviour per stock and the average move after market news. */
"use strict";

(() => {
  const { t, fmt, esc, cls } = SS;
  const INTERVAL_S = 15;              // same as the classic tab: the calculation reads all prices of the range
  const S = { el: null, range: null, prices: null, news: null, last: 0, busy: false };
  const q = (sel) => S.el.querySelector(sel);
  const pct = (v) => esc(fmt.pct(v));
  const upct = (v) => esc(fmt.pct(v, false));
  const stock = (r) => `<b>${esc(r.stock)}</b>`;

  function mount(el) {
    S.el = el;
    el.innerHTML = `
      <div class="st">
        <div class="toolbar"><div data-role="range"></div><span class="note" data-role="updated"></span></div>
        <section class="panel box">
          <h2>${esc(t("stats.prices"))}</h2><div class="note">${esc(t("stats.prices_note"))}</div>
          <div data-role="prices" class="grow"></div>
        </section>
        <section class="panel box">
          <h2>${esc(t("stats.news"))}</h2><div class="note">${esc(t("stats.news_note"))}</div>
          <div data-role="news" class="grow"></div>
        </section>
      </div>`;
    S.range = SS.ui.rangeBar(q('[data-role="range"]'), "1h", () => { S.last = 0; refresh(); });
    S.prices = SS.ui.table(q('[data-role="prices"]'), {
      sortKey: "stock", sortDesc: false, empty: "–", rowClass: (r) => cls(r.dist),
      columns: [
        { key: "stock", label: t("common.stock"), render: stock },
        { key: "last", label: t("common.price"), align: "r", render: (r) => esc(fmt.price(r.last)) },
        { key: "lo", label: t("stats.col_min"), align: "r", render: (r) => esc(fmt.price(r.lo)) },
        { key: "hi", label: t("stats.col_max"), align: "r", render: (r) => esc(fmt.price(r.hi)) },
        { key: "spread", label: t("stats.col_spread"), align: "r", render: (r) => upct(r.spread) },
        { key: "vol_min", label: t("stats.col_vol_min"), align: "r", render: (r) => upct(r.vol_min) },
        { key: "vol_h", label: t("stats.col_vol_h"), align: "r", render: (r) => upct(r.vol_h) },
        { key: "base", label: t("col.base"), align: "r", render: (r) => esc(fmt.price(r.base)) },
        { key: "dist", label: t("stats.col_dist"), align: "r", cls: (r) => cls(r.dist), render: (r) => pct(r.dist) },
        { key: "above", label: t("stats.col_above"), align: "r", render: (r) => upct(r.above) },
        { key: "below", label: t("stats.col_below"), align: "r", render: (r) => upct(r.below) },
        { key: "cross", label: t("stats.col_cross"), align: "r", render: (r) => (r.cross == null ? "–" : String(r.cross)) },
      ],
    });
    const effect = (key, label) => ({ key, label, align: "r", cls: (r) => cls(r[key]), render: (r) => pct(r[key]) });
    S.news = SS.ui.table(q('[data-role="news"]'), {
      sortKey: "stock", sortDesc: false, empty: "–",
      columns: [
        { key: "stock", label: t("common.stock"), render: stock },
        { key: "n_high", label: t("stats.col_n_high"), align: "r" },
        effect("h1", t("stats.col_high_1")), effect("h5", t("stats.col_high_5")), effect("h15", t("stats.col_high_15")),
        { key: "n_low", label: t("stats.col_n_low"), align: "r" },
        effect("l1", t("stats.col_low_1")), effect("l5", t("stats.col_low_5")), effect("l15", t("stats.col_low_15")),
      ],
    });
  }

  async function refresh() {
    if (S.busy || Date.now() - S.last < INTERVAL_S * 1000) return;
    S.busy = true;
    try {
      const d = await SS.call("statistics", S.range.get());
      if (!d || !d.prices) return;
      S.last = Date.now();
      S.prices.set(d.prices);
      S.news.set(d.news);
      q('[data-role="updated"]').textContent = t("stats.updated", { time: fmt.clock(d.calculated), s: INTERVAL_S });
    } finally { S.busy = false; }
  }

  SS.registerTab("stats", { mount, refresh });
})();
