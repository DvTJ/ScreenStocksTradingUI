# ScreenStocks Trading Bot

[English](README.md)

Ein Desktop-Begleiter für das Spiel **Screen Stocks**. Die App liest die Exportdateien des Mods,
zeichnet eine dauerhafte Kurs- und Portfolio-Historie auf, handelt mit genauen Prozentwerten und
führt automatische Regeln wie Stop-Loss und Take-Profit aus.

*Inoffizielles Fan-Projekt – nicht mit den Entwicklern von Screen Stocks verbunden.*

Seit 2.0 hat die App eine neue Oberfläche (dunkles Design, TradingView-Charts). Die bisherige Oberfläche bleibt
erhalten: umschalten unter **⚙ Einstellungen → Allgemein → Oberfläche**. Fehlt die Microsoft-Edge-WebView2-Laufzeit
(bei Windows 10/11 dabei), startet automatisch die klassische Oberfläche und bietet den Download an.
Unter macOS nutzt die neue Oberfläche das eingebaute WebKit. Unter Linux nutzt sie Qt WebEngine (im Linux-Download
enthalten) oder GTK WebKit; funktioniert keins von beiden, startet die klassische Oberfläche.

## Funktionen

- **Markt** – alle Aktien mit Kurs, Veränderung (1m/5m/15m/1h), Dividende, Verfügbarkeit, eigener Position
  und G/V; Kurschart je Aktie mit Markt-News, deinen Trades (K Kauf · V Verkauf · S Short · C Cover),
  Ø-Einstiegskurs, geplanten Ereignissen und aktiven Automatik-Regeln. CSV-Export.
- **Handeln** – Kaufen, Verkaufen, Shorten, Covern oder Schließen der gewählten Aktie in Prozent
  (1–100 %, ganze Zahlen, da das Spiel rundet). Zeigt die Rückmeldung des Spiels (ausgeführt / abgelehnt + Grund).
- **Automatik** – Stop-Loss, Take-Profit (fester Preis oder % vom Einstieg), Trailing-Stop, Limit-Kauf,
  Limit-Short, Trailing-Kauf / Trailing-Short (folgen dem Tief / Hoch und steigen ein, wenn der Kurs um X % dreht;
  optional erst ab einem Aktivierungskurs). Optional „Bestätigen nach N Sekunden“ gegen kurze Ausreißer. Standardmäßig löst eine Regel
  einmal aus und deaktiviert sich; mit **↻ Wiederholen** bleibt sie aktiv und löst jedes Mal erneut aus,
  wenn der Kurs den Auslösebereich verlassen und wieder erreicht hat. Bei Cooldown/Rate-Limit wird automatisch
  erneut versucht.
- **Angekündigte Ereignisse** – das Spiel kündigt Pumps (~1 min vorher) und Crashs (Stunden vorher) an. Mit den
  Schaltern im Automatik-Tab (standardmäßig aus) kauft die App nach einer Pump-Ankündigung, verkauft beim Rückgang
  von der Spitze, shortet und covert nahe dem Ausgangskurs; vor einem Crash verkauft und shortet sie N Minuten
  vorher und covert und kauft beim Anstieg vom Tief zurück; den Rückkauf hält sie, bis sich der Kurs größtenteils
  erholt hat (mit Stop-Loss und maximaler Haltezeit). Bei einem Sprung weit über den Kurs vor dem Crash covert und
  kauft sie nicht, zurückgekauft wird nur deutlich unter diesem Kurs, und ein zu teurer echter Kauf wird sofort
  wieder verkauft; das Protokoll zeigt das Ergebnis jedes Ereignisses. Eine Aktienliste legt fest, welche Aktien
  gehandelt werden. Alle Schwellen sind einstellbar.
- **Bot** – ein Mean-Reversion-Trader (standardmäßig aus): Kurse schwanken um ein langsames Mittel, er kauft weit
  unter dem gleitenden Mittel und verkauft bei der Rückkehr (optional Shorts, Stop-Loss, maximale Haltezeit, ein
  Befehl zur Zeit, beachtet die Cooldowns). Ein Backtest spielt die Historie mit derselben Logik ab. Die
  Einstellungen sind im Konfig-Export enthalten.
