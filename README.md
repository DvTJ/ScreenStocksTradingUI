# ScreenStocks Trading Bot

[Deutsch](README.de.md)

A desktop companion for the game **Screen Stocks**. It reads the game's mod export files,
records a permanent price and portfolio history, lets you trade by exact percentages and runs
automated rules such as stop-loss and take-profit.

*Unofficial fan project – not affiliated with the developers of Screen Stocks.*

Since 2.0 the app has a new interface (dark design, TradingView charts). The previous interface is still
available: switch under **⚙ Settings → General → Interface**. If the Microsoft Edge WebView2 runtime is
missing (it ships with Windows 10/11), the app starts the classic interface automatically and offers the download.

## Features

- **Market** – all stocks with price, change (1m/5m/15m/1h), dividend, availability, your position and P/L;
  price chart per stock with market-news markers, your trades (B buy · S sell · H short · C cover),
  average entry price, scheduled events and active automation rules. CSV export.
- **Trade** – buy, sell, short, cover or close the selected stock by percentage (1–100%, whole numbers,
  as the game rounds them). Shows the result the game reports (done / rejected + reason).
- **Automation** – stop-loss, take-profit (fixed price or % from entry), trailing stop, limit buy,
  limit short, trailing buy / trailing short (follow the low / high and enter when the price turns by X %, optionally
  only once the price has reached an activation level). Optional "confirm after N seconds" against short spikes. By default a rule fires once and
  disables itself; with **↻ Repeat** it stays active and fires again each time the price leaves the
  trigger zone and reaches it again. Cooldown / rate-limit rejections are retried automatically.
- **Announced events** – the game announces pumps (~1 min ahead) and crashes (hours ahead). With the switches
  in the Automation tab (off by default) the app buys after a pump announcement, sells on the pullback from the
  peak, shorts and covers near the starting price; before a crash it sells and shorts N minutes ahead and covers
  and buys back on the rebound from the low. All thresholds are adjustable.
