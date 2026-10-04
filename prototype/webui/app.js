/* Design preview of the Market tab. Data comes from preview.py (window.pywebview.api). */
"use strict";

const TEXT = {
  de: {
    net: "Nettovermögen", cash: "Bargeld", level: "Level", buyCd: "Kauf-CD", shortCd: "Short-CD", ready: "bereit",
    watchlist: "Markt", pl: "G/V", divShort: "Div.", trade: "Handeln", price: "Kurs", owned: "Besitz",
    avgBuy: "Ø Kauf", short: "Short", divMin: "Div. / min", amount: "Menge", buy: "Kaufen", sell: "Verkaufen",
    shortAct: "Shorten", cover: "Covern", close: "Schließen",
    draftNote: "Entwurf: Diese Vorschau liest nur Daten. Handeln funktioniert hier noch nicht – dafür die App nutzen.",
    zoomHint: "Mausrad = Zoom · Ziehen = verschieben · Doppelklick auf die Zeitachse = alles zeigen",
    all: "Alles", min: "Min", max: "Max", avg: "Ø", spread: "Spanne", points: "Datenpunkte", trades: "Trades",
    noData: "Keine Kursdaten", draftToast: "Im Entwurf deaktiviert", sellPreview: "Verkaufen {p} %: {n} Aktien ≈ {v}",
    coverPreview: "Covern {p} %: {n} Aktien", openPreview: "Kaufen/Shorten {p} % des maximal Möglichen",
    event: "⚠ Angekündigt: {d} → {t} um {at} (in {in})", avgShort: "Ø Short", live: "LIVE", offline: "PAUSIERT",
    tabs: ["Markt", "Vergleich", "Portfolio", "Dividenden", "Journal", "Statistik", "News", "Automatik"],
    kinds: { buy: ["K", "Kauf"], sell: ["V", "Verkauf"], short: ["S", "Short"], cover: ["C", "Cover"] },
  },
  en: {
    net: "Net worth", cash: "Cash", level: "Level", buyCd: "Buy CD", shortCd: "Short CD", ready: "ready",
    watchlist: "Market", pl: "P/L", divShort: "Div.", trade: "Trade", price: "Price", owned: "Owned",
    avgBuy: "Avg buy", short: "Short", divMin: "Div. / min", amount: "Amount", buy: "Buy", sell: "Sell",
    shortAct: "Short", cover: "Cover", close: "Close",
    draftNote: "Design preview: read-only. Trading does not work here yet – use the app for that.",
    zoomHint: "Mouse wheel = zoom · drag = pan · double-click the time axis = show all",
    all: "All", min: "Min", max: "Max", avg: "Avg", spread: "Spread", points: "data points", trades: "trades",
    noData: "No price data", draftToast: "Disabled in the preview", sellPreview: "Sell {p}%: {n} shares ≈ {v}",
    coverPreview: "Cover {p}%: {n} shares", openPreview: "Buy/short {p}% of the maximum possible",
    event: "⚠ Announced: {d} → {t} at {at} (in {in})", avgShort: "Avg short", live: "LIVE", offline: "PAUSED",
    tabs: ["Market", "Compare", "Portfolio", "Dividends", "Journal", "Statistics", "News", "Automation"],
    kinds: { buy: ["B", "Buy"], sell: ["S", "Sell"], short: ["H", "Short"], cover: ["C", "Cover"] },
  },
};
const PALETTE = ["#58a6ff", "#3fb950", "#f0883e", "#d2a8ff", "#ff7b72", "#56d4dd", "#e3b341", "#a5d6ff"];
const TRADE_COLORS = { buy: "#3fb950", sell: "#f85149", short: "#a371f7", cover: "#58a6ff" };
const RANGES = [["1m", "1m"], ["5m", "5m"], ["15m", "15m"], ["1h", "1h"], ["6h", "6h"], ["24h", "24h"], ["all", null]];

const S = { lang: "en", colors: {}, selected: null, range: "1h", rows: [], snap: null, lastMs: 0, pct: 25, sortKey: "d5" };
let T = TEXT.en, nf2, nf3, nf4, chart, series, markersApi, priceLines = [];
const $ = (id) => document.getElementById(id);

