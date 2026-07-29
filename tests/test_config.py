import tempfile
import unittest
from pathlib import Path

from newsdigest import config as config_module
from newsdigest.config import ConfigError

MINIMAL = {
    "categories": {"deutschland": "Deutschland"},
    "feed": [{"id": "a", "name": "A", "url": "https://a.de/rss", "category": "deutschland"}],
}


def with_feed(**overrides):
    entry = dict(MINIMAL["feed"][0])
    entry.update(overrides)
    return {"categories": MINIMAL["categories"], "feed": [entry]}


class Defaults(unittest.TestCase):
    def test_settings_have_sensible_defaults(self):
        cfg = config_module.from_dict(MINIMAL)
        self.assertEqual(cfg.settings.window_hours, 24)
        self.assertEqual(cfg.settings.timezone, "Europe/Berlin")
        self.assertFalse(cfg.feeds[0].optional)

    def test_settings_can_be_overridden(self):
        cfg = config_module.from_dict({**MINIMAL, "settings": {"window_hours": 6}})
        self.assertEqual(cfg.settings.window_hours, 6)
        self.assertEqual(cfg.settings.max_per_source, 12)

    def test_category_order_is_preserved(self):
        cfg = config_module.from_dict({
            "categories": {"zzz": "Zuletzt", "aaa": "Zuerst"},
            "feed": [
                {"id": "a", "name": "A", "url": "https://a.de", "category": "zzz"},
                {"id": "b", "name": "B", "url": "https://b.de", "category": "aaa"},
            ],
        })
        self.assertEqual(list(cfg.categories), ["zzz", "aaa"])

    def test_feeds_by_category(self):
        cfg = config_module.from_dict({
            "categories": {"x": "X", "y": "Y"},
            "feed": [
                {"id": "a", "name": "A", "url": "https://a.de", "category": "x"},
                {"id": "b", "name": "B", "url": "https://b.de", "category": "y"},
            ],
        })
        self.assertEqual([f.id for f in cfg.feeds_by_category("x")], ["a"])


class Validation(unittest.TestCase):
    def assert_error(self, raw, needle):
        with self.assertRaises(ConfigError) as caught:
            config_module.from_dict(raw)
        self.assertIn(needle, str(caught.exception))

    def test_unknown_category_is_rejected_with_hint(self):
        self.assert_error(with_feed(category="tippfehler"), "tippfehler")

    def test_missing_required_field(self):
        self.assert_error(with_feed(url=""), "'url'")

    def test_duplicate_ids_are_rejected(self):
        raw = {"categories": MINIMAL["categories"], "feed": MINIMAL["feed"] * 2}
        self.assert_error(raw, "doppelte id")

    def test_no_categories(self):
        self.assert_error({"feed": MINIMAL["feed"]}, "[categories]")

    def test_no_feeds(self):
        self.assert_error({"categories": MINIMAL["categories"]}, "keine [[feed]]")

    def test_zero_is_rejected_where_it_makes_no_sense(self):
        self.assert_error({**MINIMAL, "settings": {"window_hours": 0}}, "positive Zahl")

    def test_negative_setting_is_rejected(self):
        self.assert_error({**MINIMAL, "settings": {"retries": -1}}, "Zahl ab 0")

    def test_non_numeric_setting_is_rejected(self):
        self.assert_error({**MINIMAL, "settings": {"retries": "zwei"}}, "Zahl ab 0")

    def test_boolean_is_not_accepted_as_a_number(self):
        self.assert_error({**MINIMAL, "settings": {"retries": True}}, "Zahl ab 0")

    def test_retries_may_be_zero(self):
        """0 bedeutet: einmal versuchen, nicht wiederholen - eine gültige Wahl."""
        cfg = config_module.from_dict({**MINIMAL, "settings": {"retries": 0}})
        self.assertEqual(cfg.settings.retries, 0)


class LoadingFiles(unittest.TestCase):
    def test_missing_file(self):
        with self.assertRaises(ConfigError) as caught:
            config_module.load("/nicht/vorhanden.toml")
        self.assertIn("nicht gefunden", str(caught.exception))

    def test_broken_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kaputt.toml"
            path.write_text("das ist [kein toml", encoding="utf-8")
            with self.assertRaises(ConfigError) as caught:
                config_module.load(path)
            self.assertIn("gültiges TOML", str(caught.exception))

    def test_shipped_config_is_valid(self):
        """Die ausgelieferte feeds.toml muss jederzeit ladbar sein."""
        cfg = config_module.load(Path(__file__).parent.parent / "feeds.toml")
        self.assertGreater(len(cfg.feeds), 10)
        for feed in cfg.feeds:
            self.assertIn(feed.category, cfg.categories)
            self.assertTrue(feed.url.startswith("https://"), feed.url)
        # Alle vier vom Nutzer gewünschten Bereiche sind abgedeckt.
        self.assertEqual(
            set(cfg.categories), {"agenturen", "deutschland", "wirtschaft", "tech"}
        )
        for category in cfg.categories:
            self.assertTrue(cfg.feeds_by_category(category), f"{category} hat keine Quelle")


if __name__ == "__main__":
    unittest.main()
