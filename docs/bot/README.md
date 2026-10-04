# The mean-reversion bot

Code: [`screenstocks/bot.py`](../../screenstocks/bot.py) · self-check: `python tools/check_bot.py` · evaluation:
`tools/eval_bot.py` · parameter search: `tools/tune_bot.py` · instructions for continuing: [`PROMPT.md`](PROMPT.md)

## 1. The idea

In the recorded prices, minute-to-minute returns are strongly **negatively autocorrelated** (about −0.4): a price
is a slow level plus a lot of noise, and a price far from its recent average comes back within a minute or two.
The bot buys when a price is unusually low, shorts when it is unusually high, and closes when the price is back
at its average.

The bot only sends orders when **both the bot and the automation are switched on** and the game is live. It only
manages positions it opened itself. It is **off by default**.

## 2. The algorithm, step by step

### 2.1 Signal (per stock, every second)

```
m = exponential moving average of ln(price)           time constant tau_s
v = matching exponential moving variance
z = (ln(price) − m) / max(√v, 0.002)                  normalised distance from the average
```

For the first `tau_s` seconds after start-up (or after a gap in the data) z is not used ("warming up").

### 2.2 Entry

A stock is a candidate when **all** of these hold:

| Condition | Buy | Short |
|---|---|---|
| Distance | `z ≤ −entry_z` | `z ≥ +entry_z` (only if shorts are allowed) |
| **Confirmation** | the distance has lasted ≥ `confirm_s` seconds | same |
| Expected gain | `(average / price − 1) ≥ min_edge_pct` | `(price / average − 1) ≥ min_edge_pct` |
| Game cooldown | buy cooldown is over | short cooldown is over |
| Context | no foreign position, no announced pump/crash, stock unlocked, shares available (buy only) | same, except shares |
| Pause | the stock is not paused (see 2.5) | same |
| Room | fewer than `max_positions` positions open | same |
| Selection | the stock is among the best ones (see 3) and not excluded | same |

The **confirmation** ignores one-tick blips. On $PLAIN the price changes only about once every thirteen seconds,
but by ±4 % (median). Without the filter the bot entered on such a jump, the price reverted the next second and
it left again, paying the fees for nothing (see example 1).

Buy and short each have a cooldown (≈ 85 s); on every opportunity the **best candidate** wins (largest
`|z| / entry_z`).

### 2.3 Size

```
pct    = trade_pct × min(1, |z| / (2 × entry_z))                        at least 1 %
budget = cash × max_loss_pct / (stop_pct × 1.5)                         most money one entry may use
pct    = min(pct, 100 × budget / money a 100 % order would move)
```

The stake is half of `trade_pct` at the entry threshold and the full `trade_pct` from twice the threshold on;
it **never exceeds** the chosen percentage. On top of that comes a **risk budget**: the stake is capped so that a
stop-loss, with 50 % of slippage (prices jump past the stop), costs at most `max_loss_pct` % of your cash. Risky
trades stay possible, but one bad trade can no longer take a large part of your money. The bot sends the
resulting percentage to the game, which works out the amount itself: *pct % of the maximum allowed*, i.e. your
cash and, for a buy, the shares still available.

### 2.4 Exit (no cooldown, checked before any entry)

In this order of priority:

1. **stop**: the position has lost `stop_pct` %;
2. **time limit**: the position has been open for `max_hold_s` seconds;
3. **back to normal**: `z ≥ −exit_z` (long) or `z ≤ +exit_z` (short).

"Back to normal" does **not** mean "winning": the price came back near the average, but the average itself may
have moved. The reason shown therefore depends on the outcome: **"target reached"** when the trade made money,
**"back to normal, but at a loss"** when it did not (the journal then says "below the entry price").

A position can only be closed once its entry order has filled: the simulation starts the stop and the time limit
at the fill, and live the entry price is the average price the game reports for the new position.

### 2.5 Guard rails

- a **loss limit** (`loss_limit_pct`, 3 % of the cash by default, 0 = off): once the money lost since the bot was
  switched on reaches it, the bot opens no new trade (it still closes open ones) until it is switched off and on
  again; the status sentence says so;