// ------------------------------------------------------------------ format
function fmtNum(v, d) { return v == null ? "–" : new Intl.NumberFormat(S.lang === "de" ? "de-DE" : "en-US", { minimumFractionDigits: d, maximumFractionDigits: d }).format(v); }
function fmtPrice(v) { if (v == null) return "–"; const a = Math.abs(v); return fmtNum(v, a >= 100 ? 2 : a >= 1 ? 3 : 4); }
function fmtBig(v) {
  if (v == null) return "–";
  const a = Math.abs(v), de = S.lang === "de";
  const steps = de ? [[1e12, " Bio."], [1e9, " Mrd."], [1e6, " Mio."], [1e4, " Tsd."]] : [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e4, "K"]];
  for (const [lim, suf] of steps) if (a >= lim) return fmtNum(v / lim, 2) + suf;
  return fmtNum(v, 2);
}
function fmtPct(v, signed = true) {
  if (v == null) return "–";
  const s = fmtNum(v, 2);
  return (signed && v > 0 ? "+" : "") + s + (S.lang === "de" ? " %" : "%");
}
function fmtDur(sec) {
  sec = Math.max(0, Math.round(sec)); const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}
const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
const fill = (tpl, o) => tpl.replace(/\{(\w+)\}/g, (_, k) => o[k]);
const colorOf = (id) => S.colors[id] || PALETTE[S.rows.findIndex((r) => r.id === id) % PALETTE.length] || "#58a6ff";
function toast(msg) { const el = $("toast"); el.textContent = msg; el.classList.remove("hidden"); clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.add("hidden"), 1800); }

// ------------------------------------------------------------------ static UI
function buildStatic() {
  document.querySelectorAll("[data-t]").forEach((el) => { el.textContent = T[el.dataset.t] ?? el.textContent; });
  $("tabs").innerHTML = T.tabs.map((t, i) => `<button class="${i === 0 ? "active" : ""}">${t}</button>`).join("");
  $("ranges").innerHTML = RANGES.map(([k]) => `<button data-r="${k}" class="${k === S.range ? "active" : ""}">${k === "all" ? T.all : k}</button>`).join("");
  $("ranges").onclick = (e) => { const r = e.target.dataset.r; if (!r) return; S.range = r; markActive("ranges", "r", r); loadSeries(); };
  $("sort").onclick = (e) => { const k = e.target.dataset.sort; if (!k) return; S.sortKey = k; markActive("sort", "sort", k); renderRows(); };
  $("quick").innerHTML = [10, 25, 50, 75, 100].map((p) => `<button data-p="${p}">${p}</button>`).join("");
  $("quick").onclick = (e) => { if (e.target.dataset.p) setPct(+e.target.dataset.p); };
  $("pct").oninput = (e) => setPct(+e.target.value);
  document.querySelectorAll(".act").forEach((b) => (b.onclick = () => toast(T.draftToast)));
  $("attribution").onclick = (e) => { e.preventDefault(); window.pywebview.api.open_url(e.currentTarget.href); };
}
function markActive(id, attr, val) { $(id).querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset[attr] === val)); }
function setPct(p) { S.pct = p; $("pct").value = p; $("pct-label").textContent = p + (S.lang === "de" ? " %" : "%"); renderTrade(); }

// ------------------------------------------------------------------ chart
function buildChart() {
  const LW = LightweightCharts;
  chart = LW.createChart($("chart"), {
    autoSize: true,
    layout: { background: { type: "solid", color: "transparent" }, textColor: "#8b919a", fontFamily: "Segoe UI, sans-serif", fontSize: 11, attributionLogo: false },
    grid: { vertLines: { color: "#1c1f23" }, horzLines: { color: "#1c1f23" } },
    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
    timeScale: { borderVisible: false, timeVisible: true, secondsVisible: true, rightOffset: 4 },
    crosshair: { mode: LW.CrosshairMode.Normal, vertLine: { color: "#3a3f46", labelBackgroundColor: "#2a2e34" }, horzLine: { color: "#3a3f46", labelBackgroundColor: "#2a2e34" } },
    localization: { priceFormatter: fmtPrice },
  });
  series = chart.addSeries(LW.AreaSeries, { lineWidth: 2, priceLineVisible: true, lastValueVisible: true });
  markersApi = LW.createSeriesMarkers(series, []);
  chart.subscribeCrosshairMove((p) => {
    const v = p && p.seriesData && p.seriesData.get(series);
    if (!v) { $("legend").innerHTML = ""; return; }
    const d = new Date((p.time - S.offset) * 1000);
    $("legend").innerHTML = `${d.toLocaleString(S.lang === "de" ? "de-DE" : "en-US")} &nbsp; <b>${fmtPrice(v.value)}</b>`;
  });
}

