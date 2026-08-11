# Tägliche Nachrichtenübersicht

Erzeugt jeden Tag eine HTML-Seite mit den aktuellen Meldungen aus deutschen
Nachrichtenmedien, Wirtschafts- und Tech-Quellen sowie den Nachrichtenagenturen.
Meldungen, die mehrere Quellen gleichzeitig bringen, stehen als **Top-Themen**
ganz oben.

Kein Installationsaufwand: das Projekt kommt mit **Python 3.11+** und der
Standardbibliothek aus – keine Abhängigkeiten, keine virtuelle Umgebung nötig.

> Im selben Repository liegt ein zweites, eigenständiges Programm:
> [**studywatch**](#tägliche-studienübersicht-studywatch) holt täglich die neuesten
> Studien aus dem Critical Care Reviews Journal Watch, fasst sie auf Deutsch
> zusammen und legt das Ergebnis als Entwurf im Gmail-Postfach ab.

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

128 Tests für `newsdigest` (257 im ganzen Repository), keine Netzabhängigkeit:
die HTTP-Tests laufen gegen einen lokalen Testserver, alles andere gegen
Fixtures. Sie laufen bei jedem Push über
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

---

# Tägliche Studienübersicht (studywatch)

Ruft jeden Tag die Seite
[Critical Care Reviews – Journal Watch](https://criticalcarereviews.com/latest-evidence/journal-watch)
ab, erkennt die dort verlinkten Studien, holt zu jeder Metadaten und Abstract von
**Crossref** und **PubMed**, schreibt eine deutsche Kurzfassung mit der Claude-API
und legt das Ganze als **Entwurf im Gmail-Postfach** ab.

Verschickt wird nichts. Der Entwurf liegt morgens in *Entwürfe* und wartet – lesen,
weiterleiten oder löschen entscheidest du.

Enthalten ist nur, was seit dem letzten Lauf dazugekommen ist. Gibt es nichts
Neues, entsteht auch kein Entwurf.

## Schnellstart

```bash
pip install -r requirements-studywatch.txt   # nur für die Kurzfassungen nötig

export ANTHROPIC_API_KEY="sk-ant-…"
export GMAIL_BENUTZER="du@gmail.com"
export GMAIL_APP_PASSWORT="abcd efgh ijkl mnop"   # App-Passwort, nicht das Kontopasswort

python3 -m studywatch
```

Geschrieben wird nur `state/gesehen.json` – die Merkliste bereits gezeigter
Studien. Alles andere landet in Gmail.

**Ohne API-Schlüssel läuft das Programm trotzdem durch** – statt einer Kurzfassung
steht dann die Schlussfolgerung aus dem Abstract im Entwurf, und die Mail weist das
aus. Dasselbe gilt, wenn das Paket `anthropic` fehlt oder die API ausfällt.

**Ohne Gmail-Zugang bricht der Lauf dagegen ab** (Rückgabewert `3`) und lässt die
Merkliste unangetastet – sonst gälten die Studien als erledigt, obwohl sie nie
jemand gesehen hat. Der nächste Lauf nimmt dieselben noch einmal.

### Erst ansehen, dann zustellen

```bash
python3 -m studywatch --kein-entwurf --out vorschau --state /tmp/vorschau.json
open vorschau/index.html
```

`--out` erzeugt zusätzlich die HTML-Seite, die es früher als einzige Ausgabe gab.
Ohne die Option entsteht keine Datei.

**Beim Ausprobieren `--state` immer auf einen Pfad außerhalb des Repositorys
legen.** Sonst verbraucht der Testlauf den Erstlauf, und der echte Lauf hält
später alles für längst bekannt.

### Ohne Netzzugang ausprobieren

```bash
python3 tools/demo_studien.py /tmp/studien
python3 -m studywatch \
  --seite /tmp/studien/journal-watch.html \
  --offline-dir /tmp/studien \
  --state /tmp/studien/gesehen.json \
  --keine-zusammenfassung --kein-entwurf \
  --out /tmp/vorschau
```

Die Inhalte in `tools/demo_studien.py` sind frei erfunden.

### Optionen

| Option | Bedeutung |
| --- | --- |
| `-c, --config PFAD` | Konfigurationsdatei (Standard: `studies.toml`) |
| `-o, --out PFAD` | Zusätzlich eine HTML-Seite dorthin schreiben (Standard: keine Datei) |
| `--state PFAD` | Merkliste (Standard: `state/gesehen.json`) |
| `--max N` | Obergrenze neuer Studien, überschreibt die Konfiguration |
| `--kein-entwurf` | Keinen Gmail-Entwurf anlegen |
| `--seite PFAD` | Übersichtsseite aus einer HTML-Datei lesen statt abrufen |
| `--offline-dir PFAD` | Alle HTTP-Antworten aus einem Verzeichnis lesen |
| `--kein-netz` | Keine Netzaufrufe: weder Anreicherung noch Kurzfassung noch Entwurf |
| `--keine-zusammenfassung` | Ohne Claude-API, nur Abstracts |
| `--alle` | Merkliste ignorieren und alles Gefundene zeigen |
| `--trockenlauf` | Nichts schreiben, nur berichten, was passieren würde |
| `--no-archive` | Bei `--out`: kein Tagesarchiv |
| `--date JJJJ-MM-TT` | Datum des Archiveintrags (Standard: heute) |
| `-v, --verbose` | Zeigt jeden Schritt mit Zahlen |

Rückgabewerte: `0` = in Ordnung, `1` = Quellseite nicht erreichbar,
`2` = Fehler in der Konfiguration, `3` = Entwurf konnte nicht abgelegt werden.

## Gmail einrichten

Der Zugang läuft über ein **App-Passwort** und IMAP. Das braucht kein
Google-Cloud-Projekt und keine zusätzliche Bibliothek – `imaplib` steckt in der
Standardbibliothek.

1. **Zwei-Faktor-Anmeldung aktivieren**, falls noch nicht geschehen:
   <https://myaccount.google.com/signinoptions/twosv>. Ohne sie gibt es keine
   App-Passwörter.
2. **App-Passwort erzeugen**: <https://myaccount.google.com/apppasswords>.
   Einen Namen vergeben (z. B. `studywatch`), erzeugen, die 16 Zeichen kopieren.
   Sie werden nur einmal angezeigt. Die Leerzeichen der Vierergruppen sind
   Kosmetik – das Programm entfernt sie selbst.
3. **IMAP im Postfach aktivieren**: Gmail → Zahnrad → *Alle Einstellungen
   ansehen* → *Weiterleitung und POP/IMAP* → *IMAP aktivieren* → speichern.
4. **Als GitHub-Secrets hinterlegen** (Settings → Secrets and variables →
   Actions → *New repository secret*):
   - `GMAIL_BENUTZER` – deine Gmail-Adresse
   - `GMAIL_APP_PASSWORT` – das App-Passwort aus Schritt 2

Sind App-Passwörter in deinem Konto gesperrt (kommt bei verwalteten
Workspace-Konten vor), meldet der Lauf das beim Anmelden. Dann bleibt der Weg
über die Gmail-API mit OAuth – dafür müsste `mail.py` erweitert werden.

Den Entwürfe-Ordner sucht das Programm über das IMAP-Merkmal `\Drafts`, nicht
über den Namen – damit ist es egal, ob dein Konto auf Deutsch oder Englisch
steht. Nur falls das schiefgeht, lässt sich unter `[entwurf].ordner` ein Name
fest eintragen.

## Wie es funktioniert

1. **Abrufen** – die Übersichtsseite als HTML.
2. **Erkennen** – Studien sind Links auf Verlags- und Datenbank-Domains
   (`doi.org`, `pubmed.ncbi.nlm.nih.gov`, `nejm.org`, …). Das ist bewusst nicht an
   CSS-Klassen der Seite festgemacht: solche Selektoren brechen beim nächsten
   Redesign, die Zieladressen nicht. Steht der Titel nicht im Link, sondern
   daneben – etwa bei „PubMed"- oder „full text"-Links – wird der Text davor
   verwendet. Verweist ein Eintrag sowohl auf DOI als auch auf PubMed, werden
   beide zu **einer** Studie zusammengeführt.
3. **Aussortieren** – alles, was schon in `state/gesehen.json` steht, fällt raus.
4. **Anreichern** – Journal, Datum, Autoren und Abstract über Crossref (per DOI)
   und PubMed (per DOI oder Titelsuche). Beide Dienste sind frei zugänglich; ein
   Ausfall kostet nur Detailtiefe, nicht den Lauf.
5. **Zusammenfassen** – je Studie ein Aufruf der Claude-API mit dem Abstract als
   einziger Grundlage. Die Antwort ist über *structured outputs* auf fünf Felder
   festgelegt (Kernaussage, Hintergrund, Methodik, Ergebnis, Bedeutung), sodass
   nichts nachträglich aus Fließtext geparst werden muss.
6. **Zustellen** – die Mail entsteht mit Text- und HTML-Teil und wird per IMAP
   in den Entwürfe-Ordner gelegt. Der HTML-Teil kommt ohne `<style>`-Block und
   ohne aufklappbare Abschnitte aus, weil Mail-Programme beides nicht
   verlässlich unterstützen; die Stilangaben stehen direkt an den Elementen.

### Was „neu" heißt

Die Journal-Watch-Seite trägt kein verlässliches Datum pro Eintrag. „Neu" heißt
deshalb: *heute zum ersten Mal auf der Seite gesehen*. Dafür merkt sich
`state/gesehen.json` die Kennung jeder Studie (DOI, sonst PMID, sonst URL) – die
Datei gehört ins Repository, sonst beginnt jeder Lauf von vorn.

Beim **allerersten Lauf** ist die Merkliste leer und damit die gesamte Seite
„neu". Damit nicht tagelang ein Altbestand nachrieselt, nimmt der erste Lauf die
obersten `max_studien` Einträge und vermerkt den Rest als bekannt. Später
gefundene Überhänge bleiben dagegen liegen und erscheinen im nächsten Lauf.

Die Merkliste wird **erst nach erfolgreicher Zustellung** geschrieben. Scheitert
der Entwurf, ändert sich nichts – der nächste Lauf versucht dieselben Studien
erneut.

### Kosten

Ein Aufruf pro Studie, mit `effort = "low"` und einem Abstract als Eingabe – das
sind je Studie grob 1 000 Eingabe- und wenige hundert Ausgabe-Tokens. Bei
15 Studien am Tag liegt das im Bereich weniger Cent pro Tag. Nach jedem Lauf
steht der tatsächliche Verbrauch in der Ausgabe:

```
Modellverbrauch: 12 Anfragen, 14 233 Eingabe- und 3 918 Ausgabe-Tokens
```

`max_studien` in `studies.toml` deckelt den Verbrauch nach oben.

## Anpassen

Alles steckt in [`studies.toml`](studies.toml).

Fehlt ein Verlag, wird seine Domain unter `verlags_hosts` ergänzt – dafür ist
keine Codeänderung nötig:

```toml
[einstellungen]
verlags_hosts = ["doi.org", "pubmed.ncbi.nlm.nih.gov", "nejm.org", "…"]
```

Unter `[entwurf]` lassen sich Betreff (`{datum}` und `{anzahl}` als Platzhalter),
Empfänger, Ordner und die Frage einstellen, ob das Abstract mit in die Mail soll.
`auch_ohne_studien = true` erzeugt auch an ereignislosen Tagen einen Entwurf –
als Lebenszeichen, dass der Lauf noch funktioniert.

Unter `[zusammenfassung]` stehen Modell, `effort` und Obergrenzen, unter
`[anreicherung]` lassen sich die beiden Datendienste einzeln abschalten.

## Automatischer Lauf

[`.github/workflows/studien.yml`](.github/workflows/studien.yml) startet den Abruf
täglich um 05:30 UTC (07:30 MESZ / 06:30 MEZ) und committet danach die Merkliste.
Der Lauf lässt sich unter *Actions → Tägliche Studienübersicht → Run workflow*
auch von Hand auslösen.

Nötig sind:

1. **Der Workflow muss im Standard-Branch liegen.** GitHub führt geplante
   Workflows ausschließlich aus dem Standard-Branch aus.
2. **Schreibrechte für Actions** unter *Settings → Actions → General →
   Workflow permissions* – für den Commit der Merkliste.
3. **Die Secrets** unter *Settings → Secrets and variables → Actions*:

   | Secret | Pflicht | Wofür |
   | --- | --- | --- |
   | `GMAIL_BENUTZER` | ja | Gmail-Adresse, in deren Entwürfe die Mail geht |
   | `GMAIL_APP_PASSWORT` | ja | App-Passwort (siehe [Gmail einrichten](#gmail-einrichten)) |
   | `ANTHROPIC_API_KEY` | nein | Ohne ihn stehen Abstract-Auszüge statt Kurzfassungen in der Mail |
   | `NCBI_API_KEY` | nein | Hebt das PubMed-Limit von 3 auf 10 Anfragen pro Sekunde |

Schlägt der Entwurf fehl, endet der Job sichtbar rot (Code `3`) und die Merkliste
bleibt unverändert – ein stiller Ausfall, bei dem Studien verloren gehen, ist
damit ausgeschlossen.

## Grenzen

- **Die Erkennung ist eine Heuristik.** Sie stützt sich auf die Zieladressen der
  Links und ist damit gegen Layoutänderungen robust – aber nicht gegen jede.
  Findet der Lauf keinen einzigen Studienlink, steht das als Hinweis in der Mail;
  dann lohnt ein Blick auf `verlags_hosts`.
- **Kurzfassungen sind kein Ersatz für die Originalarbeit.** Sie entstehen
  ausschließlich aus dem Abstract und stehen unter einem entsprechenden Hinweis.
  Das Modell wird angewiesen, nichts zu ergänzen, Zahlen wörtlich zu übernehmen
  und keine Behandlungsempfehlung zu formulieren – prüfen muss man sie trotzdem.
- **Abstracts fehlen manchmal.** Ohne Abstract gibt es keine Kurzfassung, sondern
  nur Titel, Journal und Links.
- **Ein Entwurf ist flüchtig.** Gelöscht ist gelöscht – ein Archiv gibt es seit
  der Umstellung auf Gmail nicht mehr. Wer eines möchte, ergänzt `--out docs/studien`
  im Workflow und committet das Verzeichnis mit.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

129 Tests für `studywatch`, ohne Netz, ohne API-Schlüssel und ohne Gmail-Konto:
HTTP-Antworten kommen aus Fixtures, die Claude-Aufrufe gegen einen Stub-Client,
der IMAP-Server gegen einen Fake, der mitschreibt statt zu verbinden. Abgedeckt
sind auch die Rückfallebenen – abgelehnte Anfrage, unlesbare Antwort, fehlender
Schlüssel, ausgefallener Datendienst, abgelehnte Anmeldung.

## Aufbau

```
studywatch/
  __main__.py      Kommandozeile und Ablaufsteuerung
  config.py        studies.toml lesen und prüfen
  http.py          Abruf mit Timeout, Wiederholung und Offline-Modus
  scrape.py        Studienlinks aus der Übersichtsseite
  state.py         Merkliste bereits gezeigter Studien
  enrich.py        Crossref und PubMed
  summarize.py     Claude-API mit Rückfall auf den Abstract
  render.py        Fassungen für Mail (Text und HTML) und Webseite
  mail.py          Entwurf per IMAP im Gmail-Postfach ablegen
  assets/style.css Layout der Webseite, hell und dunkel
studies.toml       Quelle, Verlage, Zustellung und Einstellungen
tools/demo_studien.py Beispieldaten für den netzlosen Durchlauf
```
