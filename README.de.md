# ScreenStocks Trading Bot

[English](README.md)

Ein Desktop-Begleiter für das Spiel **Screen Stocks**. Die App liest die Exportdateien des Mods,
zeichnet eine dauerhafte Kurs- und Portfolio-Historie auf, handelt mit genauen Prozentwerten und
führt automatische Regeln wie Stop-Loss und Take-Profit aus.

*Inoffizielles Fan-Projekt – nicht mit den Entwicklern von Screen Stocks verbunden.*

Seit 2.0 hat die App eine neue Oberfläche (dunkles Design, TradingView-Charts). Die bisherige Oberfläche bleibt
erhalten: umschalten unter **⚙ Einstellungen → Allgemein → Oberfläche**. Fehlt die Microsoft-Edge-WebView2-Laufzeit
(bei Windows 10/11 dabei), startet automatisch die klassische Oberfläche und bietet den Download an.

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
- **Angekündigte Ereignisse** – das Spiel kündigt Pumps (~1 min vorher) und Crashs (Stunden vorher) an. Mit den
  Schaltern im Automatik-Tab (standardmäßig aus) kauft die App nach einer Pump-Ankündigung, verkauft beim Rückgang
  von der Spitze, shortet und covert nahe dem Ausgangskurs; vor einem Crash verkauft und shortet sie N Minuten
  vorher und covert und kauft beim Anstieg vom Tief zurück. Alle Schwellen sind einstellbar.
- **Chart-Zoom** – Mausrad zoomt, Ziehen verschiebt, **Shift + Ziehen** zoomt auf ein Rechteck (Zeit und Kurs),
  Doppelklick, **R** oder „Zoom zurücksetzen“ setzt zurück. In der klassischen Oberfläche: Rechteck aufziehen
  zoomt, rechte Maustaste verschiebt.
- **Vergleich** – alle Aktien normiert in % in einem Chart.
- **Portfolio** – Nettovermögen und Bargeld im Verlauf, offene Positionen, Positionsänderungen.
- **Dividenden** – der Export enthält nur den Dividendensatz; Auszahlungen werden daher an Bargeld-Anstiegen
  zur vollen Minute erkannt (auch rückwirkend aus der vorhandenen Historie). Die App ermittelt deinen
  Dividenden-Faktor (Upgrades/Level) aus den letzten Auszahlungen und zeigt die erwartete Dividende pro Minute
  je Aktie, die Summe pro Minute/Stunde, erhaltene Dividenden im Zeitraum und eine Auszahlungsliste.
- **News** – Hoch/Tief-Meldungen und geplante Ereignisse mit Countdown.
- **Tab Dividenden** – Ranking aller Aktien nach Dividendenrendite auf das eingesetzte Geld (pro Minute /
  Stunde, Ertrag je 1 Mio.), deine eigene Dividende je Aktie und ob Aktien kaufbar sind.
- **Tab Journal** – alle Trades mit realisierter G/V (Marktkurs zum Trade-Zeitpunkt − Ø Einstieg),
  Trefferquote, Ø Gewinn/Verlust, bester/schlechtester Trade, G/V je Aktie und erhaltene Dividenden – für
  jeden Zeitraum.
- **Tab Statistik** – Volatilität pro Minute/Stunde, Min/Max/Spanne, Zeit über/unter dem Basispreis,
  Kreuzungen der Basis und Ø Kursbewegung 1/5/15 Minuten nach Hoch-/Tief-Meldungen.
- **Einstellungen** (⚙) – Sprache (sofort wirksam), Oberfläche, Ordner, Datenbank; feste Farbe je Aktie
  (Palette oder freie Farbe); Datenpflege; Update-Prüfung; „Über“ mit den verwendeten Bibliotheken und Lizenzen.
- **Tastatur** – **1–8** wechseln die Tabs, **Strg+,** öffnet die Einstellungen, **Esc** schließt Dialoge; im
  Markt-Tab wählen **↑ / ↓** die vorherige / nächste Aktie, **R** setzt den Chart-Zoom zurück.
- **Update-Prüfung** – bei jedem Start (abschaltbar); Hinweis mit Link zum Release, in der installierten App
  auf Wunsch Download und Start des neuen Installers.
- **Verdichten** – Kurse und Portfolio-Snapshots älter als 7 Tage werden beim Start auf einen Wert pro
  10 Sekunden reduziert; Trades, News, Dividenden und Regeln bleiben immer vollständig.
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

Alles lässt sich später unter **⚙ Einstellungen** ändern; den Assistenten selbst öffnet der Startmenü-Eintrag
„ScreenStocks Trading Bot – Setup“ (oder `--setup`) erneut. Die Einstellungen liegen in `%APPDATA%\ScreenStocksTradingBot\settings.json`;
bei der Deinstallation bleiben Einstellungen und Historie erhalten.

> **Hinweis:** Handelsbefehle und Automatik-Regeln wirken über die Befehlsdateien des Mods im Spiel.
> Regeln lösen nur aus, solange die App läuft und das Spiel live ist. Ein Ausführungskurs genau am
> Auslöser ist nicht garantiert.

## Aus dem Quellcode starten

Benötigt Python 3.10+ (Windows, inkl. tkinter). Die neue Oberfläche braucht `pywebview`;
ohne startet die klassische Oberfläche.

```
pip install -r requirements.txt
python main.py              # Dashboard + Aufzeichnung
python main.py --ui classic # klassische Oberfläche für einen Start
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

## Fremdsoftware

| Komponente | Lizenz | Wofür |
|---|---|---|
| [pywebview](https://github.com/r0x0r/pywebview) | BSD-3-Clause | Fenster der neuen Oberfläche |
| [pythonnet](https://github.com/pythonnet/pythonnet) | MIT | von pywebview genutzt, um WebView2 anzusprechen |
| [TradingView Lightweight Charts™](https://github.com/tradingview/lightweight-charts) | Apache-2.0 | Charts (liegt in `screenstocks/web/static/vendor/`) |
| Microsoft Edge WebView2 | Microsoft | stellt die Oberfläche dar (Teil von Windows) |

Die Charts verwenden TradingView Lightweight Charts™, © TradingView, Inc. Das TradingView-Logo ist in den Charts
ausgeblendet; stattdessen stehen der Hinweis und ein Link zu [tradingview.com](https://www.tradingview.com/) unter
dem Markt-Chart und unter **⚙ Einstellungen → Über**.

Dieses Projekt steht unter der Apache License 2.0.
