/* News tab: market news (high/low alerts) and scheduled pump/crash events with countdown. */
"use strict";

(() => {
  const { t, fmt, esc } = SS;
  const S = { el: null, news: null, sched: null, colors: {} };
  const q = (sel) => S.el.querySelector(sel);
  const stock = (r) => `<b style="color:${S.colors[r.stock] || "inherit"}">${esc(r.stock)}</b>`;
  const clock = (ms) => `<span class="mono">${esc(fmt.clock(ms, true))}</span>`;

  function mount(el) {
    S.el = el;
    el.innerHTML = `
      <div class="nw">
        <section class="panel box"><h2>${esc(t("news.market"))}</h2><div data-role="news" class="grow"></div></section>
        <section class="panel box"><h2>${esc(t("news.scheduled"))}</h2><div data-role="sched" class="grow"></div></section>
      </div>`;
    S.news = SS.ui.table(q('[data-role="news"]'), {
      sortKey: "time", empty: "–", rowClass: (r) => (r.kind === "high" ? "up" : r.kind === "low" ? "down" : ""),
      columns: [
        { key: "time", label: t("common.time"), render: (r) => clock(r.time) },
        { key: "stock", label: t("common.stock"), render: stock },
        { key: "kind", label: t("news.signal"), cls: (r) => (r.kind === "high" ? "up" : r.kind === "low" ? "down" : ""),
          render: (r) => esc(r.kind === "high" ? t("news.high") : r.kind === "low" ? t("news.low") : r.kind) },
        { key: "price", label: t("news.price"), align: "r", render: (r) => esc(fmt.price(r.price)) },
        { key: "lookback", label: t("news.lookback"), align: "r", render: (r) => (r.lookback == null ? "" : `${esc(String(r.lookback))} min`) },
      ],
    });
    S.sched = SS.ui.table(q('[data-role="sched"]'), {
      sortKey: "scheduled", empty: "–",
      rowClass: (r) => (r.countdown < 0 ? "muted" : r.direction === "crash" ? "down" : "up"),
      columns: [
        { key: "stock", label: t("common.stock"), render: stock },
        { key: "direction", label: t("news.direction"),
          render: (r) => esc(["pump", "crash"].includes(r.direction) ? t(`event.${r.direction}`) : r.direction) },
        { key: "target", label: t("news.target"), align: "r", render: (r) => esc(fmt.price(r.target)) },
        { key: "scheduled", label: t("news.scheduled_for"), render: (r) => clock(r.scheduled) },
        { key: "published", label: t("news.published"), render: (r) => clock(r.published) },
        { key: "countdown", label: t("common.status"), align: "r",
          render: (r) => esc(r.countdown >= 0 ? t("news.in", { countdown: fmt.duration(r.countdown / 1000) }) : t("news.past")) },
      ],
    });
  }

  async function refresh() {
    const d = await SS.call("news");
    if (!d || !d.news) return;
    S.colors = d.colors || {};
    const now = d.server_now || 0;
    S.news.set(d.news);
    S.sched.set(d.scheduled.map((r) => ({ ...r, countdown: now ? r.scheduled - now : -1 })));
  }

  SS.registerTab("news", { mount, refresh });
})();
