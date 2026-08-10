import json
import logging
import unittest
from datetime import date

from studywatch import config as config_modul
from studywatch import enrich
from studywatch.http import AbrufFehler, Netz
from studywatch.study import Studie


def setUpModule():
    logging.getLogger("studywatch.enrich").setLevel(logging.CRITICAL)


CROSSREF_ANTWORT = {
    "message": {
        "title": ["Restrictive versus liberal oxygen targets in ventilated adults"],
        "container-title": ["The New England Journal of Medicine"],
        "issued": {"date-parts": [[2026, 8, 4]]},
        "author": [
            {"given": "Ada", "family": "Beispiel"},
            {"given": "Ben", "family": "Muster"},
        ],
        "abstract": "<jats:p>Abstract Kurzfassung aus Crossref.</jats:p>",
    }
}

PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation>
<PMID>40000001</PMID>
<Article>
<Journal><ISOAbbreviation>N Engl J Med</ISOAbbreviation><Title>New England Journal</Title>
<JournalIssue><PubDate><Year>2026</Year><Month>Aug</Month></PubDate></JournalIssue></Journal>
<ArticleTitle>Restrictive versus liberal oxygen targets in <i>ventilated</i> adults</ArticleTitle>
<ArticleDate><Year>2026</Year><Month>08</Month><Day>04</Day></ArticleDate>
<Abstract>
<AbstractText Label="BACKGROUND">Die optimale Zielsättigung ist unklar.</AbstractText>
<AbstractText Label="CONCLUSIONS">Kein Unterschied in der 90-Tage-Sterblichkeit.</AbstractText>
</Abstract>
<AuthorList><Author><LastName>Beispiel</LastName><Initials>A</Initials></Author></AuthorList>
</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>
"""

SUCH_ANTWORT = {"esearchresult": {"idlist": ["40000001"]}}


class FakeNetz(Netz):
    """Beantwortet Anfragen aus einer Tabelle statt aus dem Netz."""

    def __init__(self, antworten: dict[str, bytes], **kwargs):
        super().__init__(**kwargs)
        self.antworten = antworten
        self.aufrufe: list[str] = []

    def hole(self, url: str, *, accept: str = "*/*") -> bytes:
        self.aufrufe.append(url)
        for marker, rumpf in self.antworten.items():
            if marker in url:
                return rumpf
        raise AbrufFehler(f"HTTP 404 für {url}")


def netz_mit(**teile) -> FakeNetz:
    tabelle = {}
    if "crossref" in teile:
        tabelle["api.crossref.org"] = json.dumps(teile["crossref"]).encode()
    if "esearch" in teile:
        tabelle["esearch.fcgi"] = json.dumps(teile["esearch"]).encode()
    if "efetch" in teile:
        tabelle["efetch.fcgi"] = teile["efetch"].encode()
    return FakeNetz(tabelle)


def config(**anreicherung):
    return config_modul.from_dict({
        "quelle": {"name": "JW", "url": "https://example.invalid/jw"},
        "anreicherung": {"parallel": 1, **anreicherung},
    })


class Crossref(unittest.TestCase):
    def test_metadata_is_taken_over(self):
        studie = Studie(titel="Kurz", link="https://doi.org/10.1/a", doi="10.1/a")
        enrich.anreichern([studie], config(pubmed=False), netz_mit(crossref=CROSSREF_ANTWORT))

        self.assertEqual(studie.journal, "The New England Journal of Medicine")
        self.assertEqual(studie.veroeffentlicht, date(2026, 8, 4))
        self.assertEqual(studie.autoren, ("Ada Beispiel", "Ben Muster"))
        self.assertIn("Crossref", studie.herkunft)

    def test_longer_title_replaces_the_scraped_one(self):
        studie = Studie(titel="Kurz", link="l", doi="10.1/a")
        enrich.anreichern([studie], config(pubmed=False), netz_mit(crossref=CROSSREF_ANTWORT))
        self.assertTrue(studie.titel.startswith("Restrictive versus liberal"))

    def test_jats_markup_is_stripped_from_abstract(self):
        studie = Studie(titel="Kurz", link="l", doi="10.1/a")
        enrich.anreichern([studie], config(pubmed=False), netz_mit(crossref=CROSSREF_ANTWORT))
        self.assertEqual(studie.abstract, "Kurzfassung aus Crossref.")

    def test_failure_leaves_the_study_usable(self):
        studie = Studie(titel="Kurz", link="l", doi="10.1/a")
        enrich.anreichern([studie], config(pubmed=False), netz_mit())
        self.assertEqual(studie.titel, "Kurz")
        self.assertIsNone(studie.abstract)

    def test_without_doi_crossref_is_not_called(self):
        studie = Studie(titel="Kurz", link="l")
        netz = netz_mit(crossref=CROSSREF_ANTWORT)
        enrich.anreichern([studie], config(pubmed=False), netz)
        self.assertEqual(netz.aufrufe, [])


class PubMed(unittest.TestCase):
    def test_structured_abstract_is_assembled(self):
        studie = Studie(titel="Kurz", link="l", pmid="40000001")
        enrich.anreichern([studie], config(crossref=False), netz_mit(efetch=PUBMED_XML))

        self.assertIn("Background: Die optimale", studie.abstract)
        self.assertIn("Conclusions: Kein Unterschied", studie.abstract)
        self.assertEqual(studie.journal, "N Engl J Med")
        self.assertEqual(studie.autoren, ("Beispiel A",))
        self.assertIn("PubMed", studie.herkunft)

    def test_article_date_is_preferred_over_pubdate(self):
        studie = Studie(titel="Kurz", link="l", pmid="40000001")
        enrich.anreichern([studie], config(crossref=False), netz_mit(efetch=PUBMED_XML))
        self.assertEqual(studie.veroeffentlicht, date(2026, 8, 4))

    def test_nested_markup_in_title_is_flattened(self):
        studie = Studie(titel="Kurz", link="l", pmid="40000001")
        enrich.anreichern([studie], config(crossref=False), netz_mit(efetch=PUBMED_XML))
        self.assertEqual(
            studie.titel, "Restrictive versus liberal oxygen targets in ventilated adults"
        )

    def test_pmid_is_looked_up_by_doi(self):
        studie = Studie(titel="Kurz", link="l", doi="10.1/a")
        netz = netz_mit(esearch=SUCH_ANTWORT, efetch=PUBMED_XML)
        enrich.anreichern([studie], config(crossref=False), netz)

        self.assertEqual(studie.pmid, "40000001")
        self.assertTrue(any("10.1%2Fa%5BAID%5D" in u for u in netz.aufrufe))

    def test_pubmed_abstract_wins_over_crossref(self):
        studie = Studie(titel="Kurz", link="l", doi="10.1/a", pmid="40000001")
        netz = netz_mit(crossref=CROSSREF_ANTWORT, efetch=PUBMED_XML)
        enrich.anreichern([studie], config(), netz)
        self.assertIn("Conclusions:", studie.abstract)

    def test_broken_xml_is_survived(self):
        studie = Studie(titel="Kurz", link="l", pmid="40000001")
        enrich.anreichern([studie], config(crossref=False), netz_mit(efetch="<kein"))
        self.assertIsNone(studie.abstract)

    def test_short_title_without_doi_is_not_searched(self):
        studie = Studie(titel="Kurz", link="l")
        netz = netz_mit(esearch=SUCH_ANTWORT)
        enrich.anreichern([studie], config(crossref=False), netz)
        self.assertEqual(netz.aufrufe, [])


class Abschaltung(unittest.TestCase):
    def test_both_services_off_means_no_requests(self):
        studie = Studie(titel="Kurz", link="l", doi="10.1/a", pmid="1")
        netz = netz_mit(crossref=CROSSREF_ANTWORT, efetch=PUBMED_XML)
        enrich.anreichern([studie], config(crossref=False, pubmed=False), netz)
        self.assertEqual(netz.aufrufe, [])


if __name__ == "__main__":
    unittest.main()
