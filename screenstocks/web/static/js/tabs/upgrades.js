/* Upgrades tab (only with the game extension, installed in the setup wizard or Settings → Extension):
   the game's upgrade catalog with a buy button per upgrade. */
"use strict";

(() => {
  const { t, fmt, esc } = SS;
  const S = { el: null, table: null, last: 0, busy: false, cash: null, data: null };
  const q = (sel) => S.el.querySelector(sel);
  const value = (v) => (v === null || v === undefined ? "–" : fmt.num(v, Number.isInteger(v) ? 0 : 2));
  const tooExpensive = (r) => r.price !== null && S.cash !== null && r.price > S.cash;

  function mount(el) {
    S.el = el;
    el.innerHTML = `
      <div class="upg">
        <section class="panel box"><div data-role="state"></div></section>
        <section class="panel box grow hidden" data-role="catalog">
          <h2>${esc(t("upg.catalog"))}</h2>
          <div data-role="table" class="grow"></div>
          <div class="hint">${esc(t("upg.buy_hint"))}</div>
        </section>
      </div>`;
    S.table = SS.ui.table(q('[data-role="table"]'), {
      sortKey: "name", sortDesc: false, empty: "–",
      rowClass: (r) => (r.maxed ? "muted" : ""),
      columns: [
        { key: "name", label: t("upg.col_name"), value: (r) => r.name,
          render: (r) => `<b>${esc(r.name)}</b>${r.description ? `<div class="upg-desc">${esc(r.description)}</div>` : ""}` },
        { key: "currentLevel", label: t("upg.col_level"), align: "r",
          render: (r) => esc(r.hasMaxLevel ? `${r.currentLevel} / ${r.maxLevel}` : String(r.currentLevel)) },
        { key: "currentValue", label: t("upg.col_value"), align: "r", render: (r) => esc(value(r.currentValue)) },
        { key: "nextValue", label: t("upg.col_next"), align: "r",
          render: (r) => (r.maxed ? esc(t("upg.maxed")) : esc(value(r.nextValue))) },
        { key: "price", label: t("upg.col_price"), align: "r", value: (r) => r.price ?? Infinity,
          render: (r) => `<span class="${tooExpensive(r) ? "down" : ""}">${esc(r.maxed ? "–" : fmt.big(r.price))}</span>` },
        { key: "buy", label: "", value: () => 0,
          render: (r) => `<button class="btn primary small" data-buy="${esc(r.upgradeId)}"
            ${r.maxed || tooExpensive(r) ? "disabled" : ""}>${esc(t("upg.buy"))}</button>` },
      ],
    });
    q('[data-role="table"]').addEventListener("click", (e) => {
      const b = e.target.closest("[data-buy]");
      if (b) buy(b.dataset.buy);
    });
  }

  function renderState(d) {
    const box = q('[data-role="state"]');
    q('[data-role="catalog"]').classList.toggle("hidden", !d.upgrades);
    const lines = [`${esc(t("upg.game_dir"))}: <span class="mono">${esc(d.game_dir || "–")}</span>`];
    if (d.found && !d.tested) lines.push(`<span class="warn">${esc(t("upg.untested"))}</span>`);
    if (!d.installed) lines.push(esc(t("upg.not_installed")));
    else if (d.conn) lines.push(esc(["offline", "no_token"].includes(d.conn.error) ? t("upg.offline") : SS.forms.extError(d.conn)));
    else lines.push(`<span class="up">${esc(t("upg.connected", { version: d.plugin_version || d.bridge }))}</span>`);
    const noLaunch = d.installed && d.launch_option && d.launch_set === false && !d.upgrades;
    if (noLaunch) lines.push(`<span class="warn">${esc(t("upg.launch_missing"))}</span>`);
    box.innerHTML = `<p class="upg-lines">${lines.join("<br>")}</p>`;
    if (noLaunch) box.appendChild(SS.forms.launchBox(d));
  }

  async function load() {
    const d = await SS.call("upgrades");
    if (!d || d.supported === undefined) return;
    S.data = d;
    renderState(d);
    if (d.upgrades) {
      S.table.set(d.upgrades.filter((u) => !u.hidden).map((u) => ({
        ...u, name: u.displayName || u.upgradeId, price: u.nextPrice === null ? null : Number(u.nextPrice),
      })));
    }
  }

  async function buy(id) {
    const u = (S.data && S.data.upgrades || []).find((x) => x.upgradeId === id);
    if (!u || S.busy) return;
    const name = u.displayName || u.upgradeId;
    if (!(await SS.confirm(t("upg.buy"), t("upg.confirm_buy", { name, price: fmt.big(Number(u.nextPrice)) }), t("upg.buy")))) return;
    S.busy = true;
    try {
      const r = await SS.call("upgrades_buy", id, 1);
      if (r && r.error) SS.toast(SS.forms.extError(r), "err", 6000);
      else SS.toast(t("upg.bought", { name }), "ok", 6000);
    } finally {
      S.busy = false;
      await load();
    }
  }

  async function refresh(tick) {
    S.cash = tick && tick.cash !== undefined ? tick.cash : S.cash;
    if (S.busy || Date.now() - S.last < 2000) return;
    S.last = Date.now();
    await load();
  }

  SS.registerTab("upgrades", { mount, refresh, show: () => { S.last = 0; } });
})();
