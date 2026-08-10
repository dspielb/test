"""HTML-Ausgabe der Studienübersicht."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from .study import Studie

_ASSETS = Path(__file__).parent / "assets"

WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONATE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)

_FELDER = (
    ("hintergrund", "Hintergrund"),
    ("methodik", "Methodik"),
    ("ergebnis", "Ergebnis"),
    ("bedeutung", "Bedeutung"),
)

HINWEIS = (
    "Automatisch erzeugte Kurzfassungen – keine ärztliche Empfehlung und kein Ersatz "
    "für die Originalarbeit. Vor jeder klinischen Konsequenz gilt die Publikation selbst."
)


@dataclass
class Bericht:
    """Alles, was die Seite eines Tages anzeigt."""

    studien: list[Studie]
    quelle_name: str
    quelle_url: str
    erzeugt_am: datetime
    gefunden_gesamt: int = 0
    modell: str = ""
    hinweise: list[str] = field(default_factory=list)

    @property
    def anzahl(self) -> int:
        return len(self.studien)

    @property
    def vom_modell(self) -> int:
        return sum(1 for s in self.studien if s.zusammenfassung and s.zusammenfassung.vom_modell)


def render_bericht(bericht: Bericht, *, timezone: str = "Europe/Berlin") -> str:
    tz = ZoneInfo(timezone)
    lokal = bericht.erzeugt_am.astimezone(tz)

    teile = [
        _kopf(f"Neue Studien – {lokal:%d.%m.%Y}"),
        _seitenkopf(bericht, lokal),
        '<main class="wrap">',
    ]

    if not bericht.studien:
        teile.append(
            '<p class="empty">Heute keine neuen Studien im Journal Watch. '
            "Die Seite wurde erfolgreich abgerufen – es war nur nichts dabei, "
            "was hier noch nicht stand.</p>"
        )
    else:
        teile.append(
            f'<ol class="studien">{"".join(_studie(s) for s in bericht.studien)}</ol>'
        )

    teile.append(_seitenfuss(bericht, lokal))
    teile.append("</main></body></html>")
    return "\n".join(teile)


def render_archiv_index(tage: list[date]) -> str:
    eintraege = "\n".join(
        f'<li><a href="{tag.isoformat()}.html">{_langes_datum(tag)}</a>'
        f'<span class="weekday">{WOCHENTAGE[tag.weekday()]}</span></li>'
        for tag in sorted(tage, reverse=True)
    )
    return (
        f"{_kopf('Archiv – Studienübersicht')}"
        '<header class="page"><div class="wrap">'
        "<h1>Archiv</h1>"
        f'<p class="dateline">{_zaehle(len(tage), "Ausgabe", "Ausgaben")}</p>'
        '<a class="back" href="../index.html">← Zur aktuellen Ausgabe</a>'
        "</div></header>"
        f'<main class="wrap"><ul class="archive">{eintraege}</ul></main>'
        "</body></html>"
    )


# --- Bausteine ------------------------------------------------------------


def _kopf(titel: str) -> str:
    css = (_ASSETS / "style.css").read_text(encoding="utf-8")
    return (
        "<!DOCTYPE html>"
        '<html lang="de"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(titel)}</title>"
        f"<style>{css}</style>"
        "</head><body>"
    )


def _seitenkopf(bericht: Bericht, lokal: datetime) -> str:
    meta = [
        _zaehle(bericht.anzahl, "neue Studie", "neue Studien"),
        f"{bericht.gefunden_gesamt} Einträge auf der Quellseite geprüft",
    ]
    if bericht.anzahl:
        meta.append(f"{bericht.vom_modell} von {bericht.anzahl} Kurzfassungen vom Modell")

    return (
        '<header class="page"><div class="wrap">'
        "<h1>Neue Studien</h1>"
        f'<p class="dateline">{WOCHENTAGE[lokal.weekday()]}, {_langes_datum(lokal.date())} · '
        f"Stand {lokal:%H:%M} Uhr</p>"
        f'<p class="meta">{escape(" · ".join(meta))}</p>'
        f'<p class="quelle">Quelle: <a href="{escape(bericht.quelle_url, quote=True)}" '
        f'rel="noopener">{escape(bericht.quelle_name)}</a></p>'
        "</div></header>"
    )


def _studie(studie: Studie) -> str:
    zeilen = [
        '<li class="studie">',
        f'<h2><a href="{escape(studie.link, quote=True)}" rel="noopener">'
        f"{escape(studie.titel)}</a></h2>",
        _zeile(studie),
    ]

    zusammenfassung = studie.zusammenfassung
    if zusammenfassung:
        zeilen.append(f'<p class="kernaussage">{escape(zusammenfassung.kernaussage)}</p>')
        felder = [
            (label, getattr(zusammenfassung, feld))
            for feld, label in _FELDER
            if getattr(zusammenfassung, feld)
        ]
        if felder:
            eintraege = "".join(
                f"<dt>{escape(label)}</dt><dd>{escape(wert)}</dd>" for label, wert in felder
            )
            zeilen.append(f'<dl class="details">{eintraege}</dl>')
    elif studie.kontext:
        zeilen.append(f'<p class="kontext">{escape(studie.kontext)}</p>')
    else:
        zeilen.append(
            '<p class="kontext">Kein Abstract gefunden – bitte die Originalarbeit ansehen.</p>'
        )

    if studie.abstract:
        zeilen.append(
            "<details><summary>Abstract im Original</summary>"
            f'<div class="abstract">{_absaetze(studie.abstract)}</div></details>'
        )

    zeilen.append(f'<p class="herkunft">{_herkunft(studie)}</p>')
    zeilen.append("</li>")
    return "".join(zeilen)


def _zeile(studie: Studie) -> str:
    stuecke = []
    if studie.journal:
        stuecke.append(f'<span class="journal">{escape(studie.journal)}</span>')
    if studie.veroeffentlicht:
        stuecke.append(
            f'<time datetime="{studie.veroeffentlicht.isoformat()}">'
            f"{_langes_datum(studie.veroeffentlicht)}</time>"
        )
    if studie.autoren_kurz:
        stuecke.append(f'<span class="autoren">{escape(studie.autoren_kurz)}</span>')

    verweise = []
    if studie.doi_link:
        verweise.append(
            f'<a href="{escape(studie.doi_link, quote=True)}" rel="noopener">DOI</a>'
        )
    if studie.pubmed_link:
        verweise.append(
            f'<a href="{escape(studie.pubmed_link, quote=True)}" rel="noopener">PubMed</a>'
        )
    if verweise:
        stuecke.append(f'<span class="links">{" · ".join(verweise)}</span>')

    return f'<div class="byline">{"".join(stuecke)}</div>' if stuecke else ""


def _herkunft(studie: Studie) -> str:
    if studie.zusammenfassung and studie.zusammenfassung.vom_modell:
        text = "Kurzfassung: automatisch aus dem Abstract erzeugt"
    elif studie.zusammenfassung:
        text = "Kurzfassung: wörtlicher Auszug aus dem Abstract"
    else:
        text = "Keine Kurzfassung verfügbar"
    if studie.herkunft:
        text += f" · Angaben aus {', '.join(studie.herkunft)}"
    return escape(text)


def _seitenfuss(bericht: Bericht, lokal: datetime) -> str:
    hinweise = "".join(f"<li>{escape(zeile)}</li>" for zeile in bericht.hinweise)
    hinweisblock = f'<ul class="status">{hinweise}</ul>' if hinweise else ""
    modell = (
        f" Kurzfassungen erzeugt mit {escape(bericht.modell)}." if bericht.modell else ""
    )

    return (
        '<footer class="page">'
        f'<p class="disclaimer">{escape(HINWEIS)}</p>'
        f"{hinweisblock}"
        f"<p>Automatisch erzeugt am {lokal:%d.%m.%Y um %H:%M} Uhr "
        f"({lokal.tzname() or 'UTC'}).{modell} "
        "Alle Rechte an den verlinkten Inhalten liegen bei den jeweiligen Verlagen. "
        '<a href="archiv/index.html">Archiv</a></p>'
        "</footer>"
    )


def _absaetze(text: str) -> str:
    return "".join(
        f"<p>{escape(absatz.strip())}</p>" for absatz in text.split("\n\n") if absatz.strip()
    )


def _zaehle(anzahl: int, singular: str, plural: str) -> str:
    return f"{anzahl} {singular if anzahl == 1 else plural}"


def _langes_datum(tag: date) -> str:
    return f"{tag.day}. {MONATE[tag.month - 1]} {tag.year}"
