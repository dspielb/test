"""Parser für RSS 2.0, RSS 1.0 (RDF) und Atom.

Bewusst nur mit der Standardbibliothek umgesetzt: die Feeds der großen
Nachrichtenhäuser sind wohlgeformt, und so bleibt das Projekt ohne
Abhängigkeiten installierbar.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

ATOM = "http://www.w3.org/2005/Atom"
RSS1 = "http://purl.org/rss/1.0/"
DC = "http://purl.org/dc/elements/1.1/"

#: Tracking-Parameter, die beim Vergleich zweier Links ignoriert werden.
_TRACKING_PREFIXES = ("utm_", "at_")
_TRACKING_KEYS = {"fbclid", "gclid", "wt_mc", "wtrid", "ref", "cmpid", "ico", "sara_ecid"}

_SUMMARY_MAX_CHARS = 320


class ParseError(Exception):
    """Der Feed-Inhalt ließ sich nicht als RSS/Atom lesen."""


@dataclass(frozen=True)
class Article:
    title: str
    link: str
    summary: str
    published: datetime | None
    source_id: str
    source_name: str
    category: str

    @property
    def canonical_link(self) -> str:
        return canonical_url(self.link)


def parse_feed(
    data: bytes | str,
    *,
    source_id: str,
    source_name: str,
    category: str,
) -> list[Article]:
    """Wandelt einen Feed in Artikel um. Defekte Einzeleinträge werden übersprungen."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ParseError(str(exc)) from None

    nodes = (
        root.findall(".//item")
        or root.findall(f".//{{{RSS1}}}item")
        or root.findall(f".//{{{ATOM}}}entry")
    )

    articles: list[Article] = []
    for node in nodes:
        title = _clean(_first_text(node, ("title", f"{{{RSS1}}}title", f"{{{ATOM}}}title")))
        link = _extract_link(node)
        if not title or not link:
            continue

        articles.append(
            Article(
                title=title,
                link=link,
                summary=_extract_summary(node),
                published=_extract_published(node),
                source_id=source_id,
                source_name=source_name,
                category=category,
            )
        )
    return articles


def canonical_url(url: str) -> str:
    """Entfernt Tracking-Parameter und Fragmente, damit Links vergleichbar werden."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()

    keep = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES) and key.lower() not in _TRACKING_KEYS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(keep), ""))


# --- interne Helfer -------------------------------------------------------


def _extract_link(node: ET.Element) -> str:
    for tag in ("link", f"{{{RSS1}}}link"):
        text = _text_of(node.find(tag))
        if text:
            return text

    # Atom: <link rel="alternate" href="..."/>; rel fehlt oft und heißt dann alternate.
    candidates = node.findall(f"{{{ATOM}}}link")
    for wanted in ("alternate", None):
        for element in candidates:
            rel = element.get("rel")
            if rel == wanted or (wanted == "alternate" and rel is None):
                href = (element.get("href") or "").strip()
                if href:
                    return href

    for tag in ("guid", f"{{{ATOM}}}id", f"{{{RSS1}}}about"):
        text = _text_of(node.find(tag))
        if text.startswith(("http://", "https://")):
            return text
    return ""


def _extract_summary(node: ET.Element) -> str:
    raw = _first_text(
        node,
        (
            "description",
            f"{{{RSS1}}}description",
            f"{{{ATOM}}}summary",
            f"{{{DC}}}description",
            f"{{{ATOM}}}content",
            "{http://purl.org/rss/1.0/modules/content/}encoded",
        ),
    )
    text = _clean(strip_html(raw))
    if len(text) <= _SUMMARY_MAX_CHARS:
        return text
    cut = text[:_SUMMARY_MAX_CHARS].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.–-") + " …"


def _extract_published(node: ET.Element) -> datetime | None:
    for tag in (
        "pubDate",
        f"{{{DC}}}date",
        f"{{{ATOM}}}published",
        f"{{{ATOM}}}updated",
        "lastBuildDate",
    ):
        text = _text_of(node.find(tag))
        if text:
            parsed = parse_datetime(text)
            if parsed:
                return parsed
    return None


def parse_datetime(value: str) -> datetime | None:
    """Liest RFC-822- (RSS) und ISO-8601-Zeitstempel (Atom) als UTC-Datum."""
    value = value.strip()
    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        parsed = None

    if parsed is None:
        iso = value.replace("Z", "+00:00")
        # Manche Feeds liefern Sekundenbruchteile mit mehr als 6 Stellen.
        iso = re.sub(r"(\.\d{6})\d+", r"\1", iso)
        try:
            parsed = datetime.fromisoformat(iso)
        except ValueError:
            return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("p", "br", "div", "li"):
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def strip_html(value: str) -> str:
    """Entfernt Markup aus Feed-Beschreibungen."""
    if not value:
        return ""
    stripper = _Stripper()
    try:
        stripper.feed(value)
        stripper.close()
    except Exception:  # kaputtes Markup: lieber grob säubern als aufgeben
        return re.sub(r"<[^>]+>", " ", value)
    return "".join(stripper.parts)


def _first_text(node: ET.Element, tags: tuple[str, ...]) -> str:
    for tag in tags:
        text = _text_of(node.find(tag))
        if text:
            return text
    return ""


def _text_of(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()