function nearestTime(times, t) {
  let lo = 0, hi = times.length - 1;
  if (hi < 0) return t;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (times[mid] < t) lo = mid + 1; else hi = mid; }
  const a = times[Math.max(0, lo - 1)], b = times[lo];
  return Math.abs(a - t) <= Math.abs(b - t) ? a : b;
}

async function loadSeries() {
  if (!S.selected) return;
  const sid = S.selected, color = colorOf(sid);
  const res = await window.pywebview.api.series(sid, S.range);
  if (sid !== S.selected) return;
  S.offset = res.offset;
  S.lastMs = res.last_ms;
  S.times = res.data.map((d) => d.time);
  series.applyOptions({ lineColor: color, topColor: color + "55", bottomColor: color + "04", priceLineColor: color });
  series.setData(res.data);

  const marks = [];
  for (const n of res.news) {
    marks.push({ time: nearestTime(S.times, n.time), position: n.kind === "high" ? "aboveBar" : "belowBar",
                 color: n.kind === "high" ? "#3fb95099" : "#f8514999", shape: n.kind === "high" ? "arrowDown" : "arrowUp", size: 0.6 });
  }
  for (const m of res.markers) {
    const [letter] = T.kinds[m.kind];
    marks.push({ time: nearestTime(S.times, m.time), position: m.kind === "buy" || m.kind === "cover" ? "belowBar" : "aboveBar",
                 color: TRADE_COLORS[m.kind], shape: "circle", text: letter, size: 1.4 });
  }
  marks.sort((a, b) => a.time - b.time);
  markersApi.setMarkers(marks);

  priceLines.forEach((l) => series.removePriceLine(l));
  priceLines = res.lines.map((l) => series.createPriceLine({
    price: l.price, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true,
    color: l.kind === "avg_buy" ? "#58a6ff" : l.kind === "avg_short" ? "#d2a8ff" : "#f0883e",
    title: l.kind === "avg_buy" ? T.avgBuy : l.kind === "avg_short" ? T.avgShort : l.label,
  }));
  S.events = res.events;
  chart.timeScale().fitContent();
  renderStats(res.data, res.markers.length);
  renderHeader();
}

async function pollSeries() {
  if (!S.selected || !S.lastMs) return;
  const sid = S.selected;
  const res = await window.pywebview.api.updates(sid, S.lastMs);
  if (sid !== S.selected || !res.data.length) return;
  for (const d of res.data) {
    if (!S.times.length || d.time >= S.times[S.times.length - 1]) {
      series.update(d);
      if (!S.times.length || d.time > S.times[S.times.length - 1]) S.times.push(d.time);
    }
  }
  S.lastMs = res.last_ms;
}

function renderStats(data, nTrades) {
  if (!data.length) { $("stats").innerHTML = T.noData; return; }
  let lo = Infinity, hi = -Infinity, sum = 0;
  for (const d of data) { lo = Math.min(lo, d.value); hi = Math.max(hi, d.value); sum += d.value; }
  const change = (data[data.length - 1].value / data[0].value - 1) * 100;
  $("stats").innerHTML = [
    [T.min, fmtPrice(lo)], [T.max, fmtPrice(hi)], [T.avg, fmtPrice(sum / data.length)],
    [T.spread, fmtPct((hi / lo - 1) * 100, false)], [T.points, fmtNum(data.length, 0)], [T.trades, nTrades],
  ].map(([k, v]) => `<span>${k} <b>${v}</b></span>`).join("");
  const ch = $("change"); ch.textContent = fmtPct(change); ch.className = "pill " + cls(change);
}

// ------------------------------------------------------------------ watchlist
function spark(values, color) {
  if (!values || values.length < 2) return "<svg></svg>";
  const lo = Math.min(...values), hi = Math.max(...values), w = 86, h = 30, span = hi - lo || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1) * w).toFixed(1)},${(h - 3 - (v - lo) / span * (h - 6)).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 ${w} ${h}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
}