- one command at a time; the next one is sent only after the result of the previous one (8 s at most, then it is
  cancelled);
- a stock whose command fails is skipped for 30 s;
- a stock that **loses twice in a row** is paused for 15 minutes;
- a position closed by hand in the game is forgotten by the bot;
- no entry on a stock with a foreign position, nor during an announced pump/crash.

## 3. The "mini AI": calibration on the history

At start-up, then every `recalib_min` minutes (10 by default) and whenever the settings change, the bot replays
**the last 3 hours** of recorded prices (recording gaps longer than a minute are cut out) on a separate thread:

1. for **each stock** it tries 12 sets `(tau_s, entry_z)`: `tau_s ∈ {60, 120, 240}` ×
   `entry_z ∈ {base − 0.5, base, base + 0.5, base + 1}`, where *base* comes from the chosen caution level; the
   other settings (stop, time limit, confirmation, minimum gain) come from the caution level;
2. each try is a simulation **with the same strategy as live**, with 2 s latency, 0.3 % fee per order, the
   game's cooldown and the stake calculation above;
3. it keeps the set with the best **net profit in money** (not in %), and a stock only counts as "proven" if that
   profit is positive over at least 3 trades;
4. it ranks the proven stocks and only trades the best `max(3, 2 × max_positions)`.

Until the first calibration has finished, or with less than 15 minutes of history, the bot does not trade (the
status sentence says so). If no stock is proven: "no stock looks profitable right now".

## 4. Levels and caution

| Level | What you set |
|---|---|
| **Simple** | the switch and the stake %. Everything else: caution *Balanced*, no shorts, 3 positions |
| **Medium** | + caution, max. positions, shorts |
| **Advanced** | + every threshold, the calibration interval, the loss limit and the excluded stocks. Fields are pre-filled by the calibration ("auto"). A value changed by hand ("manual") replaces the calibration for all stocks |

| Caution | tau_s | entry_z | exit_z | min_edge % | stop % | time limit (s) | confirmation (s) | max. loss per trade (% of cash) | positions |
|---|---|---|---|---|---|---|---|---|---|
| Cautious | 240 | 1.0 | 0.1 | 2 | 15 | 300 | 8 | 3 | 1 |
| Balanced | 240 | 1.0 | 0.1 | 2 | 15 | 300 | 8 | **10** | 2 |
| Aggressive | 240 | 1.0 | 0.1 | 2 | 15 | 300 | 8 | 20 | 3 |

The three modes share the tuned signal (section 8d) and differ only in risk (`max_loss_pct`) and positions.
The calibration still tries `tau_s` 60 / 120 / 240 and `entry_z` base − 0.5 … base + 1 per stock.


## 5. The history test

The "Test on history" button runs a **walk-forward test**. The bot learns on the history *before* the tested
period (3 h at most), then trades that period (15 min, 30 min, 1 h, 3 h, 6 h, 24 h or "all" = the second half). The
simulation applies the cooldown, the 2 s latency, the 0.3 % fee and the game's real stake rule (your cash or the
starting money you type in; shares available for buys). The detail window lists every trade with its time and
gives the totals per stock and for the last 15 min / 30 min / 1 h / 3 h / 6 h.

**Known limits**, to keep in mind when reading a result:

- the **impact of your own orders** on the price is not simulated (buying millions of shares moves the price);
  real results are worse;
- announced **pumps and crashes**, which the bot avoids live, are not simulated;
- the number of available shares is today's, not the one at the time;
- 2 s of latency is optimistic: with 5 s several settings lose their edge;
- with a large stake a few trades dominate the result: look at the **average return per trade** and the **win
  rate** rather than the total gain; over 15 to 60 minutes a losing streak is normal.

## 6. Exporting to share

- **Export my algo… / Import an algo…** (tab header): the settings alone, saved switched off; importing leaves
  the on/off switch untouched. Same format as the Automation tab's export (a `bot` block), so a full config file
  imports too.
- **Export results…** (in the "Show details" window): a JSON `screenstocks-bot-report`:

