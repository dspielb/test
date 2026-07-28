"""Aus den Rohartikeln die Tagesübersicht bauen.

Drei Schritte: nach Zeitfenster filtern, Duplikate zusammenführen und die
Themen finden, über die mehrere Quellen gleichzeitig berichten.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .config import Config
from .fetch import FetchResult
from .parse import Article

#: Häufige Wörter, die für den Themenvergleich nichts beitragen.
_STOPWORDS = frozenset(
    """
    aber alle allem allen aller alles als also andere anderen auch auf aus bei beim bin bis bist
    dabei dafür damit dann dass dazu dein dem den denn der des dessen die dies diese diesem diesen
    dieser dieses doch dort durch ein eine einem einen einer eines er erst es etwa euch für gegen
    gibt hat hatte haben hier hin ihr ihre ihrem ihren ihrer im immer in ins ist jetzt kann kein
    keine man mehr mein mit nach neu neue neuem neuen neuer neues nicht noch nun nur ob oder ohne
    schon sein seine seit sich sie
    sind so soll sowie über um und uns unter vom von vor war waren was weil weiter wenn werden
    wie wieder wir wird wirst wo zu zum zur zwei
    a about after all also an and are as at be been but by can could for from has have how in into
    is it its just like more new not now of on one only or our out over said say says than that the
    their them then there these they this to two up was we were what when which who will with would
    """.split()
)

_WORD = re.compile(r"[\wäöüßÄÖÜ]+", re.UNICODE)
_MIN_TOKEN_LENGTH = 4
#: Ab diesem Anteil gemeinsamer Stichwörter gelten zwei Schlagzeilen als dasselbe Thema.
_CLUSTER_THRESHOLD = 0.45


@dataclass
class Story:
    """Ein Thema - meist ein Artikel, bei Übereinstimmung mehrere aus verschiedenen Quellen."""

    article: Article
    duplicates: list[Article] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        """Alle berichtenden Quellen, Hauptquelle zuerst, ohne Wiederholungen."""
        names = [self.article.source_name]
        for other in self.duplicates:
            if other.source_name not in names:
                names.append(other.source_name)
        return names

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def published(self) -> datetime | None:
        return self.article.published


@dataclass
class SourceStatus:
    id: str
    name: str
    category: str
    ok: bool
    article_count: int
    optional: bool
    error: str | None = None


@dataclass
class CategorySection:
    key: str
    label: str
    stories: list[Story]


@dataclass
class Digest:
    generated_at: datetime
    window_hours: int
    sections: list[CategorySection]
    top_stories: list[Story]
    sources: list[SourceStatus]

    @property
    def total_stories(self) -> int:
        return sum(len(section.stories) for section in self.sections)

    @property
    def failed_sources(self) -> list[SourceStatus]:
        return [s for s in self.sources if not s.ok]

    @property
    def ok_sources(self) -> list[SourceStatus]:
        return [s for s in self.sources if s.ok]


def build(
    results: list[FetchResult],
    config: Config,
    *,
    now: datetime | None = None,
) -> Digest:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=config.settings.window_hours)

    sources = [
        SourceStatus(
            id=result.feed.id,
            name=result.feed.name,
            category=result.feed.category,
            ok=result.ok,
            article_count=len(result.articles),
            optional=result.feed.optional,
            error=result.error,
        )
        for result in results
    ]

    sections: list[CategorySection] = []
    for key, label in config.categories.items():
        articles: list[Article] = []
        for result in results:
            if result.feed.category != key:
                continue
            fresh = [a for a in result.articles if _within(a, cutoff)]
            fresh.sort(key=_sort_key, reverse=True)
            articles.extend(fresh[: config.settings.max_per_source])

        stories = cluster(articles)
        stories.sort(key=lambda s: (s.source_count > 1, _sort_key(s.article)), reverse=True)
        sections.append(
            CategorySection(
                key=key,
                label=label,
                stories=stories[: config.settings.max_per_category],
            )
        )

    return Digest(
        generated_at=now,
        window_hours=config.settings.window_hours,
        sections=sections,
        top_stories=_top_stories(sections),
        sources=sources,
    )


def cluster(articles: list[Article]) -> list[Story]:
    """Fasst gleiche Meldungen zusammen - erst über den Link, dann über die Schlagzeile."""
    stories: list[Story] = []
    by_link: dict[str, Story] = {}
    fingerprints: list[tuple[frozenset[str], Story]] = []

    for article in articles:
        link = article.canonical_link
        existing = by_link.get(link)
        if existing is not None:
            _attach(existing, article)
            continue

        tokens = keywords(article.title)
        match = _best_match(tokens, fingerprints)
        if match is not None:
            _attach(match, article)
            by_link.setdefault(link, match)
            continue

        story = Story(article=article)
        stories.append(story)
        by_link[link] = story
        if tokens:
            fingerprints.append((tokens, story))

    return stories


def keywords(title: str) -> frozenset[str]:
    """Bedeutungstragende Stichwörter einer Schlagzeile, normalisiert für den Vergleich."""
    words = set()
    for match in _WORD.findall(title.lower()):
        word = _fold(match)
        if len(word) >= _MIN_TOKEN_LENGTH and word not in _STOPWORDS:
            words.add(word)
    return frozenset(words)


def _fold(word: str) -> str:
    """Umlaute und Akzente entfernen, damit 'Türkei' und 'Turkei' zusammenfinden."""
    replaced = word.translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    decomposed = unicodedata.normalize("NFKD", replaced)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def similarity(left: frozenset[str], right: frozenset[str]) -> float:
    """Jaccard-Ähnlichkeit zweier Stichwortmengen."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _best_match(
    tokens: frozenset[str],
    fingerprints: list[tuple[frozenset[str], Story]],
) -> Story | None:
    if len(tokens) < 2:
        return None
    best: Story | None = None
    best_score = _CLUSTER_THRESHOLD
    for other, story in fingerprints:
        score = similarity(tokens, other)
        if score >= best_score:
            best, best_score = story, score
    return best