function renderRows() {
  const rows = [...S.rows].sort((a, b) => (b[S.sortKey] ?? -Infinity) - (a[S.sortKey] ?? -Infinity));
  $("rows").innerHTML = rows.map((r) => {
    const color = colorOf(r.id), d5 = r.d5;
    const meta = [`1m <span class="${cls(r.d1)}">${fmtPct(r.d1)}</span>`, `1h <span class="${cls(r.d60)}">${fmtPct(r.d60)}</span>`];
    if (r.owned) meta.push(`<span class="own">● ${fmtBig(r.owned)}</span>`);
    if (r.pl != null) meta.push(`<span class="${cls(r.pl)}">${fmtBig(r.pl)}</span>`);
    return `<div class="row ${r.id === S.selected ? "selected" : ""}" data-id="${r.id}">
      <div class="bar" style="background:${color}"></div>
      <div><div class="id">${r.id}${r.name !== r.id ? ` <span class="sub">${r.name}</span>` : ""}</div><div class="meta">${meta.join(" · ")}</div></div>
      ${spark(r.spark, d5 >= 0 ? "#3fb950" : "#f85149")}
      <div class="right"><div class="px">${fmtPrice(r.price)}</div><span class="pill ${cls(d5)}">${fmtPct(d5)}</span></div>
    </div>`;
  }).join("");
  $("rows").querySelectorAll(".row").forEach((el) => (el.onclick = () => select(el.dataset.id)));
}

function select(id) {
  if (id === S.selected) return;
  S.selected = id;
  renderRows();
  loadSeries();
  renderTrade();
}

// ------------------------------------------------------------------ header / trade
function renderHeader() {
  const s = S.snap; if (!s) return;
  $("kpi-live").classList.toggle("off", !s.live);
  $("live-text").textContent = s.live ? T.live : T.offline;
  $("kpi-net").textContent = fmtBig(s.net);
  $("kpi-cash").textContent = fmtBig(s.cash);
  $("kpi-level").textContent = s.level ?? "–";
  for (const [id, cd] of [["kpi-buy", s.buy_cd], ["kpi-short", s.short_cd]]) {
    const el = $(id); el.textContent = cd <= 0 ? T.ready : fmtDur(cd); el.className = cd <= 0 ? "ready" : "";
  }
  const r = S.rows.find((x) => x.id === S.selected); if (!r) return;
  $("ticker").textContent = r.id; $("name").textContent = r.name !== r.id ? r.name : "";
  $("swatch").style.background = colorOf(r.id);
  $("price").textContent = fmtPrice(r.price);
  const ev = (S.events || [])[0];
  const banner = $("event");
  if (ev) {
    banner.textContent = fill(T.event, { d: ev.direction, t: fmtPrice(ev.target), at: new Date(ev.at).toLocaleTimeString(), in: fmtDur((ev.at - s.now) / 1000) });
    banner.classList.remove("hidden");
  } else banner.classList.add("hidden");
}

function renderTrade() {
  const r = S.rows.find((x) => x.id === S.selected); if (!r) return;
  $("trade-ticker").textContent = r.id;
  $("t-price").textContent = fmtPrice(r.price);
  $("t-owned").textContent = r.owned ? fmtBig(r.owned) : "0";
  $("t-avg").textContent = r.owned ? fmtPrice(r.avg) : "–";
  $("t-short").textContent = r.shorted ? fmtBig(r.shorted) : "0";
  const pl = $("t-pl"); pl.textContent = r.pl != null ? fmtBig(r.pl) : "–"; pl.className = cls(r.pl);
  $("t-div").textContent = r.div ? fmtBig(r.div) : "–";
  const p = S.pct / 100, lines = [];
  if (r.owned) lines.push(fill(T.sellPreview, { p: S.pct, n: fmtBig(r.owned * p), v: fmtBig(r.owned * p * r.price) }));
  if (r.shorted) lines.push(fill(T.coverPreview, { p: S.pct, n: fmtBig(r.shorted * p) }));
  lines.push(fill(T.openPreview, { p: S.pct }));
  $("preview").innerHTML = lines.join("<br>");
  document.querySelector(".act.sell").disabled = !r.owned;
  document.querySelector(".act.cover").disabled = !r.shorted;
  document.querySelector(".act.close").disabled = !(r.owned || r.shorted);
}

// ------------------------------------------------------------------ loop
async function tick() {
  try {
    S.snap = await window.pywebview.api.snapshot();
    S.rows = S.snap.rows;
    if (!S.selected && S.rows.length) {
      const own = [...S.rows].sort((a, b) => (b.div ?? 0) - (a.div ?? 0))[0];
      select(own.id);
    }
    renderRows(); renderHeader(); renderTrade();
    await pollSeries();
  } catch (err) { console.error(err); }
  setTimeout(tick, 1000);
}

window.addEventListener("pywebviewready", async () => {
  const init = await window.pywebview.api.init();
  S.lang = init.lang === "de" ? "de" : "en"; T = TEXT[S.lang]; S.colors = init.colors || {};
  document.documentElement.lang = S.lang;
  buildStatic(); buildChart(); setPct(25);
  tick();
});
