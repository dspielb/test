import contextlib
import io
import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from newsdigest.__main__ import main

FEED_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>{name}</title>
{items}
</channel></rss>"""

CONFIG = """
[settings]
window_hours = 24
timezone = "Europe/Berlin"

[categories]
deutschland = "Deutschland & Welt"
tech = "Tech & IT"

[[feed]]
id = "eins"
name = "Quelle Eins"
url = "https://eins.invalid/rss"
category = "deutschland"

[[feed]]
id = "zwei"
name = "Quelle Zwei"
url = "https://zwei.invalid/rss"
category = "tech"
"""


def setUpModule():
    logging.getLogger("newsdigest").setLevel(logging.CRITICAL)


def item(title: str, hours_ago: float) -> str:
    when = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return (
        f"<item><title>{title}</title>"
        f"<link>https://beispiel.invalid/{abs(hash(title)) % 9999}</link>"
        f"<description>Ein Anriss.</description>"
        f"<pubDate>{when.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
    )


class CliCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.config_path = self.tmp / "feeds.toml"
        self.config_path.write_text(CONFIG, encoding="utf-8")

        self.feeds = self.tmp / "feeds"
        self.feeds.mkdir()
        self.out = self.tmp / "out"

    def write_feed(self, feed_id: str, name: str, items: list[str]):
        (self.feeds / f"{feed_id}.xml").write_text(
            FEED_TEMPLATE.format(name=name, items="\n".join(items)), encoding="utf-8"
        )

    def run_cli(self, *extra: str) -> tuple[int, str, str]:
        argv = [
            "--config", str(self.config_path),
            "--out", str(self.out),
            "--offline-dir", str(self.feeds),
            *extra,
        ]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()


class SuccessfulRun(CliCase):
    def setUp(self):
        super().setUp()
        self.write_feed("eins", "Quelle Eins", [
            item("Erste Meldung des Tages", 1),
            item("Zweite Meldung am Morgen", 3),
        ])
        self.write_feed("zwei", "Quelle Zwei", [item("Technik-Neuigkeit", 2)])

    def test_exits_successfully(self):
        code, stdout, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("3 Meldungen aus 2 Quellen", stdout)

    def test_writes_index_and_archive(self):
        self.run_cli("--date", "2026-07-28")
        self.assertTrue((self.out / "index.html").exists())
        self.assertTrue((self.out / "archiv" / "2026-07-28.html").exists())
        self.assertTrue((self.out / "archiv" / "index.html").exists())

    def test_index_and_archive_entry_are_identical(self):
        self.run_cli("--date", "2026-07-28")
        self.assertEqual(
            (self.out / "index.html").read_text(encoding="utf-8"),
            (self.out / "archiv" / "2026-07-28.html").read_text(encoding="utf-8"),
        )

    def test_page_contains_the_headlines(self):
        self.run_cli()
        html = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn("Erste Meldung des Tages", html)
        self.assertIn("Technik-Neuigkeit", html)

    def test_creates_missing_output_directories(self):
        nested = self.out / "tief" / "verschachtelt"
        code, _, _ = self.run_cli("--out", str(nested))
        self.assertEqual(code, 0)
        self.assertTrue((nested / "index.html").exists())

    def test_no_archive_option(self):
        self.run_cli("--no-archive")
        self.assertTrue((self.out / "index.html").exists())
        self.assertFalse((self.out / "archiv").exists())

    def test_rerun_updates_the_same_files(self):
        self.run_cli("--date", "2026-07-28")
        first = (self.out / "index.html").read_text(encoding="utf-8")
        self.write_feed("eins", "Quelle Eins", [item("Ganz frische Eilmeldung", 0.5)])
        self.run_cli("--date", "2026-07-28")
        second = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertNotEqual(first, second)
        self.assertIn("Ganz frische Eilmeldung", second)
        self.assertEqual(len(list((self.out / "archiv").glob("2026-*.html"))), 1)

    def test_archive_index_grows_with_each_day(self):
        self.run_cli("--date", "2026-07-27")
        self.run_cli("--date", "2026-07-28")
        listing = (self.out / "archiv" / "index.html").read_text(encoding="utf-8")
        self.assertIn("2026-07-27.html", listing)
        self.assertIn("2026-07-28.html", listing)
        self.assertIn("2 Ausgaben", listing)


class WindowOption(CliCase):
    def setUp(self):
        super().setUp()
        self.write_feed("eins", "Quelle Eins", [
            item("Ganz frisch", 1),
            item("Schon etwas aelter", 10),
        ])
        self.write_feed("zwei", "Quelle Zwei", [])

    def test_hours_option_narrows_the_window(self):
        self.run_cli("--hours", "2")
        html = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn("Ganz frisch", html)
        self.assertNotIn("Schon etwas aelter", html)
        self.assertIn("Zeitfenster 2 Stunden", html)

    def test_without_the_option_the_configured_window_applies(self):
        self.run_cli()
        html = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn("Schon etwas aelter", html)


class Failures(CliCase):
    def test_missing_config_is_reported(self):
        code, _, stderr = self.run_cli("--config", str(self.tmp / "gibtsnicht.toml"))
        self.assertEqual(code, 2)
        self.assertIn("nicht gefunden", stderr)

    def test_invalid_config_is_reported(self):
        broken = self.tmp / "kaputt.toml"
        broken.write_text('[categories]\nx = "X"\n[[feed]]\nid = "a"\n', encoding="utf-8")
        code, _, stderr = self.run_cli("--config", str(broken))
        self.assertEqual(code, 2)
        self.assertIn("Konfiguration", stderr)

    def test_all_sources_down_exits_nonzero_and_writes_nothing(self):
        # Kein einziges Offline-File vorhanden -> jede Quelle schlägt fehl.
        code, _, stderr = self.run_cli()
        self.assertEqual(code, 1)
        self.assertIn("Keine einzige Quelle", stderr)
        self.assertFalse(self.out.exists())

    def test_partial_failure_still_produces_a_page(self):
        self.write_feed("eins", "Quelle Eins", [item("Diese Quelle laeuft", 1)])
        code, stdout, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("1 nicht erreichbar", stdout)
        html = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn("Diese Quelle laeuft", html)
        self.assertIn("Quelle Zwei", html)  # taucht im Quellen-Status auf

    def test_rejects_a_malformed_date(self):
        self.write_feed("eins", "Quelle Eins", [item("Meldung", 1)])
        with self.assertRaises(SystemExit):
            self.run_cli("--date", "28.07.2026")


class EmptyResult(CliCase):
    def test_reachable_but_stale_sources_produce_an_empty_page(self):
        self.write_feed("eins", "Quelle Eins", [item("Uralt", 200)])
        self.write_feed("zwei", "Quelle Zwei", [item("Ebenfalls uralt", 300)])
        code, _, _ = self.run_cli()
        self.assertEqual(code, 0)
        html = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertIn("Keine Meldungen", html)


if __name__ == "__main__":
    unittest.main()
