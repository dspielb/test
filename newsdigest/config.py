"""Laden und Validieren der feeds.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Die Konfigurationsdatei ist unbrauchbar."""


@dataclass(frozen=True)
class Feed:
    id: str
    name: str
    url: str
    category: str
    optional: bool = False


@dataclass(frozen=True)
class Settings:
    window_hours: int = 24
    max_per_source: int = 12
    max_per_category: int = 40
    timezone: str = "Europe/Berlin"
    timeout_seconds: int = 20
    retries: int = 2


@dataclass(frozen=True)
class Config:
    settings: Settings
    #: Kategorie-Schlüssel -> Anzeigename, in der Reihenfolge aus der TOML-Datei.
    categories: dict[str, str]
    feeds: list[Feed] = field(default_factory=list)

    def feeds_by_category(self, category: str) -> list[Feed]:
        return [f for f in self.feeds if f.category == category]


#: Einstellungen, die echt größer als null sein müssen.
_POSITIVE_SETTINGS = (
    "window_hours",
    "max_per_source",
    "max_per_category",
    "timeout_seconds",
)
#: Einstellungen, bei denen null erlaubt ist (retries = 0 heißt: kein zweiter Versuch).
_NON_NEGATIVE_SETTINGS = ("retries",)


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
    categories = raw.get("categories") or {}
    if not categories:
        raise ConfigError(f"{source}: Abschnitt [categories] fehlt oder ist leer.")
    for key, label in categories.items():
        if not isinstance(label, str):
            raise ConfigError(f"{source}: Kategorie '{key}' braucht einen Text als Anzeigename.")

    settings = _settings_from(raw.get("settings") or {}, source)

    feeds: list[Feed] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw.get("feed") or [], start=1):
        where = f"{source}: [[feed]] Nr. {index}"
        for required in ("id", "name", "url", "category"):
            if not entry.get(required):
                raise ConfigError(f"{where} hat kein Feld '{required}'.")

        feed_id = str(entry["id"])
        if feed_id in seen:
            raise ConfigError(f"{where}: doppelte id '{feed_id}'.")
        seen.add(feed_id)

        category = str(entry["category"])
        if category not in categories:
            known = ", ".join(categories)
            raise ConfigError(
                f"{where}: Kategorie '{category}' ist unbekannt. Bekannt sind: {known}."
            )

        feeds.append(
            Feed(
                id=feed_id,
                name=str(entry["name"]),
                url=str(entry["url"]),
                category=category,
                optional=bool(entry.get("optional", False)),
            )
        )

    if not feeds:
        raise ConfigError(f"{source}: keine [[feed]]-Einträge gefunden.")

    return Config(settings=settings, categories=dict(categories), feeds=feeds)


def _settings_from(raw: dict, source: str) -> Settings:
    values: dict[str, object] = {}
    for key, minimum in (
        *((k, 1) for k in _POSITIVE_SETTINGS),
        *((k, 0) for k in _NON_NEGATIVE_SETTINGS),
    ):
        if key not in raw:
            continue
        value = raw[key]
        # bool ist in Python ein int - hier aber nie gemeint.
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            wanted = "eine positive Zahl" if minimum else "eine Zahl ab 0"
            raise ConfigError(f"{source}: [settings].{key} muss {wanted} sein.")
        values[key] = value
    if "timezone" in raw:
        if not isinstance(raw["timezone"], str):
            raise ConfigError(f"{source}: [settings].timezone muss ein Text sein.")
        values["timezone"] = raw["timezone"]
    return Settings(**values)  # type: ignore[arg-type]
