# ScreenStocks Trading Bot

[English](README.md)

Ein Desktop-Begleiter für das Spiel **Screen Stocks**. Die App liest die Exportdateien des Mods,
zeichnet eine dauerhafte Kurs- und Portfolio-Historie auf, handelt mit genauen Prozentwerten und
führt automatische Regeln wie Stop-Loss und Take-Profit aus.

*Inoffizielles Fan-Projekt – nicht mit den Entwicklern von Screen Stocks verbunden.*

## Funktionen

- **Markt** – alle Aktien mit Kurs, Veränderung (1m/5m/15m/1h), Dividende, Verfügbarkeit, eigener Position
  und G/V; Kurschart je Aktie mit Markt-News, deinen Trades (K Kauf · V Verkauf · S Short · C Cover),
  Ø-Einstiegskurs, geplanten Ereignissen und aktiven Automatik-Regeln. CSV-Export.
- **Handeln** – Kaufen, Verkaufen, Shorten, Covern oder Schließen der gewählten Aktie in Prozent
  (1–100 %, ganze Zahlen, da das Spiel rundet). Zeigt die Rückmeldung des Spiels (ausgeführt / abgelehnt + Grund).
- **Automatik** – Stop-Loss, Take-Profit (fester Preis oder % vom Einstieg), Trailing-Stop, Limit-Kauf,
  Limit-Short. Optional „Bestätigen nach N Sekunden“ gegen kurze Ausreißer. Standardmäßig löst eine Regel
  einmal aus und deaktiviert sich; mit **↻ Wiederholen** bleibt sie aktiv und löst jedes Mal erneut aus,
  wenn der Kurs den Auslösebereich verlassen und wieder erreicht hat. Bei Cooldown/Rate-Limit wird automatisch
  erneut versucht.
- **Vergleich** – alle Aktien normiert in % in einem Chart.
- **Portfolio** – Nettovermögen und Bargeld im Verlauf, offene Positionen, Positionsänderungen.
- **Dividenden** – der Export enthält nur den Dividendensatz; Auszahlungen werden daher an Bargeld-Anstiegen
  zur vollen Minute erkannt (auch rückwirkend aus der vorhandenen Historie). Die App ermittelt deinen
  Dividenden-Faktor (Upgrades/Level) aus den letzten Auszahlungen und zeigt die erwartete Dividende pro Minute
  je Aktie, die Summe pro Minute/Stunde, erhaltene Dividenden im Zeitraum und eine Auszahlungsliste.
- **News** – Hoch/Tief-Meldungen und geplante Ereignisse mit Countdown.
- Oberfläche auf Deutsch und Englisch, Einrichtungsassistent beim ersten Start.

## Installation

Die neueste `ScreenStocksTradingBot-Setup-x.y.z.exe` unter [Releases](../../releases) herunterladen
und ausführen. Es sind keine Administratorrechte nötig (Installation pro Benutzer).
Zu jedem Release gibt es zusätzlich eine portable ZIP-Datei.

Beim ersten Start fragt ein kurzer Assistent:

1. **Sprache** – Deutsch / English
2. **Spiel-Ordner** – der `export`-Ordner des Mods, normalerweise
   `%USERPROFILE%\AppData\LocalLow\Conradical Games\Screen Stocks\mods\export`
   (wird automatisch erkannt). Der Assistent kann `export` und `commands` in der
   `mod-settings.json` des Spiels einschalten.
3. **Datenbank** – Speicherort der Historie (Standard `%LOCALAPPDATA%\ScreenStocksTradingBot\screenstocks.db`)

Über **⚙ Einstellungen** (oder den Startmenü-Eintrag „ScreenStocks Trading Bot – Setup“) lässt sich der
Assistent jederzeit erneut öffnen. Die Einstellungen liegen in `%APPDATA%\ScreenStocksTradingBot\settings.json`;
bei der Deinstallation bleiben Einstellungen und Historie erhalten.

> **Hinweis:** Handelsbefehle und Automatik-Regeln wirken über die Befehlsdateien des Mods im Spiel.
> Regeln lösen nur aus, solange die App läuft und das Spiel live ist. Ein Ausführungskurs genau am
> Auslöser ist nicht garantiert.

## Aus dem Quellcode starten

Benötigt Python 3.10+ (Windows, inkl. tkinter). Keine externen Pakete.

```
python main.py              # Dashboard + Aufzeichnung
python main.py --setup      # Einrichtungsassistent erneut starten
python main.py --headless   # Aufzeichnung + Automatik ohne Fenster
python main.py --lang de    # Sprache für einen Start überschreiben
```

## Build

```
pip install pyinstaller
pyinstaller --noconfirm ScreenStocksTradingBot.spec            # -> dist/ScreenStocksTradingBot/
iscc /DMyAppVersion=1.0.0 installer\ScreenStocksTradingBot.iss  # -> dist/installer/ (benötigt Inno Setup 6)
```

### Releases über GitHub Actions

`.github/workflows/build.yml` baut App, Installer und portable ZIP auf `windows-latest`.

- Tag `vX.Y.Z` pushen → ein GitHub-Release mit Installer und ZIP wird automatisch erstellt
  (die Version kommt aus dem Tag).
- „Run workflow“ im Actions-Tab → gleicher Build, Dateien als Workflow-Artefakte.

```
git tag v1.0.0
git push origin v1.0.0
```
