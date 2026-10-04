"""Minimal translation layer (German / English).

    from screenstocks.i18n import t
    t("market.title")                 -> "Markt" / "Market"
    t("trade.sent", action="Buy", ...) -> formatted string

The language is chosen once at startup (set_language) and stays fixed for
the session; switching it in the settings takes effect after a restart.
"""

import ctypes
import locale
from typing import Optional

LANGUAGES = {"de": "Deutsch", "en": "English"}

_lang = "en"

# key -> (German, English)
STRINGS: dict[str, tuple[str, str]] = {
    # ---- general
    "app.title": ("Screen Stocks – Marktdaten & Historie", "Screen Stocks – Market Data & History"),
    "common.none": ("–", "–"),
    "common.ready": ("bereit", "ready"),
    "common.stock": ("Aktie", "Stock"),
    "common.time": ("Zeit", "Time"),
    "common.status": ("Status", "Status"),
    "common.price": ("Kurs", "Price"),
    "common.cash": ("Bargeld", "Cash"),
    "common.owned": ("Besitz", "Owned"),
    "common.short": ("Short", "Short"),
    "common.avg_buy": ("Ø Kauf", "Avg buy"),
    "common.avg_short": ("Ø Short", "Avg short"),
    "common.pl": ("G/V", "P/L"),
    "common.net_worth": ("Nettovermögen", "Net worth"),
    "common.level": ("Level", "Level"),
    "common.range": ("Zeitraum:", "Range:"),
    "common.all": ("Alles", "All"),
    "common.shares": ("Aktien", "shares"),
    "common.no_data": ("Noch keine Daten aufgezeichnet", "No data recorded yet"),
    "common.error": ("Fehler: {error}", "Error: {error}"),
    "common.settings": ("⚙ Einstellungen", "⚙ Settings"),

    # ---- header / status bar
    "hdr.state": ("Status", "Status"),
    "hdr.buy_cd": ("Kauf-Cooldown", "Buy cooldown"),
    "hdr.short_cd": ("Short-Cooldown", "Short cooldown"),
    "hdr.updated": ("Letztes Update", "Last update"),
    "hdr.live": ("● LIVE", "● LIVE"),
    "hdr.no_market": ("● keine market.json", "● no market.json"),
    "hdr.paused": ("● Spiel pausiert/aus", "● game paused/off"),
    "status.bar": ("Quelle: {src}   |   DB: {db} – {prices} Kurse, {snaps} Snapshots, {news} News   |   "
                   "Spielversion {game}   |   v{version}",
                   "Source: {src}   |   DB: {db} – {prices} prices, {snaps} snapshots, {news} news   |   "
                   "game version {game}   |   v{version}"),
    "status.read_errors": ("   |   Lesefehler: {n} ({error})", "   |   read errors: {n} ({error})"),

    # ---- tabs
    "tab.market": ("  Markt  ", "  Market  "),
    "tab.compare": ("  Vergleich  ", "  Compare  "),
    "tab.portfolio": ("  Portfolio  ", "  Portfolio  "),
    "tab.news": ("  News  ", "  News  "),
    "tab.automation": ("  Automatik  ", "  Automation  "),

    # ---- market tab
    "col.ticker": ("Ticker", "Ticker"),
    "col.name": ("Name", "Name"),
    "col.base": ("Basis", "Base"),
    "col.cap": ("Cap", "Cap"),
    "col.dividend": ("Dividende", "Dividend"),
    "col.available": ("Verfügbar", "Available"),
    "col.max_volume": ("Max. Vol.", "Max vol."),
    "market.export_csv": ("CSV exportieren…", "Export CSV…"),
    "market.no_prices": ("Keine Kursdaten in diesem Zeitraum", "No price data in this range"),
    "market.news_marker": ("News: {kind} ({lookback} min) bei {price}", "News: {kind} ({lookback} min) at {price}"),
    "market.trade_marker": ("{kind}: {shares} Aktien @ {price}", "{kind}: {shares} shares @ {price}"),
    "market.scheduled_line": ("Geplant {direction}", "Scheduled {direction}"),
    "market.scheduled_info": ("⚠ Geplant: {direction} → {target} um {time} (in {countdown})",
                              "⚠ Scheduled: {direction} → {target} at {time} (in {countdown})"),
    "market.stats": ("{range}:  Min {lo}   Max {hi}   Ø {avg}   Änderung {change}   Spanne {spread}   {n} Datenpunkte",
                     "{range}:  min {lo}   max {hi}   avg {avg}   change {change}   spread {spread}   {n} data points"),
    "market.news_count": ("{n} Markt-News (▲/▼)", "{n} market news (▲/▼)"),
    "market.trade_count": ("{n} Trades (K Kauf · V Verkauf · S Short · C Cover)",
                           "{n} trades (B buy · S sell · H short · C cover)"),
    "export.title": ("Kurse als CSV exportieren", "Export prices as CSV"),
    "export.none": ("Noch keine Daten vorhanden.", "No data available yet."),
    "export.done": ("{n} Kurse exportiert nach\n{path}", "{n} prices exported to\n{path}"),

    # trade kinds in charts: letter, label
    "tradekind.buy.letter": ("K", "B"),
    "tradekind.sell.letter": ("V", "S"),
    "tradekind.short.letter": ("S", "H"),
    "tradekind.cover.letter": ("C", "C"),
    "tradekind.buy": ("Kauf", "Buy"),
    "tradekind.sell": ("Verkauf", "Sell"),
    "tradekind.short": ("Short", "Short"),
    "tradekind.cover": ("Cover", "Cover"),

    # ---- trade panel
    "trade.title": ("Handeln", "Trade"),
    "trade.title_stock": ("Handeln: {stock}", "Trade: {stock}"),
    "trade.buy_cd": ("Kauf-CD", "Buy CD"),
    "trade.short_cd": ("Short-CD", "Short CD"),
    "trade.amount": ("Menge:", "Amount:"),
    "trade.confirm_cb": ("Vor dem Senden bestätigen", "Confirm before sending"),
    "trade.log": ("Auftragsprotokoll (vom Spiel)", "Order log (from the game)"),
    "trade.col_action": ("Aktion", "Action"),
    "trade.enter_pct": ("Bitte Prozentwert 1–100 eingeben.", "Please enter a percentage from 1 to 100."),
    "trade.preview_sell": ("Verkaufen {p} %: {shares} Aktien", "Sell {p}%: {shares} shares"),
    "trade.preview_cover": ("Covern {p} %: {shares} Aktien", "Cover {p}%: {shares} shares"),
    "trade.preview_open": ("Kaufen/Shorten {p} %: {p} % des maximal Möglichen (höchstens ≈ {cash} Bargeld)",
                           "Buy/short {p}%: {p}% of the maximum possible (at most ≈ {cash} cash)"),
    "trade.not_live": ("⚠ Spiel nicht live – Befehle sind gesperrt.", "⚠ Game not live – commands are locked."),
    "trade.invalid_pct": ("Ungültiger Prozentwert (1–100).", "Invalid percentage (1–100)."),
    "trade.not_live_short": ("Spiel ist nicht live – Befehl nicht gesendet.", "Game is not live – command not sent."),
    "trade.busy": ("Vorheriger Befehl läuft noch – bitte kurz warten.", "Previous command still running – please wait."),
    "trade.commands_disabled": ('In mod-settings.json ist "commands" deaktiviert.',
                                '"commands" is disabled in mod-settings.json.'),
    "trade.confirm_title": ("Auftrag bestätigen", "Confirm order"),
    "trade.confirm_text": ("{action}: {p} % von {stock}\n\n{preview}\n\nSenden?",
                           "{action}: {p}% of {stock}\n\n{preview}\n\nSend?"),
    "trade.sent": ("Gesendet: {action} {p} % {stock} – warte auf das Spiel…",
                   "Sent: {action} {p}% {stock} – waiting for the game…"),
    "trade.result": ("{action} {p} % {stock}: {status}", "{action} {p}% {stock}: {status}"),
    "trade.not_picked_up": ("Spiel hat den Befehl nicht abgeholt – zurückgenommen.",
                            "The game did not pick up the command – withdrawn."),
    "trade.no_response": ("Keine Rückmeldung vom Spiel erhalten (Ergebnis im Auftragsprotokoll prüfen).",
                          "No response from the game (check the order log)."),

    # ---- actions / command results
    "action.buy": ("Kaufen", "Buy"),
    "action.sell": ("Verkaufen", "Sell"),
    "action.short": ("Shorten", "Short"),
    "action.cover": ("Covern", "Cover"),
    "action.close": ("Schließen", "Close"),
    "action.max_suffix": (" (max)", " (max)"),
    "cmdstatus.running": ("läuft", "running"),
    "cmdstatus.done": ("ausgeführt", "done"),
    "cmdstatus.rejected": ("abgelehnt", "rejected"),
    "cmdstatus.failed": ("fehlgeschlagen", "failed"),
    "reason.invalid-json": ("Befehlsdatei ungültig", "Invalid command file"),
    "reason.not-ready": ("Markt nicht bereit", "Market not ready"),
    "reason.unknown-stock": ("Unbekannte Aktie", "Unknown stock"),
    "reason.invalid-percent": ("Ungültiger Prozentwert", "Invalid percentage"),
    "reason.held": ("Position gesperrt", "Position held"),
    "reason.queue-full": ("Warteschlange voll", "Queue full"),
    "reason.no-position": ("Keine Position vorhanden", "No position"),
    "reason.unknown-action": ("Unbekannte Aktion", "Unknown action"),
    "reason.locked": ("Aktie gesperrt", "Stock locked"),
    "reason.cooldown": ("Cooldown aktiv", "Cooldown active"),
    "reason.no-volume": ("Kein Volumen verfügbar", "No volume available"),
    "reason.cannot-afford": ("Nicht genug Geld", "Not enough money"),
    "reason.rate-limited": ("Zu viele Befehle (max. ~1/s)", "Too many commands (max ~1/s)"),
    "cmd.folder_missing": ("Befehlsordner fehlt: {path} (Aktie freigeschaltet, Spiel gestartet?)",
                           "Command folder missing: {path} (stock unlocked, game started?)"),
    "cmd.unknown_action": ("Unbekannte Aktion: {action}", "Unknown action: {action}"),

    # ---- compare tab
    # ---- portfolio tab
    "pf.invested": ("Investiert", "Invested"),
    "pf.delta": ("Δ Nettovermögen (Zeitraum)", "Δ net worth (range)"),
    "pf.open_pl": ("Offene G/V", "Open P/L"),
    "pf.value": ("Wert", "Value"),
    "pf.pl_pct": ("G/V %", "P/L %"),
    "pf.short_pl": ("Short G/V", "Short P/L"),
    "pf.positions": ("Aktuelle Positionen", "Current positions"),
    "pf.changes": ("Positionsänderungen (Trades)", "Position changes (trades)"),
    "col.div_min": ("Div./min", "Div./min"),
    "pf.div_min": ("Dividende / min", "Dividend / min"),
    "pf.div_received": ("Dividenden erhalten (Zeitraum)", "Dividends received (range)"),
    "pf.div_hour": ("≈ {v} / Std.", "≈ {v} / h"),
    "pf.div_factor": ("Faktor ×{f} (aus {n} Auszahlungen)", "factor ×{f} (from {n} payouts)"),
    "pf.div_factor_unknown": ("Faktor noch unbekannt – wird ab der ersten Auszahlung ermittelt",
                              "factor not known yet – determined from the first payout"),
    "pf.dividends": ("Dividenden-Auszahlungen", "Dividend payouts"),
    "pf.div_amount": ("Betrag", "Amount"),
    "pf.div_factor_col": ("Faktor", "Factor"),
    "pf.no_data": ("Noch keine Portfolio-Daten", "No portfolio data yet"),

    # ---- news tab
    "news.market": ("Markt-News (Hoch/Tief-Meldungen)", "Market news (high/low alerts)"),
    "news.scheduled": ("Geplante Ereignisse", "Scheduled events"),
    "news.signal": ("Signal", "Signal"),
    "news.price": ("Preis", "Price"),
    "news.lookback": ("Zeitraum", "Lookback"),
    "news.high": ("▲ Hoch", "▲ High"),
    "news.low": ("▼ Tief", "▼ Low"),
    "news.high_word": ("Hoch", "High"),
    "news.low_word": ("Tief", "Low"),
    "news.direction": ("Richtung", "Direction"),
    "news.target": ("Zielpreis", "Target"),
    "news.scheduled_for": ("Geplant für", "Scheduled for"),
    "news.published": ("Veröffentlicht", "Published"),
    "news.in": ("in {countdown}", "in {countdown}"),
    "news.past": ("vorbei", "past"),

    # ---- automation
    "kind.stop_loss": ("Stop-Loss", "Stop-loss"),
    "kind.take_profit": ("Take-Profit", "Take-profit"),
    "kind.trailing_stop": ("Trailing-Stop", "Trailing stop"),
    "kind.buy_limit": ("Limit-Kauf", "Limit buy"),
    "kind.short_limit": ("Limit-Short", "Limit short"),
    "side.long": ("Long", "Long"),
    "side.short": ("Short", "Short"),
    "mode.price": ("Preis", "Price"),
    "mode.pct": ("% vom Einstieg", "% from entry"),
    "mode.trail": ("% Rückgang", "% pullback"),
    "trigger.trail": ("{v} % vom {base}", "{v}% from {base}"),
    "trigger.trail_high": ("Hoch", "high"),
    "trigger.trail_low": ("Tief", "low"),
    "trigger.entry": ("{sign}{v} % vom Einstieg", "{sign}{v}% from entry"),
    "engine.starting": ("startet", "starting"),
    "engine.active": ("aktiv", "active"),
    "engine.paused": ("pausiert", "paused"),
    "engine.not_live": ("Spiel nicht live", "game not live"),
    "engine.label": ("Engine: {state}", "Engine: {state}"),
    "rule.st.active": ("aktiv", "active"),
    "rule.st.disabled": ("deaktiviert", "disabled"),
    "rule.st.wait_position": ("wartet auf Position", "waiting for position"),
    "rule.st.wait_reference": ("wartet auf Referenzpreis", "waiting for reference price"),
    "rule.st.confirming": ("Bedingung erfüllt – bestätige ({n}/{total} s)", "condition met – confirming ({n}/{total} s)"),
    "rule.st.wait_buy_cd": ("wartet: Kauf-Cooldown", "waiting: buy cooldown"),
    "rule.st.wait_short_cd": ("wartet: Short-Cooldown", "waiting: short cooldown"),
    "rule.st.send_error": ("Fehler beim Senden: {error}", "Send error: {error}"),
    "rule.st.triggered": ("ausgelöst – warte auf Spiel", "triggered – waiting for game"),
    "rule.st.done": ("ausgeführt", "done"),
    "rule.st.waiting_reason": ("wartet: {reason}", "waiting: {reason}"),
    "rule.st.final": ("{status}: {reason}", "{status}: {reason}"),
    "rule.st.rearm": ("wartet, bis der Kurs den Auslöser wieder verlässt ({n}× ausgeführt)",
                      "waiting for the price to leave the trigger zone ({n}× executed)"),
    "rule.st.rejected_rearm": ("{status}: {reason} – wartet auf erneute Auslösung",
                               "{status}: {reason} – waiting for the next crossing"),
    "rule.st.no_response": ("keine Rückmeldung – neuer Versuch", "no response – retrying"),
    "rule.log.send_failed": ("Senden fehlgeschlagen: {error}", "Sending failed: {error}"),
    "rule.log.triggered": ("{kind} ausgelöst: Kurs {price} {op} {trigger} → {action} {p} %",
                           "{kind} triggered: price {price} {op} {trigger} → {action} {p}%"),
    "rule.log.done": ("Ausgeführt: {action} {p} %", "Executed: {action} {p}%"),
    "rule.log.retry": ("{status} ({reason}) – neuer Versuch", "{status} ({reason}) – retrying"),
    "rule.log.disabled": ("{status} ({reason}) – Regel deaktiviert", "{status} ({reason}) – rule disabled"),
    "rule.log.rearmed": ("Wieder scharf – Kurs hat den Auslösebereich verlassen",
                         "Re-armed – the price left the trigger zone"),
    "rule.log.rejected_rearm": ("{status} ({reason}) – Regel bleibt aktiv (Wiederholen)",
                                "{status} ({reason}) – rule stays active (repeat)"),
    "rule.log.repeat_on": ("Wiederholen eingeschaltet", "Repeat switched on"),
    "rule.log.repeat_off": ("Wiederholen ausgeschaltet", "Repeat switched off"),
    "rule.log.no_response": ("Keine Rückmeldung vom Spiel – Befehl zurückgenommen",
                             "No response from the game – command withdrawn"),
    "rule.log.created": ("Regel angelegt: {kind} {side} {trigger}, Menge {p} %",
                         "Rule created: {kind} {side} {trigger}, amount {p}%"),
    "rule.log.edited": ("Regel geändert: {kind} {trigger}, Menge {p} %{rep}",
                        "Rule edited: {kind} {trigger}, amount {p}%{rep}"),
    "auto.edit": ("Bearbeiten", "Edit"),
    "auto.save": ("Änderungen speichern", "Save changes"),
    "auto.cancel_edit": ("Abbrechen", "Cancel"),
    "rule.log.enabled": ("Regel aktiviert", "Rule enabled"),
    "rule.log.disabled_manual": ("Regel deaktiviert", "Rule disabled"),
    "rule.log.deleted": ("Regel gelöscht", "Rule deleted"),
    "rule.log.master_on": ("Automatik eingeschaltet", "Automation switched on"),
    "rule.log.master_off": ("Automatik ausgeschaltet", "Automation switched off"),
    "auto.master": ("Automatik aktiv", "Automation enabled"),
    "auto.type": ("Typ", "Type"),
    "auto.side": ("Seite", "Side"),
    "auto.trigger": ("Auslöser", "Trigger"),
    "auto.amount_pct": ("Menge %", "Amount %"),
    "auto.confirm_after": ("Bestätigen nach (s)", "Confirm after (s)"),
    "auto.use_price": ("Kurs übernehmen", "Use current price"),
    "auto.repeat": ("Wiederholen", "Repeat"),
    "auto.repeat_on_help": ("↻ Wiederholen: Die Regel bleibt nach jeder Ausführung aktiv und löst erneut aus, "
                            "sobald der Kurs den Auslöser wieder verlassen und danach erneut erreicht hat.",
                            "↻ Repeat: the rule stays active after each execution and fires again once the "
                            "price has left the trigger and then reaches it again."),
    "auto.repeat_off_help": ("Ohne „Wiederholen“ läuft die Regel genau einmal und deaktiviert sich danach.",
                             "Without “Repeat” the rule runs exactly once and then disables itself."),
    "auto.toggle_repeat": ("Wiederholen an/aus", "Toggle repeat"),
    "auto.col_repeat": ("Wdh.", "Repeat"),
    "auto.repeat_cell": ("↻ {n}×", "↻ {n}×"),
    "auto.once_cell": ("1×", "1×"),
    "auto.add": ("Regel anlegen", "Create rule"),
    "auto.rules": ("Regeln", "Rules"),
    "auto.delete": ("Löschen", "Delete"),
    "auto.toggle": ("Aktivieren / Deaktivieren", "Enable / Disable"),
    "auto.log": ("Automatik-Protokoll", "Automation log"),
    "auto.col_amount": ("Menge", "Amount"),
    "auto.col_distance": ("Abstand", "Distance"),
    "auto.col_confirm": ("Bestät.", "Confirm"),
    "auto.col_active": ("Aktiv", "Active"),
    "auto.col_rule": ("Regel", "Rule"),
    "auto.col_message": ("Meldung", "Message"),
    "auto.dir_below": ("Kurs fällt darunter", "price falls below"),
    "auto.dir_above": ("Kurs steigt darüber", "price rises above"),
    "auto.help.stop_loss": ("Stop-Loss: schließt {pct} % der {side}-Position, wenn der Kurs den Auslöser gegen "
                            "dich erreicht ({dir}).",
                            "Stop-loss: closes {pct}% of the {side} position when the price reaches the trigger "
                            "against you ({dir})."),
    "auto.help.take_profit": ("Take-Profit: schließt {pct} % der {side}-Position, wenn der Kurs das Gewinnziel "
                              "erreicht ({dir}).",
                              "Take-profit: closes {pct}% of the {side} position when the price reaches the "
                              "profit target ({dir})."),
    "auto.help.trailing_stop": ("Trailing-Stop: merkt sich das beste Kursniveau seit Positionseröffnung und "
                                "schließt {pct} % der {side}-Position, wenn der Kurs um den Wert in % davon "
                                "zurückfällt.",
                                "Trailing stop: tracks the best price since the position was opened and closes "
                                "{pct}% of the {side} position when the price pulls back by the given %."),
    "auto.help.buy_limit": ("Limit-Kauf: kauft {pct} % (des maximal Möglichen), sobald der Kurs auf/unter den "
                            "Preis fällt.",
                            "Limit buy: buys {pct}% (of the maximum possible) as soon as the price falls to/below "
                            "the limit."),
    "auto.help.short_limit": ("Limit-Short: shortet {pct} % (des maximal Möglichen), sobald der Kurs auf/über den "
                              "Preis steigt.",
                              "Limit short: shorts {pct}% (of the maximum possible) as soon as the price rises "
                              "to/above the limit."),
    "auto.current_trigger": ("Auslöser aktuell: {trigger}", "Current trigger: {trigger}"),
    "auto.current_price": ("Kurs: {price}", "Price: {price}"),
    "auto.no_position": ("⚠ keine {side}-Position in {stock} – Regel wartet darauf",
                         "⚠ no {side} position in {stock} – the rule waits for one"),
    "auto.rule_title": ("Regel", "Rule"),
    "auto.invalid_form": ("Bitte Aktie, Auslöser, Menge und Bestätigungszeit korrekt angeben.",
                          "Please enter a valid stock, trigger, amount and confirmation time."),
    "auto.invalid_value": ("Der Auslöser-Wert ist ungültig.", "The trigger value is invalid."),
    "auto.would_fire": ("Die Bedingung ist beim aktuellen Kurs ({price}) bereits erfüllt – die Regel würde "
                        "sofort auslösen.\n\nTrotzdem anlegen?",
                        "The condition is already met at the current price ({price}) – the rule would fire "
                        "immediately.\n\nCreate it anyway?"),
    "auto.delete_title": ("Regel löschen", "Delete rule"),
    "auto.delete_text": ("Regel #{id} löschen?", "Delete rule #{id}?"),

    # ---- setup wizard
    "setup.title": ("Einrichtung – ScreenStocks Trading Bot", "Setup – ScreenStocks Trading Bot"),
    "setup.back": ("< Zurück", "< Back"),
    "setup.next": ("Weiter >", "Next >"),
    "setup.finish": ("Fertig", "Finish"),
    "setup.cancel": ("Abbrechen", "Cancel"),
    "setup.step": ("Schritt {n} von {total}", "Step {n} of {total}"),
    "setup.lang.heading": ("Willkommen!", "Welcome!"),
    "setup.lang.text": ("Dieser Assistent richtet den ScreenStocks Trading Bot ein. Wähle zuerst deine Sprache.",
                        "This assistant sets up the ScreenStocks Trading Bot. First, choose your language."),
    "setup.game.heading": ("Spiel-Ordner", "Game folder"),
    "setup.game.text": ("Die App liest die Exportdateien des Screen-Stocks-Mods (market.json, history.json). "
                        "Wähle den Ordner „export“ im Mod-Verzeichnis des Spiels.",
                        "The app reads the export files of the Screen Stocks mod (market.json, history.json). "
                        "Select the “export” folder inside the game's mods directory."),
    "setup.game.browse": ("Durchsuchen…", "Browse…"),
    "setup.game.detect": ("Automatisch suchen", "Detect automatically"),
    "setup.game.dir_ok": ("✔ Ordner gefunden", "✔ Folder found"),
    "setup.game.dir_missing": ("✖ Ordner existiert nicht", "✖ Folder does not exist"),
    "setup.game.market_ok": ("✔ market.json gefunden", "✔ market.json found"),
    "setup.game.market_missing": ("⚠ market.json fehlt noch – starte das Spiel einmal mit aktiviertem Mod-Export.",
                                  "⚠ market.json not found yet – start the game once with the mod export enabled."),
    "setup.game.mods_flags": ("mod-settings.json: export = {export}, commands = {commands}",
                              "mod-settings.json: export = {export}, commands = {commands}"),
    "setup.game.mods_missing": ("⚠ mod-settings.json nicht gefunden.", "⚠ mod-settings.json not found."),
    "setup.game.enable_mods": ("Export und Befehle in mod-settings.json aktivieren (nötig zum Lesen und Handeln)",
                               "Enable export and commands in mod-settings.json (required for reading and trading)"),
    "setup.game.detect_failed": ("Kein Screen-Stocks-Mod-Ordner gefunden. Bitte manuell auswählen.",
                                 "No Screen Stocks mod folder found. Please select it manually."),
    "setup.game.select_title": ("Export-Ordner wählen", "Select export folder"),
    "setup.game.continue_anyway": ("Der gewählte Ordner existiert nicht. Trotzdem fortfahren?",
                                   "The selected folder does not exist. Continue anyway?"),
    "setup.data.heading": ("Datenspeicher", "Data storage"),
    "setup.data.text": ("Kurse, Portfolio-Verlauf, Trades und Automatik-Regeln werden in einer SQLite-Datenbank "
                        "gespeichert.",
                        "Prices, portfolio history, trades and automation rules are stored in an SQLite database."),
    "setup.data.file": ("Datenbank-Datei", "Database file"),
    "setup.data.select_title": ("Datenbank-Datei wählen", "Select database file"),
    "setup.data.exists": ("✔ Vorhandene Datenbank wird weiterverwendet.", "✔ The existing database will be reused."),
    "setup.data.new": ("Eine neue Datenbank wird angelegt.", "A new database will be created."),
    "setup.done.heading": ("Fertig!", "All set!"),
    "setup.done.text": ("Zusammenfassung deiner Einstellungen. Du kannst sie jederzeit über „⚙ Einstellungen“ ändern.",
                        "Summary of your settings. You can change them at any time via “⚙ Settings”."),
    "setup.done.language": ("Sprache", "Language"),
    "setup.done.export": ("Export-Ordner", "Export folder"),
    "setup.done.db": ("Datenbank", "Database"),
    "setup.done.note": ("Hinweis: Die App kann über die Befehlsdateien des Mods im Spiel handeln. Automatik-Regeln "
                        "lösen nur aus, solange die App läuft und das Spiel live ist.",
                        "Note: the app can trade in the game through the mod's command files. Automation rules "
                        "only fire while the app is running and the game is live."),
    "setup.restart": ("Einige Änderungen (z. B. Sprache, Ordner) werden nach einem Neustart der App wirksam.\n\n"
                      "Jetzt neu starten?",
                      "Some changes (e.g. language, folders) take effect after restarting the app.\n\n"
                      "Restart now?"),
    "setup.mods_write_failed": ("mod-settings.json konnte nicht geschrieben werden:\n{error}",
                                "Could not write mod-settings.json:\n{error}"),
    # ---- web interface
    "web.placeholder": ("Kommt in Phase {phase} der neuen Oberfläche.", "Coming in phase {phase} of the new interface."),
    "web.paused": ("PAUSIERT", "PAUSED"),
    "web.no_market": ("KEINE DATEN", "NO DATA"),
    "web.source": ("Quelle", "Source"),
    "web.game": ("Spielversion", "game version"),
    "web.installing": ("Installer wird gestartet …", "Starting installer …"),
    "web.ui_web": ("Neue Oberfläche", "New interface"),
    "web.ui_web_desc": ("Modernes Design mit TradingView-Charts", "Modern design with TradingView charts"),
    "web.ui_classic": ("Klassische Oberfläche", "Classic interface"),
    "web.ui_classic_desc": ("Die bisherige Oberfläche (Tkinter)", "The previous interface (Tkinter)"),
    "web.restart_now": ("Jetzt neu starten", "Restart now"),
    "web.key_tab": ("Taste {n}", "Key {n}"),
    "web.key_ctrl": ("Strg", "Ctrl"),
    "web.zoom_hint": ("Mausrad = Zoom · Ziehen = verschieben · Shift + Ziehen = Bereich zoomen · Doppelklick / R = "
                      "zurücksetzen · ↑ / ↓ = Aktie wechseln",
                      "Mouse wheel = zoom · drag = pan · Shift + drag = zoom to area · double-click / R = reset · "
                      "↑ / ↓ = change stock"),
    "web.details": ("Details zur Aktie", "Stock details"),
    "web.points": ("Datenpunkte", "data points"),
    "web.trades": ("Trades", "trades"),
    "web.auto.created": ("Regel #{id} angelegt", "Rule #{id} created"),
    "web.auto.saved": ("Regel #{id} gespeichert", "Rule #{id} saved"),
    "web.auto.new_rule": ("Neue Regel", "New rule"),
    "web.auto.edit_rule": ("Regel #{id} bearbeiten", "Edit rule #{id}"),
    "web.auto.no_rules": ("Noch keine Regeln – lege oben die erste an.", "No rules yet – create the first one above."),
    "web.auto.no_events": ("Keine angekündigten Ereignisse.", "No announced events."),
    "web.auto.params": ("Parameter", "Parameters"),
    "web.auto.engine_hint": ("Regeln und Ereignis-Handel laufen nur, solange die App läuft und das Spiel live ist.",
                             "Rules and event trading only run while the app is running and the game is live."),
    "web.fallback_title": ("Klassische Oberfläche", "Classic interface"),
    "web.fallback_text": ("Die neue Oberfläche kann auf diesem PC nicht starten, deshalb öffnet sich die klassische.\n\n"
                          "Grund: {reason}\n\nMeist fehlt die Microsoft-WebView2-Laufzeit. Download-Seite öffnen?",
                          "The new interface cannot start on this PC, so the classic one opens instead.\n\n"
                          "Reason: {reason}\n\nUsually the Microsoft WebView2 runtime is missing. Open the download page?"),
    "settings.ui": ("Oberfläche", "Interface"),
    "settings.tab_about": ("Über", "About"),
    "web.set.lang_note": ("Die Sprache wird sofort übernommen.", "The language is applied immediately."),
    "web.set.restart_note": ("Oberfläche, Export-Ordner und Datenbank werden nach einem Neustart der App wirksam.",
                             "Interface, export folder and database take effect after restarting the app."),
    "web.set.restart": ("Oberfläche, Export-Ordner oder Datenbank wurden geändert. Das wird nach einem Neustart "
                        "der App wirksam.\n\nJetzt neu starten?",
                        "Interface, export folder or database were changed. This takes effect after restarting "
                        "the app.\n\nRestart now?"),
    "web.set.saved": ("Einstellungen gespeichert", "Settings saved"),
    "web.set.color_custom": ("Eigene Farbe …", "Custom colour …"),
    "web.set.color_default": ("Standard", "Default"),
    "web.set.no_stocks": ("Noch keine Aktien aufgezeichnet.", "No stocks recorded yet."),
    "web.set.db_size": ("Größe", "Size"),
    "web.set.db_prices": ("Kurse", "Prices"),
    "web.set.db_snaps": ("Snapshots", "Snapshots"),
    "web.set.db_oldest": ("Ältester Kurs", "Oldest price"),
    "web.set.db_file": ("Datei", "File"),
    "about.text": ("Begleit-App für Screen Stocks: zeichnet Kurse und Portfolio auf, handelt über die Befehlsdateien "
                   "des Mods und führt Automatik-Regeln aus.",
                   "Companion app for Screen Stocks: records prices and portfolio, trades through the mod's command "
                   "files and runs automation rules."),
    "about.version": ("Version {version} · Lizenz Apache-2.0", "Version {version} · Apache-2.0 licence"),
    "about.source": ("Quellcode auf GitHub", "Source code on GitHub"),
    "about.libraries": ("Verwendete Bibliotheken", "Libraries used"),
    "about.col_name": ("Bibliothek", "Library"),
    "about.col_version": ("Version", "Version"),
    "about.col_license": ("Lizenz", "Licence"),
    "about.runtime": ("Laufzeit: Python {python} (PSF-Lizenz) · Darstellung: Microsoft Edge WebView2",
                      "Runtime: Python {python} (PSF licence) · Rendering: Microsoft Edge WebView2"),
    "about.tradingview": ("Die Charts verwenden TradingView Lightweight Charts™ – © TradingView, Inc., "
                          "lizenziert unter Apache-2.0. Das TradingView-Logo ist in den Charts ausgeblendet; "
                          "dieser Hinweis mit Link ersetzt es.",
                          "The charts use TradingView Lightweight Charts™ – © TradingView, Inc., licensed under "
                          "Apache-2.0. The TradingView logo is hidden in the charts; this notice and link replace it."),
    "about.tradingview_link": ("tradingview.com öffnen", "Open tradingview.com"),

    # ---- announced events (pumps / crashes)
    "event.pump": ("Pump", "Pump"),
    "event.crash": ("Crash", "Crash"),
    "event.log.sent": ("{action} {p} % gesendet", "{action} {p}% sent"),
    "event.log.rejected": ("{status} ({reason})", "{status} ({reason})"),
    "event.log.too_late": ("Zeitpunkt schon vorbei – übersprungen", "already past – skipped"),
    "event.log.peak_drop": ("Spitze {peak}, jetzt {price} – verkaufe", "peak {peak}, now {price} – selling"),
    "event.log.low_rise": ("Tief {low}, jetzt {price} – covern/zurückkaufen", "low {low}, now {price} – cover/buy back"),
    "event.log.safety": ("Notbremse (Zeit abgelaufen)", "safety timeout"),
    "event.title": ("Angekündigte Ereignisse", "Announced events"),
    "event.switch_pumps": ("Pumps handeln", "Trade pumps"),
    "event.switch_crashes": ("Crashs handeln", "Trade crashes"),
    "event.pump_params": ("Pump:", "Pump:"),
    "event.crash_params": ("Crash:", "Crash:"),
    "event.p.pump_buy_pct": ("Kauf %", "Buy %"),
    "event.p.pump_drop_pct": ("Verkauf bei −% vom Hoch", "Sell at −% from peak"),
    "event.p.pump_start_share": ("Start ab % zum Ziel", "Started at % to target"),
    "event.p.pump_safety_s": ("Notbremse s", "Safety s"),
    "event.p.pump_short_pct": ("Short % (0 = aus)", "Short % (0 = off)"),
    "event.p.pump_cover_pct": ("Cover ≤ Start +%", "Cover ≤ start +%"),
    "event.p.pump_cover_max_s": ("Cover spätestens s", "Cover at latest s"),
    "event.p.crash_minutes": ("Min. vorher", "Min. before"),
    "event.p.crash_short_pct": ("Short % (0 = aus)", "Short % (0 = off)"),
    "event.p.crash_rise_pct": ("Covern bei +% vom Tief", "Cover at +% from low"),
    "event.p.crash_safety_s": ("Notbremse s", "Safety s"),
    "event.p.crash_rebuy_pct": ("Rückkauf % (0 = aus)", "Buy back % (0 = off)"),
    "event.help": ("Pump: kaufen nach Ankündigung → ab Zeitpunkt Spitze verfolgen → verkaufen bei Rückgang (erst "
                   "wenn der Pump begonnen hat) → shorten → covern nahe Ausgangskurs.  Crash: N Minuten vorher "
                   "verkaufen und shorten → ab Zeitpunkt Tief verfolgen → bei Anstieg covern und zurückkaufen.  "
                   "Gilt nur bei aktiver Automatik.",
                   "Pump: buy after the announcement → from the scheduled time follow the peak → sell on pullback "
                   "(once the pump has started) → short → cover near the starting price.  Crash: sell and short N "
                   "minutes before → from the scheduled time follow the low → cover and buy back on the rebound.  "
                   "Only while automation is enabled."),
    "event.col_type": ("Art", "Type"),
    "event.col_target": ("Ziel", "Target"),
    "event.col_when": ("Zeitpunkt", "Scheduled"),
    "event.col_in": ("in", "in"),
    "event.col_phase": ("Phase", "Phase"),
    "event.phase.wait_buy": ("wartet auf Kauf", "waiting to buy"),
    "event.phase.buy!": ("kauft …", "buying …"),
    "event.phase.hold": ("hält, wartet auf Spitze", "holding, waiting for peak"),
    "event.phase.sell!": ("verkauft …", "selling …"),
    "event.phase.short_wait": ("wartet auf Short", "waiting to short"),
    "event.phase.short!": ("shortet …", "shorting …"),
    "event.phase.short_open": ("Short offen", "short open"),
    "event.phase.cover!": ("covert …", "covering …"),
    "event.phase.wait_pre": ("wartet", "waiting"),
    "event.phase.wait_crash": ("wartet auf Crash", "waiting for crash"),
    "event.phase.rebuy_wait": ("wartet auf Rückkauf", "waiting to buy back"),
    "event.phase.rebuy!": ("kauft zurück …", "buying back …"),
    "event.phase.done": ("erledigt", "done"),
    "event.phase.skipped": ("übersprungen", "skipped"),
    "event.phase.failed": ("fehlgeschlagen", "failed"),
    "event.off": ("aus", "off"),

    "chart.reset_zoom": ("Zoom zurücksetzen", "Reset zoom"),
    "chart.zoomed": ("Ausschnitt", "Zoomed"),

    # ---- new tabs
    "tab.dividends": ("  Dividenden  ", "  Dividends  "),
    "tab.journal": ("  Journal  ", "  Journal  "),
    "tab.stats": ("  Statistik  ", "  Statistics  "),

    # ---- dividend ranking
    "div.col_rate": ("Satz / min", "Rate / min"),
    "div.col_yield_min": ("Rendite / min", "Yield / min"),
    "div.col_yield_h": ("Rendite / Std.", "Yield / h"),
    "div.col_per_mio": ("Ertrag je 1 Mio. / Std.", "Per 1M invested / h"),
    "div.col_own": ("Deine Div. / min", "Your div. / min"),
    "div.col_buyable": ("Kaufbar", "Buyable"),
    "div.info_factor": ("Rendite = Dividendensatz × dein Faktor ×{f} (ermittelt aus {n} Auszahlungen), "
                        "bezogen auf das investierte Geld zum aktuellen Kurs.",
                        "Yield = dividend rate × your factor ×{f} (learned from {n} payouts), "
                        "relative to the money invested at the current price."),
    "div.info_no_factor": ("Faktor noch unbekannt – Rendite ohne Faktor (×1) gerechnet. Er wird ab der ersten "
                           "erkannten Auszahlung ermittelt.",
                           "Factor not known yet – yield shown without factor (×1). It is learned from the first "
                           "detected payout."),
    "div.note": ("Dividenden werden jede volle Minute auf Long-Positionen gezahlt (Stückzahl × Kurs × Satz × Faktor). "
                 "Kaufbar = es sind aktuell Aktien am Markt verfügbar.",
                 "Dividends are paid every full minute on long positions (shares × price × rate × factor). "
                 "Buyable = shares are currently available on the market."),

    # ---- journal
    "journal.realized": ("Realisierte G/V", "Realized P/L"),
    "journal.dividends": ("Dividenden", "Dividends"),
    "journal.total": ("Gesamt", "Total"),
    "journal.hit_rate": ("Trefferquote", "Win rate"),
    "journal.avg_win": ("Ø Gewinn", "Avg win"),
    "journal.avg_loss": ("Ø Verlust", "Avg loss"),
    "journal.best": ("Bester Trade", "Best trade"),
    "journal.worst": ("Schlechtester Trade", "Worst trade"),
    "journal.note": ("G/V von Verkauf/Cover = (Marktkurs zum Trade-Zeitpunkt − Ø Einstieg) × Stück; Schätzung "
                     "ohne Gebühren.",
                     "P/L of sell/cover = (market price at trade time − avg entry) × shares; estimate without fees."),
    "journal.trades": ("Trades", "Trades"),
    "journal.per_stock": ("G/V je Aktie", "P/L per stock"),
    "journal.col_kind": ("Art", "Type"),
    "journal.col_shares": ("Stück", "Shares"),
    "journal.col_entry": ("Ø Einstieg", "Avg entry"),
    "journal.col_closed": ("Schließungen", "Closings"),
    "journal.col_wins": ("Gewinne", "Wins"),
    "journal.col_realized": ("Realisiert", "Realized"),

    # ---- statistics
    "stats.prices": ("Kursverhalten", "Price behaviour"),
    "stats.prices_note": ("Volatilität = Ø absolute Kursänderung pro Minute bzw. Stunde (Schlusskurse). "
                          "Über/unter Basis = Anteil der Zeit; Kreuzungen = Wechsel über/unter den Basispreis "
                          "(Minutenwerte).",
                          "Volatility = average absolute price change per minute / hour (closing prices). "
                          "Above/below base = share of time; crossings = switches across the base price "
                          "(minute values)."),
    "stats.news": ("Kursverhalten nach Markt-News", "Price behaviour after market news"),
    "stats.news_note": ("Ø Kursänderung 1 / 5 / 15 Minuten nach einer Hoch- bzw. Tief-Meldung, gemessen vom Preis "
                        "in der Meldung.",
                        "Average price change 1 / 5 / 15 minutes after a high or low alert, measured from the price "
                        "in the alert."),
    "stats.col_min": ("Min", "Min"),
    "stats.col_max": ("Max", "Max"),
    "stats.col_spread": ("Spanne", "Spread"),
    "stats.col_vol_min": ("Vol. / min", "Vol. / min"),
    "stats.col_vol_h": ("Vol. / Std.", "Vol. / h"),
    "stats.col_dist": ("Abst. Basis", "Dist. base"),
    "stats.col_above": ("Über Basis", "Above base"),
    "stats.col_below": ("Unter Basis", "Below base"),
    "stats.col_cross": ("Kreuzungen", "Crossings"),
    "stats.col_n_high": ("# Hoch", "# High"),
    "stats.col_n_low": ("# Tief", "# Low"),
    "stats.col_high_1": ("Hoch +1m", "High +1m"),
    "stats.col_high_5": ("Hoch +5m", "High +5m"),
    "stats.col_high_15": ("Hoch +15m", "High +15m"),
    "stats.col_low_1": ("Tief +1m", "Low +1m"),
    "stats.col_low_5": ("Tief +5m", "Low +5m"),
    "stats.col_low_15": ("Tief +15m", "Low +15m"),
    "stats.updated": ("berechnet {time} (alle {s} s)", "calculated {time} (every {s} s)"),

    # ---- settings dialog
    "settings.title": ("Einstellungen", "Settings"),
    "settings.tab_general": ("Allgemein", "General"),
    "settings.tab_colors": ("Farben", "Colours"),
    "settings.tab_data": ("Daten", "Data"),
    "settings.tab_updates": ("Updates", "Updates"),
    "settings.save": ("Speichern", "Save"),
    "settings.restart_note": ("Sprache, Ordner und Datenbank werden nach einem Neustart der App wirksam.",
                              "Language, folder and database take effect after restarting the app."),
    "settings.colors_text": ("Jede Aktie behält ihre Farbe dauerhaft – auch wenn neue Aktien dazukommen. "
                             "Klick auf ein Farbfeld, um die Farbe zu ändern.",
                             "Every stock keeps its colour permanently, even when new stocks appear. "
                             "Click a colour to change it."),
    "settings.colors_reset": ("Standardfarben wiederherstellen", "Restore default colours"),
    "settings.pick_color": ("Farbe für {stock}", "Colour for {stock}"),
    "settings.data_text": ("Kurse und Portfolio-Snapshots, die älter als {days} Tage sind, werden beim Start "
                           "automatisch auf einen Wert pro {s} Sekunden verdichtet (der letzte echte Kurs bleibt). "
                           "Trades, News, Dividenden, Regeln und Protokolle bleiben immer vollständig.",
                           "Prices and portfolio snapshots older than {days} days are thinned out at start-up "
                           "to one value per {s} seconds (the last real price is kept). Trades, news, dividends, "
                           "rules and logs are always kept in full."),
    "settings.data_info": ("Datei: {path}\nGröße: {size} MB · {prices} Kurse · {snaps} Snapshots · ältester Kurs: "
                           "{oldest}",
                           "File: {path}\nSize: {size} MB · {prices} prices · {snaps} snapshots · oldest price: "
                           "{oldest}"),
    "settings.compact_now": ("Jetzt verdichten und Datei verkleinern", "Compact now and shrink the file"),
    "settings.compacting": ("Verdichte … (kann bei großen Datenbanken etwas dauern)",
                            "Compacting … (may take a while for large databases)"),
    "settings.compact_done": ("Fertig: {prices} Kurse und {snaps} Snapshots entfernt, {before} MB → {after} MB.",
                              "Done: {prices} prices and {snaps} snapshots removed, {before} MB → {after} MB."),
    "settings.version": ("Installierte Version: {version}", "Installed version: {version}"),
    "settings.check_on_start": ("Bei jedem Start nach Updates suchen", "Check for updates on every start"),
    "settings.check_now": ("Jetzt nach Updates suchen", "Check for updates now"),

    # ---- updates
    "update.title": ("Update", "Update"),
    "update.banner": ("Neue Version {version} verfügbar (installiert: {current})",
                      "New version {version} available (installed: {current})"),
    "update.open_page": ("Release ansehen", "View release"),
    "update.install": ("Jetzt installieren", "Install now"),
    "update.later": ("Später", "Later"),
    "update.confirm": ("Version {version} herunterladen und installieren?\n\nDie App schließt sich dabei "
                       "(Aufzeichnung und Automatik stoppen) und der Installer startet die neue Version.",
                       "Download and install version {version}?\n\nThe app closes (recording and automation "
                       "stop) and the installer starts the new version."),
    "update.downloading": ("Lade Update herunter …", "Downloading update …"),
    "update.checking": ("Suche nach Updates …", "Checking for updates …"),
    "update.up_to_date": ("Du hast die neueste Version ({version}).", "You have the latest version ({version})."),
    "update.available": ("Version {version} ist verfügbar – siehe Hinweis oben im Hauptfenster.",
                         "Version {version} is available – see the notice at the top of the main window."),
    "update.failed": ("Update-Prüfung fehlgeschlagen: {error}", "Update check failed: {error}"),
}


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGUAGES else "en"


def get_language() -> str:
    return _lang


def t(key: str, default: Optional[str] = None, **kwargs) -> str:
    pair = STRINGS.get(key)
    if pair is None:
        text = default if default is not None else key
    else:
        text = pair[0] if _lang == "de" else pair[1]
    return text.format(**kwargs) if kwargs else text


def system_language() -> str:
    """'de' for a German Windows UI, otherwise 'en'."""
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "de" if lang_id & 0x3FF == 0x07 else "en"
    except Exception:
        loc = (locale.getlocale()[0] or "").lower()
        return "de" if loc.startswith("de") or loc.startswith("german") else "en"
