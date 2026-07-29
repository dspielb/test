import unittest
from datetime import datetime, timedelta, timezone

from newsdigest import config as config_module
from newsdigest import digest as digest_module
from newsdigest.fetch import FetchResult
from newsdigest.parse import Article

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)

CONFIG = config_module.from_dict(
    {
        "settings": {"window_hours": 24, "max_per_source": 3, "max_per_category": 10},
        "categories": {"deutschland": "Deutschland & Welt", "tech": "Tech & IT"},
        "feed": [
            {"id": "a", "name": "Quelle A", "url": "https://a.de/rss", "category": "deutschland"},
            {"id": "b", "name": "Quelle B", "url": "https://b.de/rss", "category": "deutschland"},
            {"id": "c", "name": "Quelle C", "url": "https://c.de/rss", "category": "deutschland"},
            {"id": "t", "name": "Tech-Quelle", "url": "https://t.de/rss", "category": "tech"},
            {"id": "t2", "name": "Tech-Zwei", "url": "https://t2.de/rss", "category": "tech"},
        ],
    }
)

FEEDS = {feed.id: feed for feed in CONFIG.feeds}


def article(title, *, source="a", name="Quelle A", ago_hours=1, link=None, category="deutschland"):
    return Article(
        title=title,
        link=link or f"https://{source}.de/{abs(hash(title)) % 10**6}",
        summary="",
        published=NOW - timedelta(hours=ago_hours),
        source_id=source,
        source_name=name,
        category=category,
    )


def result(feed_id, articles, error=None):
    return FetchResult(feed=FEEDS[feed_id], articles=articles, error=error)


def build(results):
    return digest_module.build(results, CONFIG, now=NOW)


class Keywords(unittest.TestCase):
    def test_drops_stopwords_and_short_words(self):
        self.assertEqual(
            digest_module.keywords("Die Regierung hat ein neues Gesetz"),
            frozenset({"regierung", "gesetz"}),
        )

    def test_folds_umlauts_so_variants_match(self):
        self.assertEqual(
            digest_module.keywords("Türkei"), digest_module.keywords("Tuerkei")
        )

    def test_case_insensitive(self):
        self.assertEqual(digest_module.keywords("KLIMAPAKET"), frozenset({"klimapaket"}))


class Similarity(unittest.TestCase):
    def test_identical_sets(self):
        tokens = frozenset({"a", "b"})
        self.assertEqual(digest_module.similarity(tokens, tokens), 1.0)

    def test_disjoint_sets(self):
        self.assertEqual(
            digest_module.similarity(frozenset({"a"}), frozenset({"b"})), 0.0
        )

    def test_empty_set_is_never_similar(self):
        self.assertEqual(digest_module.similarity(frozenset(), frozenset({"a"})), 0.0)


class Clustering(unittest.TestCase):
    def test_same_link_is_merged_even_with_different_titles(self):
        stories = digest_module.cluster(
            [
                article("Schlagzeile eins", link="https://a.de/x?utm_source=rss"),
                article("Völlig andere Formulierung", source="b", name="Quelle B",
                        link="https://a.de/x#kommentare"),
            ]
        )
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0].source_count, 2)

    def test_similar_headlines_from_different_sources_are_merged(self):
        stories = digest_module.cluster(
            [
                article("Bundestag beschließt neues Klimapaket", ago_hours=2),
                article(
                    "Bundestag beschließt Klimapaket mit breiter Mehrheit",
                    source="b",
                    name="Quelle B",
                    ago_hours=1,
                ),
            ]
        )
        self.assertEqual(len(stories), 1)
        self.assertEqual(stories[0].sources, ["Quelle B", "Quelle A"])

    def test_newest_article_becomes_the_headline(self):
        stories = digest_module.cluster(
            [
                article("Zentralbank erhöht Leitzins deutlich", ago_hours=5),
                article(
                    "Zentralbank erhöht Leitzins erneut deutlich",
                    source="b",
                    name="Quelle B",
                    ago_hours=1,
                ),
            ]
        )
        self.assertEqual(stories[0].article.source_name, "Quelle B")
        self.assertEqual(len(stories[0].duplicates), 1)

    def test_unrelated_headlines_stay_separate(self):
        stories = digest_module.cluster(
            [
                article("Bundestag beschließt Klimapaket"),
                article("Fußball: Bayern gewinnt Pokalfinale", source="b", name="Quelle B"),
            ]
        )
        self.assertEqual(len(stories), 2)

    def test_short_headlines_are_not_clustered_by_accident(self):
        stories = digest_module.cluster(
            [article("Streik"), article("Streit", source="b", name="Quelle B")]
        )
        self.assertEqual(len(stories), 2)

    def test_same_source_twice_counts_as_one_source(self):
        stories = digest_module.cluster(
            [
                article("Zentralbank erhöht Leitzins deutlich", ago_hours=3),
                article("Zentralbank erhöht Leitzins abermals deutlich", ago_hours=1),
            ]
        )
        self.assertEqual(stories[0].source_count, 1)


