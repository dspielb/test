import re
import unittest
from datetime import date, datetime, timedelta, timezone

from newsdigest import config as config_module
from newsdigest import digest as digest_module
from newsdigest.fetch import FetchResult
from newsdigest.parse import Article
from newsdigest.render import render_archive_index, render_digest

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)

CONFIG = config_module.from_dict({
    "categories": {"deutschland": "Deutschland & Welt", "tech": "Tech & IT"},
    "feed": [
        {"id": "a", "name": "Quelle A", "url": "https://a.de/rss", "category": "deutschland"},
        {"id": "b", "name": "Quelle B", "url": "https://b.de/rss", "category": "deutschland"},
        {"id": "t", "name": "Tech-Quelle", "url": "https://t.de/rss", "category": "tech"},
    ],
})
FEEDS = {f.id: f for f in CONFIG.feeds}


def article(title, *, source="a", name="Quelle A", ago_hours=1, summary="", link=None,
            category="deutschland"):
    return Article(
        title=title,
        link=link or f"https://{source}.de/{abs(hash(title)) % 10**6}",
        summary=summary,
        published=NOW - timedelta(hours=ago_hours),
        source_id=source,
        source_name=name,
        category=category,
    )


def render(results):
    built = digest_module.build(results, CONFIG, now=NOW)
    return render_digest(built, timezone="Europe/Berlin")


def result(feed_id, articles, error=None):
    return FetchResult(feed=FEEDS[feed_id], articles=articles, error=error)


class Structure(unittest.TestCase):
    def setUp(self):
        self.html = render([
            result("a", [article("Erste Meldung des Tages", summary="Eine Zusammenfassung.")]),
            result("t", [article("Technik-Meldung", source="t", name="Tech-Quelle",
                                 category="tech")]),
        ])

    def test_is_a_complete_html_document(self):
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))
        self.assertTrue(self.html.rstrip().endswith("</html>"))
        self.assertIn('<html lang="de">', self.html)
        self.assertIn('<meta charset="utf-8">', self.html)
        self.assertIn("viewport", self.html)

    def test_css_is_inlined_so_the_file_stands_alone(self):
        self.assertIn("<style>", self.html)
        self.assertIn("--accent", self.html)
        self.assertNotIn("<link rel=\"stylesheet\"", self.html)

    def test_supports_dark_mode(self):
        self.assertIn("prefers-color-scheme: dark", self.html)

    def test_contains_titles_links_and_summaries(self):
        self.assertIn("Erste Meldung des Tages", self.html)
        self.assertIn("Eine Zusammenfassung.", self.html)
        self.assertIn("Quelle A", self.html)

    def test_sections_carry_anchors_for_the_navigation(self):
        self.assertIn('<section id="deutschland">', self.html)
        self.assertIn('href="#deutschland"', self.html)

    def test_empty_categories_are_skipped(self):
        html = render([result("a", [article("Nur Politik")])])
        self.assertNotIn('<section id="tech">', html)


class Escaping(unittest.TestCase):
    def test_special_characters_in_titles_are_escaped(self):
        html = render([result("a", [article('Firma "X" & Co. <Insolvenz>')])])
        self.assertIn("&amp;", html)
        self.assertNotIn("<Insolvenz>", html)

    def test_script_in_a_title_cannot_break_out(self):
        html = render([result("a", [article("<script>alert(1)</script> Meldung")])])
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_quotes_in_links_are_escaped(self):
        html = render([result("a", [article("Titel", link='https://a.de/x?q="böse"')])])
        self.assertNotIn('href="https://a.de/x?q="böse""', html)

    def test_umlauts_survive_intact(self):
        html = render([result("a", [article("Über Größe und Straßen")])])
        self.assertIn("Über Größe und Straßen", html)


