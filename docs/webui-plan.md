# Plan: Web-Oberfläche (Version 2.0)

Neue Oberfläche als Web-UI in einem App-Fenster (pywebview + Edge WebView2) mit
TradingView Lightweight Charts. Entwurf: `prototype/webui/`.

## Entscheidungen

| Thema | Entscheidung |
|---|---|
| Rollout | Entwicklung komplett im Hintergrund (Branch `webui`), Veröffentlichung erst als **2.0.0**, wenn alle Tabs fertig sind |
| Alte Oberfläche | bleibt erhalten: in den Einstellungen umschaltbar („Klassische Oberfläche“, wirkt nach Neustart) und **automatischer Notfall-Start**, wenn WebView2 fehlt; bekommt keine neuen Funktionen mehr |
| Zoom | Mausrad + Ziehen (TradingView-Standard) **und** Rechteck aufziehen (Shift + Ziehen), Doppelklick/Knopf setzt zurück, Ausschnitt bis „jetzt“ läuft mit |
| Navigation | 8 Tabs wie heute: Markt, Vergleich, Portfolio, Dividenden, Journal, Statistik, News, Automatik |
| TradingView-Logo | im Chart aus; Lizenzhinweis + Link zu tradingview.com in der Fußzeile und unter Einstellungen → Über |

## Architektur

```
screenstocks/              unverändert: reader, storage, collector, automation, events,
                           commands, updater, settings, i18n
screenstocks/web/          neu
  bridge.py                Python <-> Oberfläche (pywebview js_api), thread-sicher,
                           eigene Datenbankverbindungen, Sperren
  static/index.html        App-Rahmen: Kopfzeile, Tabs, Dialoge, Benachrichtigungen
  static/css/              Design-System
  static/js/               ein Modul pro Tab + gemeinsame Bausteine (Tabelle, Chart, Formulare)
  static/vendor/           Lightweight Charts (lokal, offline)
screenstocks/gui/          klassische Tkinter-Oberfläche (bleibt)
```

- Kein Build-Schritt: schlichtes JavaScript (ES-Module), kein Node.js.
- Datenfluss: Oberfläche fragt 1×/s nach Änderungen; Charts bekommen nur neue Punkte,
  Tabellen nur den aktiven Tab.
- Texte: bestehende Übersetzungen (`i18n.py`) werden an die Oberfläche übergeben.
- Schreibende Aktionen (Trades, Regeln, Einstellungen) nutzen die bestehenden, getesteten
  Python-Funktionen.
- Start: `main.py` wählt die Oberfläche nach Einstellung; fehlt WebView2 → klassisch + Hinweis.

## Phasen

| # | Inhalt |
|---|---|
| 0 | Fundament: Web-Paket, Brücke, App-Rahmen (Kopfzeile, Tabs, Update-Hinweis, Bestätigungsdialoge, Toasts), Design-System, Oberflächen-Umschalter + WebView2-Erkennung, PyInstaller/CI-Anpassung, Test-Build bei VirusTotal prüfen |
| 1 | Markt (aus dem Entwurf) mit echtem Handeln (Bestätigung, Auftragsprotokoll, Sperren), Trade-Markern, Regel-Linien, Zoom inkl. Rechteck |
| 2 | Automatik: Regeln anlegen/bearbeiten/wiederholen, Pump/Crash-Schalter + Parameter, Ereignisliste, Protokoll |
| 3 | Portfolio, Dividenden, Journal |
| 4 | Vergleich, Statistik, News |
| 5 | Einstellungen (Allgemein inkl. Oberflächen-Wahl, Farben, Daten, Updates, Über/Lizenzen) und Einrichtungsassistent |
| 6 | Feinschliff (Animationen, Tastenkürzel, kleine Fenstergrößen), Doku, Release **2.0.0** |

Hotfixes für 1.x laufen während der Entwicklung weiter über `main` und werden in `webui` übernommen.

## Tests

- Brücke: Skripte gegen Kopien der echten Datenbank.
- Oberfläche: Screenshots des App-Fensters; Seiten mit Testdaten im Browser prüfen.
- Handeln/Automatik: nur gegen einen Kopie-Befehlsordner mit simuliertem Spiel.

## Risiken

- **Virenscanner:** pywebview bringt .NET-Bausteine (pythonnet) mit → in Phase 0 mit
  Test-Build bei VirusTotal prüfen.
- **WebView2 fehlt:** Hinweis + Download-Link, klassische Oberfläche startet.
- **Threads:** js_api-Aufrufe kommen auf beliebigen Threads → eigene Verbindungen + Sperren.
- **Speicher:** ca. 150–250 MB statt 50–80 MB (eingebettetes Browserfenster).
