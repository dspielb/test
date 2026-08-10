"""Deutsche Zusammenfassungen über die Claude-API - mit Rückfallebene.

Steht kein API-Schlüssel bereit oder antwortet die API nicht, fällt das
Programm auf den Abstract zurück, statt den Lauf abzubrechen. Die Seite zeigt
in beiden Fällen an, woher eine Zusammenfassung stammt.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .config import Config, Zusammenfassung as ZusammenfassungConfig
from .study import Studie, Zusammenfassung

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Du fasst intensivmedizinische Studien für Ärztinnen und Ärzte auf einer Intensivstation \
zusammen.

Grundlage ist ausschließlich der mitgelieferte Text. Ergänze nichts aus eigenem Wissen, \
rate nicht und leite nichts her, was dort nicht steht. Was der Text nicht hergibt, bleibt \
ein leeres Feld - ein leeres Feld ist besser als eine plausible Erfindung.

Schreibe auf Deutsch, in ganzen Sätzen, ohne Aufzählungszeichen und ohne Einleitungsfloskeln. \
Fachbegriffe, Substanz- und Verfahrensnamen, Scores und Journaltitel bleiben im Original. \
Zahlen, Effektmaße, Konfidenzintervalle und p-Werte übernimmst du exakt so, wie sie im Text \
stehen; rechne nichts um.

Formuliere keine Behandlungsempfehlung. Unter "bedeutung" ordnest du ein, was die Studie \
selbst stützt, und nennst die wichtigste methodische Einschränkung.\
"""

#: Struktur der Antwort - die API erzwingt sie, damit kein Nachparsen nötig ist.
SCHEMA = {
    "type": "object",
    "properties": {
        "kernaussage": {
            "type": "string",
            "description": "Ein bis zwei Sätze, Ergebnis zuerst. Das Feld ist nie leer.",
        },
        "hintergrund": {
            "type": "string",
            "description": "Fragestellung und Ausgangslage in ein bis zwei Sätzen.",
        },
        "methodik": {
            "type": "string",
            "description": (
                "Studiendesign, Population, Fallzahl, Intervention und Vergleich, "
                "primärer Endpunkt."
            ),
        },
        "ergebnis": {
            "type": "string",
            "description": "Ergebnis des primären Endpunkts mit den Zahlen aus dem Text.",
        },
        "bedeutung": {
            "type": "string",
            "description": "Einordnung und wichtigste Einschränkung, ohne Empfehlung.",
        },
    },
    "required": ["kernaussage", "hintergrund", "methodik", "ergebnis", "bedeutung"],
    "additionalProperties": False,
}

#: Beta-Kennung für serverseitige Ausweichmodelle: lehnt ein Sicherheitsfilter
#: eine Anfrage ab, beantwortet ein anderes Modell sie im selben Aufruf.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_SCHLUSS = re.compile(
    r"(?:^|\n)\s*(?:conclusions?|interpretation|schlussfolgerung(?:en)?)\s*[:.]\s*",
    re.IGNORECASE,
)
_SATZENDE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Verbrauch:
    """Was der Lauf an Modell-Tokens gekostet hat."""

    anfragen: int = 0
    eingabe_tokens: int = 0
    ausgabe_tokens: int = 0

    def __str__(self) -> str:
        return (
            f"{self.anfragen} Anfragen, {self.eingabe_tokens} Eingabe- und "
            f"{self.ausgabe_tokens} Ausgabe-Tokens"
        )


def zusammenfassen(studien: list[Studie], cfg: Config) -> Verbrauch:
    """Schreibt in jede Studie eine Zusammenfassung - per Modell oder aus dem Abstract."""
    verbrauch = Verbrauch()
    if not studien:
        return verbrauch

    if not cfg.zusammenfassung.aktiv:
        log.info("Zusammenfassung abgeschaltet - es wird der Abstract gezeigt.")
        _alle_aus_abstract(studien)
        return verbrauch

    fasser = _Zusammenfasser(cfg.zusammenfassung)
    if not fasser.bereit:
        log.warning(
            "Kein Zugang zur Claude-API (%s) - es wird der Abstract gezeigt.", fasser.grund
        )
        _alle_aus_abstract(studien)
        return verbrauch

    arbeiter = min(cfg.zusammenfassung.parallel, max(1, len(studien)))
    with ThreadPoolExecutor(max_workers=arbeiter) as pool:
        list(pool.map(fasser.fasse, studien))

    vom_modell = sum(1 for s in studien if s.zusammenfassung and s.zusammenfassung.vom_modell)
    log.info("%d von %d Zusammenfassungen vom Modell", vom_modell, len(studien))
    return fasser.verbrauch