| Field | Content |
|---|---|
| `settings`, `effective` | the chosen settings and the parameters the level really uses |
| `cash`, `net_worth`, `stocks` | money, net worth, price / max volume / available shares per stock |
| `calibration` | per stock: chosen parameters, simulated profit, number of trades, win rate, "proven" |
| `results` | real trades since activation: side, return %, money used, entry / exit price, reason |
| `positions`, `journal` | open positions and the plain-language journal |
| `history_test` | the last test: every trade with entry and exit time, totals, cooldowns |

## 7. What the example reports taught

Real history tests (`$PLAIN`, Advanced, shorts) were exported with "Export results" and led to these changes: the
1-second round trips (→ `confirm_s`), a "target" exit filling 2 s late after a +14 % tick (→ the risk budget and the
stress test), a simulator bug (stop checked before the entry fill, fixed), the one-tick jump problem on `$PUMP` /
`$QUIK` (→ `jump_pct`, section 8c), and that 15 min to 1 h windows hold 2 to 10 trades so only 3 h windows are a fair
judge. A 1 h `$PLAIN` test with 6 trades gave +0.52 % because the risk budget caps the stake at about 9 % of the
cash (`max_loss_pct` 2 / (stop 15 x 1.5)); the gain scales with `max_loss_pct`. The report files contain real amounts
and are not kept in the repository: export your own and give them as context.

## 8. How much can it lose?

The loss is set by `max_loss_pct`, not by the strategy. Rolling 1-hour history tests (12 overlapping windows, one
every 30 minutes, `$PLAIN` only, Aggressive, calibration on the 3 hours before each window):

| max_loss_pct | sum of the 12 windows | worst window | negative windows | worst single trade |
|---|---|---|---|---|
| 1 % | +7.2 % | −0.9 % | 2 / 12 | −0.6 % of the cash |
| 1.5 % | +10.8 % | −1.4 % | 2 / 12 | −0.8 % |
| 2 % (Aggressive default) | +14.4 % | −1.9 % | 2 / 12 | −1.1 % |
| 3 % | +23.5 % | −3.0 % | 2 / 12 | −1.8 % |

Gains and losses scale together (the ratio stays around 7.5): choose the budget you can live with. The worst
window is always the same one, the example 5 hour. Things that did **not** help in these tests: a trend filter,
holding a position until it is profitable, forcing the calibration to profit on both halves of its window.
Raising the entry threshold removes most of the trades (9 trades in 12 windows, +4 %) without removing the
tail risk of fills far from the signal price.

### Rolling windows over the whole recorded history

All the recorded history is about **8 hours** of one session, so any single window holds only a few trades. To get
meaningful statistics the history test was run on **32 windows per length** (one ending every 15 minutes, each one
calibrated on the 3 hours before it, `$PLAIN` only, risk budget 2 %, pause after two losses as live). Windows
overlap, so these are about 50 to 100 distinct trades, not 90 to 320:

| Setup | Window | Positive / flat / negative | Mean | Median | Worst | Win rate | Worst trade |
|---|---|---|---|---|---|---|---|
| Aggressive | 30 min | 27 / 1 / 4 | +0.6 % | +0.7 % | −1.3 % | 79 % | −1.1 % of cash |
| Aggressive | 1 h | 24 / 5 / 3 | +1.1 % | +1.3 % | −1.6 % | 77 % | −1.1 % |
| Aggressive | 3 h | 19 / 13 / **0** | +2.5 % | +3.1 % | 0 % | 79 % | −1.2 % |
| Balanced | 1 h | 8 / 24 / 0 | +0.2 % | 0 % | 0 % | 82 % | −0.1 % |
| Prudent | any | no trade at all on `$PLAIN` | | | | | |

Reading it: over 3 hours the bot never lost money in this history; over 30 minutes to 1 hour roughly one window in
ten is negative, and those windows are all the same bad stretch described in examples 5 to 8. Balanced and
Prudent trade `$PLAIN` almost never (their entry threshold is too high for it), and without shorts the Aggressive
setup takes no trade either, so on `$PLAIN` the whole result comes from shorting price spikes. **Few trades and a
loss in a short window is therefore expected**, not a sign that the setting is wrong; a 3-hour window or longer is
the fair way to judge it.

