/* Shared UI components: KPI cards, sortable table, range bar, line chart with zoom. */
"use strict";

(() => {
  const { t, fmt, esc } = SS;
  const ui = (SS.ui = {});

  ui.RANGES = ["1m", "5m", "15m", "1h", "6h", "24h", "all"];

  /** Segmented range buttons. Returns {get()}. */
  ui.rangeBar = (el, initial, onChange) => {
    let value = initial;
    el.className = "seg";
    el.innerHTML = ui.RANGES.map((r) => `<button data-r="${r}" class="${r === value ? "active" : ""}">${r === "all" ? esc(t("common.all")) : r}</button>`).join("");
    el.onclick = (e) => {
      const r = e.target.dataset.r;
      if (!r || r === value) return;
      value = r;
      el.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.r === r));
      onChange(r);
    };
    return { get: () => value };
  };

  /** KPI cards: items = [{key, label}] -> {set(key, text, kind, sub)} */
  ui.kpis = (el, items) => {
    el.className = "kpi-row";
    el.innerHTML = items.map((i) => `<div class="kcard" data-k="${i.key}"><label>${esc(i.label)}</label><div class="v">–</div><div class="sub hidden"></div></div>`).join("");
    return {
      set(key, text, kind = "", sub = null) {
        const card = el.querySelector(`[data-k="${key}"]`);
        const v = card.querySelector(".v");
        v.textContent = text;
        v.className = "v " + kind;
        const s = card.querySelector(".sub");
        s.classList.toggle("hidden", !sub);
        if (sub) { s.textContent = sub; s.title = sub; }
      },
    };
  };

  /**
   * Sortable table. columns: [{key, label, align: "r", render(row) -> html, value(row) -> sort value}]
   * Returns {set(rows)}; re-renders only when the data changed.
   */
  ui.table = (el, { columns, sortKey, sortDesc = true, rowClass, empty, rowKey }) => {
    let rows = [], sig = "";
    let key = sortKey, desc = sortDesc;
    el.innerHTML = `<div class="tbl-wrap"><table class="tbl"><thead><tr>${columns.map((c) =>
      `<th class="sortable ${c.align === "r" ? "r" : ""}" data-k="${c.key}">${esc(c.label)}</th>`).join("")}</tr></thead><tbody></tbody></table></div>`;
    const head = el.querySelector("thead"), body = el.querySelector("tbody");
    const valueOf = (c, r) => (c.value ? c.value(r) : r[c.key]);

    function render(force) {
      const col = columns.find((c) => c.key === key);
      const sorted = [...rows];
      if (col) {
        sorted.sort((a, b) => {
          const va = valueOf(col, a), vb = valueOf(col, b);
          if (va == null && vb == null) return 0;
          if (va == null) return 1;                 // empty values always at the bottom
          if (vb == null) return -1;
          const cmp = typeof va === "string" ? va.localeCompare(vb) : va - vb;
          return desc ? -cmp : cmp;
        });
      }
      const html = sorted.length ? sorted.map((r) => `<tr class="${rowClass ? rowClass(r) : ""}">${columns.map((c) =>
        `<td class="${c.align === "r" ? "r" : ""} ${c.cls ? c.cls(r) : ""}">${c.render ? c.render(r) : esc(r[c.key] ?? "")}</td>`).join("")}</tr>`).join("")
        : `<tr><td colspan="${columns.length}" class="empty-row">${esc(empty || "–")}</td></tr>`;
      if (!force && html === sig) return;
      sig = html;
      body.innerHTML = html;
      head.querySelectorAll("th").forEach((th) => {
        th.classList.toggle("sorted", th.dataset.k === key);
        th.classList.toggle("asc", th.dataset.k === key && !desc);
      });
    }
    head.onclick = (e) => {
      const th = e.target.closest("th");
      if (!th) return;
      if (th.dataset.k === key) desc = !desc;
      else { key = th.dataset.k; desc = typeof valueOf(columns.find((c) => c.key === key), rows[0] || {}) !== "string"; }
      render(true);
    };
    render(true);
    return { set(newRows) { rows = newRows || []; render(false); } };
  };

  /**
   * Line chart (TradingView Lightweight Charts) with legend, wheel/drag zoom, Shift+drag
   * rectangle zoom and reset (double-click / button). series: [{key, label, color, area}]
   * setData({key: points}, offset) - points are {time, value} with local-shifted seconds.
   * setSeries(list) replaces the series (e.g. when stocks appear), setVisible(key, on) hides one.
   */
  ui.lineChart = (el, { series, priceFormat = fmt.price }) => {
    const LW = LightweightCharts;
    el.classList.add("chart-box");
    el.innerHTML = `<div class="lw"></div><div class="legend"></div><div class="zoombox hidden"></div>
      <button class="btn reset-zoom hidden">↺ ${esc(t("chart.reset_zoom"))}</button><div class="empty hidden">${esc(t("common.no_data"))}</div>`;
    const chart = LW.createChart(el.querySelector(".lw"), {
      autoSize: true,
      layout: { background: { type: "solid", color: "transparent" }, textColor: "#8b919a", fontFamily: "Segoe UI, sans-serif", fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: "#1c1f23" }, horzLines: { color: "#1c1f23" } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.15, bottom: 0.08 } },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: true, rightOffset: 4 },
      crosshair: { mode: LW.CrosshairMode.Normal, vertLine: { color: "#3a3f46", labelBackgroundColor: "#2a2e34" }, horzLine: { color: "#3a3f46", labelBackgroundColor: "#2a2e34" } },
      localization: { priceFormatter: priceFormat, locale: SS.locale() },
    });
    let handles = {}, list = [];
    const hidden = new Set();
    const state = { offset: 0, zoomed: false };
    const legend = el.querySelector(".legend"), reset = el.querySelector(".reset-zoom");
    const shown = () => list.filter((s) => !hidden.has(s.key));
    const legendHtml = (vals) => shown().map((s) => `<span><i style="background:${s.color}"></i>${esc(s.label)} <b>${vals && vals[s.key] != null ? esc(priceFormat(vals[s.key])) : ""}</b></span>`).join("");

    function build(next) {
      for (const h of Object.values(handles)) chart.removeSeries(h);
      handles = {};
      list = next;
      for (const s of list) {
        handles[s.key] = s.area
          ? chart.addSeries(LW.AreaSeries, { lineColor: s.color, topColor: s.color + "44", bottomColor: s.color + "04", lineWidth: 2, priceLineVisible: false })
          : chart.addSeries(LW.LineSeries, { color: s.color, lineWidth: 2, priceLineVisible: false });
        if (hidden.has(s.key)) handles[s.key].applyOptions({ visible: false });
      }
      legend.innerHTML = legendHtml(null);
    }
    build(series);

    chart.subscribeCrosshairMove((p) => {
      if (!p || !p.time || !p.seriesData || !p.seriesData.size) { legend.innerHTML = legendHtml(null); return; }
      const vals = {};
      for (const s of list) { const d = p.seriesData.get(handles[s.key]); vals[s.key] = d ? d.value : null; }
      legend.innerHTML = `<span>${esc(fmt.clock((p.time - state.offset) * 1000, true))}</span>` + legendHtml(vals);
    });
    const setZoomed = (on) => { state.zoomed = on; reset.classList.toggle("hidden", !on); };
    const doReset = () => { chart.priceScale("right").applyOptions({ autoScale: true }); chart.timeScale().fitContent(); setZoomed(false); };
    reset.onclick = doReset;
    el.addEventListener("dblclick", doReset);
    el.addEventListener("wheel", () => setZoomed(true), { passive: true });
    // the rectangle converts y to a price via the first visible series (all share the right price scale)
    ui.rectZoom(el, chart, { coordinateToPrice: (y) => { const s = shown()[0]; return s ? handles[s.key].coordinateToPrice(y) : null; } },
      () => setZoomed(true));

    return {
      chart,
      setData(data, offset) {
        state.offset = offset || 0;
        let any = false;
        for (const s of list) { const pts = data[s.key] || []; handles[s.key].setData(pts); any = any || pts.length > 0; }
        el.querySelector(".empty").classList.toggle("hidden", any);
        if (!state.zoomed) chart.timeScale().fitContent();
      },
      setSeries: build,
      setVisible(key, on) {
        if (on) hidden.delete(key); else hidden.add(key);
        if (handles[key]) handles[key].applyOptions({ visible: on });
        legend.innerHTML = legendHtml(null);
      },
      series: (key) => handles[key],
      isZoomed: () => state.zoomed,
      resetZoom: doReset,
    };
  };

  /** Shift + drag: rectangle zoom on time and price (flat drag = time only); plain drag counts as zoom. */
  ui.rectZoom = (wrap, chart, series, onZoomed) => {
    const box = wrap.querySelector(".zoombox");
    let start = null, pan = null;
    const pos = (e) => { const r = wrap.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    wrap.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      if (!e.shiftKey) { pan = { x: e.clientX, y: e.clientY }; return; }
      e.stopPropagation(); e.preventDefault();
      start = pos(e);
      Object.assign(box.style, { left: `${start.x}px`, top: `${start.y}px`, width: "0px", height: "0px" });
      box.classList.remove("hidden");
    }, true);
    window.addEventListener("mousemove", (e) => {
      if (pan && Math.hypot(e.clientX - pan.x, e.clientY - pan.y) > 5) { onZoomed(); pan = null; }
      if (!start) return;
      const p = pos(e);
      Object.assign(box.style, {
        left: `${Math.min(p.x, start.x)}px`, top: `${Math.min(p.y, start.y)}px`,
        width: `${Math.abs(p.x - start.x)}px`, height: `${Math.abs(p.y - start.y)}px`,
      });
    }, true);
    window.addEventListener("mouseup", (e) => {
      pan = null;
      if (!start) return;
      const p = pos(e), s = start;
      start = null;
      box.classList.add("hidden");
      if (Math.abs(p.x - s.x) < 8) return;
      const ts = chart.timeScale();
      const t1 = ts.coordinateToTime(Math.min(p.x, s.x)), t2 = ts.coordinateToTime(Math.max(p.x, s.x));
      if (t1 == null || t2 == null) return;
      ts.setVisibleRange({ from: t1, to: t2 });
      if (Math.abs(p.y - s.y) >= 8) {
        const v1 = series.coordinateToPrice(Math.min(p.y, s.y)), v2 = series.coordinateToPrice(Math.max(p.y, s.y));
        if (v1 != null && v2 != null) chart.priceScale("right").setVisibleRange({ from: Math.min(v1, v2), to: Math.max(v1, v2) });
      }
      onZoomed();
    }, true);
  };
})();