class TopStorySection(unittest.TestCase):
    def test_shown_when_several_sources_report_the_same_topic(self):
        html = render([
            result("a", [article("Bundestag beschließt Klimapaket", ago_hours=3)]),
            result("b", [article("Bundestag beschließt Klimapaket mit Mehrheit",
                                 source="b", name="Quelle B", ago_hours=1)]),
        ])
        self.assertIn("Top-Themen", html)
        self.assertIn("2 Quellen", html)
        self.assertIn("auch bei", html)

    def test_hidden_when_every_topic_has_a_single_source(self):
        html = render([result("a", [article("Ein einzelnes Thema")])])
        # Nicht auf den Text prüfen - "Top-Themen" steht auch als CSS-Kommentar im Dokument.
        self.assertNotIn('<section class="top"', html)


class Metadata(unittest.TestCase):
    def test_header_shows_german_date_and_time(self):
        html = render([result("a", [article("Meldung")])])
        self.assertIn("Dienstag, 28. Juli 2026", html)
        self.assertIn("Stand 14:00 Uhr", html)  # 12:00 UTC = 14:00 in Berlin (Sommerzeit)

    def test_article_times_are_shown_in_local_time(self):
        html = render([result("a", [article("Meldung", ago_hours=2)])])
        self.assertIn("12:00 Uhr", html)
        self.assertIn('<time datetime="2026-07-28T12:00:00+02:00">', html)

    def test_source_status_lists_failures_with_reason(self):
        html = render([
            result("a", [article("Meldung")]),
            result("b", [], error="HTTP 503"),
        ])
        self.assertIn("Quellen-Status", html)
        self.assertIn("HTTP 503", html)
        self.assertIn('class="failed"', html)

    def test_notice_when_nothing_was_found(self):
        html = render([result("a", [], error="HTTP 500")])
        self.assertIn("Keine Meldungen", html)

    def test_links_to_the_archive(self):
        html = render([result("a", [article("Meldung")])])
        self.assertIn('href="archiv/index.html"', html)

    def test_singular_is_used_for_a_single_item(self):
        html = render([result("a", [article("Genau eine Meldung")])])
        self.assertIn("1 Meldung aus 1 Quelle ·", html)
        self.assertNotIn("1 Meldungen", html)
        self.assertNotIn("1 Quellen", html)

    def test_plural_is_used_for_several_items(self):
        html = render([
            result("a", [article("Erstes Thema hier")]),
            result("b", [article("Zweites Thema dort", source="b", name="Quelle B")]),
        ])
        self.assertIn("2 Meldungen aus 2 Quellen", html)


class ArchiveIndex(unittest.TestCase):
    def test_lists_days_newest_first(self):
        html = render_archive_index([date(2026, 7, 26), date(2026, 7, 28), date(2026, 7, 27)])
        order = re.findall(r'href="(2026-07-\d\d)\.html"', html)
        self.assertEqual(order, ["2026-07-28", "2026-07-27", "2026-07-26"])

    def test_shows_german_dates_and_weekdays(self):
        html = render_archive_index([date(2026, 7, 28)])
        self.assertIn("28. Juli 2026", html)
        self.assertIn("Dienstag", html)

    def test_links_back_to_the_current_edition(self):
        self.assertIn('href="../index.html"', render_archive_index([date(2026, 7, 28)]))

    def test_empty_archive_is_valid_html(self):
        html = render_archive_index([])
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("0 Ausgaben", html)

    def test_singular_for_one_edition(self):
        self.assertIn("1 Ausgabe", render_archive_index([date(2026, 7, 28)]))


class WellFormed(unittest.TestCase):
    def test_output_parses_as_xhtml_like_markup(self):
        """Grobe Struktur prüfen: alle geöffneten Abschnitte werden geschlossen."""
        html = render([
            result("a", [article("Meldung eins", summary="Text")]),
            result("t", [article("Meldung zwei", source="t", name="Tech-Quelle",
                                 category="tech")]),
        ])
        for tag in ("section", "ol", "li", "h3", "footer", "main"):
            self.assertEqual(
                len(re.findall(rf"<{tag}[ >]", html)),
                len(re.findall(rf"</{tag}>", html)),
                f"<{tag}> ist nicht ausgeglichen",
            )


if __name__ == "__main__":
    unittest.main()
