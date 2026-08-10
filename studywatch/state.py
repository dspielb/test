"""Merkliste bereits gezeigter Studien.

Die Journal-Watch-Seite trägt kein verlässliches Datum pro Eintrag. "Neu" heißt
deshalb: heute zum ersten Mal auf der Seite gesehen. Dafür genügt eine Datei
mit den Kennungen aller bisherigen Studien.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .study import Studie

log = logging.getLogger(__name__)

FORMAT_VERSION = 1


@dataclass
class Merkliste:
    """Kennung -> Datum des ersten Auftauchens."""

    gesehen: dict[str, str] = field(default_factory=dict)

    def ist_neu(self, studie: Studie) -> bool:
        return studie.kennung not in self.gesehen

    def eintragen(self, studien: list[Studie], tag: date) -> None:
        for studie in studien:
            self.gesehen.setdefault(studie.kennung, tag.isoformat())

    def __len__(self) -> int:
        return len(self.gesehen)


def laden(pfad: str | Path) -> Merkliste:
    """Liest die Merkliste. Fehlt oder bricht die Datei, beginnt der Lauf bei null."""
    pfad = Path(pfad)
    if not pfad.exists():
        return Merkliste()

    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Merkliste %s ist unlesbar (%s) - starte mit leerer Liste.", pfad, exc)
        return Merkliste()

    gesehen = daten.get("gesehen") if isinstance(daten, dict) else None
    if not isinstance(gesehen, dict):
        log.warning("Merkliste %s hat ein unerwartetes Format - starte mit leerer Liste.", pfad)
        return Merkliste()

    return Merkliste({str(k): str(v) for k, v in gesehen.items()})


def speichern(merkliste: Merkliste, pfad: str | Path) -> Path:
    """Schreibt die Merkliste atomar, damit ein Abbruch sie nicht zerstört."""
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)

    inhalt = json.dumps(
        {"version": FORMAT_VERSION, "gesehen": dict(sorted(merkliste.gesehen.items()))},
        ensure_ascii=False,
        indent=1,
    )
    zwischendatei = pfad.with_suffix(pfad.suffix + ".tmp")
    zwischendatei.write_text(inhalt + "\n", encoding="utf-8")
    zwischendatei.replace(pfad)
    return pfad


def nur_neue(studien: list[Studie], merkliste: Merkliste) -> list[Studie]:
    return [studie for studie in studien if merkliste.ist_neu(studie)]
