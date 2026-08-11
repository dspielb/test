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
    """Alles, was eine Ausgabe des Tages anzeigt."""

    studien: list[Studie]
    quelle_name: str
    quelle_url: str
    erzeugt_am: datetime
    gefunden_gesamt: int = 0
    modell: str = ""
    hinweise: list[str] = field(default_factory=list)
    zeitzone: str = "Europe/Berlin"

    @property
    def anzahl(self) -> int:
        return len(self.studien)

    @property
    def vom_modell(self) -> int:
        return sum(1 for s in self.studien if s.zusammenfassung and s.zusammenfassung.vom_modell)

    @property
    def erzeugt_am_lokal(self) -> datetime:
        return self.erzeugt_am.astimezone(ZoneInfo(self.zeitzone))


def render_bericht(bericht: Bericht) -> str:
    lokal = bericht.erzeugt_am_lokal

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


# --- Fassung für die E-Mail ----------------------------------------------

# Mail-Programme kennen weder <style>-Blöcke noch <details> zuverlässig.
# Deshalb eine eigene, schlichtere Fassung mit Stilangaben direkt am Element.
_M_RAHMEN = "max-width:680px;margin:0;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#14181d;line-height:1.55;"
_M_KOPFZEILE = "margin:0 0 4px;font-size:20px;font-weight:600;"
_M_DATUM = "margin:0 0 24px;font-size:13px;color:#5b6672;"
_M_TITEL = "margin:0 0 6px;font-size:17px;line-height:1.4;font-weight:600;"
_M_TITEL_LINK = "color:#14181d;text-decoration:none;"
_M_ZEILE = "margin:0 0 12px;font-size:13px;color:#5b6672;"
_M_KERN = "margin:0 0 12px;padding:10px 14px;background:#e6f0f5;border-left:3px solid #1f5f7a;font-size:15px;"
_M_FELD = "margin:0 0 8px;font-size:14px;color:#3c4650;"
_M_ETIKETT = "color:#8a939e;font-size:12px;text-transform:uppercase;letter-spacing:0.04em;"
_M_HERKUNFT = "margin:0;font-size:11px;color:#8a939e;"
_M_TRENNER = "border:0;border-top:1px solid #dfe3e8;margin:24px 0;"
_M_FUSS = "margin:0 0 8px;font-size:12px;color:#5b6672;"


def render_mail_html(bericht: Bericht, *, mit_abstract: bool = False) -> str:
    """HTML-Teil der Mail: ohne <style>-Block, ohne aufklappbare Abschnitte."""
    lokal = bericht.erzeugt_am_lokal
    teile = [
        f'<div style="{_M_RAHMEN}">',
        f'<p style="{_M_KOPFZEILE}">Neue Studien</p>',
        f'<p style="{_M_DATUM}">{WOCHENTAGE[lokal.weekday()]}, {_langes_datum(lokal.date())} · '
        f"{_zaehle(bericht.anzahl, 'neue Studie', 'neue Studien')} von "
        f"{bericht.gefunden_gesamt} geprüften Einträgen</p>",
    ]

    if not bericht.studien:
        teile.append(f'<p style="{_M_FELD}">Heute keine neuen Studien im Journal Watch.</p>')

    for studie in bericht.studien:
        teile.append(_mail_studie(studie, mit_abstract=mit_abstract))

    teile.append(f'<hr style="{_M_TRENNER}">')
    teile.append(f'<p style="{_M_FUSS}">{escape(HINWEIS)}</p>')
    for hinweis in bericht.hinweise:
        teile.append(f'<p style="{_M_FUSS}">{escape(hinweis)}</p>')
    teile.append(
        f'<p style="{_M_FUSS}">Quelle: '
        f'<a href="{escape(bericht.quelle_url, quote=True)}">{escape(bericht.quelle_name)}</a> · '
        f"erzeugt am {lokal:%d.%m.%Y um %H:%M} Uhr"
        + (f" · Kurzfassungen mit {escape(bericht.modell)}" if bericht.modell else "")
        + "</p>"
    )
    teile.append("</div>")
    return "\n".join(teile)