- **Konfig-Export / -Import** – im Automatik-Tab lassen sich gewählte Regeln und die Pump-/Crash-Einstellungen
  als JSON exportieren und wieder importieren (identische Regeln werden übersprungen).
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
- **Spiel-Erweiterung** (optional, neue Oberfläche) – die Mod-Schnittstelle des Spiels kennt weder
  Upgrades noch Rangliste. Ein Häkchen im Einrichtungsassistenten (oder später **⚙ Einstellungen → Erweiterung**)
  installiert die [Screen Stocks Bridge](https://github.com/fuubox/screen-stocks-bridge) eines anderen Entwicklers
  (ein BepInEx-Plugin) in den Spielordner: feste Versionen von BepInEx und Bridge, Prüfsummen werden vor dem
  Entpacken geprüft, das automatische Abholen von Level-Belohnungen und Schließen des Willkommen-zurück-Fensters der
  Bridge ist aus. **Erweiterung entfernen** auf derselben Einstellungsseite nimmt alles wieder heraus (BepInEx nur,
  wenn diese App es installiert hat). Installieren und Entfernen bei geschlossenem Spiel. Unter macOS (natives Spiel)
  und Linux (Proton) muss Steam das Spiel mit BepInEx starten: Nach der Installation zeigt die App die Zeile für
  **Screen Stocks → Eigenschaften → Allgemein → Startoptionen** (macOS: `"<Spielordner>/run_bepinex.sh" %command%`,
  Proton: `WINEDLLOVERRIDES="winhttp=n,b" %command%`) und prüft, ob sie gesetzt ist. Die App liest die
  Steam-Einstellungen nur, sie ändert sie nie. Nach dem Entfernen die Zeile wieder löschen; unter macOS startet das
  Spiel sonst nicht. Nur solange die Erweiterung installiert ist:
  - **Tab Upgrades** – Stufe, Wirkung und Preis jedes Upgrades; kauft pro Klick eine Stufe über die normale
    Kauffunktion des Spiels (online prüft der Server).
  - **Tab Rangliste** – die Ranglisten des Spiels: um dich herum, Allzeit, IPO, Top 100 und die beiden Clan-Listen,
    deine eigene Zeile hervorgehoben. Das Spiel beantwortet eine Ranglisten-Anfrage pro 30 Sekunden, deshalb wird
    eine Liste einmal pro Minute aktualisiert.
  - **Upgrades selbst kaufen** im Bot-Tab – die Freigabe für den Bot: Er kauft eine Stufe selbst, wenn sie sich
    innerhalb einer festgelegten Zeit bezahlt macht (Standard 60 Minuten) und ins Stundenbudget passt (Standard 5 %
    des Cashs); Einkommen und Dividendenbonus bewertet er nach deinen Einnahmen, Cooldowns und Volumen nach seinem
    eigenen gemessenen Gewinn. Standardmäßig aus, nie im Übungsmodus.
- **Einstellungen** (⚙) – Sprache (sofort wirksam), Oberfläche, Ordner, Datenbank; feste Farbe je Aktie
  (Palette oder freie Farbe); Datenpflege; Update-Prüfung; „Über“ mit den verwendeten Bibliotheken und Lizenzen.
- **Tastatur** – **1–8** wechseln die Tabs, **Strg+,** öffnet die Einstellungen, **Esc** schließt Dialoge; im
  Markt-Tab wählen **↑ / ↓** die vorherige / nächste Aktie, **R** setzt den Chart-Zoom zurück. Unter macOS
  öffnet auch **Cmd+,** die Einstellungen.
- **Update-Prüfung** – bei jedem Start (abschaltbar); Hinweis mit Link zum Release, in der installierten App
  auf Wunsch Download und Start des neuen Installers. Unter macOS und Linux gibt es keinen Installer: der
  Hinweis verlinkt die Release-Seite.
- **Verdichten** – Kurse und Portfolio-Snapshots älter als 7 Tage werden beim Start auf einen Wert pro
  10 Sekunden reduziert; Trades, News, Dividenden und Regeln bleiben immer vollständig.
- Oberfläche auf Deutsch, Englisch und Französisch, Einrichtungsassistent beim ersten Start.

## Installation

Die neueste `ScreenStocksTradingBot-Setup-x.y.z.exe` unter [Releases](../../releases) herunterladen
und ausführen. Es sind keine Administratorrechte nötig (Installation pro Benutzer).
Zu jedem Release gibt es zusätzlich eine portable ZIP-Datei.

**macOS** – `ScreenStocksTradingBot-x.y.z-macos-arm64.dmg` (Apple Silicon) oder
`ScreenStocksTradingBot-x.y.z-macos-x86_64.dmg` (Intel) herunterladen, öffnen und `ScreenStocksTradingBot.app` in
den Ordner „Programme“ kopieren. Die App ist nicht von Apple signiert, deshalb blockiert macOS den ersten Start.
Entweder die App mit Rechtsklick (Ctrl-Klick) → **Öffnen** → **Öffnen** starten, oder sie einmal zu starten
versuchen und dann unter **Systemeinstellungen → Datenschutz & Sicherheit** auf **Dennoch öffnen** klicken. Ab
macOS 15 funktioniert nur noch der zweite Weg.

**Linux** – das Spiel hat keine Linux-Version; es läuft über Steam Proton, und die App findet den Spiel-Ordner im
Proton-Prefix. `ScreenStocksTradingBot-x.y.z-linux-x86_64.tar.gz` herunterladen, entpacken und die App starten:

```
tar -xzf ScreenStocksTradingBot-x.y.z-linux-x86_64.tar.gz
./ScreenStocksTradingBot/ScreenStocksTradingBot
```

Der Build entsteht auf Ubuntu 22.04 (benötigt glibc 2.35 oder neuer) und enthält Qt, nutzt aber die üblichen
X11-/Qt-Systembibliotheken. Startet die App nicht, diese installieren, unter Debian/Ubuntu zum Beispiel
`sudo apt install libgl1 libgl1-mesa-dri libegl1 libxkbcommon-x11-0 libxcb-cursor0 libnss3 libwayland-server0 libpulse0 libgbm1`. Kann Qt nicht starten, öffnet sich
stattdessen die klassische Oberfläche und nennt die Bibliotheken.

Ubuntu 23.10 und neuer (AppArmor) sperren die Sandbox, die Qt WebEngine nutzt; dort läuft die Webansicht der App
ohne sie (sie zeigt nur die eigenen Seiten der App). Wer die Sandbox behalten will, führt einmal
`sudo ./ScreenStocksTradingBot/install-apparmor-profile.sh` aus – nach dem Verschieben des Ordners erneut;
`sudo ./ScreenStocksTradingBot/install-apparmor-profile.sh --remove` entfernt es wieder.

Unter macOS und Linux gibt es keinen Installer: für ein Update die neue Datei unter [Releases](../../releases)
herunterladen und die alte App ersetzen. Einstellungen und Historie bleiben, wo sie sind.

Den Mod-Support im Spiel schaltet `"modSupport" : true` in der Datei `thesmallshort_online_settings.sav` im
Spiel-Ordner ein (siehe [Wo die Dateien liegen](#wo-die-dateien-liegen)); erst dann schreibt das Spiel `market.json`.

Beim ersten Start fragt ein kurzer Assistent:

1. **Sprache** – Deutsch / English / Français
2. **Spiel-Ordner** – der `export`-Ordner des Mods, normalerweise
   `%USERPROFILE%\AppData\LocalLow\Conradical Games\Screen Stocks\mods\export`
   (wird automatisch erkannt). Der Assistent kann `export` und `commands` in der
   `mod-settings.json` des Spiels einschalten.
3. **Datenbank** – Speicherort der Historie (Standard `%LOCALAPPDATA%\ScreenStocksTradingBot\screenstocks.db`)

Die Standardpfade unter macOS und Linux stehen unter [Wo die Dateien liegen](#wo-die-dateien-liegen).

Alles lässt sich später unter **⚙ Einstellungen** ändern; den Assistenten selbst öffnet der Startmenü-Eintrag
„ScreenStocks Trading Bot – Setup“ (oder `--setup`) erneut. Die Einstellungen liegen in `%APPDATA%\ScreenStocksTradingBot\settings.json`;
bei der Deinstallation bleiben Einstellungen und Historie erhalten.
Unter macOS und Linux gibt es keinen Startmenü-Eintrag; dort `--setup` verwenden.

### Wo die Dateien liegen

**Windows**

- Einstellungen: `%APPDATA%\ScreenStocksTradingBot\settings.json`
- Datenbank und Log: `%LOCALAPPDATA%\ScreenStocksTradingBot\` (`screenstocks.db`, `app.log`)
- Spiel-Ordner: `%USERPROFILE%\AppData\LocalLow\Conradical Games\Screen Stocks\` – der Export liegt in
  `mods\export`, die Spiel-Einstellungen in `thesmallshort_online_settings.sav`

**macOS**

- Einstellungen, Datenbank und Log: `~/Library/Application Support/ScreenStocksTradingBot/`
- Spiel-Ordner: `~/Library/Application Support/Conradical Games/Screen Stocks/` (gleicher Inhalt wie unter Windows).
  Wer die Windows-Version in einer CrossOver- oder Whisky-Bottle spielt: die App sucht auch in
  `drive_c/users/<Benutzer>/AppData/LocalLow/Conradical Games/Screen Stocks/` jeder Bottle.

**Linux**

- Einstellungen: `~/.config/ScreenStocksTradingBot/settings.json` (oder `$XDG_CONFIG_HOME`)
- Datenbank und Log: `~/.local/share/ScreenStocksTradingBot/` (oder `$XDG_DATA_HOME`)
- Spiel-Ordner (Proton):
  `<Steam-Bibliothek>/steamapps/compatdata/4356780/pfx/drive_c/users/steamuser/AppData/LocalLow/Conradical Games/Screen Stocks/`
  (die Demo nutzt `5124200` statt `4356780`; gleicher Inhalt wie unter Windows). Die App sucht im Standard-Steam-Ordner
  (`~/.local/share/Steam`, Flatpak `~/.var/app/com.valvesoftware.Steam/.local/share/Steam`,
  Snap `~/snap/steam/common/.local/share/Steam`) und in jeder Bibliothek aus Steams `libraryfolders.vdf`.
  Auch einfache Wine- (`~/.wine`), Bottles- und Lutris-Präfixe (`~/Games/<Präfix>`) werden durchsucht.

Wer die App unter macOS oder Linux schon aus dem Quellcode gestartet hat und in `~/ScreenStocksTradingBot` deren
`settings.json` oder `screenstocks.db` hat, behält diesen Ordner für Einstellungen, Datenbank und Log. Wird der Spiel-Ordner nicht gefunden, den `export`-Ordner
im Einrichtungsassistenten von Hand wählen.

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

Unter macOS und Linux `python3 main.py` verwenden (oder `./start.sh`, das dieselben Optionen annimmt).

- **macOS** – Python von python.org enthält tkinter (Homebrew-Python braucht `brew install python-tk`);
  `pip install -r requirements.txt` installiert pywebview mit allem, was es für WebKit braucht.
- **Linux** – tkinter ist ein eigenes Paket (`sudo apt install python3-tk`). Die neue Oberfläche braucht ein
  pywebview-Backend: entweder GTK WebKit (`sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1`,
  für das System-Python oder eine mit `--system-site-packages` angelegte virtuelle Umgebung) oder Qt
  (`pip install "pywebview[qt]"`). Ohne Backend startet die klassische Oberfläche.

## Build

```
pip install pyinstaller
pyinstaller --noconfirm ScreenStocksTradingBot.spec            # -> dist/ScreenStocksTradingBot/
iscc /DMyAppVersion=1.0.0 installer\ScreenStocksTradingBot.iss  # -> dist/installer/ (benötigt Inno Setup 6)
```

Unter macOS baut derselbe `pyinstaller`-Befehl `dist/ScreenStocksTradingBot.app`, unter Linux
`dist/ScreenStocksTradingBot/` (vorher `pip install "pywebview[pyside6]"`, damit Qt enthalten ist). Den Installer gibt
es nur für Windows.

### Releases über GitHub Actions

`.github/workflows/build.yml` baut App, Installer und portable ZIP auf `windows-latest`.
Außerdem baut er die macOS-`.dmg`-Dateien (arm64 auf `macos-15`, x86_64 auf `macos-15-intel`) und das Linux-`.tar.gz`
(auf `ubuntu-22.04`) und führt die Tests unter Windows, macOS und Linux aus. Die gebaute macOS-App und der
Linux-Download (auf Ubuntu 22.04 und 24.04, unter Xvfb) werden einmal mit ihrer Weboberfläche gestartet
(`--smoke-test`); unter Linux auch mit AppArmors Sperre, mit dem Profil-Skript und mit einem Qt, das nicht starten
kann (klassische Oberfläche).

- Tag `vX.Y.Z` pushen → ein GitHub-Release mit Installer und ZIP wird automatisch erstellt
  (die Version kommt aus dem Tag). Das Release enthält auch die macOS- und Linux-Dateien.
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
| [PyObjC](https://github.com/ronaldoussoren/pyobjc) | MIT | von pywebview unter macOS genutzt, um WebKit anzusprechen |
| WebKit (WKWebView) | Apple | stellt die Oberfläche unter macOS dar (Teil von macOS) |
| [PySide6](https://doc.qt.io/qtforpython-6/) | LGPL-3.0 | von pywebview im Linux-Build genutzt |
| [Qt](https://www.qt.io/) inkl. Qt WebEngine | LGPL-3.0 | stellt die Oberfläche im Linux-Build dar |
| [BepInEx](https://github.com/BepInEx/BepInEx) | LGPL-2.1 | Mod-Lader, nur für die optionale Upgrade-Erweiterung heruntergeladen |
| [Screen Stocks Bridge](https://github.com/fuubox/screen-stocks-bridge) | MIT-0 | Upgrades, nur für die optionale Upgrade-Erweiterung heruntergeladen |

Die Charts verwenden TradingView Lightweight Charts™, © TradingView, Inc. Das TradingView-Logo ist in den Charts
ausgeblendet; stattdessen stehen der Hinweis und ein Link zu [tradingview.com](https://www.tradingview.com/) unter
dem Markt-Chart und unter **⚙ Einstellungen → Über**.

Dieses Projekt steht unter der Apache License 2.0.