- **Bot** – a mean-reversion trader (off by default): prices swing around a slow average, so it buys when a price is
  far below its moving average and sells when it returns (optional shorts, stop-loss, max hold time, one command at
  a time, respects the game's cooldowns). A backtest replays the recorded history with the same logic. Its settings
  are included in the config export.
- **Config export / import** – the Automation tab can export chosen rules and the pump/crash settings to a JSON
  file and import them again (identical rules are skipped).
- **Chart zoom** – mouse wheel zooms, dragging pans, **Shift + drag** zooms into a rectangle (time and price),
  double-click, **R** or “Reset zoom” resets. In the classic interface: drag a rectangle to zoom, right mouse
  button to pan.
- **Compare** – all stocks normalised to % change on one chart.
- **Portfolio** – net worth and cash over time, open positions, position changes.
- **Dividends** – the export only contains the dividend rate, so payouts are detected from cash increases
  at the full minute (also back-filled from existing history). The app learns your dividend multiplier
  (upgrades/level) from the last payouts and shows the expected dividend per minute per stock, the total
  per minute/hour, dividends received in the selected range and a payout list.
- **News** – market high/low alerts and scheduled events with countdown.
- **Dividends tab** – ranking of all stocks by dividend yield per invested money (per minute / hour,
  income per 1M invested), your own dividend per stock and whether shares are available to buy.
- **Journal tab** – all trades with realized P/L (market price at trade time − average entry), win rate,
  average win/loss, best/worst trade, P/L per stock and dividends received – for any time range.
- **Statistics tab** – volatility per minute/hour, min/max/spread, time above/below the base price,
  base crossings and the average price move 1/5/15 minutes after high/low market news.
- **Settings** (⚙) – language (applied immediately), interface, folders, database; a fixed colour per stock
  (palette or any colour); data maintenance; update check; About with the libraries and licences used.
- **Keyboard** – **1–8** switch tabs, **Ctrl+,** opens the settings, **Esc** closes dialogs; in the market tab
  **↑ / ↓** select the previous / next stock and **R** resets the chart zoom.
- **Update check** – on every start (can be switched off); shows a notice with a link to the release and,
  in the installed app, downloads and starts the new installer on request.
- **Data compaction** – prices and portfolio snapshots older than 7 days are thinned out to one value per
  10 seconds at start-up; trades, news, dividends and rules are always kept.
- German, English and French UI, setup wizard on first start.

## Installation

Download the latest `ScreenStocksTradingBot-Setup-x.y.z.exe` from
[Releases](../../releases) and run it. No admin rights are needed (per-user install).
A portable ZIP is attached to every release as well.

On first start a short setup wizard asks for:

1. **Language** – Deutsch / English / Français
2. **Game folder** – the mod's `export` folder, usually
   `%USERPROFILE%\AppData\LocalLow\Conradical Games\Screen Stocks\mods\export`
   (detected automatically). The wizard can switch on `export` and `commands`
   in the game's `mod-settings.json`.
3. **Database** – where the history is stored (default `%LOCALAPPDATA%\ScreenStocksTradingBot\screenstocks.db`)

Everything can be changed later under **⚙ Settings**; the wizard itself can be reopened via the start-menu
entry "ScreenStocks Trading Bot – Setup" (or `--setup`). Settings live in `%APPDATA%\ScreenStocksTradingBot\settings.json`;
uninstalling keeps your settings and history.

> **Note:** trading commands and automation rules act in the game through the mod's command files.
> Rules only fire while the app is running and the game is live. Fills are not guaranteed at the
> trigger price.

## Running from source

Requires Python 3.10+ (Windows, tkinter included). The new interface needs `pywebview`;
without it the classic interface starts.

```
pip install -r requirements.txt
python main.py              # dashboard + recording
python main.py --ui classic # classic interface for one run
python main.py --setup      # run the setup wizard again
python main.py --headless   # record + automation without a window
python main.py --lang en    # override the UI language for one run
```

## Building

```
pip install pyinstaller
pyinstaller --noconfirm ScreenStocksTradingBot.spec            # -> dist/ScreenStocksTradingBot/
iscc /DMyAppVersion=1.0.0 installer\ScreenStocksTradingBot.iss  # -> dist/installer/ (needs Inno Setup 6)
```

### Releases via GitHub Actions

`.github/workflows/build.yml` builds the app, the installer and a portable ZIP on `windows-latest`.

- Push a tag `vX.Y.Z` → a GitHub release with the installer and ZIP is created automatically
  (the version is taken from the tag).
- "Run workflow" in the Actions tab → same build, files attached as workflow artifacts.

```
git tag v1.0.0
git push origin v1.0.0
```

## How it works

The game's mod writes `market.json` (prices, player, positions, news, command results) about once per
second and `history.json` (last 900 one-second samples per stock). The app watches both files, stores
everything in SQLite and sends trades by writing `{"execute": true, "percent": N}` to
`mods/commands/<stock>/<action>percent.json`.

```
main.py                     entry point / CLI
screenstocks/reader.py      robust JSON reading + parsing
screenstocks/storage.py     SQLite schema and queries
screenstocks/collector.py   background thread watching the export files
screenstocks/commands.py    trade commands via the mod's command files
screenstocks/events.py      trading on announced pumps / crashes
screenstocks/automation.py  rule engine (stop-loss, take-profit, trailing stop, limits)
screenstocks/settings.py    user settings, paths, stock colours
screenstocks/updater.py     update check and installer download (GitHub releases)
screenstocks/i18n/           UI texts, one file per language (de, en, fr)
screenstocks/web/           new interface: pywebview window, Python API for the page, static/ (HTML, CSS, JS)
screenstocks/gui/           classic tkinter interface, chart, setup wizard, theme
installer/                  Inno Setup script
tools/make_icon.py          generates assets/icon.ico
```

## Third-party software

| Component | Licence | Used for |
|---|---|---|
| [pywebview](https://github.com/r0x0r/pywebview) | BSD-3-Clause | window of the new interface |
| [pythonnet](https://github.com/pythonnet/pythonnet) | MIT | used by pywebview to reach WebView2 |
| [TradingView Lightweight Charts™](https://github.com/tradingview/lightweight-charts) | Apache-2.0 | charts (bundled in `screenstocks/web/static/vendor/`) |
| Microsoft Edge WebView2 | Microsoft | renders the interface (part of Windows) |

The charts use TradingView Lightweight Charts™, © TradingView, Inc. The TradingView logo is hidden in the
charts; the attribution with a link to [tradingview.com](https://www.tradingview.com/) is shown under the
market chart and in **⚙ Settings → About** instead.

This project is licensed under the Apache License 2.0.
