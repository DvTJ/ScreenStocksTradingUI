# Continuing work on the ScreenStocks bot

Answer in the user's language (French). Goal: best risk-adjusted result (small worst window), not the best backtest.

## Read
`docs/bot/README.md` (algorithm, parameters, findings), `screenstocks/bot.py` (`Params`, `PRESETS`, `Strategy`,
`simulate`, `calibrate`, `BotTrader`), `tools/check_bot.py`, `tools/eval_bot.py`. UIs: `gui/bot_tab.py`,
`web/bot_api.py` + `web/static/js/tabs/bot.js`; texts in `i18n/{de,en,fr}.py`.

## Rules
- Branch `feature/bot-tab`, local. Never push or commit unless asked. Never `git stash`/reset the working tree.
- Bot off by default; trades only with bot **and** automation on. One `Strategy` for live, `simulate` and `calibrate`:
  a live rule must exist in the simulation (events and news live-only exceptions are documented).
- Texts in German, English, French with the same keys; docs in English; assert-based scripts only, no test framework.
- New parameters: `Params` field (+ preset value) → use in `Strategy`/`stake_pct`/`simulate` → i18n `bot.p.<n>` /
  `bot.d.<n>` ×3 → `STEP` in `gui/bot_tab.py` and `bot.js` → assert in `check_bot.py` → README. Advanced level only.
- Presets are a risk gradient (Prudent small → Aggressive) on the same signal; the dial is `max_loss_pct`.
- Respect the game's buy/short cooldown (shared by all stocks); keep it free before events.
- Run scripts on a **copy** of `%LOCALAPPDATA%\ScreenStocksTradingBot\screenstocks.db` (+ `-wal`, `-shm`).
  `python -m pip`, `PYTHONIOENCODING=utf-8` on Windows. Packages may be installed to test and removed after.

## Method
1. Baseline: `python tools/eval_bot.py --db <copy> --stocks '$PLAIN' --windows 15,60,180` (also without `--no-shorts`
   variants and all stocks). 2. One change at a time, same command; compare distributions (positive/flat/negative
   windows, mean, median, worst window, worst trade % of cash), not the mean. 3. Pick on the older half
   (`--skip 16 --count 16`), confirm on the newer one. 4. Stress: `--latency 5 --fee 0.6`. 5. Keep a change only if it
   gains; otherwise revert to the previous behaviour and document it as rejected. 6. `python tools/check_bot.py`.

## Settled decisions
Defaults: max_loss_pct 10 % (user's choice), 3 presets sharing the tuned signal (entry_z 1.0, confirm 8, exit_z 0.1, tau 240),
search with `tools/tune_bot.py` (stdlib parallel, no package).
Objective: minimise the worst window (≤ 2 % per hour, ≤ 3 % since activation), `$PLAIN` with shorts, stake 100 %
with the risk budget, own-order impact ignored. Calibration score = net profit − worst trade. Jump budget forced on
wild stocks, calibrated on calm ones. News entry manual only. Rejected: trend/median filters, loss-adaptive stake,
tighter stop, higher entry threshold, news as calibrated option.

## Data that would help next
Measured delays (`command_results.received_ms/finished_ms`) and real fills; days of extra history; more events.
