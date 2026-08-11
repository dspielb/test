#!/usr/bin/env python3
"""Beispieldaten für einen Durchlauf ohne Netzzugang.

    python3 tools/demo_studien.py /tmp/demo
    python3 -m studywatch --seite /tmp/demo/journal-watch.html \\
        --offline-dir /tmp/demo --state /tmp/demo/gesehen.json \\
        --keine-zusammenfassung --kein-entwurf --out /tmp/vorschau

Die Inhalte sind frei erfunden. Sie zeigen das Layout und prüfen die
Verarbeitungskette, ohne echte Verlagsseiten anzufassen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

# Das Paket liegt eine Ebene über diesem Skript.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studywatch.enrich import CROSSREF, EUTILS  # noqa: E402
from studywatch.http import dateiname_fuer  # noqa: E402

STUDIEN = [
    {
        "doi": "10.1000/demo.2026.0001",
        "pmid": "40000001",
        "titel": (
            "Restrictive versus liberal oxygen targets in mechanically ventilated adults: "
            "the DEMO-OX randomised clinical trial"
        ),
        "journal": "N Engl J Med",
        "iso": "N Engl J Med",
        "jahr": 2026,
        "monat": 8,
        "tag": 4,
        "autoren": [("Fictional", "AB"), ("Beispiel", "CD"), ("Muster", "EF")],
        "abstract": (
            "Background: The optimal oxygenation target for adults receiving invasive "
            "mechanical ventilation is uncertain.\n\n"
            "Methods: In this multicentre, parallel-group randomised trial, we assigned 2 140 "
            "adults within 12 hours of intubation to a restrictive target (PaO2 8-10 kPa) or a "
            "liberal target (PaO2 12-14 kPa). The primary outcome was 90-day all-cause "
            "mortality.\n\n"
            "Results: At 90 days, 312 of 1 068 patients (29.2%) in the restrictive group and 341 "
            "of 1 072 (31.8%) in the liberal group had died (absolute difference -2.6 percentage "
            "points, 95% CI -6.5 to 1.3; p=0.19). Ventilator-free days did not differ.\n\n"
            "Conclusions: Among mechanically ventilated adults, a restrictive oxygenation target "
            "did not significantly reduce 90-day mortality compared with a liberal target."
        ),
    },
    {
        "doi": "10.1000/demo.2026.0002",
        "pmid": "40000002",
        "titel": (
            "Early versus delayed renal replacement therapy in septic shock with acute kidney "
            "injury: a systematic review and meta-analysis of demonstration data"
        ),
        "journal": "Intensive Care Medicine",
        "iso": "Intensive Care Med",
        "jahr": 2026,
        "monat": 7,
        "tag": 29,
        "autoren": [("Probe", "GH"), ("Exempel", "IJ")],
        "abstract": (
            "Purpose: To compare early and delayed initiation of renal replacement therapy (RRT) "
            "in adults with septic shock and acute kidney injury.\n\n"
            "Methods: We searched three databases for randomised trials up to March 2026 and "
            "pooled 11 trials with 4 806 participants using a random-effects model.\n\n"
            "Results: Early initiation was not associated with lower 28-day mortality "
            "(risk ratio 0.98, 95% CI 0.90 to 1.06; I2 = 21%) but increased catheter-related "
            "complications (risk ratio 1.34, 95% CI 1.09 to 1.65).\n\n"
            "Conclusions: Routine early initiation of RRT is not supported; a watchful strategy "
            "avoids catheter-related harm without a mortality penalty."
        ),
    },
    {
        "doi": "10.1000/demo.2026.0003",
        "pmid": "40000003",
        "titel": (
            "Balanced crystalloids and post-cardiac-arrest neurological outcome: a demonstration "
            "cohort study of 3 400 admissions"
        ),
        "journal": "Critical Care",
        "iso": "Crit Care",
        "jahr": 2026,
        "monat": 8,
        "tag": 1,
        "autoren": [("Testfall", "KL")],
        "abstract": (
            "Background: Fluid choice after cardiac arrest is debated.\n\n"
            "Methods: Retrospective cohort of 3 400 adults admitted after out-of-hospital cardiac "
            "arrest across 24 fictional centres between 2020 and 2025.\n\n"
            "Results: Favourable neurological outcome at discharge occurred in 24.1% with "
            "balanced crystalloids and 22.7% with saline (adjusted odds ratio 1.06, 95% CI 0.89 "
            "to 1.27).\n\n"
            "Conclusions: In this observational dataset, fluid choice was not associated with "
            "neurological outcome; residual confounding cannot be excluded."
        ),
    },
]


def seite() -> str:
    """Eine Übersichtsseite in dem Stil, den Journal-Watch-Seiten üblicherweise haben."""
    bloecke = []
    for eintrag in STUDIEN:
        bloecke.append(
            "<article>"
            f'<h3><a href="https://doi.org/{eintrag["doi"]}">{eintrag["titel"]}</a></h3>'
            f'<p class="meta">{eintrag["journal"]}, '
            f'{eintrag["tag"]:02d}.{eintrag["monat"]:02d}.{eintrag["jahr"]} · '
            f'<a href="https://pubmed.ncbi.nlm.nih.gov/{eintrag["pmid"]}/">PubMed</a></p>'
            "</article>"
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Journal Watch (Demo)</title></head>
<body>
<nav><a href="/">Home</a> <a href="/about">About</a> <a href="/newsletters">Newsletter</a></nav>
<main>
<h1>Journal Watch</h1>
{"".join(bloecke)}
</main>
<footer><a href="https://twitter.com/example">Twitter</a></footer>
</body></html>
"""


