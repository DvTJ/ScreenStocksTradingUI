/* Leaderboard tab (only with the game extension): the game's player and clan rankings.
   The game allows one leaderboard request per 30 s for all lists together, so a list is refreshed
   at most once a minute while the tab is open; switching lists shows the last copy first. */
"use strict";

(() => {
  const { t, fmt, esc } = SS;
  const MODES = ["current", "all_time", "ipo", "current_top", "clan_net_worth", "clan_player_share"];
  const CLAN = new Set(["clan_net_worth", "clan_player_share"]);
  const S = { el: null, table: null, mode: "current", last: 0, busy: false, selfRank: null };
  const q = (sel) => S.el.querySelector(sel);

  function columns(clan) {
    const rank = { key: "rank", label: t("lb.col_rank"), align: "r", render: (r) => `<span class="mono">${esc(String(r.rank ?? "–"))}</span>` };
    const net = { key: "net", label: t("common.net_worth"), align: "r", value: (r) => r.net ?? -1, render: (r) => esc(fmt.big(r.net)) };
    if (clan) {
      return [rank, { key: "clan", label: t("lb.col_clan"), render: (r) => `<b>${esc(r.clan || "–")}</b>` }, net,
        { key: "share", label: t("lb.col_share"), align: "r", render: (r) => esc(r.share == null ? "–" : fmt.pct(r.share, false)) }];
    }
    return [rank, { key: "name", label: t("lb.col_player"), render: (r) => `<b>${esc(r.name || "–")}</b>` },
      { key: "clan", label: t("lb.col_clan"), render: (r) => esc(r.clan || "") }, net,
      { key: "ipo", label: t("lb.col_ipo"), align: "r", render: (r) => esc(String(r.ipo ?? "–")) }];
  }

  function makeTable() {
    S.table = SS.ui.table(q('[data-role="table"]'), {
      columns: columns(CLAN.has(S.mode)), sortKey: "rank", sortDesc: false, empty: "–",
      rowClass: (r) => (!CLAN.has(S.mode) && r.rank === S.selfRank ? "lb-self" : ""),
    });
  }

  function mount(el) {
    S.el = el;
    el.innerHTML = `
      <div class="lb">
        <div class="panel lb-top">
          <div class="seg" data-role="modes">${MODES.map((m) => `<button data-mode="${m}">${esc(t(`lb.mode.${m}`))}</button>`).join("")}</div>
          <span class="lb-me" data-role="me"></span>
          <span class="spacer"></span>
          <span class="muted" data-role="age"></span>
          <button class="btn ghost" data-role="refresh">${esc(t("lb.refresh"))}</button>
        </div>
        <section class="panel box grow"><div data-role="table" class="grow"></div>
          <div class="hint">${esc(t("lb.hint"))}</div></section>
      </div>`;
    q('[data-role="modes"]').onclick = (e) => {
      const b = e.target.closest("[data-mode]");
      if (!b || b.dataset.mode === S.mode) return;
      S.mode = b.dataset.mode;
      makeTable();
      load(false);
    };
    q('[data-role="refresh"]').onclick = () => load(true);
    makeTable();
  }

  async function load(force) {
    if (S.busy) return;
    S.busy = true;
    S.last = Date.now();
    q('[data-role="modes"]').querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset.mode === S.mode));
    try {
      const mode = S.mode;
      const d = await SS.call("leaderboard", mode, !!force);
      if (!d || mode !== S.mode) return;
      if (d.error) {
        if (["rate_limited", "leaderboard_busy"].includes(d.error)) {       // no copy of this list yet: ask again then
          S.table.set([]);
          setTimeout(() => { if (S.mode === mode) load(false); }, Math.max(1000, (d.retry_s || 5) * 1000 + 500));
        }
        const key = `upg.err.${d.error}`;
        q('[data-role="age"]').textContent = SS.texts[key] !== undefined ? t(key)
          : d.error === "rate_limited" ? t("lb.wait", { s: Math.ceil(d.retry_s || 30) }) : t("upg.err.failed");
        return;
      }
      S.selfRank = d.self_rank ?? null;
      q('[data-role="me"]').textContent = !CLAN.has(mode) && d.self_rank
        ? t("lb.me", { rank: fmt.num(d.self_rank, 0), total: d.total ? fmt.num(d.total, 0) : "–" }) : "";
      q('[data-role="age"]').textContent = d.retry_s > 0 ? t("lb.wait", { s: Math.ceil(d.retry_s) })
        : t("lb.age", { s: Math.round(d.age_s || 0) });
      S.table.set(d.rows || []);
    } finally {
      S.busy = false;
    }
  }

  async function refresh() {
    if (Date.now() - S.last >= 60000) await load(false);
  }

  SS.registerTab("leaderboard", { mount, refresh, show: () => load(false) });
})();
