"""Studienlinks aus der Journal-Watch-Seite herausziehen.

Bewusst nicht an CSS-Klassen der Seite festgemacht: solche Selektoren brechen
beim nächsten Redesign. Stattdessen zählt, wohin ein Link zeigt - Links auf
Verlags- und Datenbank-Domains sind Studien, alles andere ist Navigation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .config import Config
from .http import AbrufFehler, Netz
from .study import Studie

log = logging.getLogger(__name__)

#: Linktexte, die nie der Studientitel sind - dann steht der Titel daneben.
_ETIKETTEN = {
    "abstract",
    "article",
    "doi",
    "download",
    "editorial",
    "epub",
    "free full text",
    "full text",
    "hier",
    "journal",
    "link",
    "mehr",
    "open access",
    "paper",
    "pdf",
    "pubmed",
    "read more",
    "study",
    "weiterlesen",
}

_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>&]+)", re.IGNORECASE)
_PMID_AUS_URL = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d{5,9})")
_MEHRFACH_LEERRAUM = re.compile(r"\s+")

#: Tags, nach denen ein Zeilenumbruch gehört, damit Wörter nicht verkleben.
_BLOCK_TAGS = frozenset(
    "p div br li tr td h1 h2 h3 h4 h5 h6 section article header footer ul ol blockquote".split()
)
_UEBERSPRINGEN = frozenset({"script", "style", "noscript", "svg"})

_KONTEXT_ZEICHEN = 400


@dataclass
class _Anker:
    href: str
    text: str
    davor: str
    danach: str


class _SeitenParser(HTMLParser):
    """Zerlegt die Seite in Textstücke und Links, in Lesereihenfolge."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[tuple[str, str]] = []
        self.feeds: list[str] = []
        self._ueberspringen = 0
        self._in_anker = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        werte = {name.lower(): (wert or "") for name, wert in attrs}

        if tag in _UEBERSPRINGEN:
            self._ueberspringen += 1
            return

        if tag == "link":
            self._merke_feed(werte)
            return

        if tag == "a":
            href = werte.get("href", "").strip()
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                self.tokens.append(("a_start", href))
                self._in_anker += 1
                return

        if tag in _BLOCK_TAGS:
            self.tokens.append(("text", "\n"))

    def handle_endtag(self, tag: str) -> None:
        if tag in _UEBERSPRINGEN:
            self._ueberspringen = max(0, self._ueberspringen - 1)
            return
        if tag == "a" and self._in_anker:
            self.tokens.append(("a_end", ""))
            self._in_anker -= 1
            return
        if tag in _BLOCK_TAGS:
            self.tokens.append(("text", "\n"))

    def handle_data(self, data: str) -> None:
        if self._ueberspringen:
            return
        if data.strip() or "\n" in data:
            self.tokens.append(("text", data))

    def _merke_feed(self, werte: dict[str, str]) -> None:
        rel = werte.get("rel", "").lower()
        typ = werte.get("type", "").lower()
        href = werte.get("href", "").strip()
        if href and "alternate" in rel and ("rss" in typ or "atom" in typ or "xml" in typ):
            self.feeds.append(href)


def finde_feed(html: str, basis_url: str) -> str | None:
    """Sucht einen RSS-/Atom-Feed in den <link rel="alternate">-Angaben der Seite."""
    parser = _SeitenParser()
    parser.feed(html)
    for href in parser.feeds:
        return urljoin(basis_url, href)
    return None


def extrahiere(html: str, *, basis_url: str, cfg: Config) -> list[Studie]:
    """Wandelt die Übersichtsseite in eine Liste von Studien um."""
    parser = _SeitenParser()
    parser.feed(html)
    parser.close()

    mindestlaenge = cfg.einstellungen.min_titel_zeichen
    studien: list[Studie] = []
    nach_kennung: dict[str, Studie] = {}
    nach_titel: dict[str, Studie] = {}
    letzte: Studie | None = None

    for anker in _anker_mit_kontext(parser.tokens):
        url = urljoin(basis_url, anker.href)
        if not _ist_verlagslink(url, cfg.einstellungen.verlags_hosts):
            continue

        doi, pmid = _doi_aus(url), _pmid_aus(url)

        # "PubMed", "full text" & Co. tragen keinen Titel. Sie gehören zum
        # Eintrag darüber, wenn zwischen beiden nur dessen Kontextzeile steht -
        # steht dort etwas anderes, ist es der Titel eines neuen Eintrags.
        if letzte is not None and _ist_etikett(anker.text):
            if _gehoert_zu(_letzte_zeile(anker.davor), letzte, mindestlaenge):
                _ergaenze(letzte, doi, pmid, nach_kennung)
                continue

        titel = _titel_bestimmen(anker, mindestlaenge)
        if not titel:
            continue

        bekannt = nach_titel.get(titel.lower())
        if bekannt is not None:
            _ergaenze(bekannt, doi, pmid, nach_kennung)
            letzte = bekannt
            continue

        studie = Studie(
            titel=titel,
            link=url,
            kontext=_kuerze(anker.danach or anker.davor, 240),
            doi=doi,
            pmid=pmid,
        )
        studie.notiere("Journal Watch")

        bekannt = nach_kennung.get(studie.kennung)
        if bekannt is not None:
            _ergaenze(bekannt, doi, pmid, nach_kennung)
            letzte = bekannt
            continue

        nach_kennung[studie.kennung] = studie
        nach_titel[titel.lower()] = studie
        studien.append(studie)
        letzte = studie

    log.info("%d Studien auf der Seite gefunden", len(studien))
    return studien