class TimeWindow(unittest.TestCase):
    def test_old_articles_are_dropped(self):
        result_set = build([result("a", [
            article("Frische Meldung von heute", ago_hours=2),
            article("Uralte Meldung von vorgestern", ago_hours=48),
        ])])
        titles = [s.article.title for s in result_set.sections[0].stories]
        self.assertEqual(titles, ["Frische Meldung von heute"])

    def test_article_exactly_at_the_edge_is_kept(self):
        result_set = build([result("a", [article("Genau an der Grenze", ago_hours=24)])])
        self.assertEqual(len(result_set.sections[0].stories), 1)

    def test_articles_without_date_are_kept(self):
        undated = Article("Ohne Datum", "https://a.de/1", "", None, "a", "Quelle A", "deutschland")
        result_set = build([result("a", [undated])])
        self.assertEqual(len(result_set.sections[0].stories), 1)


#: Bewusst themenfremde Schlagzeilen - so prüfen die Limit-Tests wirklich die
#: Obergrenze und nicht versehentlich das Zusammenfassen ähnlicher Meldungen.
DISTINCT = [
    "Hochwasser bedroht Dörfer entlang der Elbe",
    "Rentenpaket passiert überraschend den Bundesrat",
    "Impfstoff gegen Grippe wird knapp",
    "Windräder liefern Rekordmenge Strom",
    "Schulreform stößt bei Lehrkräften auf Kritik",
    "Zugausfälle legen Fernverkehr lahm",
    "Ernte fällt wegen Dürre schwach aus",
]


class Limits(unittest.TestCase):
    def test_max_per_source_keeps_the_newest(self):
        articles = [
            article(title, ago_hours=index) for index, title in enumerate(DISTINCT, start=1)
        ]
        result_set = build([result("a", articles)])
        titles = [s.article.title for s in result_set.sections[0].stories]
        self.assertEqual(len(titles), 3)
        self.assertIn(DISTINCT[0], titles)
        self.assertNotIn(DISTINCT[6], titles)

    def test_limit_applies_per_source_not_per_category(self):
        result_set = build([
            result("a", [article(t, ago_hours=i) for i, t in enumerate(DISTINCT[:5], start=1)]),
            result("b", [article(f"Quelle B meldet: {t}", source="b", name="Quelle B",
                                 ago_hours=i) for i, t in enumerate(DISTINCT[:5], start=1)]),
        ])
        # 3 pro Quelle, und die Themen der beiden Quellen überschneiden sich hier.
        section = result_set.sections[0]
        self.assertEqual(sum(len(s.duplicates) + 1 for s in section.stories), 6)


class Sections(unittest.TestCase):
    def test_categories_follow_config_order(self):
        result_set = build([result("t", [article("Tech-Meldung", source="t", name="Tech-Quelle",
                                                 category="tech")])])
        self.assertEqual([s.key for s in result_set.sections], ["deutschland", "tech"])

    def test_articles_land_in_their_category(self):
        result_set = build([
            result("a", [article("Politik heute")]),
            result("t", [article("Technik heute", source="t", name="Tech-Quelle", category="tech")]),
        ])
        by_key = {s.key: s for s in result_set.sections}
        self.assertEqual(len(by_key["deutschland"].stories), 1)
        self.assertEqual(len(by_key["tech"].stories), 1)


