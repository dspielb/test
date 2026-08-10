"""Ein kleiner HTTP-Helfer mit Timeout, Wiederholung und Offline-Modus."""

from __future__ import annotations

import gzip
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; StudyWatch/1.0; +https://github.com/dspielb/test) Python-urllib"
)


class AbrufFehler(Exception):
    """Die Ressource war nicht erreichbar oder nicht lesbar."""


class Netz:
    """Holt Ressourcen über HTTP. Ein Ausfall wirft AbrufFehler, nichts anderes."""

    def __init__(
        self,
        *,
        timeout: int = 30,
        wiederholungen: int = 2,
        kontakt_email: str = "",
        offline: bool = False,
    ) -> None:
        self.timeout = timeout
        self.wiederholungen = wiederholungen
        self.kontakt_email = kontakt_email
        self.offline = offline

    def hole(self, url: str, *, accept: str = "*/*") -> bytes:
        if self.offline:
            raise AbrufFehler("Offline-Modus: kein Netzzugriff erlaubt")

        kopf = {
            "User-Agent": self._user_agent(),
            "Accept": accept,
            "Accept-Encoding": "gzip",
        }
        anfrage = urllib.request.Request(url, headers=kopf)

        letzter: Exception | None = None
        for versuch in range(self.wiederholungen + 1):
            try:
                with urllib.request.urlopen(anfrage, timeout=self.timeout) as antwort:
                    rumpf = antwort.read()
                    if antwort.headers.get("Content-Encoding") == "gzip":
                        rumpf = gzip.decompress(rumpf)
                    return rumpf
            except Exception as exc:  # noqa: BLE001 - jeder Fehler ist einen Retry wert
                letzter = exc
                if versuch < self.wiederholungen and _wiederholbar(exc):
                    time.sleep(2**versuch)
                    continue
                break
        raise AbrufFehler(_beschreibe(letzter)) from letzter

    def hole_text(self, url: str, *, accept: str = "text/html") -> str:
        return self.hole(url, accept=accept).decode("utf-8", errors="replace")

    def hole_json(self, url: str) -> dict:
        rohdaten = self.hole(url, accept="application/json")
        try:
            daten = json.loads(rohdaten)
        except json.JSONDecodeError as exc:
            raise AbrufFehler(f"Antwort war kein gültiges JSON: {exc}") from None
        if not isinstance(daten, dict):
            raise AbrufFehler("Antwort war kein JSON-Objekt")
        return daten

    def _user_agent(self) -> str:
        if self.kontakt_email:
            return f"{USER_AGENT} (mailto:{self.kontakt_email})"
        return USER_AGENT


class DateiNetz(Netz):
    """Liest statt aus dem Netz aus einem Verzeichnis - für Tests und Entwicklung.

    Der Dateiname ergibt sich aus der URL, damit sich Antworten einmal ablegen
    und beliebig oft wiederverwenden lassen.
    """

    def __init__(self, verzeichnis: str | Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.verzeichnis = Path(verzeichnis)
        self.offline = False  # das Verzeichnis ist die Quelle, kein Netz nötig

    def hole(self, url: str, *, accept: str = "*/*") -> bytes:
        pfad = self.verzeichnis / dateiname_fuer(url)
        if not pfad.exists():
            raise AbrufFehler(f"keine Offline-Datei {pfad}")
        return pfad.read_bytes()


def dateiname_fuer(url: str) -> str:
    """Ein dateisystemtauglicher Name für eine URL."""
    teile = urllib.parse.urlsplit(url)
    rest = f"{teile.path}?{teile.query}" if teile.query else teile.path
    sicher = "".join(z if z.isalnum() or z in "-_." else "_" for z in rest).strip("_")
    return f"{teile.netloc}__{sicher or 'index'}"[:180]


def _wiederholbar(exc: Exception) -> bool:
    # 4xx außer 408/429 liefern beim zweiten Versuch dasselbe Ergebnis.
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 429) or exc.code >= 500
    return True


def _beschreibe(exc: Exception | None) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"Netzwerkfehler: {exc.reason}"
    if exc is None:
        return "Abruf fehlgeschlagen"
    return f"{type(exc).__name__}: {exc}"
