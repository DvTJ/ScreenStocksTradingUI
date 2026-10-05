"""Rolling-window evaluation of the bot on the recorded history (walk-forward, like the "Test on history" button).

    python tools/eval_bot.py --db copy-of-screenstocks.db --stocks '$PLAIN' --caution aggressive --windows 30,60,180
    python tools/eval_bot.py --db copy.db --set confirm_s=8 --set max_loss_pct=1      # try advanced overrides

One test window of each length ends every --step minutes back from the newest price; each is calibrated on the
3 hours before it. Use a COPY of the database (opening it creates tables if they are missing). Windows overlap, so
the counts are not independent samples.
"""

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screenstocks import bot  # noqa: E402
from screenstocks.storage import Storage  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="path of a copy of screenstocks.db")
    ap.add_argument("--stocks", default="", help="comma separated stock ids to trade (default: all)")
    ap.add_argument("--level", default="advanced", choices=bot.LEVELS)
    ap.add_argument("--caution", default="aggressive", choices=list(bot.PRESETS))
    ap.add_argument("--no-shorts", action="store_true")
    ap.add_argument("--max-positions", type=int, default=5)
    ap.add_argument("--trade-pct", type=int, default=100)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="advanced override of a bot.Params field")
    ap.add_argument("--windows", default="30,60,180", help="test window lengths in minutes")
    ap.add_argument("--step", type=int, default=15, help="minutes between window ends")
    ap.add_argument("--count", type=int, default=32, help="number of window ends per length")
    ap.add_argument("--latency", type=int, help="order latency in seconds (default bot.LATENCY_S)")
    ap.add_argument("--fee", type=float, help="fee %% per order (default bot.FEE_PCT)")
    ap.add_argument('--skip', type=int, default=0, help='skip the newest N window ends (to test an older part)')
    args = ap.parse_args()
    bot.LATENCY_S = args.latency if args.latency is not None else bot.LATENCY_S
    bot.FEE_PCT = args.fee if args.fee is not None else bot.FEE_PCT

    db = Storage(args.db)
    first, last = db.first_time_ms(), db.latest_time_ms()
    if not last:
        sys.exit("no prices in this database")
    snap = db.latest_snapshot() or {}
    cash = snap.get("cash") or 10000.0
    cds = (snap.get("buy_cooldown_s") or 85, snap.get("short_cooldown_s") or 85)      # this account's cooldowns
    keep = {x for x in args.stocks.split(",") if x}
    excluded = [x for x in db.stock_ids() if keep and x not in keep]
    overrides = dict(kv.split("=", 1) for kv in args.set)
    s = bot.BotSettings(level=args.level, caution=args.caution, max_positions=args.max_positions,
                        shorts=not args.no_shorts, trade_pct=args.trade_pct, excluded=excluded, overrides=overrides)
    print("effective:", bot.effective(s))
    print(f"history {(last - first) / 3.6e6:.1f} h wall clock, cash {cash:.3e}; one window end every {args.step} min\n")
    print(f"{'window':>8} {'n':>3} {'pos/flat/neg':>13} {'mean':>7} {'median':>7} {'worst':>7} {'best':>7} "
          f"{'trades':>6} {'win':>5} {'worst trade (% of cash)':>24}")
    for minutes in (int(m) for m in args.windows.split(",")):
        eqs, rets, worst_trade = [], [], 0.0
        for k in range(args.skip, args.skip + args.count):
            res = bot.backtest(db, s, first, last - k * args.step * 60_000, *cds, test_s=minutes * 60, capital=cash)
            if res is None:
                continue
            eqs.append(res["equity_pct"] if res["n"] else 0.0)
            rets += [t["ret"] for t in res["trades"]]
            worst_trade = min([worst_trade] + [t["pnl"] / cash * 100 for t in res["trades"]])
        if not eqs:
            print(f"{minutes:>6} m  not enough history")
            continue
        pos, neg = sum(v > 0.05 for v in eqs), sum(v < -0.05 for v in eqs)
        win = 100 * sum(r > 0 for r in rets) / len(rets) if rets else 0.0
        print(f"{minutes:>6} m {len(eqs):>3} {pos:>4}/{len(eqs) - pos - neg:>3}/{neg:>3}  {statistics.mean(eqs):>+6.2f}% "
              f"{statistics.median(eqs):>+6.2f}% {min(eqs):>+6.2f}% {max(eqs):>+6.2f}% {len(rets):>6} {win:>4.0f}% {worst_trade:>+23.2f}%")
    db.close()


if __name__ == "__main__":
    main()