def crossref(eintrag: dict) -> dict:
    return {
        "message": {
            "title": [eintrag["titel"]],
            "container-title": [eintrag["journal"]],
            "issued": {"date-parts": [[eintrag["jahr"], eintrag["monat"], eintrag["tag"]]]},
            "author": [
                {"given": vorname, "family": nachname}
                for nachname, vorname in eintrag["autoren"]
            ],
        }
    }


def pubmed_xml(eintrag: dict) -> str:
    autoren = "".join(
        f"<Author><LastName>{nachname}</LastName><Initials>{initialen}</Initials></Author>"
        for nachname, initialen in eintrag["autoren"]
    )
    abschnitte = "".join(
        f'<AbstractText Label="{teil.split(":", 1)[0]}">'
        f'{teil.split(":", 1)[1].strip()}</AbstractText>'
        for teil in eintrag["abstract"].split("\n\n")
    )
    return f"""<?xml version="1.0"?>
<PubmedArticleSet><PubmedArticle><MedlineCitation>
<PMID>{eintrag["pmid"]}</PMID>
<Article>
<Journal><ISOAbbreviation>{eintrag["iso"]}</ISOAbbreviation>
<JournalIssue><PubDate><Year>{eintrag["jahr"]}</Year>
<Month>{eintrag["monat"]}</Month><Day>{eintrag["tag"]}</Day></PubDate></JournalIssue></Journal>
<ArticleTitle>{eintrag["titel"]}</ArticleTitle>
<Abstract>{abschnitte}</Abstract>
<AuthorList>{autoren}</AuthorList>
</Article></MedlineCitation></PubmedArticle></PubmedArticleSet>
"""


def schreibe(ziel: Path) -> None:
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "journal-watch.html").write_text(seite(), encoding="utf-8")

    for eintrag in STUDIEN:
        crossref_url = CROSSREF + quote(eintrag["doi"], safe="")
        (ziel / dateiname_fuer(crossref_url)).write_text(
            json.dumps(crossref(eintrag), ensure_ascii=False), encoding="utf-8"
        )

        efetch = f"{EUTILS}efetch.fcgi?" + urlencode(
            {"db": "pubmed", "retmode": "xml", "id": eintrag["pmid"]}
        )
        (ziel / dateiname_fuer(efetch)).write_text(pubmed_xml(eintrag), encoding="utf-8")

    print(f"Beispieldaten in {ziel} geschrieben ({len(STUDIEN)} Studien).")


if __name__ == "__main__":
    schreibe(Path(sys.argv[1] if len(sys.argv) > 1 else "demo-studien"))