def _ist_etikett(text: str) -> bool:
    return text.strip(" .:-").lower() in _ETIKETTEN


def _gehoert_zu(kandidat: str, letzte: Studie, mindestlaenge: int) -> bool:
    """Ist der Text vor einem Etikett-Link nur der Kontext der Studie davor?"""
    if len(kandidat) < mindestlaenge:
        return True
    return kandidat[:100] in letzte.kontext


def _ergaenze(
    studie: Studie, doi: str | None, pmid: str | None, nach_kennung: dict[str, Studie]
) -> None:
    """Übernimmt eine zweite Kennung derselben Studie."""
    if doi and not studie.doi:
        studie.doi = doi
    if pmid and not studie.pmid:
        studie.pmid = pmid
    # Die Kennung kann sich dadurch ändern - unter beiden auffindbar halten.
    nach_kennung.setdefault(studie.kennung, studie)


def hole_seite(cfg: Config, netz: Netz) -> str:
    """Lädt die Übersichtsseite. Ein Fehler hier beendet den Lauf."""
    try:
        return netz.hole_text(cfg.quelle.url, accept="text/html,application/xhtml+xml")
    except AbrufFehler as exc:
        raise AbrufFehler(f"{cfg.quelle.name} nicht erreichbar: {exc}") from None


# --- Bausteine ------------------------------------------------------------


def _anker_mit_kontext(tokens: list[tuple[str, str]]) -> list[_Anker]:
    """Zu jedem Link den Text davor und danach - dort stehen Titel und Journal."""
    anker: list[_Anker] = []
    offene: list[tuple[str, str]] = []  # href und der Text davor
    text_vor = ""
    laufend: list[str] = []

    for art, wert in tokens:
        if art == "text":
            if offene:
                laufend.append(wert)
            else:
                text_vor = _kuerze_ende(text_vor + wert, _KONTEXT_ZEICHEN)
                # Text nach dem zuletzt geschlossenen Link ist dessen "danach".
                if anker and len(anker[-1].danach) < _KONTEXT_ZEICHEN:
                    anker[-1].danach = _kuerze(_normalisiere(anker[-1].danach + " " + wert), _KONTEXT_ZEICHEN)
        elif art == "a_start":
            offene.append((wert, text_vor))
            laufend = []
        elif art == "a_end" and offene:
            href, davor = offene.pop()
            anker.append(
                _Anker(
                    href=href,
                    text=_normalisiere("".join(laufend)),
                    davor=davor,
                    danach="",
                )
            )
            text_vor = ""
            laufend = []

    return anker


def _titel_bestimmen(anker: _Anker, mindestlaenge: int) -> str:
    """Der Linktext, sofern er ein Titel ist - sonst der Satz direkt davor."""
    text = anker.text
    if len(text) >= mindestlaenge and not _ist_etikett(text):
        return _kuerze(text, 400)

    kandidat = _letzte_zeile(anker.davor)
    if len(kandidat) >= mindestlaenge:
        return _kuerze(kandidat, 400)

    # Kurzer, aber unverdächtiger Linktext ist besser als gar kein Titel.
    if text and not _ist_etikett(text):
        return _kuerze(text, 400)
    return ""


def _letzte_zeile(text: str) -> str:
    zeilen = [_normalisiere(zeile) for zeile in text.splitlines()]
    for zeile in reversed(zeilen):
        if zeile:
            return zeile
    return ""


def _ist_verlagslink(url: str, hosts: tuple[str, ...]) -> bool:
    host = urlsplit(url).netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return any(host == eintrag or host.endswith("." + eintrag) for eintrag in hosts)


def _doi_aus(url: str) -> str | None:
    treffer = _DOI.search(url)
    if not treffer:
        return None
    # Satzzeichen am Ende gehören meist zum umgebenden Text, nicht zur DOI.
    return treffer.group(1).rstrip(".,;)»\"'")


def _pmid_aus(url: str) -> str | None:
    treffer = _PMID_AUS_URL.search(url)
    return treffer.group(1) if treffer else None


def _normalisiere(text: str) -> str:
    return _MEHRFACH_LEERRAUM.sub(" ", text).strip()


def _kuerze(text: str, grenze: int) -> str:
    text = _normalisiere(text)
    if len(text) <= grenze:
        return text
    schnitt = text.rfind(" ", 0, grenze)
    return text[: schnitt if schnitt > grenze // 2 else grenze].rstrip() + "…"


def _kuerze_ende(text: str, grenze: int) -> str:
    """Behält das Ende - davor stehender Text ist näher am Link und damit relevanter."""
    return text[-grenze:] if len(text) > grenze else text
