"""Metadaten und Abstract über Crossref und PubMed nachladen.

Beide Dienste sind frei zugänglich und brauchen keinen Schlüssel. Fällt einer
aus, bleibt die Studie mit dem stehen, was die Übersichtsseite hergab - der
Lauf bricht deswegen nie ab.
"""

from __future__ import annotations

import html as html_modul
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import quote, urlencode
from xml.etree import ElementTree as ET

from .config import Config
from .http import AbrufFehler, Netz
from .study import Studie

log = logging.getLogger(__name__)

CROSSREF = "https://api.crossref.org/works/"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

_TAGS = re.compile(r"<[^>]+>")
_LEERRAUM = re.compile(r"\s+")

_MONATE = {
    name: nummer
    for nummer, name in enumerate(
        "jan feb mar apr may jun jul aug sep oct nov dec".split(), start=1
    )
}


class _Takt:
    """Hält einen Mindestabstand zwischen Anfragen ein (NCBI erlaubt 3/s ohne Schlüssel)."""

    def __init__(self, abstand: float) -> None:
        self.abstand = abstand
        self._sperre = threading.Lock()
        self._zuletzt = 0.0

    def warte(self) -> None:
        with self._sperre:
            rest = self.abstand - (time.monotonic() - self._zuletzt)
            if rest > 0:
                time.sleep(rest)
            self._zuletzt = time.monotonic()


def anreichern(studien: list[Studie], cfg: Config, netz: Netz) -> None:
    """Ergänzt Journal, Datum, Autoren und Abstract - so weit die Dienste mitspielen."""
    if not studien or not (cfg.anreicherung.crossref or cfg.anreicherung.pubmed):
        return

    ncbi_key = os.environ.get(cfg.anreicherung.ncbi_api_key_env, "").strip()
    takt = _Takt(0.11 if ncbi_key else 0.35)

    def eine(studie: Studie) -> None:
        try:
            if cfg.anreicherung.crossref and studie.doi:
                _crossref(studie, netz)
            if cfg.anreicherung.pubmed:
                _pubmed(studie, netz, takt=takt, api_key=ncbi_key)
        except Exception as exc:  # noqa: BLE001 - eine Studie darf den Lauf nicht kippen
            log.warning("Anreicherung fehlgeschlagen für %.60s (%s)", studie.titel, exc)

    arbeiter = min(cfg.anreicherung.parallel, max(1, len(studien)))
    with ThreadPoolExecutor(max_workers=arbeiter) as pool:
        list(pool.map(eine, studien))

    mit_abstract = sum(1 for s in studien if s.abstract)
    log.info("Abstract für %d von %d Studien gefunden", mit_abstract, len(studien))


# --- Crossref -------------------------------------------------------------


def _crossref(studie: Studie, netz: Netz) -> None:
    assert studie.doi is not None
    try:
        antwort = netz.hole_json(CROSSREF + quote(studie.doi, safe=""))
    except AbrufFehler as exc:
        log.debug("Crossref ohne Antwort für %s (%s)", studie.doi, exc)
        return

    daten = antwort.get("message")
    if not isinstance(daten, dict):
        return

    titel = _erster_text(daten.get("title"))
    if titel and len(titel) > len(studie.titel):
        studie.titel = _saubere_zeile(titel)

    journal = _erster_text(daten.get("container-title"))
    if journal and not studie.journal:
        studie.journal = _saubere_zeile(journal)

    if not studie.veroeffentlicht:
        studie.veroeffentlicht = _crossref_datum(daten)

    if not studie.autoren:
        studie.autoren = _crossref_autoren(daten)

    if not studie.abstract and isinstance(daten.get("abstract"), str):
        studie.abstract = _text_aus_markup(daten["abstract"])

    studie.notiere("Crossref")


def _crossref_datum(daten: dict) -> date | None:
    for schluessel in ("published-print", "published-online", "issued", "created"):
        teil = daten.get(schluessel)
        if not isinstance(teil, dict):
            continue
        teile = teil.get("date-parts") or []
        if teile and isinstance(teile[0], list) and teile[0] and teile[0][0]:
            zahlen = [z for z in teile[0] if isinstance(z, int)]
            return _datum(*zahlen[:3])
    return None


def _crossref_autoren(daten: dict) -> tuple[str, ...]:
    namen = []
    for eintrag in daten.get("author") or []:
        if not isinstance(eintrag, dict):
            continue
        name = " ".join(
            teil for teil in (eintrag.get("given"), eintrag.get("family")) if isinstance(teil, str)
        ).strip()
        if name:
            namen.append(name)
    return tuple(namen[:12])


# --- PubMed ---------------------------------------------------------------