What was tried on top of this and **did not help** (so it is not in the bot): a trend filter on the average (10, 30
and 60 minutes), a median filter on the price, holding a position until it is profitable, forcing the calibration to
profit on both halves of its window, and different pause rules (1, 2 or 3 losses, 10 to 60 minutes: no real change).
More recorded history would make these comparisons much more reliable: keep the app running and export a report
now and then.

Takeaway: the bot has a small edge per trade (in the order of +2 to +4 % on `$PLAIN` in the history) and a high
variance; judge it over dozens of trades, not over 15 minutes.

## 8b. Risk gradient (presets) and what was tried next

*(Measured with the previous signal, entry_z 2.5 / confirmation 5 s; see 8d for the current one.)*

Before: Cautious never traded `$PLAIN` and Balanced almost never (entry_z 3.5 / 3.0 too high), so the only presets
that did anything were the riskiest. Now the three presets share the signal that works (entry_z 2.5, min edge 2 %)
and differ by **risk** (`max_loss_pct` 0.5 / 1 / 2, stop, hold, confirmation, positions). `$PLAIN`, shorts, 32
rolling windows, 100 % stake, calibrated on the 3 h before each window:

| Setup | Window | Pos / flat / neg | Mean | Worst | Worst trade | Same at 5 s latency + 0.6 % fee (mean / worst) |
|---|---|---|---|---|---|---|
| Cautious before | 1 h / 3 h | 0 trades | 0 | 0 | 0 | |
| Cautious now | 1 h | 25 / 5 / 2 | +0.38 % | −0.45 % | −0.38 % | +0.44 % / −0.23 % |
| Cautious now | 3 h | 20 / 12 / 0 | +0.89 % | 0 % | −0.38 % | +0.84 % / 0 % |
| Balanced before | 1 h / 3 h | 9 / 23 / 0 · 2 / 30 / 0 | +0.21 % | 0 % | −0.05 % | |
| Balanced now | 1 h | 25 / 5 / 2 | +0.67 % | −0.81 % | −0.70 % | +0.51 % / −0.30 % |
| Balanced now | 3 h | 20 / 12 / 0 | +1.62 % | 0 % | −0.72 % | +1.18 % / 0 % |
| Aggressive (unchanged) | 1 h / 3 h | 25 / 5 / 2 · 20 / 12 / 0 | +1.07 % / +2.61 % | −1.30 % | −1.14 % | +0.81 % / −0.49 % |

Gain and worst loss rise together from Cautious to Aggressive, and every level holds up under the stress test
(`tools/eval_bot.py --latency 5 --fee 0.6`; `simulate` now reads `LATENCY_S` / `FEE_PCT` at call time so this works).

Tried and **rejected** in this round:

- **Stake reduced after a loss** (halve after a loss, double after a win, floor 25 %): 1 h worst window −1.30 → −0.65 %
  at 2 s latency, but nothing under the stress test, and no help on the older half of the history. Not robust.
- **News filter** (`market_news` holds only "5-minute high / low" items, no all-time high): 5 to 8 of 57 trades
  coincide with a matching news, no measurable difference (+3.3 % vs +2.5 % per trade, 5 samples). The z-score
  already captures the same 5-minute extreme, so it is not in the bot.
- Tighter stop (8 % instead of 15 %) at the same risk budget: identical results, stops rarely decide a trade.

Caution: on **all stocks** the simulation shows absurd gains (+100 % in 3 h) and −16 % worst trades; small stocks
move far more than their order book could absorb. Treat it as unmodelled order impact, not as an expectation.

## 8c. Volatility, news and events