def _mail_studie(studie: Studie, *, mit_abstract: bool) -> str:
    zeilen = [
        '<div style="margin:0 0 28px;">',
        f'<p style="{_M_TITEL}"><a href="{escape(studie.link, quote=True)}" '
        f'style="{_M_TITEL_LINK}">{escape(studie.titel)}</a></p>',
    ]

    angaben = [escape(teil) for teil in (studie.journal, studie.autoren_kurz) if teil]
    if studie.veroeffentlicht:
        angaben.insert(1 if studie.journal else 0, _langes_datum(studie.veroeffentlicht))
    for beschriftung, ziel in (("DOI", studie.doi_link), ("PubMed", studie.pubmed_link)):
        if ziel:
            angaben.append(f'<a href="{escape(ziel, quote=True)}">{beschriftung}</a>')
    if angaben:
        zeilen.append(f'<p style="{_M_ZEILE}">{" · ".join(angaben)}</p>')

    zusammenfassung = studie.zusammenfassung
    if zusammenfassung:
        zeilen.append(f'<p style="{_M_KERN}">{escape(zusammenfassung.kernaussage)}</p>')
        for feld, beschriftung in _FELDER:
            wert = getattr(zusammenfassung, feld)
            if wert:
                zeilen.append(
                    f'<p style="{_M_FELD}"><span style="{_M_ETIKETT}">{beschriftung}</span><br>'
                    f"{escape(wert)}</p>"
                )
    elif studie.kontext:
        zeilen.append(f'<p style="{_M_FELD}">{escape(studie.kontext)}</p>')

    if mit_abstract and studie.abstract:
        zeilen.append(f'<p style="{_M_FELD}">{escape(studie.abstract)}</p>')

    zeilen.append(f'<p style="{_M_HERKUNFT}">{_herkunft(studie)}</p>')
    zeilen.append("</div>")
    return "".join(zeilen)


def render_mail_text(bericht: Bericht, *, mit_abstract: bool = False) -> str:
    """Textteil der Mail - was jedes Programm anzeigen kann."""
    lokal = bericht.erzeugt_am_lokal
    zeilen = [
        "NEUE STUDIEN",
        f"{WOCHENTAGE[lokal.weekday()]}, {_langes_datum(lokal.date())} · "
        f"{_zaehle(bericht.anzahl, 'neue Studie', 'neue Studien')} von "
        f"{bericht.gefunden_gesamt} geprüften Einträgen",
        "",
    ]

    if not bericht.studien:
        zeilen.append("Heute keine neuen Studien im Journal Watch.")

    for nummer, studie in enumerate(bericht.studien, start=1):
        zeilen.append(f"{nummer}. {studie.titel}")

        angaben = [teil for teil in (studie.journal, studie.autoren_kurz) if teil]
        if studie.veroeffentlicht:
            angaben.insert(1 if studie.journal else 0, _langes_datum(studie.veroeffentlicht))
        if angaben:
            zeilen.append(f"   {' · '.join(angaben)}")
        zeilen.append(f"   {studie.link}")
        zeilen.append("")

        zusammenfassung = studie.zusammenfassung
        if zusammenfassung:
            zeilen.append(f"   {zusammenfassung.kernaussage}")
            for feld, beschriftung in _FELDER:
                wert = getattr(zusammenfassung, feld)
                if wert:
                    zeilen.append("")
                    zeilen.append(f"   {beschriftung.upper()}")
                    zeilen.append(f"   {wert}")
        elif studie.kontext:
            zeilen.append(f"   {studie.kontext}")

        if mit_abstract and studie.abstract:
            zeilen.append("")
            zeilen.append("   ABSTRACT")
            zeilen.extend(f"   {absatz}" for absatz in studie.abstract.split("\n\n") if absatz.strip())

        zeilen.append("")
        zeilen.append("-" * 60)
        zeilen.append("")

    zeilen.append(HINWEIS)
    zeilen.extend(bericht.hinweise)
    zeilen.append("")
    zeilen.append(f"Quelle: {bericht.quelle_name} – {bericht.quelle_url}")
    zeilen.append(f"Erzeugt am {lokal:%d.%m.%Y um %H:%M} Uhr")
    if bericht.modell:
        zeilen.append(f"Kurzfassungen erzeugt mit {bericht.modell}")
    return "\n".join(zeilen)


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
