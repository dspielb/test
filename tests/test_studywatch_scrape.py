import unittest

from studywatch import config as config_modul
from studywatch import scrape

BASIS = "https://criticalcarereviews.invalid/latest-evidence/journal-watch"

SEITE = """<!DOCTYPE html>
<html><head>
<link rel="alternate" type="application/rss+xml" href="/feed.xml">
</head><body>
<nav><a href="/">Home</a> <a href="https://twitter.com/x">Twitter</a>
<a href="/newsletters/current">Newsletter abonnieren</a></nav>
<main>
  <article>
    <h3><a href="https://doi.org/10.1056/NEJMoa2400001">Restrictive versus liberal oxygen
    targets in mechanically ventilated adults</a></h3>
    <p>N Engl J Med, 4 August 2026 &middot;
       <a href="https://pubmed.ncbi.nlm.nih.gov/40000001/">PubMed</a></p>
  </article>
  <article>
    <p>Early versus delayed renal replacement therapy in septic shock: a meta-analysis</p>
    <p><a href="https://link.springer.com/article/10.1007/s00134-026-00002-1">full text</a></p>
  </article>
  <article>
    <h3><a href="https://doi.org/10.1056/NEJMoa2400001">Restrictive versus liberal oxygen
    targets in mechanically ventilated adults</a></h3>
    <p>Doppelter Eintrag weiter unten auf der Seite.</p>
  </article>
  <p><a href="/about">Kurz</a></p>
</main>
<script>var a = '<a href="https://doi.org/10.1/fake">Skript</a>';</script>
</body></html>
"""


def config(**einstellungen):
    return config_modul.from_dict({
        "quelle": {"name": "Journal Watch", "url": BASIS},
        "einstellungen": einstellungen,
    })


class Extraktion(unittest.TestCase):
    def setUp(self):
        self.studien = scrape.extrahiere(SEITE, basis_url=BASIS, cfg=config())

    def test_only_publisher_links_become_studies(self):
        self.assertEqual(len(self.studien), 2)
        for studie in self.studien:
            self.assertNotIn("twitter", studie.link)

    def test_title_comes_from_link_text(self):
        self.assertTrue(self.studien[0].titel.startswith("Restrictive versus liberal oxygen"))
        # Der Zeilenumbruch im Quelltext darf nicht im Titel landen.
        self.assertNotIn("\n", self.studien[0].titel)

    def test_doi_and_pmid_are_merged_into_one_study(self):
        erste = self.studien[0]
        self.assertEqual(erste.doi, "10.1056/NEJMoa2400001")
        self.assertEqual(erste.pmid, "40000001")

    def test_label_link_takes_title_from_preceding_text(self):
        zweite = self.studien[1]
        self.assertTrue(zweite.titel.startswith("Early versus delayed renal replacement"))
        self.assertEqual(zweite.doi, "10.1007/s00134-026-00002-1")

    def test_repeated_entry_is_not_duplicated(self):
        titel = [s.titel for s in self.studien]
        self.assertEqual(len(titel), len(set(titel)))

    def test_script_content_is_ignored(self):
        self.assertNotIn("10.1/fake", [s.doi for s in self.studien])

    def test_source_is_noted(self):
        self.assertEqual(self.studien[0].herkunft, ["Journal Watch"])


class Grenzfaelle(unittest.TestCase):
    def test_page_without_studies_yields_nothing(self):
        html = '<html><body><a href="/impressum">Impressum</a></body></html>'
        self.assertEqual(scrape.extrahiere(html, basis_url=BASIS, cfg=config()), [])

    def test_relative_links_are_resolved(self):
        html = (
            '<html><body><a href="//doi.org/10.1000/relativ">'
            "A sufficiently long study title for the heuristic</a></body></html>"
        )
        studien = scrape.extrahiere(html, basis_url=BASIS, cfg=config())
        self.assertEqual(studien[0].link, "https://doi.org/10.1000/relativ")

    def test_publisher_hosts_are_configurable(self):
        html = (
            '<html><body><a href="https://hausblatt.invalid/artikel/1">'
            "A sufficiently long study title for the heuristic</a></body></html>"
        )
        self.assertEqual(scrape.extrahiere(html, basis_url=BASIS, cfg=config()), [])
        eigene = config(verlags_hosts=["hausblatt.invalid"])
        self.assertEqual(len(scrape.extrahiere(html, basis_url=BASIS, cfg=eigene)), 1)

    def test_subdomains_of_publishers_count(self):
        html = (
            '<html><body><a href="https://www.nature.com/articles/s41586-026-1">'
            "A sufficiently long study title for the heuristic</a></body></html>"
        )
        self.assertEqual(len(scrape.extrahiere(html, basis_url=BASIS, cfg=config())), 1)

    def test_short_link_text_without_context_is_skipped(self):
        html = '<html><body><a href="https://doi.org/10.1000/x">PDF</a></body></html>'
        self.assertEqual(scrape.extrahiere(html, basis_url=BASIS, cfg=config()), [])

    def test_trailing_punctuation_is_stripped_from_doi(self):
        html = (
            '<html><body><p><a href="https://doi.org/10.1000/abc.">'
            "A sufficiently long study title for the heuristic</a></p></body></html>"
        )
        studien = scrape.extrahiere(html, basis_url=BASIS, cfg=config())
        self.assertEqual(studien[0].doi, "10.1000/abc")


class FeedSuche(unittest.TestCase):
    def test_feed_link_is_found_and_resolved(self):
        self.assertEqual(
            scrape.finde_feed(SEITE, BASIS), "https://criticalcarereviews.invalid/feed.xml"
        )

    def test_missing_feed_returns_none(self):
        self.assertIsNone(scrape.finde_feed("<html><body>Nichts</body></html>", BASIS))


if __name__ == "__main__":
    unittest.main()
