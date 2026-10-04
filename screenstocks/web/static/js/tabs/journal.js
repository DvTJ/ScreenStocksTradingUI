/* Journal tab: trades with realized P/L, summary KPIs and P/L per stock. */
"use strict";

(() => {
  const { t, fmt, esc, cls } = SS;
  const S = { el: null, range: null, kpis: null, trades: null, per: null, last: 0 };
  const INTERVAL_MS = 5000;              // trades of all stocks: refresh every 5 s like the classic tab
  const q = (sel) => S.el.querySelector(sel);
  const money = (v) => esc(fmt.big(v));

  function mount(el) {
    S.el = el;
    el.innerHTML = `
      <div class="jr">
        <div data-role="kpis"></div>
        <div class="toolbar"><div data-role="range"></div><span class="note">${esc(t("journal.note"))}</span></div>
        <div class="jr-grid">
          <section class="panel box"><h2>${esc(t("journal.trades"))}</h2><div data-role="trades" class="grow"></div></section>
          <section class="panel box"><h2>${esc(t("journal.per_stock"))}</h2><div data-role="per" class="grow"></div></section>
        </div>
      </div>`;
    S.kpis = SS.ui.kpis(q('[data-role="kpis"]'), [
      { key: "realized", label: t("journal.realized") }, { key: "dividends", label: t("journal.dividends") },
      { key: "total", label: t("journal.total") }, { key: "hit", label: t("journal.hit_rate") },
      { key: "avg_win", label: t("journal.avg_win") }, { key: "avg_loss", label: t("journal.avg_loss") },
      { key: "best", label: t("journal.best") }, { key: "worst", label: t("journal.worst") },
    ]);
    S.range = SS.ui.rangeBar(q('[data-role="range"]'), "24h", () => { S.last = 0; refresh(); });
    S.trades = SS.ui.table(q('[data-role="trades"]'), {
      sortKey: "time", empty: "–", rowClass: (r) => cls(r.pnl),
      columns: [
        { key: "time", label: t("common.time"), render: (r) => `<span class="mono">${esc(fmt.clock(r.time, true))}</span>` },
        { key: "stock", label: t("common.stock"), render: (r) => `<b>${esc(r.stock)}</b>` },
        { key: "kind", label: t("journal.col_kind"), render: (r) => esc(t(`tradekind.${r.kind}`)) },
        { key: "shares", label: t("journal.col_shares"), align: "r", render: (r) => money(r.shares) },
        { key: "price", label: t("common.price"), align: "r", render: (r) => esc(fmt.price(r.price)) },
        { key: "entry", label: t("journal.col_entry"), align: "r", render: (r) => (r.entry ? esc(fmt.price(r.entry)) : "") },
        { key: "pnl", label: t("common.pl"), align: "r", cls: (r) => cls(r.pnl), render: (r) => (r.pnl != null ? money(r.pnl) : "") },
        { key: "pnl_pct", label: t("pf.pl_pct"), align: "r", cls: (r) => cls(r.pnl_pct), render: (r) => (r.pnl_pct != null ? esc(fmt.pct(r.pnl_pct)) : "") },
      ],
    });
    S.per = SS.ui.table(q('[data-role="per"]'), {
      sortKey: "pnl", empty: "–", rowClass: (r) => cls(r.pnl),
      columns: [
        { key: "stock", label: t("common.stock"), render: (r) => `<b>${esc(r.stock)}</b>` },
        { key: "closed", label: t("journal.col_closed"), align: "r" },
        { key: "wins", label: t("journal.col_wins"), align: "r" },
        { key: "pnl", label: t("journal.col_realized"), align: "r", cls: (r) => cls(r.pnl), render: (r) => money(r.pnl) },
      ],
    });
  }

  async function refresh() {
    if (Date.now() - S.last < INTERVAL_MS) return;
    S.last = Date.now();
    const d = await SS.call("journal", S.range.get());
    if (!d || !d.trades) return;
    const k = S.kpis;
    k.set("realized", d.realized != null ? fmt.big(d.realized) : "–", cls(d.realized));
    k.set("dividends", d.dividends ? fmt.big(d.dividends) : "–", d.dividends ? "up" : "");
    k.set("total", d.total != null ? fmt.big(d.total) : "–", cls(d.total));
    k.set("hit", d.hit_rate != null ? fmt.pct(d.hit_rate, false) : "–", "", d.closed ? `${d.wins}/${d.closed}` : null);
    k.set("avg_win", d.avg_win != null ? fmt.big(d.avg_win) : "–", d.avg_win ? "up" : "");
    k.set("avg_loss", d.avg_loss != null ? fmt.big(d.avg_loss) : "–", d.avg_loss ? "down" : "");
    k.set("best", d.best ? fmt.big(d.best.pnl) : "–", d.best ? cls(d.best.pnl) : "", d.best ? d.best.stock : null);
    k.set("worst", d.worst ? fmt.big(d.worst.pnl) : "–", d.worst ? cls(d.worst.pnl) : "", d.worst ? d.worst.stock : null);
    S.trades.set(d.trades);
    S.per.set(d.per_stock);
  }

  SS.registerTab("journal", { mount, refresh, show: () => { S.last = 0; } });
})();