- **`jump_pct` (typical big jump)**: the calibration measures each stock's 97th-percentile one-tick move (`$PLAIN`
  ~22–29 %, `$PUMP` 72 %, `$STEAM` 77 %, `$BANK` 8 %). The risk budget then uses `max(stop × 1.5, jump_pct)` as the
  loss one trade may cost, and no trade is taken when even a 1 % stake would exceed it: a stop cannot protect
  against a jump bigger than itself (the all-stock report showed −114 % and −55 % trades on `$PUMP` / `$QUIK`).
  It is **forced** on stocks whose jump exceeds 1.5 × the stop's reach (`$PUMP`, `$QUIK`, `$STEAM`) and **chosen by the
  calibration** on calm ones (kept only if it scores at least as well), so `$PLAIN` is not slowed down.
  Aggressive, 100 % stake, rolling windows, before → after: `$PLAIN` 3 h unchanged (+2.53 %, worst trade −1.18 %);
  all stocks 3 h mean +233 → +186 %, worst trade −62 → −31 % of the cash (gains stay inflated, see section 5).
- **Selection score**: the calibration now ranks parameter sets by net profit **minus the worst trade** (a set that
  wins only by risking a disaster loses), and `good` needs that score > 0 and ≥ 3 trades.
- **`news_s` (trade on news, Advanced, 0 = off in every preset)**: a "5-minute high" news may trigger a short, a
  "low" a buy, for `news_s` seconds, still subject to minimum gain, cooldowns and stake rules. `$PLAIN`,
  `news_s=30`: trades 41 → 59 (15 min), but win rate 78 → 68 %, negative 1 h windows 2 → 5; letting the calibration
  switch it on per stock gave 72 % wins and a −1.6 % worst trade, so **it is not calibrated, only manual**
  ("back to before" when there is no gain). Only high / low news exist (no all-time high).
- **Events** (`$PLAIN` crash to about 10, rebound, fall again; one in the history) are traded by the separate
  event trader. The bot stays out of that stock only in a window around the event (from `crash_minutes` + 90 s before
  it, or 60 s + 90 s for a pump, until 15 min / 3 min after); before, any announced event blocked its stock from the
  announcement, hours ahead, which silently cost good trades. The buy / short cooldown is shared by all stocks,
  so while an enabled event is near (crash: `crash_minutes` + 90 s before; pump: 60 s + 90 s) the bot opens no new
  trade. Not simulated.
- **Packages**: none added. Calibration takes ~14 s per 8 stocks, almost all in the sequential strategy loop;
  numpy cannot speed it up without a second (untested) copy of the strategy.

## 8d. Tuned signal and the risk dial at 10 %

`python tools/tune_bot.py --db <copy> --stocks '$PLAIN' --max-loss 10` runs a coordinate descent in parallel (stdlib
`ProcessPoolExecutor`, no package): 3 h walk-forward windows under stress (latency 5 s, fee 0.6 %), score = median
window gain, rejected when more than 1 window is negative or the worst trade exceeds 15 % of the cash. Found:
`entry_z` 1.0, `confirm_s` 8, `exit_z` 0.1, `tau_s` 240 (`max_hold_s`, `min_edge_pct` change nothing: exits come from
the target or the stop first). One-at-a-time at `max_loss_pct` 10 (`$PLAIN`, 3 h, mean): confirm 8 and `exit_z` 0.1
and `entry_z` ≤ 2 each help; confirm 3 makes 8 of 32 one-hour windows negative with −23 % worst trade; confirm 8 cuts
the worst trade from −9 % to −0.7 % at about the same gain.

| `$PLAIN`, 3 h windows, 32 ends | Normal (2 s, 0.3 %) | Stress (5 s, 0.6 %) | Worst trade, stress |
|---|---|---|---|
| Old signal at 10 % (entry 2.5, confirm 5) | +43 % mean | +33 % mean, 10 negative windows, worst −27 % | −40 % of cash |
| Tuned signal, fixed overrides | | median +78 %, worst window +38 % | −14.4 % |
| Cautious (3 %), calibrated | +72 % | +24 %, worst +9 % | −3.6 % |
| **Balanced (10 %), calibrated** | **+184 %**, worst +88 % | **+64 %**, worst +29 %, 0 negative | −13.7 % |
| Aggressive (20 %), calibrated | +360 % | +93 %, worst +32 % | −27 % |

