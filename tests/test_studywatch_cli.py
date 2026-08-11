import contextlib
import io
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote, urlencode

from studywatch import mail
from studywatch.__main__ import main
from studywatch.enrich import CROSSREF, EUTILS
from studywatch.http import dateiname_fuer
from studywatch.state import laden
from tests.test_studywatch_mail import FakeIMAP

CONFIG = """
[quelle]
name = "Journal Watch"
url = "https://example.invalid/latest-evidence/journal-watch"

[einstellungen]
max_studien = 10
zeitzone = "Europe/Berlin"

[zusammenfassung]
aktiv = false
"""

SEITE = """<!DOCTYPE html><html><body>
<nav><a href="/">Home</a></nav>
<article>
  <h3><a href="https://doi.org/10.1000/eins">Restrictive versus liberal oxygen targets in
  mechanically ventilated adults</a></h3>
  <p>N Engl J Med, 4 August 2026 ·
     <a href="https://pubmed.ncbi.nlm.nih.gov/40000001/">PubMed</a></p>
</article>
<article>
  <h3><a href="https://doi.org/10.1000/zwei">Early versus delayed renal replacement therapy in
  septic shock: a meta-analysis</a></h3>
  <p>Intensive Care Med, 29 July 2026</p>
</article>
</body></html>
"""

PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>40000001</PMID><Article>
<Journal><ISOAbbreviation>N Engl J Med</ISOAbbreviation></Journal>
<ArticleTitle>Restrictive versus liberal oxygen targets</ArticleTitle>
<ArticleDate><Year>2026</Year><Month>08</Month><Day>04</Day></ArticleDate>
<Abstract><AbstractText Label="CONCLUSIONS">Kein Unterschied nachweisbar.</AbstractText></Abstract>
</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>
"""


def setUpModule():
    for name in ("studywatch", "studywatch.enrich", "studywatch.scrape", "studywatch.state"):
        logging.getLogger(name).setLevel(logging.CRITICAL)


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.basis = Path(self.tmp.name)

        self.config = self.basis / "studies.toml"
        self.config.write_text(CONFIG, encoding="utf-8")
        self.seite = self.basis / "journal-watch.html"
        self.seite.write_text(SEITE, encoding="utf-8")

        self.out = self.basis / "docs"
        self.state = self.basis / "state" / "gesehen.json"

    def lauf(self, *extra: str) -> tuple[int, str]:
        # Die Seite ist seit der Umstellung auf Gmail-Entwürfe eine Zusatzausgabe,
        # deshalb hier ausdrücklich -o und kein Entwurf.
        argumente = [
            "-c", str(self.config),
            "-o", str(self.out),
            "--state", str(self.state),
            "--seite", str(self.seite),
            "--date", "2026-08-10",
            "--kein-entwurf",
            *extra,
        ]
        puffer = io.StringIO()
        with contextlib.redirect_stdout(puffer), contextlib.redirect_stderr(puffer):
            code = main(argumente)
        return code, puffer.getvalue()

    def index(self) -> str:
        return (self.out / "index.html").read_text(encoding="utf-8")


class Durchlauf(CliTestCase):
    def test_first_run_writes_page_archive_and_state(self):
        code, ausgabe = self.lauf("--kein-netz")

        self.assertEqual(code, 0)
        self.assertIn("2 neue Studien", ausgabe)
        self.assertTrue((self.out / "index.html").exists())
        self.assertTrue((self.out / "archiv" / "2026-08-10.html").exists())
        self.assertTrue((self.out / "archiv" / "index.html").exists())
        self.assertEqual(len(laden(self.state)), 2)

    def test_studies_appear_on_the_page(self):
        self.lauf("--kein-netz")
        html = self.index()
        self.assertIn("Restrictive versus liberal oxygen targets", html)
        self.assertIn("Early versus delayed renal replacement", html)

    def test_second_run_finds_nothing_new(self):
        self.lauf("--kein-netz")
        code, ausgabe = self.lauf("--kein-netz")

        self.assertEqual(code, 0)
        self.assertIn("0 neue Studien", ausgabe)
        self.assertIn("Heute keine neuen Studien", self.index())

    def test_alle_ignores_the_seen_list(self):
        self.lauf("--kein-netz")
        code, ausgabe = self.lauf("--kein-netz", "--alle")
        self.assertEqual(code, 0)
        self.assertIn("2 neue Studien", ausgabe)

    def test_first_run_marks_overflow_as_known(self):
        # Erstlauf mit Obergrenze 1: eine Studie wird gezeigt, beide gelten als bekannt,
        # damit nicht tagelang ein Altbestand nachrieselt.
        code, ausgabe = self.lauf("--kein-netz", "--max", "1")

        self.assertEqual(code, 0)
        self.assertIn("1 neue Studien von 2 geprüften", ausgabe)
        self.assertEqual(len(laden(self.state)), 2)
        self.assertIn("Erstlauf", self.index())

    def test_later_overflow_is_kept_for_the_next_run(self):
        # Nicht leere Merkliste ohne Bezug zur Seite: beide Studien sind neu,
        # aber es ist kein Erstlauf - der Überhang bleibt für morgen liegen.
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text(
            json.dumps({"gesehen": {"doi:10.1000/alt": "2026-08-09"}}), encoding="utf-8"
        )

        code, ausgabe = self.lauf("--kein-netz", "--max", "1")
        self.assertEqual(code, 0)
        self.assertEqual(len(laden(self.state)), 2)
        self.assertIn("überschreiten die Obergrenze", self.index())

    def test_archive_index_lists_every_day(self):
        self.lauf("--kein-netz")
        self.lauf("--kein-netz", "--alle", "--date", "2026-08-11")

        uebersicht = (self.out / "archiv" / "index.html").read_text(encoding="utf-8")
        self.assertIn("2026-08-10.html", uebersicht)
        self.assertIn("2026-08-11.html", uebersicht)

    def test_no_archive_option(self):
        self.lauf("--kein-netz", "--no-archive")
        self.assertFalse((self.out / "archiv").exists())

    def test_dry_run_writes_nothing(self):
        code, ausgabe = self.lauf("--kein-netz", "--trockenlauf")

        self.assertEqual(code, 0)
        self.assertIn("(Trockenlauf)", ausgabe)
        self.assertFalse(self.out.exists())
        self.assertFalse(self.state.exists())


class MitAnreicherung(CliTestCase):
    def setUp(self):
        super().setUp()
        self.antworten = self.basis / "antworten"
        self.antworten.mkdir()

        for doi in ("10.1000/eins", "10.1000/zwei"):
            inhalt = {"message": {"container-title": ["Demo Journal"], "title": ["Titel"]}}
            pfad = self.antworten / dateiname_fuer(CROSSREF + quote(doi, safe=""))
            pfad.write_text(json.dumps(inhalt), encoding="utf-8")

        efetch = f"{EUTILS}efetch.fcgi?" + urlencode(
            {"db": "pubmed", "retmode": "xml", "id": "40000001"}
        )
        (self.antworten / dateiname_fuer(efetch)).write_text(PUBMED_XML, encoding="utf-8")

    def test_metadata_and_abstract_reach_the_page(self):
        code, _ = self.lauf("--offline-dir", str(self.antworten))
        html = self.index()

        self.assertEqual(code, 0)
        self.assertIn("N Engl J Med", html)
        self.assertIn("Kein Unterschied nachweisbar.", html)
        # Ohne API-Schlüssel ist die Kurzfassung der Auszug aus dem Abstract.
        self.assertIn("wörtlicher Auszug aus dem Abstract", html)

    def test_missing_responses_do_not_break_the_run(self):
        (self.antworten / dateiname_fuer(CROSSREF + quote("10.1000/eins", safe=""))).unlink()
        code, _ = self.lauf("--offline-dir", str(self.antworten))
        self.assertEqual(code, 0)
        self.assertIn("Restrictive versus liberal oxygen targets", self.index())


class GmailEntwurf(CliTestCase):
    """Der Entwurf ist die eigentliche Zustellung - hier gegen einen Fake-Server."""

    def setUp(self):
        super().setUp()
        self.server = FakeIMAP()
        self.umgebung = mock.patch.dict(
            "os.environ",
            {"GMAIL_BENUTZER": "ich@gmail.invalid", "GMAIL_APP_PASSWORT": "abcd efgh ijkl mnop"},
        )
        self.umgebung.start()
        self.addCleanup(self.umgebung.stop)

        verbindung = mock.patch.object(mail, "_verbinden", lambda _: self.server)
        verbindung.start()
        self.addCleanup(verbindung.stop)

    def entwurfslauf(self, *extra: str) -> tuple[int, str]:
        argumente = [
            "-c", str(self.config),
            "--state", str(self.state),
            "--seite", str(self.seite),
            "--date", "2026-08-10",
            "--offline-dir", str(self.basis),  # Anreicherung läuft ins Leere, das ist hier egal
            *extra,
        ]
        puffer = io.StringIO()
        with contextlib.redirect_stdout(puffer), contextlib.redirect_stderr(puffer):
            code = main(argumente)
        return code, puffer.getvalue()

    def test_draft_is_created_and_state_saved(self):
        code, ausgabe = self.entwurfslauf()

        self.assertEqual(code, 0)
        self.assertIn("Gmail-Entwurf", ausgabe)
        self.assertEqual(len(self.server.appends), 1)
        self.assertEqual(len(laden(self.state)), 2)

    def test_no_html_file_is_written_by_default(self):
        self.entwurfslauf()
        self.assertFalse(self.out.exists())

    def test_draft_contains_the_studies(self):
        self.entwurfslauf()
        rohtext = self.server.appends[0][3].decode("utf-8", errors="replace")
        self.assertIn("Restrictive", rohtext.replace("=\r\n", "").replace("=\n", ""))

    def test_failed_delivery_keeps_the_state_untouched(self):
        self.server.login_fehler = True
        code, ausgabe = self.entwurfslauf()

        self.assertEqual(code, 3)
        self.assertIn("Entwurf nicht angelegt", ausgabe)
        # Entscheidend: sonst gälten die Studien als erledigt, ohne dass sie je jemand sah.
        self.assertFalse(self.state.exists())

    def test_missing_credentials_fail_loudly(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            code, ausgabe = self.entwurfslauf()

        self.assertEqual(code, 3)
        self.assertIn("GMAIL_BENUTZER", ausgabe)
        self.assertFalse(self.state.exists())

    def test_nothing_new_means_no_draft(self):
        self.entwurfslauf()
        code, ausgabe = self.entwurfslauf()

        self.assertEqual(code, 0)
        self.assertEqual(len(self.server.appends), 1)
        self.assertIn("nichts Neues", ausgabe)

    def test_empty_draft_can_be_switched_on(self):
        self.config.write_text(
            CONFIG + '\n[entwurf]\nauch_ohne_studien = true\n', encoding="utf-8"
        )
        self.entwurfslauf()
        self.entwurfslauf()
        self.assertEqual(len(self.server.appends), 2)

    def test_without_any_output_the_state_is_kept(self):
        code, ausgabe = self.entwurfslauf("--kein-entwurf")

        self.assertEqual(code, 0)
        self.assertIn("Keine Ausgabe erzeugt", ausgabe)
        self.assertFalse(self.state.exists())


class Fehlerfaelle(CliTestCase):
    def test_missing_page_returns_one(self):
        self.seite.unlink()
        code, ausgabe = self.lauf("--kein-netz")
        self.assertEqual(code, 1)
        self.assertIn("Quelle nicht erreichbar", ausgabe)

    def test_broken_config_returns_two(self):
        self.config.write_text("[quelle]\nname = 'X'\n", encoding="utf-8")
        code, ausgabe = self.lauf("--kein-netz")
        self.assertEqual(code, 2)
        self.assertIn("Fehler in der Konfiguration", ausgabe)

    def test_page_without_studies_is_reported(self):
        self.seite.write_text("<html><body><p>Nichts</p></body></html>", encoding="utf-8")
        code, _ = self.lauf("--kein-netz")

        self.assertEqual(code, 0)
        self.assertIn("kein einziger Studienlink", self.index())

    def test_invalid_date_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.lauf("--kein-netz", "--date", "10.08.2026")


if __name__ == "__main__":
    unittest.main()
