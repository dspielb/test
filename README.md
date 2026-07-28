# Tägliche Nachrichtenübersicht

Erzeugt jeden Tag eine HTML-Seite mit den aktuellen Meldungen aus deutschen
Nachrichtenmedien, Wirtschafts- und Tech-Quellen sowie den Nachrichtenagenturen.
Meldungen, die mehrere Quellen gleichzeitig bringen, stehen als **Top-Themen**
ganz oben.

Kein Installationsaufwand: das Projekt kommt mit **Python 3.11+** und der
Standardbibliothek aus – keine Abhängigkeiten, keine virtuelle Umgebung nötig.

## Schnellstart

```bash
python3 -m newsdigest
```

Das schreibt:

```
docs/index.html                 # die aktuelle Ausgabe
docs/archiv/2026-07-28.html     # Ausgabe des Tages
docs/archiv/index.html          # Übersicht aller Tage
```

Danach `docs/index.html` im Browser öffnen.

### Ohne Netzzugang ausprobieren

Um das Layout anzusehen, ohne Feeds abzurufen:

```bash
python3 tools/demo_feeds.py /tmp/demo
python3 -m newsdigest --offline-dir /tmp/demo --out vorschau
```

Die Inhalte in `tools/demo_feeds.py` sind frei erfunden.

### Optionen

| Option | Bedeutung |
| --- | --- |
| `-c, --config PFAD` | Konfigurationsdatei (Standard: `feeds.toml`) |
| `-o, --out PFAD` | Ausgabeverzeichnis (Standard: `docs`) |
| `--hours N` | Zeitfenster in Stunden, überschreibt die Konfiguration |
| `--offline-dir PFAD` | Feeds aus `<pfad>/<feed-id>.xml` lesen statt über das Netz |
| `--no-archive` | Nur `index.html` schreiben, kein Tagesarchiv |
| `--date JJJJ-MM-TT` | Datum des Archiveintrags (Standard: heute) |
| `-v, --verbose` | Zeigt pro Quelle, wie viele Artikel ankamen |

Rückgabewerte: `0` = in Ordnung, `1` = keine einzige Quelle erreichbar,
`2` = Fehler in der Konfiguration.

## Quellen anpassen

Alles steckt in [`feeds.toml`](feeds.toml). Eine neue Quelle hinzufügen:

```toml
[[feed]]
id = "taz"                                # eindeutig, dient auch als Dateiname
name = "taz"                              # so erscheint es auf der Seite
url = "https://taz.de/!p4608;rss/"
category = "deutschland"                  # muss unter [categories] stehen
optional = true                           # Ausfälle nur leise protokollieren
```

Unter `[settings]` lassen sich Zeitfenster, Obergrenzen pro Quelle und
Kategorie, Zeitzone sowie Timeout und Wiederholversuche einstellen. Die
Reihenfolge unter `[categories]` bestimmt die Reihenfolge der Abschnitte auf
der Seite.

Fehler in der Datei werden beim Start gemeldet, statt später still
danebenzugehen – unbekannte Kategorien, doppelte IDs oder fehlende Felder
brechen den Lauf mit einer konkreten Meldung ab.

### Hinweis zu dpa, Reuters und AFP

Die Agenturen bieten **keine frei zugänglichen Voll-Feeds** an; der Bezug der
Ticker ist lizenzpflichtig. Reuters hat seine öffentlichen RSS-Feeds
abgeschaltet, dpa und AFP hatten nie welche.

Die Kategorie „Agenturen" behilft sich deshalb mit Google-News-Suchfeeds
(`source:Reuters`, `source:AFP`, `source:dpa`). Das liefert die über
Partnermedien veröffentlichten Meldungen – kein vollständiger Ticker, aber die
relevanten Themen des Tages. Zusätzlich laufen mit ZEIT ONLINE und n-tv zwei
Quellen mit, die viel unveränderte dpa-Meldung übernehmen. Diese Feeds sind als
`optional = true` markiert, weil Google die Suchfeeds gelegentlich drosselt.

