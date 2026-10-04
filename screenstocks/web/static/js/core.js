/* Shared helpers for the web UI: Python bridge, translations, formatting, dialogs, toasts. */
"use strict";

const SS = (window.SS = {
  lang: "en",
  texts: {},
  info: {},
  modules: {},
});

/** Tab modules register here (loaded before shell.js): {mount(el), show(), hide(), refresh(tick)}. */
SS.registerTab = (id, module) => { SS.modules[id] = module; };

// ------------------------------------------------------------------ bridge

/** Call a Python method of the bridge (screenstocks/web/bridge.py). */
SS.call = async (name, ...args) => {
  const api = window.pywebview && window.pywebview.api;
  if (!api || !api[name]) throw new Error(`bridge method missing: ${name}`);
  return api[name](...args);
};

/** Resolves once the bridge is ready (pywebview) or the browser test data is loaded (?mock). */
SS.ready = () => new Promise((resolve) => {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.init) return resolve();
  window.addEventListener("pywebviewready", () => resolve(), { once: true });
  if (location.search.includes("mock")) {
    const s = document.createElement("script");
    s.src = "js/mock.js";
    s.onload = () => resolve();
    document.head.appendChild(s);
  }
});

// JavaScript errors go to app.log; errors before the bridge is ready are queued and sent later.
SS.errors = [];
SS.reportError = (msg) => {
  SS.errors.push(msg);
  const api = window.pywebview && window.pywebview.api;
  if (api && api.log_client_error) {
    while (SS.errors.length) api.log_client_error(SS.errors.shift()).catch(() => {});
  }
};
window.addEventListener("error", (e) => SS.reportError(`${e.message} @ ${e.filename}:${e.lineno}:${e.colno}`));
window.addEventListener("unhandledrejection", (e) => SS.reportError(String(e.reason && (e.reason.stack || e.reason))));
window.addEventListener("pywebviewready", () => SS.reportError && SS.errors.length && SS.reportError(SS.errors.pop()));

// ------------------------------------------------------------------ texts

/** Translation from i18n.py; {name} placeholders are filled from vars. */
SS.t = (key, vars) => {
  let s = SS.texts[key];
  if (s === undefined) s = key;
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] !== undefined ? vars[k] : m));
  return s;
};

SS.applyTexts = (root = document) => {
  root.querySelectorAll("[data-t]").forEach((el) => { el.textContent = SS.t(el.dataset.t).trim(); });
  root.querySelectorAll("[data-t-title]").forEach((el) => { el.title = SS.t(el.dataset.tTitle).trim(); });
};

// ------------------------------------------------------------------ formatting (mirrors gui/fmt.py)

// German and French: decimal comma, day-first dates, "12 %" (same as gui/fmt.py); French groups with a space.
SS.LANGS = { de: "de-DE", en: "en-US", fr: "fr-FR" };
SS.locale = () => SS.LANGS[SS.lang] || "en-US";
SS.commaLang = () => SS.lang === "de" || SS.lang === "fr";
const locale = SS.locale;
SS.fmt = {
  num(v, d = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "–";
    return new Intl.NumberFormat(locale(), { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
  },
  price(v) {
    if (v === null || v === undefined) return "–";
    const a = Math.abs(v);
    return SS.fmt.num(v, a >= 100 ? 2 : a >= 1 ? 3 : 4);
  },
  big(v) {
    if (v === null || v === undefined) return "–";
    const a = Math.abs(v);
    const steps = SS.commaLang()                  // French uses the German abbreviations (as in gui/fmt.py)
      ? [[1e12, " Bio."], [1e9, " Mrd."], [1e6, " Mio."], [1e4, " Tsd."]]
      : [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e4, "K"]];
    for (const [lim, suffix] of steps) if (a >= lim) return SS.fmt.num(v / lim, 2) + suffix;
    return SS.fmt.num(v, 2);
  },
  pct(v, signed = true) {
    if (v === null || v === undefined) return "–";
    return (signed && v > 0 ? "+" : "") + SS.fmt.num(v, 2) + (SS.commaLang() ? " %" : "%");
  },
  duration(sec) {
    sec = Math.round(Math.abs(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
  },
  clock(ms, withDate = false) {
    if (!ms) return "–";
    const d = new Date(ms);
    const opts = withDate
      ? { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }
      : { hour: "2-digit", minute: "2-digit", second: "2-digit" };
    return d.toLocaleString(locale(), opts);
  },
};
SS.cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
SS.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ toasts and dialogs

SS.toast = (text, kind = "info", ms = 3200) => {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = text;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), ms);
};

/**
 * Modal dialog. buttons: [{label, value, kind}] -> resolves with the value of the clicked button
 * (Escape / backdrop = null). body may be text or a DOM node.
 */
SS.dialog = ({ title, body, buttons }) => new Promise((resolve) => {
  const modal = document.getElementById("modal");
  document.getElementById("modal-title").textContent = title || "";
  const bodyEl = document.getElementById("modal-body");
  bodyEl.replaceChildren(typeof body === "string" ? document.createTextNode(body) : body);
  const actions = document.getElementById("modal-actions");
  actions.replaceChildren();
  const close = (value) => {
    modal.classList.add("hidden");
    document.removeEventListener("keydown", onKey);
    modal.onclick = null;
    resolve(value);
  };
  const onKey = (e) => { if (e.key === "Escape") close(null); };
  for (const b of buttons) {
    const btn = document.createElement("button");
    btn.className = `btn ${b.kind || ""}`;
    btn.textContent = b.label;
    btn.onclick = () => close(b.value);
    actions.appendChild(btn);
  }
  modal.onclick = (e) => { if (e.target === modal) close(null); };
  document.addEventListener("keydown", onKey);
  modal.classList.remove("hidden");
  const primary = actions.querySelector(".primary, .danger") || actions.lastElementChild;
  if (primary) primary.focus();
});

SS.confirm = (title, text, okLabel, kind = "primary") => SS.dialog({
  title, body: text,
  buttons: [{ label: SS.t("setup.cancel"), value: false, kind: "ghost" }, { label: okLabel || "OK", value: true, kind }],
}).then((v) => v === true);
