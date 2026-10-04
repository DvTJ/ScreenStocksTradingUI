/* Compare tab: all stocks on one chart, normalised to % change since the start of the range. */
"use strict";

(() => {
  const { t, fmt, esc } = SS;
  const RELOAD_MS = 10_000;          // 8 stocks x 2000 points - reload less often than every tick
  const DETAIL_TARGET = 2000;        // load full detail when fewer than this many points are visible
  const S = { el: null, range: null, chart: null, zero: null, key: "", hidden: new Set(), data: {}, bases: {},
              offset: 0, bucketMs: 0, last: 0, busy: false };
  const q = (sel) => S.el.querySelector(sel);

  function mount(el) {
    S.el = el;
    el.innerHTML = `
      <div class="cmp">
        <div class="toolbar"><div data-role="range"></div><div class="chips" data-role="chips"></div></div>
        <section class="panel" data-role="chart"></section>
      </div>`;
    S.range = SS.ui.rangeBar(q('[data-role="range"]'), "1h", () => { S.chart.resetZoom(); S.last = 0; refresh(); });
    S.chart = SS.ui.lineChart(q('[data-role="chart"]'), { series: [], priceFormat: (v) => fmt.pct(v) });
    S.zero = S.chart.chart.addSeries(LightweightCharts.LineSeries, {
      color: "#5c636c", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });
    q('[data-role="chips"]').onclick = (e) => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      const id = chip.dataset.id, on = S.hidden.has(id);
      if (on) S.hidden.delete(id); else S.hidden.add(id);
      chip.classList.toggle("off", !on);
      S.chart.setVisible(id, on);
    };
    let detailTimer = null;
    S.chart.chart.timeScale().subscribeVisibleTimeRangeChange(() => {
      clearTimeout(detailTimer);
      detailTimer = setTimeout(maybeLoadDetail, 350);
    });
  }

  /** New or recoloured stocks: rebuild chips and chart series. */
  function syncStocks(stocks) {
    const key = stocks.map((s) => s.id + s.color).join("|");
    if (key === S.key) return;
    S.key = key;
    q('[data-role="chips"]').innerHTML = stocks.map((s) =>
      `<button class="chip ${S.hidden.has(s.id) ? "off" : ""}" data-id="${esc(s.id)}" style="--c:${s.color}"><i></i>${esc(s.id)}</button>`).join("");
    S.chart.setSeries(stocks.map((s) => ({ key: s.id, label: s.id, color: s.color })));
    for (const id of S.hidden) S.chart.setVisible(id, false);
  }

  async function refresh() {
    if (S.busy || Date.now() - S.last < RELOAD_MS) return;
    if (S.last && S.chart.isZoomed()) return;           // keep a zoomed view (and its detail) still
    S.busy = true;
    try {
      const d = await SS.call("compare", S.range.get());
      if (!d || !d.stocks) return;
      S.last = Date.now();
      syncStocks(d.stocks);
      S.offset = d.offset; S.bucketMs = d.bucket_ms || 0;
      S.data = {}; S.bases = {};
      for (const s of d.stocks) { S.data[s.id] = s.data; S.bases[s.id] = s.base; }
      setZero();
      S.chart.setData(S.data, d.offset);
    } finally { S.busy = false; }
  }

  function setZero() {
    const times = Object.values(S.data).filter((a) => a.length).flatMap((a) => [a[0].time, a[a.length - 1].time]);
    S.zero.setData(times.length ? [{ time: Math.min(...times), value: 0 }, { time: Math.max(...times), value: 0 }] : []);
  }

  /** In deep zooms of a thinned range, replace the visible part with full-resolution points. */
  async function maybeLoadDetail() {
    if (!S.chart.isZoomed() || S.bucketMs <= 1000 || S.busy) return;
    const vis = S.chart.chart.timeScale().getVisibleRange();
    if (!vis) return;
    const span = vis.to - vis.from;
    if ((span * 1000) / S.bucketMs > DETAIL_TARGET) return;
    const pad = Math.ceil(span * 0.25);
    S.busy = true;
    try {
      const res = await SS.call("compare_detail", vis.from - pad, vis.to + pad, S.offset, S.bases);
      for (const [id, pts] of Object.entries(res || {})) {
        if (!pts.length || !S.data[id]) continue;
        const from = pts[0].time, to = pts[pts.length - 1].time;
        S.data[id] = S.data[id].filter((p) => p.time < from).concat(pts, S.data[id].filter((p) => p.time > to));
      }
      const range = S.chart.chart.timeScale().getVisibleRange();
      S.chart.setData(S.data, S.offset);
      if (range) S.chart.chart.timeScale().setVisibleRange(range);
    } finally { S.busy = false; }
  }

  SS.registerTab("compare", { mount, refresh, show: () => { if (!S.chart.isZoomed()) S.last = 0; } });
})();