Wer einen echten Agenturzugang hat, trägt dessen Feed einfach zusätzlich ein.

## Automatischer Lauf

[`.github/workflows/nachrichten.yml`](.github/workflows/nachrichten.yml) startet
den Abruf täglich um 04:00 UTC (06:00 MESZ / 05:00 MEZ) und committet das
Ergebnis nach `docs/`. Der Lauf lässt sich unter *Actions → Tägliche
Nachrichtenübersicht → Run workflow* auch von Hand auslösen.

Zwei Dinge sind dafür nötig:

1. **Der Workflow muss im Standard-Branch liegen.** GitHub führt geplante
   Workflows ausschließlich aus dem Standard-Branch aus – solange dieser Stand
   nur im Feature-Branch liegt, läuft nichts nach Zeitplan.
2. **Schreibrechte für Actions.** Unter *Settings → Actions → General →
   Workflow permissions* muss „Read and write permissions" aktiv sein, sonst
   scheitert der Commit.

Als Webseite veröffentlichen: *Settings → Pages → Source: Deploy from a branch*,
Branch `main`, Ordner `/docs`. Die Übersicht liegt dann unter
`https://<benutzer>.github.io/<repo>/`.

Der Lauf schlägt nur fehl, wenn **keine einzige** Quelle erreichbar war. Fallen
einzelne Quellen aus, entsteht die Seite trotzdem und der Ausfall steht unten im
Abschnitt „Quellen-Status".

## Wie die Zusammenfassung funktioniert

1. **Abrufen** – alle Feeds parallel, mit Timeout und Wiederholung bei
   Serverfehlern. Eine defekte Quelle beeinflusst die anderen nicht.
2. **Filtern** – nur Meldungen aus dem konfigurierten Zeitfenster; pro Quelle
   greift eine Obergrenze, damit ein Vielschreiber nicht alles überdeckt.
3. **Zusammenfassen** – gleiche Meldungen werden zu einem Thema verschmolzen,
   zuerst über den Link (ohne Tracking-Parameter), dann über die Ähnlichkeit
   der Schlagzeilen. Verglichen werden die bedeutungstragenden Stichwörter,
   Umlaute normalisiert; ab 45 % Übereinstimmung gilt es als dasselbe Thema.
   Die jüngste Fassung liefert die Überschrift, die übrigen erscheinen als
   „auch bei …".
4. **Top-Themen** – was mindestens zwei verschiedene Quellen melden, kommt nach
   oben. Ein Thema steht dort nur einmal, auch wenn es in mehreren Kategorien
   auftaucht (etwa als Agenturticker und als Ressortmeldung).

Die Schwellwerte stehen als Konstanten oben in
[`newsdigest/digest.py`](newsdigest/digest.py) – niedriger heißt mehr
Zusammenfassung und dadurch auch mehr Fehlgriffe.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

128 Tests, keine Netzabhängigkeit: die HTTP-Tests laufen gegen einen lokalen
Testserver, alles andere gegen Fixtures. Sie laufen bei jedem Push über
[`.github/workflows/tests.yml`](.github/workflows/tests.yml) gegen Python 3.11,
3.12 und 3.13.

## Aufbau

```
newsdigest/
  __main__.py      Kommandozeile
  config.py        feeds.toml lesen und prüfen
  fetch.py         paralleler Abruf (HTTP oder lokales Verzeichnis)
  parse.py         RSS 2.0, RSS 1.0 und Atom
  digest.py        Zeitfenster, Duplikate, Top-Themen
  render.py        HTML-Ausgabe
  assets/style.css Layout, hell und dunkel
feeds.toml         Quellen und Einstellungen
tools/demo_feeds.py Beispieldaten für den netzlosen Durchlauf
tests/             Tests und Fixtures
```

Die Seite ist eine einzelne HTML-Datei mit eingebettetem CSS – kein
JavaScript, keine externen Aufrufe. Sie folgt der Hell-/Dunkel-Einstellung des
Systems und lässt sich sauber ausdrucken.
