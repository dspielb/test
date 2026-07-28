import unittest
from datetime import datetime, timezone
from pathlib import Path

from newsdigest.parse import ParseError, canonical_url, parse_datetime, parse_feed, strip_html

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str, **kwargs):
    defaults = dict(source_id="test", source_name="Test", category="deutschland")
    defaults.update(kwargs)
    return parse_feed((FIXTURES / name).read_bytes(), **defaults)


class ParseRss2(unittest.TestCase):
    def setUp(self):
        self.articles = load("rss2.xml")

    def test_skips_entries_without_title_or_link(self):
        titles = [a.title for a in self.articles]
        self.assertNotIn("Eintrag ohne Link wird verworfen", titles)
        self.assertEqual(len(self.articles), 4)

    def test_reads_title_link_and_metadata(self):
        first = self.articles[0]
        self.assertEqual(first.title, "Bundestag beschließt neues Klimapaket")
        self.assertEqual(first.source_name, "Test")
        self.assertEqual(first.category, "deutschland")
        self.assertEqual(
            first.published, datetime(2026, 7, 28, 6, 30, tzinfo=timezone.utc)
        )

    def test_strips_markup_from_description(self):
        self.assertEqual(
            self.articles[0].summary,
            "Der Bundestag hat am Donnerstag mit breiter Mehrheit das neue Klimapaket beschlossen.",
        )

    def test_unescapes_entities_in_title(self):
        self.assertEqual(self.articles[1].title, "Umlaute: Über die Türkei & Grüße")

    def test_missing_date_is_none_not_an_error(self):
        without_date = next(a for a in self.articles if a.title == "Eintrag ohne Datum")
        self.assertIsNone(without_date.published)
        self.assertEqual(without_date.summary, "")

    def test_falls_back_to_guid_when_link_is_missing(self):
        from_guid = next(a for a in self.articles if a.title == "GUID als Link-Ersatz")
        self.assertEqual(from_guid.link, "https://beispiel.de/aus-guid-999.html")
        self.assertEqual(
            from_guid.published, datetime(2026, 7, 28, 4, 15, tzinfo=timezone.utc)
        )


class ParseAtom(unittest.TestCase):
    def setUp(self):
        self.articles = load("atom.xml", source_id="tech", source_name="Tech", category="tech")

    def test_prefers_alternate_link_over_related(self):
        self.assertEqual(self.articles[0].link, "https://tech.beispiel.de/sicherheitsluecke-1")

    def test_published_wins_over_updated(self):
        self.assertEqual(
            self.articles[0].published, datetime(2026, 7, 28, 5, 45, tzinfo=timezone.utc)
        )

    def test_link_without_rel_attribute(self):
        self.assertEqual(self.articles[1].link, "https://tech.beispiel.de/ohne-rel-2")

    def test_content_used_when_summary_missing(self):
        self.assertEqual(self.articles[1].summary, "Inhalt statt summary.")

    def test_id_used_as_link_when_no_link_element(self):
        self.assertEqual(self.articles[2].link, "https://tech.beispiel.de/aus-id-3")


class ParseRss1(unittest.TestCase):
    def test_reads_rdf_items(self):
        articles = load("rss1.xml")
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "Wirtschaft wächst langsamer als erwartet")
        self.assertEqual(
            articles[0].published, datetime(2026, 7, 28, 5, 0, tzinfo=timezone.utc)
        )


class BrokenInput(unittest.TestCase):
    def test_raises_on_non_xml(self):
        with self.assertRaises(ParseError):
            parse_feed(b"<html>kein feed", source_id="x", source_name="X", category="c")

    def test_empty_feed_yields_no_articles(self):
        xml = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Leer</title></channel></rss>'
        self.assertEqual(parse_feed(xml, source_id="x", source_name="X", category="c"), [])


class Dates(unittest.TestCase):
    def test_rfc822(self):
        self.assertEqual(
            parse_datetime("Tue, 28 Jul 2026 08:30:00 +0200"),
            datetime(2026, 7, 28, 6, 30, tzinfo=timezone.utc),
        )

    def test_iso_with_zulu(self):
        self.assertEqual(
            parse_datetime("2026-07-28T04:15:00Z"),
            datetime(2026, 7, 28, 4, 15, tzinfo=timezone.utc),
        )

    def test_naive_timestamp_is_treated_as_utc(self):
        self.assertEqual(
            parse_datetime("2026-07-28T04:15:00"),
            datetime(2026, 7, 28, 4, 15, tzinfo=timezone.utc),
        )

    def test_overlong_fractional_seconds(self):
        self.assertEqual(
            parse_datetime("2026-07-28T04:15:00.1234567+00:00"),
            datetime(2026, 7, 28, 4, 15, 0, 123456, tzinfo=timezone.utc),
        )

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_datetime("neulich"))
        self.assertIsNone(parse_datetime(""))


class CanonicalUrls(unittest.TestCase):
    def test_removes_tracking_parameters(self):
        self.assertEqual(
            canonical_url("https://a.de/x?utm_source=rss&utm_medium=feed&id=7"),
            "https://a.de/x?id=7",
        )

    def test_removes_fragment_and_trailing_slash_and_lowercases_host(self):
        self.assertEqual(canonical_url("https://A.de/x/#top"), "https://a.de/x")

    def test_two_variants_of_the_same_article_match(self):
        self.assertEqual(
            canonical_url("https://a.de/artikel-1.html?utm_source=feed"),
            canonical_url("https://a.de/artikel-1.html#kommentare"),
        )

    def test_distinct_articles_stay_distinct(self):
        self.assertNotEqual(canonical_url("https://a.de/eins"), canonical_url("https://a.de/zwei"))


class StripHtml(unittest.TestCase):
    def test_drops_tags_and_script_content(self):
        self.assertIn("Text", strip_html("<p>Text</p><script>böse()</script>"))
        self.assertNotIn("böse", strip_html("<p>Text</p><script>böse()</script>"))

    def test_handles_empty_and_plain_input(self):
        self.assertEqual(strip_html(""), "")
        self.assertEqual(strip_html("nur Text"), "nur Text")

    def test_truncates_long_summaries(self):
        long = "<p>" + ("Wort " * 200) + "</p>"
        articles = parse_feed(
            f'<rss version="2.0"><channel><item><title>T</title>'
            f"<link>https://a.de/1</link><description>{long}</description>"
            f"</item></channel></rss>".encode(),
            source_id="x",
            source_name="X",
            category="c",
        )
        self.assertLessEqual(len(articles[0].summary), 325)
        self.assertTrue(articles[0].summary.endswith("…"))


if __name__ == "__main__":
    unittest.main()
