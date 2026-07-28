"""Feeds parallel abrufen - über HTTP oder aus einem lokalen Verzeichnis."""

from __future__ import annotations

import gzip
import logging
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .config import Config, Feed
from .parse import Article, ParseError, parse_feed

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; NewsDigest/1.0; +https://github.com/dspielb/test) "
    "Python-urllib"
)


@dataclass
class FetchResult:
    feed: Feed
    articles: list[Article]
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def fetch_all(config: Config, *, offline_dir: str | Path | None = None) -> list[FetchResult]:
    """Holt alle Feeds nebenläufig. Ein Ausfall betrifft nie die anderen Quellen."""
    loader = (
        _OfflineLoader(Path(offline_dir))
        if offline_dir
        else _HttpLoader(config.settings.timeout_seconds, config.settings.retries)
    )

    workers = min(12, max(1, len(config.feeds)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda feed: _fetch_one(feed, loader), config.feeds))

    # Reihenfolge der Konfiguration beibehalten, damit die Ausgabe stabil bleibt.
    return results


def _fetch_one(feed: Feed, loader: "_Loader") -> FetchResult:
    try:
        payload = loader.load(feed)
    except Exception as exc:
        message = _describe(exc)
        log.log(
            logging.INFO if feed.optional else logging.WARNING,
            "%s: Abruf fehlgeschlagen (%s)",
            feed.id,
            message,
        )
        return FetchResult(feed=feed, articles=[], error=message)

    try:
        articles = parse_feed(
            payload,
            source_id=feed.id,
            source_name=feed.name,
            category=feed.category,
        )
    except ParseError as exc:
        log.warning("%s: Feed nicht lesbar (%s)", feed.id, exc)
        return FetchResult(feed=feed, articles=[], error=f"Feed nicht lesbar: {exc}")

    if not articles:
        return FetchResult(feed=feed, articles=[], error="Feed enthielt keine Artikel")

    log.info("%s: %d Artikel", feed.id, len(articles))
    return FetchResult(feed=feed, articles=articles)


class _Loader:
    def load(self, feed: Feed) -> bytes:
        raise NotImplementedError


class _HttpLoader(_Loader):
    def __init__(self, timeout: int, retries: int) -> None:
        self.timeout = timeout
        self.retries = retries

    def load(self, feed: Feed) -> bytes:
        request = urllib.request.Request(
            feed.url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
                "Accept-Encoding": "gzip",
            },
        )

        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body
            except Exception as exc:  # noqa: BLE001 - jeder Fehler ist ein Retry wert
                last = exc
                if attempt < self.retries and _retryable(exc):
                    time.sleep(2**attempt)
                    continue
                break
        raise last if last else RuntimeError("Abruf fehlgeschlagen")


class _OfflineLoader(_Loader):
    """Liest <offline_dir>/<feed-id>.xml - für Tests und Entwicklung ohne Netz."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def load(self, feed: Feed) -> bytes:
        path = self.directory / f"{feed.id}.xml"
        if not path.exists():
            raise FileNotFoundError(f"keine Offline-Datei {path}")
        return path.read_bytes()


def _retryable(exc: Exception) -> bool:
    # 4xx außer 408/429 wiederholen sich nur mit demselben Ergebnis.
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 429) or exc.code >= 500
    return True


def _describe(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"Netzwerkfehler: {exc.reason}"
    if isinstance(exc, FileNotFoundError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"
