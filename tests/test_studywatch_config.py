import unittest

from studywatch import config as config_modul
from studywatch.config import ConfigError

MINIMAL = {"quelle": {"name": "Journal Watch", "url": "https://example.invalid/jw"}}


class Defaults(unittest.TestCase):
    def test_defaults_are_sensible(self):
        cfg = config_modul.from_dict(MINIMAL)
        self.assertEqual(cfg.quelle.name, "Journal Watch")
        self.assertEqual(cfg.einstellungen.max_studien, 20)
        self.assertEqual(cfg.einstellungen.zeitzone, "Europe/Berlin")
        self.assertTrue(cfg.zusammenfassung.aktiv)
        self.assertEqual(cfg.zusammenfassung.modell, "claude-opus-5")
        self.assertIn("doi.org", cfg.einstellungen.verlags_hosts)

    def test_sections_can_be_overridden(self):
        cfg = config_modul.from_dict({
            **MINIMAL,
            "einstellungen": {"max_studien": 3, "verlags_hosts": ["www.NEJM.org", ".bmj.com"]},
            "anreicherung": {"pubmed": False, "kontakt_email": "a@b.invalid"},
            "zusammenfassung": {"effort": "high", "aktiv": False},
        })
        self.assertEqual(cfg.einstellungen.max_studien, 3)
        # Hosts werden normalisiert, damit der Vergleich im Scraper trifft.
        self.assertEqual(cfg.einstellungen.verlags_hosts, ("www.nejm.org", "bmj.com"))
        self.assertFalse(cfg.anreicherung.pubmed)
        self.assertEqual(cfg.zusammenfassung.effort, "high")
        self.assertFalse(cfg.zusammenfassung.aktiv)

    def test_helpers_return_modified_copies(self):
        cfg = config_modul.from_dict(MINIMAL)
        enger = config_modul.mit_max_studien(cfg, 5)
        ohne = config_modul.ohne_zusammenfassung(cfg)
        self.assertEqual(enger.einstellungen.max_studien, 5)
        self.assertFalse(ohne.zusammenfassung.aktiv)
        # Das Original bleibt unangetastet.
        self.assertEqual(cfg.einstellungen.max_studien, 20)
        self.assertTrue(cfg.zusammenfassung.aktiv)


class Fehler(unittest.TestCase):
    def test_missing_source_is_rejected(self):
        with self.assertRaises(ConfigError):
            config_modul.from_dict({})

    def test_missing_url_is_rejected(self):
        with self.assertRaises(ConfigError):
            config_modul.from_dict({"quelle": {"name": "X"}})

    def test_non_http_url_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "http"):
            config_modul.from_dict({"quelle": {"name": "X", "url": "ftp://a.invalid"}})

    def test_unknown_effort_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "effort"):
            config_modul.from_dict({**MINIMAL, "zusammenfassung": {"effort": "turbo"}})

    def test_zero_max_studien_is_rejected(self):
        with self.assertRaises(ConfigError):
            config_modul.from_dict({**MINIMAL, "einstellungen": {"max_studien": 0}})

    def test_boolean_is_not_a_number(self):
        with self.assertRaises(ConfigError):
            config_modul.from_dict({**MINIMAL, "einstellungen": {"max_studien": True}})

    def test_empty_publisher_list_is_rejected(self):
        with self.assertRaises(ConfigError):
            config_modul.from_dict({**MINIMAL, "einstellungen": {"verlags_hosts": []}})

    def test_missing_file_is_reported(self):
        with self.assertRaisesRegex(ConfigError, "nicht gefunden"):
            config_modul.load("/nicht/vorhanden/studies.toml")

    def test_repository_config_is_valid(self):
        cfg = config_modul.load("studies.toml")
        self.assertIn("criticalcarereviews.com", cfg.quelle.url)


if __name__ == "__main__":
    unittest.main()
