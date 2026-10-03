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
    "rule.st.no_response": ("keine Rückmeldung – neuer Versuch", "no response – retrying"),
    "rule.log.send_failed": ("Senden fehlgeschlagen: {error}", "Sending failed: {error}"),
    "rule.log.triggered": ("{kind} ausgelöst: Kurs {price} {op} {trigger} → {action} {p} %",
                           "{kind} triggered: price {price} {op} {trigger} → {action} {p}%"),
    "rule.log.done": ("Ausgeführt: {action} {p} %", "Executed: {action} {p}%"),
    "rule.log.retry": ("{status} ({reason}) – neuer Versuch", "{status} ({reason}) – retrying"),
    "rule.log.disabled": ("{status} ({reason}) – Regel deaktiviert", "{status} ({reason}) – rule disabled"),
    "rule.log.no_response": ("Keine Rückmeldung vom Spiel – Befehl zurückgenommen",
                             "No response from the game – command withdrawn"),
    "rule.log.created": ("Regel angelegt: {kind} {side} {trigger}, Menge {p} %",
                         "Rule created: {kind} {side} {trigger}, amount {p}%"),
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