class _Zusammenfasser:
    """Kapselt Client, Ausweichlogik und Verbrauchszählung."""

    def __init__(self, cfg: ZusammenfassungConfig) -> None:
        self.cfg = cfg
        self.verbrauch = Verbrauch()
        self.grund = ""
        self._client = None
        self._mit_fallback = True
        self._sperre = threading.Lock()

        try:
            import anthropic  # noqa: PLC0415 - optionale Abhängigkeit, erst hier nötig
        except ImportError:
            self.grund = "Paket 'anthropic' ist nicht installiert"
            return

        try:
            schluessel = os.environ.get(cfg.api_key_env, "").strip()
            # Ohne Schlüssel greift die Anmeldung der SDK (z. B. ein `ant auth`-Profil).
            self._client = (
                anthropic.Anthropic(api_key=schluessel) if schluessel else anthropic.Anthropic()
            )
        except Exception as exc:  # noqa: BLE001 - fehlende Anmeldedaten sind kein Absturzgrund
            self.grund = f"{cfg.api_key_env} nicht gesetzt und keine Anmeldung gefunden ({exc})"
            self._client = None

    @property
    def bereit(self) -> bool:
        return self._client is not None

    def fasse(self, studie: Studie) -> None:
        text = _anfragetext(studie)
        if not text:
            studie.zusammenfassung = None
            return

        try:
            studie.zusammenfassung = self._vom_modell(text)
            return
        except _Abgelehnt as exc:
            log.warning("Modell hat abgelehnt (%s) für %.60s", exc, studie.titel)
        except Exception as exc:  # noqa: BLE001 - eine Studie darf den Lauf nicht kippen
            log.warning("Zusammenfassung fehlgeschlagen für %.60s (%s)", studie.titel, exc)

        studie.zusammenfassung = aus_abstract(studie)

    def _vom_modell(self, text: str) -> Zusammenfassung:
        antwort = self._anfrage(text)
        self._zaehle(antwort)

        if getattr(antwort, "stop_reason", None) == "refusal":
            grund = getattr(getattr(antwort, "stop_details", None), "category", "ohne Angabe")
            raise _Abgelehnt(str(grund))

        rohtext = next(
            (
                block.text
                for block in antwort.content
                if getattr(block, "type", None) == "text" and getattr(block, "text", "")
            ),
            "",
        )
        daten = json.loads(rohtext)
        kern = str(daten.get("kernaussage", "")).strip()
        if not kern:
            raise ValueError("Antwort enthielt keine Kernaussage")

        return Zusammenfassung(
            kernaussage=kern,
            hintergrund=str(daten.get("hintergrund", "")).strip(),
            methodik=str(daten.get("methodik", "")).strip(),
            ergebnis=str(daten.get("ergebnis", "")).strip(),
            bedeutung=str(daten.get("bedeutung", "")).strip(),
            herkunft="claude",
        )

    def _anfrage(self, text: str):
        parameter = {
            "model": self.cfg.modell,
            "max_tokens": self.cfg.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": text}],
            "output_config": {
                "format": {"type": "json_schema", "schema": SCHEMA},
                "effort": self.cfg.effort,
            },
        }

        if self._mit_fallback:
            try:
                return self._client.beta.messages.create(
                    betas=[FALLBACK_BETA],
                    extra_body={"fallbacks": "default"},
                    **parameter,
                )
            except Exception as exc:  # noqa: BLE001 - nur die Ausweichlogik abschalten
                if not _betrifft_fallback(exc):
                    raise
                with self._sperre:
                    if self._mit_fallback:
                        log.info(
                            "Serverseitige Ausweichmodelle nicht verfügbar (%s) - weiter ohne.",
                            exc,
                        )
                        self._mit_fallback = False

        return self._client.messages.create(**parameter)

    def _zaehle(self, antwort) -> None:
        nutzung = getattr(antwort, "usage", None)
        with self._sperre:
            self.verbrauch.anfragen += 1
            self.verbrauch.eingabe_tokens += int(getattr(nutzung, "input_tokens", 0) or 0)
            self.verbrauch.ausgabe_tokens += int(getattr(nutzung, "output_tokens", 0) or 0)


class _Abgelehnt(Exception):
    """Ein Sicherheitsfilter hat die Anfrage abgelehnt."""


def aus_abstract(studie: Studie) -> Zusammenfassung | None:
    """Rückfallebene: die Schlussfolgerung des Abstracts, sonst dessen erste Sätze."""
    if not studie.abstract:
        return None

    schluss = _schlussfolgerung(studie.abstract)
    kern = schluss or _erste_saetze(studie.abstract, 2)
    if not kern:
        return None

    return Zusammenfassung(kernaussage=_kuerze(kern, 600), herkunft="abstract")


def _alle_aus_abstract(studien: list[Studie]) -> None:
    for studie in studien:
        studie.zusammenfassung = aus_abstract(studie)


def _anfragetext(studie: Studie) -> str:
    """Was das Modell zu sehen bekommt - nichts weiter als die belegten Angaben."""
    if not studie.abstract:
        return ""

    zeilen = [f"Titel: {studie.titel}"]
    if studie.journal:
        zeilen.append(f"Journal: {studie.journal}")
    if studie.veroeffentlicht:
        zeilen.append(f"Veröffentlicht: {studie.veroeffentlicht.isoformat()}")
    if studie.autoren:
        zeilen.append(f"Autoren: {', '.join(studie.autoren)}")
    zeilen.append(f"\nAbstract:\n{studie.abstract}")
    return "\n".join(zeilen)


def _schlussfolgerung(abstract: str) -> str:
    treffer = _SCHLUSS.search(abstract)
    if not treffer:
        return ""
    rest = abstract[treffer.end() :].strip()
    # Bis zum nächsten Abschnittstitel eines strukturierten Abstracts.
    naechster = _SCHLUSS.search(rest)
    return (rest[: naechster.start()] if naechster else rest).strip()


def _erste_saetze(text: str, anzahl: int) -> str:
    saetze = _SATZENDE.split(text.strip())
    return " ".join(saetze[:anzahl]).strip()


def _kuerze(text: str, grenze: int) -> str:
    text = " ".join(text.split())
    if len(text) <= grenze:
        return text
    schnitt = text.rfind(" ", 0, grenze)
    return text[: schnitt if schnitt > grenze // 2 else grenze].rstrip() + " …"


def _betrifft_fallback(exc: Exception) -> bool:
    """Weist die SDK oder die API die Ausweich-Parameter zurück?"""
    if isinstance(exc, TypeError):
        return True
    text = str(exc).lower()
    return "fallback" in text or "beta" in text
