"""Laden und Prüfen der studies.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path


class ConfigError(Exception):
    """Die Konfigurationsdatei ist unbrauchbar."""


#: Hosts, hinter denen eine wissenschaftliche Publikation vermutet wird.
#: Nur Links auf diese Domains gelten als Studie - alles andere auf der Seite
#: (Navigation, Newsletter-Anmeldung, Social Media) fliegt damit heraus.
STANDARD_VERLAGS_HOSTS: tuple[str, ...] = (
    "doi.org",
    "dx.doi.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "nejm.org",
    "evidence.nejm.org",
    "thelancet.com",
    "jamanetwork.com",
    "bmj.com",
    "atsjournals.org",
    "ahajournals.org",
    "acpjournals.org",
    "annalsofsurgery.com",
    "link.springer.com",
    "ccforum.biomedcentral.com",
    "biomedcentral.com",
    "sciencedirect.com",
    "onlinelibrary.wiley.com",
    "academic.oup.com",
    "journals.lww.com",
    "chestjournal.org",
    "journal.chestnet.org",
    "nature.com",
    "science.org",
    "cell.com",
    "frontiersin.org",
    "mdpi.com",
    "karger.com",
    "tandfonline.com",
    "sagepub.com",
    "physiology.org",
    "asahq.org",
    "pubs.asahq.org",
    "esicm.org",
    "intensivecarejournal.com",
    "icm-experimental.springeropen.com",
    "medrxiv.org",
    "biorxiv.org",
)


@dataclass(frozen=True)
class Quelle:
    name: str
    url: str


@dataclass(frozen=True)
class Einstellungen:
    #: Obergrenze neuer Studien pro Lauf - schützt vor Kosten- und Laufzeitausreißern,
    #: wenn die Quelle einmal sehr viele Einträge auf einmal veröffentlicht.
    max_studien: int = 20
    timeout_sekunden: int = 30
    wiederholungen: int = 2
    zeitzone: str = "Europe/Berlin"
    verlags_hosts: tuple[str, ...] = STANDARD_VERLAGS_HOSTS
    #: Kürzeste Länge eines Linktexts, damit er als Studientitel durchgeht.
    min_titel_zeichen: int = 25


@dataclass(frozen=True)
class Anreicherung:
    crossref: bool = True
    pubmed: bool = True
    #: Crossref und NCBI bitten um eine Kontaktadresse ("polite pool"); wer sie
    #: mitschickt, bekommt stabilere Antwortzeiten.
    kontakt_email: str = ""
    ncbi_api_key_env: str = "NCBI_API_KEY"
    parallel: int = 4


@dataclass(frozen=True)
class Zusammenfassung:
    aktiv: bool = True
    modell: str = "claude-opus-5"
    #: low reicht für das Verdichten eines Abstracts und hält die Kosten unten.
    effort: str = "low"
    max_tokens: int = 2000
    api_key_env: str = "ANTHROPIC_API_KEY"
    parallel: int = 4


@dataclass(frozen=True)
class Config:
    quelle: Quelle
    einstellungen: Einstellungen = field(default_factory=Einstellungen)
    anreicherung: Anreicherung = field(default_factory=Anreicherung)
    zusammenfassung: Zusammenfassung = field(default_factory=Zusammenfassung)


_ERLAUBTE_EFFORTS = ("low", "medium", "high", "xhigh", "max")


def load(path: str | Path) -> Config:
    """Liest die Konfiguration und prüft sie auf die üblichen Tippfehler."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"Konfigurationsdatei nicht gefunden: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} ist kein gültiges TOML: {exc}") from None

    return from_dict(raw, source=str(path))


