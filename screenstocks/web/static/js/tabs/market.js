/* Market tab: watchlist, TradingView chart (wheel/drag zoom + Shift-rectangle), trading, order log. */
"use strict";

(() => {
  const { t, fmt, esc, cls } = SS;
  const RANGES = ["1m", "5m", "15m", "1h", "6h", "24h", "all"];
  const TRADE_COLORS = { buy: "#3fb950", sell: "#f85149", short: "#a371f7", cover: "#58a6ff" };
  const LINE_COLORS = {
    avg_buy: "#58a6ff", avg_short: "#d2a8ff", event: "#d29922", stop_loss: "#f85149", take_profit: "#3fb950",
    trailing_stop: "#f0883e", buy_limit: "#56d4dd", short_limit: "#d2a8ff",
    trailing_buy: "#7ee787", trailing_short: "#ff7b72",
  };
  const DETAIL_TARGET = 2000;       // load full detail when fewer than this many points are visible

  // sortKey "id" (A–Z) by default: the rows do not jump around while clicking
  const S = {
    el: null, selected: null, range: "1h", sortKey: "id", rows: [], data: null, pct: 25, confirm: true,
    chart: null, series: null, markers: null, lines: [], offset: 0, lastMs: 0, times: [], bucketMs: 0,
    zoomed: false, loading: false, lastReload: 0, lastTradeState: null, factor: null,
  };
  const q = (sel) => S.el.querySelector(sel);

  // ------------------------------------------------------------------ layout
  function mount(el) {
    S.el = el;
    el.innerHTML = `
      <div class="market">
        <section class="panel watch">
          <div class="head">
            <h2>${esc(t("tab.market").trim())}</h2>
            <div class="seg" data-role="sort">
              <button data-sort="id" class="active">A–Z</button>
              <button data-sort="d5">Δ 5m</button>
              <button data-sort="pl">${esc(t("common.pl"))}</button>
              <button data-sort="div">${esc(t("col.div_min"))}</button>
            </div>
          </div>
          <div class="rows" data-role="rows"></div>
        </section>

        <section class="panel cpanel">
          <div class="chead">
            <div class="ctitle">
              <span class="swatch" data-role="swatch"></span>
              <div><div class="ticker" data-role="ticker">–</div><div class="ticker-sub" data-role="name"></div></div>
              <div class="bigprice" data-role="price">–</div>
              <span class="pill" data-role="change">–</span>
            </div>
            <div class="ctools">
              <div class="seg" data-role="ranges">${RANGES.map((r) => `<button data-r="${r}">${r === "all" ? esc(t("common.all")) : r}</button>`).join("")}</div>
              <button class="btn ghost" data-role="export">${esc(t("market.export_csv"))}</button>
            </div>
          </div>
          <div class="event-banner hidden" data-role="event"></div>
          <div class="cwrap" data-role="cwrap">
            <div class="cchart" data-role="chart"></div>
            <div class="legend" data-role="legend"></div>
            <div class="zoombox hidden" data-role="zoombox"></div>
            <button class="btn reset-zoom hidden" data-role="reset">↺ ${esc(t("chart.reset_zoom"))}</button>
            <div class="empty hidden" data-role="empty">${esc(t("market.no_prices"))}</div>
          </div>
          <div class="cstats" data-role="stats"></div>
          <div class="cfoot">
            <span class="hint" title="${esc(t("web.zoom_hint"))}">${esc(t("web.zoom_hint"))}</span>
            <a class="attribution" data-role="attribution">Charts: TradingView Lightweight Charts™ · © TradingView, Inc. · tradingview.com</a>
          </div>
        </section>

        <aside class="panel tpanel">
          <h2 data-role="ttitle">${esc(t("trade.title"))}</h2>
          <div class="facts" data-role="facts"></div>
          <details class="more"><summary>${esc(t("web.details"))}</summary><div class="facts" data-role="facts2"></div></details>
          <div>
            <div class="amount-head"><label>${esc(t("trade.amount").replace(":", ""))}</label>
              <span><input type="number" min="1" max="100" step="1" data-role="pctnum"> %</span></div>
            <input type="range" min="1" max="100" step="1" data-role="pct">
            <div class="quick" data-role="quick">${[10, 25, 50, 75, 100].map((p) => `<button data-p="${p}">${p}</button>`).join("")}</div>
          </div>
          <div class="actions">
            <button class="act buy" data-a="buy">${esc(t("action.buy"))}</button>
            <button class="act sell" data-a="sell">${esc(t("action.sell"))}</button>
            <button class="act short" data-a="short">${esc(t("action.short"))}</button>
            <button class="act cover" data-a="cover">${esc(t("action.cover"))}</button>
            <button class="act close" data-a="close">${esc(t("action.close"))}</button>
          </div>
          <p class="preview" data-role="preview"></p>
          <label class="confirm-row"><input type="checkbox" data-role="confirm" checked> ${esc(t("trade.confirm_cb"))}</label>
          <div class="tstatus" data-role="tstatus"></div>
          <div class="orderlog"><h3>${esc(t("trade.log"))}</h3><div class="list" data-role="log"></div></div>
        </aside>
      </div>`;

    q('[data-role="sort"]').onclick = (e) => {
      const k = e.target.dataset.sort; if (!k) return;
      S.sortKey = k; markActive('[data-role="sort"]', "sort", k); renderRows();
    };
    q('[data-role="ranges"]').onclick = (e) => {
      const r = e.target.dataset.r; if (!r) return;
      S.range = r; markActive('[data-role="ranges"]', "r", r); loadSeries(false);
    };
    markActive('[data-role="ranges"]', "r", S.range);
    q('[data-role="export"]').onclick = exportCsv;
    q('[data-role="attribution"]').onclick = () => SS.call("open_url", "https://www.tradingview.com/");
    q('[data-role="quick"]').onclick = (e) => { if (e.target.dataset.p) setPct(+e.target.dataset.p); };
    q('[data-role="pct"]').oninput = (e) => setPct(+e.target.value);
    q('[data-role="pctnum"]').onchange = (e) => setPct(+e.target.value);
    q('[data-role="confirm"]').onchange = (e) => { S.confirm = e.target.checked; };
    S.el.querySelectorAll(".act").forEach((b) => (b.onclick = () => execute(b.dataset.a)));
    q('[data-role="reset"]').onclick = resetZoom;
    buildChart();
    setPct(S.pct);
  }

  function markActive(sel, attr, val) {
    q(sel).querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset[attr] === val));
  }

  // ------------------------------------------------------------------ chart
  function buildChart() {
    const LW = LightweightCharts;
    S.chart = LW.createChart(q('[data-role="chart"]'), {
      autoSize: true,
      layout: { background: { type: "solid", color: "transparent" }, textColor: "#8b919a", fontFamily: "Segoe UI, sans-serif", fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: "#1c1f23" }, horzLines: { color: "#1c1f23" } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
      timeScale: { borderVisible: false, timeVisible: true, secondsVisible: true, rightOffset: 4, shiftVisibleRangeOnNewBar: true },
      crosshair: { mode: LW.CrosshairMode.Normal, vertLine: { color: "#3a3f46", labelBackgroundColor: "#2a2e34" }, horzLine: { color: "#3a3f46", labelBackgroundColor: "#2a2e34" } },
      localization: { priceFormatter: fmt.price, locale: SS.locale() },
    });
    S.series = S.chart.addSeries(LW.AreaSeries, { lineWidth: 2, priceLineVisible: true, lastValueVisible: true });
    S.markers = LW.createSeriesMarkers(S.series, []);

    S.chart.subscribeCrosshairMove((p) => {
      const v = p && p.seriesData && p.seriesData.get(S.series);
      const legend = q('[data-role="legend"]');
      if (!v) { legend.innerHTML = ""; return; }
      legend.innerHTML = `${esc(fmt.clock((p.time - S.offset) * 1000, true))} &nbsp; <b>${esc(fmt.price(v.value))}</b>`;
    });

    // user zoom/pan (wheel, drag) -> show the reset button; load detail for deep zooms
    let detailTimer = null;
    S.chart.timeScale().subscribeVisibleTimeRangeChange(() => {
      clearTimeout(detailTimer);
      detailTimer = setTimeout(maybeLoadDetail, 350);
    });
    const wrap = q('[data-role="cwrap"]');
    wrap.addEventListener("wheel", () => setZoomed(true), { passive: true });
    wrap.addEventListener("dblclick", resetZoom);
    bindRectangleZoom(wrap);
  }

  function setZoomed(on) {
    S.zoomed = on;
    q('[data-role="reset"]').classList.toggle("hidden", !on);
  }

  function resetZoom() {
    S.chart.priceScale("right").applyOptions({ autoScale: true });
    S.chart.timeScale().fitContent();
    setZoomed(false);
  }

  /** Shift + drag draws a rectangle and zooms time and price to it. */
  function bindRectangleZoom(wrap) {
    const box = q('[data-role="zoombox"]');
    let start = null;
    const pos = (e) => { const r = wrap.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    let pan = null;   // plain drag pans the chart -> counts as zoomed once the mouse really moved
    wrap.addEventListener("mousedown", (e) => {
      if (!e.shiftKey || e.button !== 0) { if (e.button === 0) pan = { x: e.clientX, y: e.clientY }; return; }
      e.stopPropagation(); e.preventDefault();          // keep the chart from panning
      start = pos(e);
      Object.assign(box.style, { left: `${start.x}px`, top: `${start.y}px`, width: "0px", height: "0px" });
      box.classList.remove("hidden");
    }, true);
    window.addEventListener("mousemove", (e) => {
      if (pan && Math.hypot(e.clientX - pan.x, e.clientY - pan.y) > 5) { setZoomed(true); pan = null; }
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
      if (Math.abs(p.x - s.x) < 8) return;                // a click, not a drag
      const ts = S.chart.timeScale();
      const t1 = ts.coordinateToTime(Math.min(p.x, s.x)), t2 = ts.coordinateToTime(Math.max(p.x, s.x));
      if (t1 == null || t2 == null) return;
      ts.setVisibleRange({ from: t1, to: t2 });
      if (Math.abs(p.y - s.y) >= 8) {                     // a flat drag zooms the time only
        const v1 = S.series.coordinateToPrice(Math.min(p.y, s.y)), v2 = S.series.coordinateToPrice(Math.max(p.y, s.y));
        if (v1 != null && v2 != null) S.chart.priceScale("right").setVisibleRange({ from: Math.min(v1, v2), to: Math.max(v1, v2) });
      }
      setZoomed(true);
    }, true);
  }

  /** In deep zooms of a thinned range, replace the visible part with full-resolution points. */
  async function maybeLoadDetail() {
    if (!S.zoomed || S.bucketMs <= 1000 || S.loading || !S.times.length) return;
    const vis = S.chart.timeScale().getVisibleRange();
    if (!vis) return;
    const span = vis.to - vis.from;
    if ((span * 1000) / S.bucketMs > DETAIL_TARGET) return;
    const sid = S.selected, pad = Math.ceil(span * 0.25);
    const res = await SS.call("series_detail", sid, vis.from - pad, vis.to + pad, S.offset);
    if (sid !== S.selected || !res.data.length) return;
    const from = res.data[0].time, to = res.data[res.data.length - 1].time;
    const merged = S.data.filter((d) => d.time < from).concat(res.data, S.data.filter((d) => d.time > to));
    const range = S.chart.timeScale().getVisibleRange();
    S.data = merged;
    S.times = merged.map((d) => d.time);
    S.series.setData(merged);
    if (range) S.chart.timeScale().setVisibleRange(range);
  }

  function nearestTime(t0) {
    const a = S.times;
    if (!a.length) return t0;
    let lo = 0, hi = a.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (a[mid] < t0) lo = mid + 1; else hi = mid; }
    const prev = a[Math.max(0, lo - 1)];
    return Math.abs(prev - t0) <= Math.abs(a[lo] - t0) ? prev : a[lo];
  }

  async function loadSeries(keepView) {
    if (!S.selected) return;
    const sid = S.selected;
    S.loading = true;
    let res;
    try { res = await SS.call("series", sid, S.range); } finally { S.loading = false; }
    if (sid !== S.selected) return;
    const view = keepView && S.zoomed ? S.chart.timeScale().getVisibleRange() : null;
    S.offset = res.offset; S.lastMs = res.last_ms; S.bucketMs = res.bucket_ms || 0;
    S.data = res.data; S.times = res.data.map((d) => d.time);
    S.lastReload = Date.now();
    const row = S.rows.find((r) => r.id === sid);
    const color = (row && row.color) || "#58a6ff";
    S.series.applyOptions({ lineColor: color, topColor: color + "55", bottomColor: color + "04", priceLineColor: color });
    S.series.setData(res.data);
    q('[data-role="empty"]').classList.toggle("hidden", res.data.length > 0);

    const marks = [];
    for (const n of res.news) {
      marks.push({ time: nearestTime(n.time), position: n.kind === "high" ? "aboveBar" : "belowBar",
                   color: n.kind === "high" ? "#3fb95099" : "#f8514999", shape: n.kind === "high" ? "arrowDown" : "arrowUp", size: 0.6 });
    }
    for (const m of res.markers) {
      marks.push({ time: nearestTime(m.time), position: m.kind === "buy" || m.kind === "cover" ? "belowBar" : "aboveBar",
                   color: TRADE_COLORS[m.kind], shape: "circle", text: m.letter, size: 1.4 });
    }
    marks.sort((a, b) => a.time - b.time);
    S.markers.setMarkers(marks);

    S.lines.forEach((l) => S.series.removePriceLine(l));
    S.lines = res.lines.map((l) => S.series.createPriceLine({
      price: l.price, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true,
      color: LINE_COLORS[l.kind] || "#f0883e", title: l.title,
    }));
    S.events = res.events;
    if (view) S.chart.timeScale().setVisibleRange(view);
    else { S.chart.priceScale("right").applyOptions({ autoScale: true }); S.chart.timeScale().fitContent(); setZoomed(false); }
    renderStats(res.markers.length);
    renderHead();
  }

  async function pollSeries() {
    if (!S.selected || !S.lastMs || S.loading) return;
    const sid = S.selected;
    const res = await SS.call("updates", sid, S.lastMs);
    if (sid !== S.selected || !res.data.length) return;
    for (const d of res.data) {
      const last = S.times[S.times.length - 1];
      if (last === undefined || d.time >= last) {
        S.series.update(d);
        if (last === undefined || d.time > last) { S.times.push(d.time); S.data.push(d); }
        else S.data[S.data.length - 1] = d;
      }
    }
    S.lastMs = res.last_ms;
  }

  function renderStats(nTrades) {
    const data = S.data || [];
    const stats = q('[data-role="stats"]');
    if (!data.length) { stats.innerHTML = ""; return; }
    let lo = Infinity, hi = -Infinity, sum = 0;
    for (const d of data) { lo = Math.min(lo, d.value); hi = Math.max(hi, d.value); sum += d.value; }
    const change = (data[data.length - 1].value / data[0].value - 1) * 100;
    stats.innerHTML = [
      ["Min", fmt.price(lo)], ["Max", fmt.price(hi)], ["Ø", fmt.price(sum / data.length)],
      [t("stats.col_spread"), fmt.pct((hi / lo - 1) * 100, false)], [t("web.points"), fmt.num(data.length, 0)],
      [t("web.trades"), nTrades],
    ].map(([k, v]) => `<span>${esc(k)} <b>${esc(v)}</b></span>`).join("");
    const ch = q('[data-role="change"]');
    ch.textContent = fmt.pct(change);
    ch.className = "pill " + cls(change);
  }

  // ------------------------------------------------------------------ watchlist
  function spark(values, color) {
    if (!values || values.length < 2) return "<svg></svg>";
    const lo = Math.min(...values), hi = Math.max(...values), w = 84, h = 30, span = hi - lo || 1;
    const pts = values.map((v, i) => `${((i / (values.length - 1)) * w).toFixed(1)},${(h - 3 - ((v - lo) / span) * (h - 6)).toFixed(1)}`).join(" ");
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  }

  function renderRows() {
    const key = S.sortKey;
    const rows = [...S.rows].sort((a, b) => key === "id" ? a.id.localeCompare(b.id) : (b[key] ?? -Infinity) - (a[key] ?? -Infinity));
    q('[data-role="rows"]').innerHTML = rows.map((r) => {
      const meta = [`1m <span class="${cls(r.d1)}">${fmt.pct(r.d1)}</span>`, `1h <span class="${cls(r.d60)}">${fmt.pct(r.d60)}</span>`];
      if (r.owned) meta.push(`<span class="own">● ${fmt.big(r.owned)}</span>`);
      if (r.shorted) meta.push(`<span class="own">▼ ${fmt.big(r.shorted)}</span>`);
      if (r.pl != null) meta.push(`<span class="${cls(r.pl)}">${fmt.big(r.pl)}</span>`);
      return `<div class="wrow ${r.id === S.selected ? "selected" : ""} ${r.unlocked ? "" : "locked"}" data-id="${esc(r.id)}">
        <div class="bar" style="background:${esc(r.color)}"></div>
        <div><div class="id">${esc(r.id)}${r.name !== r.id ? `<small>${esc(r.name)}</small>` : ""}</div><div class="meta">${meta.join(" · ")}</div></div>
        ${spark(r.spark, (r.d5 ?? 0) >= 0 ? "#3fb950" : "#f85149")}
        <div class="right"><div class="px">${esc(fmt.price(r.price))}</div><span class="pill ${cls(r.d5)}">${esc(fmt.pct(r.d5))}</span></div>
      </div>`;
    }).join("");
    q('[data-role="rows"]').querySelectorAll(".wrow").forEach((el) => (el.onclick = () => select(el.dataset.id)));
  }

  function select(id) {
    if (id === S.selected) return;
    S.selected = id;
    renderRows();
    renderTrade();
    loadSeries(false);
  }

  // ------------------------------------------------------------------ header + events
  function renderHead() {
    const r = S.rows.find((x) => x.id === S.selected);
    if (!r) return;
    q('[data-role="ticker"]').textContent = r.id;
    q('[data-role="name"]').textContent = r.name !== r.id ? r.name : "";
    q('[data-role="swatch"]').style.background = r.color;
    q('[data-role="price"]').textContent = fmt.price(r.price);
    const ev = (S.events || [])[0], banner = q('[data-role="event"]');
    const now = SS.lastTick && SS.lastTick.server_now;
    if (ev && now && ev.at >= now) {
      banner.textContent = t("market.scheduled_info", {
        direction: ev.direction, target: fmt.price(ev.target), time: fmt.clock(ev.at), countdown: fmt.duration((ev.at - now) / 1000),
      });
      banner.classList.remove("hidden");
    } else banner.classList.add("hidden");
  }

  // ------------------------------------------------------------------ trading
  function setPct(p) {
    p = Math.max(1, Math.min(100, Math.round(+p || 1)));
    S.pct = p;
    q('[data-role="pct"]').value = p;
    q('[data-role="pctnum"]').value = p;
    renderTrade();
  }

  function fact(label, value, kls = "") {
    return `<div><label>${esc(label)}</label><b class="${kls}">${esc(value)}</b></div>`;
  }

  function cooldownText(cd) {
    if (cd === null || cd === undefined) return ["–", ""];
    return cd <= 0 ? [t("common.ready"), "ready"] : [fmt.duration(cd), "warn"];
  }

  function renderTrade() {
    const r = S.rows.find((x) => x.id === S.selected);
    if (!r) return;
    const tick = SS.lastTick || {};
    q('[data-role="ttitle"]').textContent = t("trade.title_stock", { stock: r.id });
    const [buyCd, buyCls] = cooldownText(tick.buy_cd), [shortCd, shortCls] = cooldownText(tick.short_cd);
    q('[data-role="facts"]').innerHTML = [
      fact(t("common.price"), fmt.price(r.price)), fact(t("common.cash"), fmt.big(tick.cash)),
      fact(t("common.owned"), r.owned ? fmt.big(r.owned) : "0"), fact(t("common.avg_buy"), r.owned ? fmt.price(r.avg) : "–"),
      fact(t("common.short"), r.shorted ? fmt.big(r.shorted) : "0"), fact(t("common.avg_short"), r.shorted ? fmt.price(r.avg_short) : "–"),
      fact(t("common.pl"), r.pl != null ? fmt.big(r.pl) : "–", cls(r.pl)), fact(t("col.div_min"), r.div ? fmt.big(r.div) : "–"),
      fact(t("trade.buy_cd"), buyCd, buyCls), fact(t("trade.short_cd"), shortCd, shortCls),
    ].join("");
    q('[data-role="facts2"]').innerHTML = [
      fact(t("col.base"), fmt.price(r.base)), fact(t("col.cap"), fmt.price(r.cap)),
      fact(t("col.dividend"), fmt.pct((r.rate || 0) * 100, false)), fact(t("col.available"), fmt.big(r.avail)),
      fact(t("col.max_volume"), fmt.num(r.maxvol, 0)),
    ].join("");

    const p = S.pct / 100, lines = [];
    if (r.owned) lines.push(t("trade.preview_sell", { p: S.pct, shares: fmt.big(r.owned * p) }) + (r.price ? ` ≈ ${fmt.big(r.owned * p * r.price)}` : ""));
    if (r.shorted) lines.push(t("trade.preview_cover", { p: S.pct, shares: fmt.big(r.shorted * p) }) + (r.price ? ` ≈ ${fmt.big(r.shorted * p * r.price)}` : ""));
    if (tick.cash) lines.push(t("trade.preview_open", { p: S.pct, cash: fmt.big(tick.cash * p) }));
    if (!tick.live) lines.push(t("trade.not_live"));
    q('[data-role="preview"]').innerHTML = lines.map(esc).join("<br>");

    const live = !!tick.live;
    const enable = { buy: live, short: live, sell: live && !!r.owned, cover: live && !!r.shorted, close: live && !!(r.owned || r.shorted) };
    S.el.querySelectorAll(".act").forEach((b) => { b.disabled = !enable[b.dataset.a]; });
  }

  async function execute(action) {
    const r = S.rows.find((x) => x.id === S.selected);
    if (!r) return;
    const label = t(`action.${action}`);
    if (S.confirm) {
      const ok = await SS.confirm(t("trade.confirm_title"),
        t("trade.confirm_text", { action: label, p: S.pct, stock: r.id, preview: q('[data-role="preview"]').innerText }),
        label, action === "sell" || action === "short" ? "danger" : "primary");
      if (!ok) return;
    }
    const res = await SS.call("trade", r.id, action, S.pct);
    showTradeStatus(res.ok ? { kind: "warn", text: res.text } : { kind: "err", text: res.text });
    if (!res.ok) SS.toast(res.text, "err");
  }

  function showTradeStatus(st) {
    const el = q('[data-role="tstatus"]');
    el.textContent = st ? st.text : "";
    el.className = "tstatus " + (st ? st.kind : "");
  }

  function renderLog(log) {
    q('[data-role="log"]').innerHTML = log.slice(0, 40).map((x) => `
      <div class="item ${esc(x.status)}">
        <span class="mono">${esc(fmt.clock(x.time))}</span><b>${esc(x.stock)}</b><span>${esc(x.action)}</span>
        <span class="mono">${x.pct ? esc(fmt.num(x.pct, 0)) + "%" : ""}</span>
        <span class="st">${esc(x.status_text)}${x.reason ? " – " + esc(x.reason) : ""}</span>
      </div>`).join("");
  }

  async function exportCsv() {
    const res = await SS.call("export_csv", S.range);
    if (res.text) SS.toast(res.text, res.ok ? "ok" : "err", 5000);
  }

  // ------------------------------------------------------------------ refresh (every second while visible)
  async function refresh(tick) {
    SS.lastTick = tick;
    const m = await SS.call("market");
    S.rows = m.rows;
    S.factor = m.factor;
    if (!S.selected && S.rows.length) {
      const best = [...S.rows].sort((a, b) => (b.div ?? 0) - (a.div ?? 0))[0];
      select(best.id);
    } else {
      renderRows();
      renderTrade();
      renderHead();
    }
    renderLog(m.log);
    const st = m.trade;
    showTradeStatus(st);
    if (st && st.state !== S.lastTradeState) {
      if (st.state === "done") { SS.toast(st.text, "ok"); loadSeries(true); }
      else if (st.state === "rejected" || st.state === "timeout") SS.toast(st.text, "err", 5000);
      S.lastTradeState = st.state;
    }
    if (Date.now() - S.lastReload > 60_000) loadSeries(true);   // new trades, rules, events
    else await pollSeries();
  }

  /** Keyboard: arrow up/down = previous/next stock in the shown order, R = reset the chart zoom. */
  function key(e) {
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      const rows = [...q('[data-role="rows"]').querySelectorAll(".wrow")];
      if (!rows.length) return false;
      const i = rows.findIndex((el) => el.dataset.id === S.selected);
      const next = rows[Math.max(0, Math.min(rows.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
      select(next.dataset.id);
      q(`.wrow[data-id="${CSS.escape(next.dataset.id)}"]`).scrollIntoView({ block: "nearest" });
      return true;
    }
    if (e.key === "r" || e.key === "R") { resetZoom(); return true; }
    return false;
  }

  SS.registerTab("market", { mount, refresh, key, show: () => { if (S.selected) loadSeries(true); } });
})();
