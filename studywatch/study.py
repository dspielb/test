"""Das Datenmodell einer Studie, das alle Schritte gemeinsam befüllen."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PREFIXE = ("utm_", "at_")
_TRACKING_SCHLUESSEL = {"fbclid", "gclid", "ref", "cmpid", "src", "source"}


@dataclass
class Zusammenfassung:
    """Die verdichtete Fassung einer Studie."""

    kernaussage: str
    hintergrund: str = ""
    methodik: str = ""
    ergebnis: str = ""
    bedeutung: str = ""
    #: "claude" = vom Modell geschrieben, "abstract" = ungekürzter Notbehelf.
    herkunft: str = "claude"

    @property
    def vom_modell(self) -> bool:
        return self.herkunft == "claude"


@dataclass
class Studie:
    """Ein Eintrag des Journal Watch, über die Schritte hinweg angereichert."""

    titel: str
    link: str
    #: Text, der auf der Übersichtsseite direkt am Link stand - oft Journal und Datum.
    kontext: str = ""
    doi: str | None = None
    pmid: str | None = None
    journal: str | None = None
    veroeffentlicht: date | None = None
    autoren: tuple[str, ...] = ()
    abstract: str | None = None
    zusammenfassung: Zusammenfassung | None = None
    #: Wo die Metadaten herkamen, für den Quellen-Status in der Fußzeile.
    herkunft: list[str] = field(default_factory=list)

    @property
    def kennung(self) -> str:
        """Stabile Kennung für die Merkliste - bevorzugt die DOI."""
        if self.doi:
            return f"doi:{self.doi.lower()}"
        if self.pmid:
            return f"pmid:{self.pmid}"
        return f"url:{kanonische_url(self.link)}"

    @property
    def autoren_kurz(self) -> str:
        if not self.autoren:
            return ""
        if len(self.autoren) == 1:
            return self.autoren[0]
        return f"{self.autoren[0]} et al."

    @property
    def pubmed_link(self) -> str | None:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/" if self.pmid else None

    @property
    def doi_link(self) -> str | None:
        return f"https://doi.org/{self.doi}" if self.doi else None

    def notiere(self, woher: str) -> None:
        if woher not in self.herkunft:
            self.herkunft.append(woher)


def kanonische_url(url: str) -> str:
    """URL ohne Tracking-Parameter und Fragment - für Vergleiche."""
    teile = urlsplit(url)
    behalten = [
        (schluessel, wert)
        for schluessel, wert in parse_qsl(teile.query, keep_blank_values=True)
        if schluessel.lower() not in _TRACKING_SCHLUESSEL
        and not schluessel.lower().startswith(_TRACKING_PREFIXE)
    ]
    pfad = teile.path.rstrip("/") or "/"
    return urlunsplit(
        (teile.scheme.lower(), teile.netloc.lower(), pfad, urlencode(behalten), "")
    )