def from_dict(raw: dict, source: str = "<dict>") -> Config:
    quelle_raw = raw.get("quelle") or {}
    for pflicht in ("name", "url"):
        if not quelle_raw.get(pflicht):
            raise ConfigError(f"{source}: [quelle] braucht das Feld '{pflicht}'.")
    url = str(quelle_raw["url"])
    if not url.startswith(("http://", "https://")):
        raise ConfigError(f"{source}: [quelle].url muss mit http:// oder https:// beginnen.")

    return Config(
        quelle=Quelle(name=str(quelle_raw["name"]), url=url),
        einstellungen=_einstellungen(raw.get("einstellungen") or {}, source),
        anreicherung=_anreicherung(raw.get("anreicherung") or {}, source),
        zusammenfassung=_zusammenfassung(raw.get("zusammenfassung") or {}, source),
    )


def mit_max_studien(cfg: Config, anzahl: int) -> Config:
    return replace(cfg, einstellungen=replace(cfg.einstellungen, max_studien=anzahl))


def ohne_zusammenfassung(cfg: Config) -> Config:
    return replace(cfg, zusammenfassung=replace(cfg.zusammenfassung, aktiv=False))


def _einstellungen(raw: dict, source: str) -> Einstellungen:
    werte: dict[str, object] = {}
    for key in ("max_studien", "timeout_sekunden", "wiederholungen", "min_titel_zeichen"):
        if key in raw:
            werte[key] = _zahl(raw[key], key, source, minimum=0 if key == "wiederholungen" else 1)
    if "zeitzone" in raw:
        werte["zeitzone"] = _text(raw["zeitzone"], "zeitzone", source)
    if "verlags_hosts" in raw:
        hosts = raw["verlags_hosts"]
        if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
            raise ConfigError(f"{source}: [einstellungen].verlags_hosts muss eine Liste von Texten sein.")
        if not hosts:
            raise ConfigError(f"{source}: [einstellungen].verlags_hosts darf nicht leer sein.")
        werte["verlags_hosts"] = tuple(h.strip().lower().lstrip(".") for h in hosts)
    return Einstellungen(**werte)  # type: ignore[arg-type]


def _anreicherung(raw: dict, source: str) -> Anreicherung:
    werte: dict[str, object] = {}
    for key in ("crossref", "pubmed"):
        if key in raw:
            werte[key] = _wahrheitswert(raw[key], key, source)
    for key in ("kontakt_email", "ncbi_api_key_env"):
        if key in raw:
            werte[key] = _text(raw[key], key, source)
    if "parallel" in raw:
        werte["parallel"] = _zahl(raw["parallel"], "parallel", source, minimum=1)
    return Anreicherung(**werte)  # type: ignore[arg-type]


def _zusammenfassung(raw: dict, source: str) -> Zusammenfassung:
    werte: dict[str, object] = {}
    if "aktiv" in raw:
        werte["aktiv"] = _wahrheitswert(raw["aktiv"], "aktiv", source)
    for key in ("modell", "api_key_env"):
        if key in raw:
            werte[key] = _text(raw[key], key, source)
    for key in ("max_tokens", "parallel"):
        if key in raw:
            werte[key] = _zahl(raw[key], key, source, minimum=1)
    if "effort" in raw:
        effort = _text(raw["effort"], "effort", source)
        if effort not in _ERLAUBTE_EFFORTS:
            erlaubt = ", ".join(_ERLAUBTE_EFFORTS)
            raise ConfigError(
                f"{source}: [zusammenfassung].effort muss einer von {erlaubt} sein, war '{effort}'."
            )
        werte["effort"] = effort
    return Zusammenfassung(**werte)  # type: ignore[arg-type]


def _zahl(wert: object, key: str, source: str, *, minimum: int) -> int:
    # bool ist in Python ein int - hier aber nie gemeint.
    if not isinstance(wert, int) or isinstance(wert, bool) or wert < minimum:
        wunsch = "eine positive Zahl" if minimum else "eine Zahl ab 0"
        raise ConfigError(f"{source}: {key} muss {wunsch} sein.")
    return wert


def _text(wert: object, key: str, source: str) -> str:
    if not isinstance(wert, str):
        raise ConfigError(f"{source}: {key} muss ein Text sein.")
    return wert


def _wahrheitswert(wert: object, key: str, source: str) -> bool:
    if not isinstance(wert, bool):
        raise ConfigError(f"{source}: {key} muss true oder false sein.")
    return wert
