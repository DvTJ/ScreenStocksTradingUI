"""Coordinate-descent search of the bot parameters on the recorded history (use a COPY of the database).

    python tools/tune_bot.py --db copy.db --stocks '$PLAIN' --max-loss 10

Each candidate runs 3 h walk-forward windows (as tools/eval_bot.py) under stress (latency 5 s, fee 0.6 %); the score is
the median window gain, rejected when more than one window is negative or the worst trade exceeds --worst-trade
(% of cash). The winner is re-run on the older and newer half. Candidates run in parallel (stdlib only).
"""

import argparse
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screenstocks import bot  # noqa: E402
from screenstocks.storage import Storage  # noqa: E402

SPACE = {"entry_z": (1.0, 1.25, 1.5, 1.75, 2.0, 2.5), "confirm_s": (4, 5, 6, 7, 8, 9, 10), "exit_z": (0.05, 0.1, 0.2, 0.3),
         "stop_pct": (10, 15, 20, 25), "min_edge_pct": (1, 2, 3), "tau_s": (0, 60, 120, 240)}    # tau_s 0 = calibrated
CFG: dict = {}


def run(overrides: dict, skip: int = 0, count: int = 32) -> dict:
    """Stats of the 3 h windows for one set of overrides."""
    bot.LATENCY_S, bot.FEE_PCT = CFG["latency"], CFG["fee"]
    db = Storage(CFG["db"])
    try:
        first, last = db.first_time_ms(), db.latest_time_ms()
        snap = db.latest_snapshot() or {}
        cash = snap.get("cash") or 10000.0
        cds = (snap.get("buy_cooldown_s") or 85, snap.get("short_cooldown_s") or 85)      # this account's cooldowns
        keep = {x for x in CFG["stocks"].split(",") if x}
        s = bot.BotSettings(level="advanced", caution="aggressive", max_positions=5, shorts=True, trade_pct=100,
                            excluded=[x for x in db.stock_ids() if keep and x not in keep],
                            overrides={k: v for k, v in overrides.items() if v})
        eqs, worst = [], 0.0
        for k in range(skip, skip + count):
            r = bot.backtest(db, s, first, last - k * 900_000, *cds, test_s=10800, capital=cash)
            if r:
                eqs.append(r["equity_pct"] if r["n"] else 0.0)
                worst = min([worst] + [x["pnl"] / cash * 100 for x in r["trades"]])
    finally:
        db.close()
    neg = sum(v < -0.05 for v in eqs)
    ok = bool(eqs) and neg <= 1 and worst >= -CFG["worst_trade"]
    return {"ov": overrides, "median": statistics.median(eqs) if eqs else 0.0, "mean": statistics.mean(eqs) if eqs else 0.0,
            "min": min(eqs, default=0.0), "neg": neg, "worst": worst, "ok": ok}


def show(tag: str, r: dict) -> None:
    print(f"{tag:>8} median {r['median']:+7.1f}% mean {r['mean']:+7.1f}% worst window {r['min']:+7.1f}% neg {r['neg']} "
          f"worst trade {r['worst']:+6.1f}%  {'' if r['ok'] else 'REJECTED '}{r['ov']}", flush=True)


def init(cfg: dict) -> None:
    CFG.update(cfg)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True)
    ap.add_argument("--stocks", default="")
    ap.add_argument("--max-loss", type=float, default=10.0)
    ap.add_argument("--worst-trade", type=float, default=15.0, help="reject candidates whose worst trade loses more (%% of cash)")
    ap.add_argument("--latency", type=int, default=5)
    ap.add_argument("--fee", type=float, default=0.6)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    cfg = {"db": args.db, "stocks": args.stocks, "latency": args.latency, "fee": args.fee, "worst_trade": args.worst_trade}
    init(cfg)
    cur = {"max_loss_pct": args.max_loss, "entry_z": 2.0, "confirm_s": 8, "exit_z": 0.1}
    with ProcessPoolExecutor(args.workers, initializer=init, initargs=(cfg,)) as pool:
        best = run(cur)
        show("start", best)
        for rnd in range(args.rounds):
            for key, values in SPACE.items():
                cands = [{**best["ov"], key: v} for v in values if best["ov"].get(key) != v]
                for r in pool.map(run, cands):
                    if r["ok"] and (not best["ok"] or r["median"] > best["median"]):
                        best = r
                        show(f"r{rnd + 1} {key}", r)
        print("\nbest:", best["ov"])
        for name, skip in (("older half", 16), ("newer half", 0)):
            show(name, run(best["ov"], skip, 16))
            show("  base", run(cur, skip, 16))


if __name__ == "__main__":
    main()