def _pubmed(studie: Studie, netz: Netz, *, takt: _Takt, api_key: str) -> None:
    pmid = studie.pmid or _pubmed_suche(studie, netz, takt=takt, api_key=api_key)
    if not pmid:
        return

    studie.pmid = pmid
    takt.warte()
    parameter = {"db": "pubmed", "retmode": "xml", "id": pmid}
    if api_key:
        parameter["api_key"] = api_key

    try:
        xml = netz.hole(f"{EUTILS}efetch.fcgi?{urlencode(parameter)}", accept="application/xml")
    except AbrufFehler as exc:
        log.debug("PubMed efetch fehlgeschlagen für %s (%s)", pmid, exc)
        return

    try:
        wurzel = ET.fromstring(xml)
    except ET.ParseError as exc:
        log.debug("PubMed-Antwort nicht lesbar für %s (%s)", pmid, exc)
        return

    artikel = wurzel.find(".//PubmedArticle/MedlineCitation/Article")
    if artikel is None:
        return

    titel = _knotentext(artikel.find("ArticleTitle"))
    if titel and len(titel) > len(studie.titel):
        studie.titel = titel

    journal = artikel.find("Journal")
    if journal is not None:
        # Die ISO-Abkürzung ist kürzer als Crossrefs Volltitel und passt besser
        # in die Kopfzeile einer Studienkarte - sie darf deshalb überschreiben.
        kuerzel = _knotentext(journal.find("ISOAbbreviation")) or _knotentext(journal.find("Title"))
        if kuerzel:
            studie.journal = kuerzel

    datum = _pubmed_datum(artikel)
    if datum and not studie.veroeffentlicht:
        studie.veroeffentlicht = datum

    autoren = _pubmed_autoren(artikel)
    if autoren and not studie.autoren:
        studie.autoren = autoren

    abstract = _pubmed_abstract(artikel)
    # PubMed-Abstracts sind strukturiert und damit besser als Crossrefs JATS-Rohtext.
    if abstract:
        studie.abstract = abstract

    studie.notiere("PubMed")


def _pubmed_suche(studie: Studie, netz: Netz, *, takt: _Takt, api_key: str) -> str | None:
    if studie.doi:
        begriff = f"{studie.doi}[AID]"
    elif len(studie.titel) >= 25:
        begriff = f"{studie.titel}[Title]"
    else:
        return None

    parameter = {"db": "pubmed", "retmode": "json", "retmax": "1", "term": begriff}
    if api_key:
        parameter["api_key"] = api_key

    takt.warte()
    try:
        antwort = netz.hole_json(f"{EUTILS}esearch.fcgi?{urlencode(parameter)}")
    except AbrufFehler as exc:
        log.debug("PubMed-Suche fehlgeschlagen (%s)", exc)
        return None

    treffer = ((antwort.get("esearchresult") or {}).get("idlist")) or []
    return str(treffer[0]) if treffer else None


def _pubmed_abstract(artikel: ET.Element) -> str | None:
    teile = []
    for knoten in artikel.findall("./Abstract/AbstractText"):
        text = _knotentext(knoten)
        if not text:
            continue
        etikett = (knoten.get("Label") or "").strip()
        teile.append(f"{etikett.title()}: {text}" if etikett else text)
    return "\n\n".join(teile) if teile else None


def _pubmed_autoren(artikel: ET.Element) -> tuple[str, ...]:
    namen = []
    for autor in artikel.findall("./AuthorList/Author"):
        nachname = _knotentext(autor.find("LastName"))
        initialen = _knotentext(autor.find("Initials"))
        kollektiv = _knotentext(autor.find("CollectiveName"))
        if nachname:
            namen.append(f"{nachname} {initialen}".strip())
        elif kollektiv:
            namen.append(kollektiv)
    return tuple(namen[:12])


def _pubmed_datum(artikel: ET.Element) -> date | None:
    # ArticleDate ist das elektronische Erscheinungsdatum und damit das genauere.
    for pfad in ("./ArticleDate", "./Journal/JournalIssue/PubDate"):
        knoten = artikel.find(pfad)
        if knoten is None:
            continue
        jahr = _ganzzahl(_knotentext(knoten.find("Year")))
        if not jahr:
            continue
        return _datum(jahr, _monat(_knotentext(knoten.find("Month"))), _ganzzahl(_knotentext(knoten.find("Day"))))
    return None


# --- Kleinkram ------------------------------------------------------------


def _knotentext(knoten: ET.Element | None) -> str:
    if knoten is None:
        return ""
    return _LEERRAUM.sub(" ", "".join(knoten.itertext())).strip()


def _erster_text(wert: object) -> str:
    if isinstance(wert, list) and wert and isinstance(wert[0], str):
        return wert[0]
    return wert if isinstance(wert, str) else ""


def _text_aus_markup(markup: str) -> str:
    ohne_tags = _TAGS.sub(" ", markup)
    text = _LEERRAUM.sub(" ", html_modul.unescape(ohne_tags)).strip()
    # Crossref stellt dem Abstract oft die Überschrift "Abstract" voran.
    return re.sub(r"^abstract[:\s]*", "", text, flags=re.IGNORECASE).strip()


def _saubere_zeile(text: str) -> str:
    return _LEERRAUM.sub(" ", html_modul.unescape(text)).strip()


def _ganzzahl(wert: str) -> int | None:
    try:
        return int(wert)
    except (TypeError, ValueError):
        return None


def _monat(wert: str) -> int | None:
    if not wert:
        return None
    zahl = _ganzzahl(wert)
    if zahl:
        return zahl
    return _MONATE.get(wert[:3].lower())


def _datum(jahr: int | None, monat: int | None = None, tag: int | None = None) -> date | None:
    if not jahr:
        return None
    try:
        return date(jahr, monat or 1, tag or 1)
    except ValueError:
        return date(jahr, 1, 1)