class TopStories(unittest.TestCase):
    def test_multi_source_topics_are_promoted(self):
        result_set = build([
            result("a", [
                article("Bundestag beschließt neues Klimapaket", ago_hours=3),
                article("Einzelmeldung ohne Entsprechung anderswo", ago_hours=2),
            ]),
            result("b", [article("Bundestag beschließt Klimapaket mit Mehrheit",
                                 source="b", name="Quelle B", ago_hours=1)]),
        ])
        self.assertEqual(len(result_set.top_stories), 1)
        self.assertEqual(result_set.top_stories[0].source_count, 2)

    def test_single_source_topics_are_not_top_stories(self):
        result_set = build([result("a", [article("Nur eine Quelle berichtet darüber")])])
        self.assertEqual(result_set.top_stories, [])

    def test_same_topic_in_two_categories_appears_only_once(self):
        """Agenturticker und Ressortmeldung sind dasselbe Thema."""
        result_set = build([
            # Kategorie "deutschland": zwei Quellen zum Pflegethema
            result("a", [article("Bundestag beschließt Reform der Pflegeversicherung",
                                 ago_hours=3)]),
            result("b", [article("Bundestag beschließt Reform der Pflegeversicherung "
                                 "mit Mehrheit", source="b", name="Quelle B", ago_hours=2)]),
            # Kategorie "tech": dasselbe Thema, dort eigenständig geclustert
            result("t", [article("Bundestag beschließt Reform der Pflegeversicherung heute",
                                 source="t", name="Tech-Quelle", category="tech", ago_hours=4)]),
            result("t2", [article("Bundestag beschließt Reform der Pflegeversicherung endlich",
                                  source="t2", name="Tech-Zwei", category="tech", ago_hours=1)]),
        ])
        titles = [s.article.title for s in result_set.top_stories]
        self.assertEqual(len(titles), 1, titles)

    def test_the_version_with_the_widest_coverage_wins(self):
        headline = "Zentralbank erhöht Leitzins deutlich"
        result_set = build([
            result("a", [article(headline, ago_hours=3)]),
            result("b", [article(f"{headline} an", source="b", name="Quelle B", ago_hours=2)]),
            result("c", [article(f"{headline} erneut", source="c", name="Quelle C",
                                 ago_hours=1)]),
            result("t", [article(f"{headline} heute", source="t", name="Tech-Quelle",
                                 category="tech", ago_hours=5)]),
            result("t2", [article(f"{headline} weiter", source="t2", name="Tech-Zwei",
                                  category="tech", ago_hours=4)]),
        ])
        self.assertEqual(len(result_set.top_stories), 1)
        # "deutschland" hat drei Quellen, "tech" nur zwei.
        self.assertEqual(result_set.top_stories[0].source_count, 3)

    def test_distinct_topics_across_categories_are_all_kept(self):
        result_set = build([
            result("a", [article("Hochwasser bedroht Dörfer an der Elbe", ago_hours=3)]),
            result("b", [article("Hochwasser erreicht Dörfer entlang der Elbe", source="b",
                                 name="Quelle B", ago_hours=2)]),
            result("t", [article("Kritische Sicherheitslücke in Server-Software entdeckt",
                                 source="t", name="Tech-Quelle", category="tech", ago_hours=5)]),
            result("t2", [article("Kritische Sicherheitslücke in Server-Software gemeldet",
                                  source="t2", name="Tech-Zwei", category="tech", ago_hours=4)]),
        ])
        self.assertEqual(len(result_set.top_stories), 2)


class SourceStatusReporting(unittest.TestCase):
    def test_failed_sources_are_recorded_with_reason(self):
        result_set = build([
            result("a", [article("Läuft")]),
            result("b", [], error="HTTP 503"),
        ])
        self.assertEqual([s.name for s in result_set.ok_sources], ["Quelle A"])
        self.assertEqual(result_set.failed_sources[0].error, "HTTP 503")

    def test_one_broken_source_does_not_hide_the_others(self):
        result_set = build([
            result("a", [article("Trotzdem da")]),
            result("b", [], error="Netzwerkfehler"),
        ])
        self.assertEqual(result_set.total_stories, 1)

    def test_all_sources_are_listed_even_when_empty(self):
        result_set = build([result("a", [], error="leer"), result("b", [], error="leer")])
        self.assertEqual(len(result_set.sources), 2)
        self.assertEqual(result_set.total_stories, 0)


if __name__ == "__main__":
    unittest.main()
