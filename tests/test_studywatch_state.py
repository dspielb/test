import json
import logging
import tempfile
import unittest
from datetime import date
from pathlib import Path

from studywatch import state as state_modul
from studywatch.study import Studie, kanonische_url


def setUpModule():
    logging.getLogger("studywatch.state").setLevel(logging.CRITICAL)


class Kennungen(unittest.TestCase):
    def test_doi_wins_over_url(self):
        studie = Studie(titel="T", link="https://a.invalid/x", doi="10.1/AbC", pmid="123")
        self.assertEqual(studie.kennung, "doi:10.1/abc")

    def test_pmid_is_used_without_doi(self):
        self.assertEqual(Studie(titel="T", link="https://a.invalid/x", pmid="123").kennung, "pmid:123")

    def test_url_is_the_last_resort(self):
        studie = Studie(titel="T", link="https://A.invalid/x/?utm_source=news&id=7")
        self.assertEqual(studie.kennung, "url:https://a.invalid/x?id=7")

    def test_tracking_parameters_do_not_change_identity(self):
        self.assertEqual(
            kanonische_url("https://a.invalid/x?utm_campaign=1"),
            kanonische_url("https://a.invalid/x/"),
        )

    def test_author_shorthand(self):
        self.assertEqual(Studie(titel="T", link="l").autoren_kurz, "")
        self.assertEqual(Studie(titel="T", link="l", autoren=("Meier A",)).autoren_kurz, "Meier A")
        self.assertEqual(
            Studie(titel="T", link="l", autoren=("Meier A", "Schulz B")).autoren_kurz,
            "Meier A et al.",
        )


class Merkliste(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pfad = Path(self.tmp.name) / "unterordner" / "gesehen.json"

    def test_missing_file_starts_empty(self):
        self.assertEqual(len(state_modul.laden(self.pfad)), 0)

    def test_round_trip(self):
        merkliste = state_modul.Merkliste()
        merkliste.eintragen([Studie(titel="T", link="l", doi="10.1/a")], date(2026, 8, 10))
        state_modul.speichern(merkliste, self.pfad)

        wieder = state_modul.laden(self.pfad)
        self.assertEqual(wieder.gesehen, {"doi:10.1/a": "2026-08-10"})

    def test_first_seen_date_is_kept(self):
        merkliste = state_modul.Merkliste()
        studie = Studie(titel="T", link="l", doi="10.1/a")
        merkliste.eintragen([studie], date(2026, 8, 1))
        merkliste.eintragen([studie], date(2026, 8, 10))
        self.assertEqual(merkliste.gesehen["doi:10.1/a"], "2026-08-01")

    def test_broken_file_starts_empty(self):
        self.pfad.parent.mkdir(parents=True)
        self.pfad.write_text("{kaputt", encoding="utf-8")
        self.assertEqual(len(state_modul.laden(self.pfad)), 0)

    def test_unexpected_format_starts_empty(self):
        self.pfad.parent.mkdir(parents=True)
        self.pfad.write_text(json.dumps({"gesehen": ["a", "b"]}), encoding="utf-8")
        self.assertEqual(len(state_modul.laden(self.pfad)), 0)

    def test_only_new_studies_pass(self):
        merkliste = state_modul.Merkliste({"doi:10.1/a": "2026-08-01"})
        alt = Studie(titel="alt", link="l", doi="10.1/A")
        neu = Studie(titel="neu", link="l2", doi="10.1/b")
        self.assertEqual(state_modul.nur_neue([alt, neu], merkliste), [neu])

    def test_no_temp_file_is_left_behind(self):
        state_modul.speichern(state_modul.Merkliste(), self.pfad)
        self.assertEqual([p.name for p in self.pfad.parent.iterdir()], ["gesehen.json"])


if __name__ == "__main__":
    unittest.main()