def _attach(story: Story, article: Article) -> None:
    """Artikel an ein Thema hängen; die frühere Meldung bleibt die Hauptquelle."""
    if _sort_key(article) > _sort_key(story.article):
        story.duplicates.insert(0, story.article)
        story.article = article
    else:
        story.duplicates.append(article)


def _top_stories(sections: list[CategorySection], limit: int = 8) -> list[Story]:
    """Themen, die mindestens zwei unterschiedliche Quellen melden.

    Zusammengefasst wird innerhalb einer Kategorie - dieselbe Meldung kann
    also mehrfach vorliegen, etwa als Agenturticker und als Ressortmeldung.
    In der Top-Liste soll ein Thema aber nur einmal stehen, und zwar mit der
    breitesten Quellenlage.
    """
    multi = [s for section in sections for s in section.stories if s.source_count > 1]
    multi.sort(key=lambda s: (s.source_count, _sort_key(s.article)), reverse=True)

    chosen: list[Story] = []
    seen_links: set[str] = set()
    fingerprints: list[frozenset[str]] = []

    for story in multi:
        link = story.article.canonical_link
        if link in seen_links:
            continue
        tokens = keywords(story.article.title)
        if len(tokens) >= 2 and any(
            similarity(tokens, other) >= _CLUSTER_THRESHOLD for other in fingerprints
        ):
            continue

        chosen.append(story)
        seen_links.add(link)
        seen_links.update(d.canonical_link for d in story.duplicates)
        fingerprints.append(tokens)
        if len(chosen) == limit:
            break

    return chosen


def _within(article: Article, cutoff: datetime) -> bool:
    # Artikel ohne Zeitstempel behalten wir - lieber zu viel als eine fehlende Meldung.
    return article.published is None or article.published >= cutoff


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _sort_key(article: Article) -> datetime:
    return article.published or _EPOCH
