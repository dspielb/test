import unittest
from datetime import date, datetime, timezone

from studywatch.render import Bericht, render_archiv_index, render_bericht
from studywatch.study import Studie, Zusammenfassung

ERZEUGT = datetime(2026, 8, 10, 4, 30, tzinfo=timezone.utc)


def bericht(studien, **felder) -> Bericht:
    grund = {
        "studien": studien,
        "quelle_name": "Critical Care Reviews – Journal Watch",
        "quelle_url": "https://example.invalid/jw",
        "erzeugt_am": ERZEUGT,
        "gefunden_gesamt": len(studien),
    }
    grund.update(felder)
    return Bericht(**grund)


def studie(**felder) -> Studie:
    grund = {
        "titel": "Restrictive versus liberal oxygen targets",
        "link": "https://doi.org/10.1056/NEJMoa2400001",
        "doi": "10.1056/NEJMoa2400001",
        "pmid": "40000001",
        "journal": "N Engl J Med",
        "veroeffentlicht": date(2026, 8, 4),
        "autoren": ("Beispiel A", "Muster B"),
        "abstract": "Background: Eins.\n\nConclusions: Zwei.",
        "zusammenfassung": Zusammenfassung(
            kernaussage="Kein Unterschied in der Sterblichkeit.",
            hintergrund="Unklare Zielsättigung.",
            methodik="Randomisiert, n=2140.",
            ergebnis="29,2 % gegenüber 31,8 %.",
            bedeutung="Kein Vorteil belegt.",
        ),
    }
    grund.update(felder)
    return Studie(**grund)


class Seite(unittest.TestCase):
    def setUp(self):
        self.html = render_bericht(bericht([studie()]))

    def test_page_is_self_contained_german_html(self):
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))
        self.assertIn('<html lang="de">', self.html)
        self.assertIn("<style>", self.html)
        self.assertNotIn("<script", self.html)

    def test_study_details_are_shown(self):
        for erwartet in (
            "Restrictive versus liberal oxygen targets",
            "N Engl J Med",
            "4. August 2026",
            "Beispiel A et al.",
            "Kein Unterschied in der Sterblichkeit.",
            "Randomisiert, n=2140.",
        ):
            self.assertIn(erwartet, self.html)

    def test_identifiers_are_linked(self):
        self.assertIn("https://doi.org/10.1056/NEJMoa2400001", self.html)
        self.assertIn("https://pubmed.ncbi.nlm.nih.gov/40000001/", self.html)

    def test_abstract_is_collapsed(self):
        self.assertIn("<details><summary>Abstract im Original</summary>", self.html)

    def test_local_time_is_used(self):
        # 04:30 UTC ist 06:30 in Europe/Berlin (MESZ).
        self.assertIn("Stand 06:30 Uhr", self.html)

    def test_disclaimer_is_present(self):
        self.assertIn("keine ärztliche Empfehlung", self.html)


class Herkunft(unittest.TestCase):
    def test_model_summary_is_labelled(self):
        html = render_bericht(bericht([studie()]))
        self.assertIn("automatisch aus dem Abstract erzeugt", html)

    def test_abstract_fallback_is_labelled(self):
        s = studie(zusammenfassung=Zusammenfassung(kernaussage="Zwei.", herkunft="abstract"))
        html = render_bericht(bericht([s]))
        self.assertIn("wörtlicher Auszug aus dem Abstract", html)

    def test_missing_summary_is_labelled(self):
        s = studie(zusammenfassung=None, abstract=None, kontext="")
        html = render_bericht(bericht([s]))
        self.assertIn("Keine Kurzfassung verfügbar", html)
        self.assertIn("Kein Abstract gefunden", html)

    def test_context_is_shown_without_a_summary(self):
        s = studie(zusammenfassung=None, abstract=None, kontext="N Engl J Med, 4. August 2026")
        self.assertIn("N Engl J Med, 4. August 2026", render_bericht(bericht([s])))


class Sonderfaelle(unittest.TestCase):
    def test_empty_day_explains_itself(self):
        html = render_bericht(bericht([]))
        self.assertIn("Heute keine neuen Studien", html)
        self.assertIn("0 neue Studien", html)

    def test_html_in_content_is_escaped(self):
        s = studie(titel="Sauerstoff <script>alert(1)</script> & mehr")
        html = render_bericht(bericht([s]))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp; mehr", html)

    def test_notes_are_listed(self):
        html = render_bericht(bericht([], hinweise=["Erstlauf: Merkliste war leer."]))
        self.assertIn("Erstlauf: Merkliste war leer.", html)

    def test_singular_is_used_for_one_study(self):
        self.assertIn("1 neue Studie ·", render_bericht(bericht([studie()])))

    def test_model_name_appears_only_when_used(self):
        self.assertIn("claude-opus-5", render_bericht(bericht([studie()], modell="claude-opus-5")))
        self.assertNotIn("claude-opus-5", render_bericht(bericht([studie()])))


class Archiv(unittest.TestCase):
    def test_days_are_listed_newest_first(self):
        html = render_archiv_index([date(2026, 8, 8), date(2026, 8, 10), date(2026, 8, 9)])
        reihenfolge = [html.index(f"{tag}.html") for tag in ("2026-08-10", "2026-08-09", "2026-08-08")]
        self.assertEqual(reihenfolge, sorted(reihenfolge))
        self.assertIn("3 Ausgaben", html)

    def test_weekday_is_shown(self):
        self.assertIn("Montag", render_archiv_index([date(2026, 8, 10)]))


if __name__ == "__main__":
    unittest.main()