Out of sample (old half / new half, stress, fixed overrides): median +97 % / +49 % against +60 % / +31 % for the
previous best, 0 negative windows in both. Windows compound the cash, so the percentages are large; the point is the
ratio between rows. Not helpful: holding a losing position longer (a "target" exit at a raw loss never happens with
these settings: identical results); a "range position" filter (81 of 98 longs already enter in the lowest third of the
previous 3 h with +19 % mean, 89 of 109 shorts in the highest third; the 17 mid-range longs gain only +2.3 %).
Caveats: one 8-hour session, own-order impact ignored on purpose, and the worst trade at 10 % is about −14 % of the
cash (the loss limit of 3 % since activation stops the bot long before).

**Max. positions**: with `$PLAIN` alone it changes nothing (one stock, one position). On all stocks (stress, 3 h,
32 windows) 1 and 2 positions had 0 negative windows, 3, 5 and 10 had 6 of 32, hence 1 / 2 / 3 in the presets. Absolute
all-stock gains are meaningless (no volume limit on small-stock shorts), only the ranking counts. The settings screen
now explains every field with a hover "i".

## 8e. Experimental tab and practice mode

The tab is labelled **experimental** and shows a one-time warning (money can be lost; acknowledgement stored in the
`bot_warning_ack` setting). **Practice mode** (`paper` setting, switch next to the bot switch) runs the same live
strategy on a **virtual wallet** (the game cash at activation + closed trades): no command is ever written, the
automation switch is not needed, and positions / results are kept in separate sheets (`bot_state_paper`,
`bot_results_paper`) so real trading is untouched. Fills are at the current price with the 0.3 % fee per side, no
latency (a little optimistic), with its own 85 s buy / short cooldowns. `tools/check_bot.py` asserts that no order is
sent and the real sheets stay empty. Exports (setup, report, automation config) offer to open the folder (toast button
on the web UI, a question in Tk).

## 8f. "What the bot thinks" and the warm start

A panel (web and Tk) lists, per stock, why the bot acts or not, in plain language and the three languages
(`Strategy.why_not`, `BotTrader._say`): warming up, price near normal (z and the threshold), confirming (x / y s),
expected move too small, cooldown (seconds left), positions full, ready, holding (gain, z, exit), paused, event, loss
limit, and a **DECISION** line for each entry (z, seconds confirmed, expected move, stake). A stock's line is repeated at
most every 60 s while nothing changes. **Warm start**: the live strategy is fed the last 30 minutes of recorded prices
when the bot starts; before, a restart needed `tau_s` (240 s) of live prices before any signal, so a bot started during a
good setup silently missed it (a replay of the last 40 minutes showed trades at 18:12:38 and 18:13:34 that the freshly
started bot could not take).

**Trades history**: the "See details" button under the results opens a table of every trade of the current
activation (real or practice sheet): time, stock, side, return, money used, profit, entry / exit price, duration,
reason, with a summary and per-stock totals. "Export trades (CSV)" writes a spreadsheet-friendly file (comma separated,
UTF-8 with BOM); "Export results" writes the full JSON report.

**Order rules checked against the real command log**: a buy starts only the buy cooldown (85 s), a sell has none, the short
cooldown is separate; a stock is never long and short at once (0 such rows in `position_history`); a command runs in
0.2 to 0.3 s and one at a time. The simulation and the practice mode now also send **one command per second** (the other
signals are re-evaluated the next second), as the live bot does. Balanced, `$PLAIN`, 3 h: +184 → +176 % normal, +64 → +64 %
stressed (worst window +29 → +13 %). Not modelled: refused orders (108 of 214 logged commands failed with `no-volume`,
i.e. no shares available at that moment; the practice mode does skip buys when none are available).

## 9. Checking the code

```
python tools/check_bot.py
python tools/eval_bot.py --db <copy of screenstocks.db> --stocks '$PLAIN' --windows 30,60,180
python tools/tune_bot.py --db <copy> --stocks '$PLAIN' --max-loss 10     # parameter search
```

`tools/eval_bot.py` produces the rolling-window tables of section 8 (use a **copy** of the database).
`PROMPT.md` is a ready-to-use prompt for continuing the work on the algorithm.

An assert script (no framework): strategy, confirmation filter, levels and settings, stake, volume limits,
calibration, history test, export / import, German / English / French texts (same keys, same placeholders), bot
off by default.
