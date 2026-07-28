"""HTML-Ausgabe der Tagesübersicht."""

from __future__ import annotations

from datetime import date, datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from .digest import Digest, SourceStatus, Story

_ASSETS = Path(__file__).parent / "assets"

WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
MONTHS = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)


def render_digest(digest: Digest, *, timezone: str = "Europe/Berlin") -> str:
    tz = ZoneInfo(timezone)
    local = digest.generated_at.astimezone(tz)

    parts = [
        _head(f"Nachrichten – {local:%d.%m.%Y}"),
        _header(digest, local),
        '<main class="wrap">',
    ]

    if digest.total_stories == 0:
        parts.append(
            '<p class="empty">Keine Meldungen im gewählten Zeitfenster. '
            "Prüfe den Quellen-Status weiter unten.</p>"
        )

    if digest.top_stories:
        parts.append(_top_section(digest, tz))

    for section in digest.sections:
        if not section.stories:
            continue
        parts.append(
            f'<section id="{escape(section.key)}">'
            f"<h2>{escape(section.label)}"
            f'<span class="count">'
            f"{_count(len(section.stories), 'Meldung', 'Meldungen')}</span></h2>"
            f"{_story_list(section.stories, tz)}"
            "</section>"
        )

    parts.append(_footer(digest, local, tz))
    parts.append("</main></body></html>")
    return "\n".join(parts)


def render_archive_index(entries: list[date], *, timezone: str = "Europe/Berlin") -> str:
    """Übersichtsseite über alle archivierten Tage, neueste zuerst."""
    items = "\n".join(
        f'<li><a href="{day.isoformat()}.html">{_long_date(day)}</a>'
        f'<span class="weekday">{WEEKDAYS[day.weekday()]}</span></li>'
        for day in sorted(entries, reverse=True)
    )
    body = (
        f"{_head('Archiv – Nachrichtenübersicht')}"
        '<header class="page"><div class="wrap">'
        "<h1>Archiv</h1>"
        f'<p class="dateline">{_count(len(entries), "Ausgabe", "Ausgaben")}</p>'
        '<a class="back" href="../index.html">← Zur aktuellen Ausgabe</a>'
        "</div></header>"
        f'<main class="wrap"><ul class="archive">{items}</ul></main>'
        "</body></html>"
    )
    return body


# --- Bausteine ------------------------------------------------------------


def _head(title: str) -> str:
    css = (_ASSETS / "style.css").read_text(encoding="utf-8")
    return (
        "<!DOCTYPE html>"
        '<html lang="de"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{escape(title)}</title>"
        f"<style>{css}</style>"
        "</head><body>"
    )


def _header(digest: Digest, local: datetime) -> str:
    nav = "".join(
        f'<a href="#{escape(section.key)}">{escape(section.label)}</a>'
        for section in digest.sections
        if section.stories
    )
    failed = len(digest.failed_sources)
    meta = (
        f"{_count(digest.total_stories, 'Meldung', 'Meldungen')} aus "
        f"{_count(len(digest.ok_sources), 'Quelle', 'Quellen')} · "
        f"Zeitfenster {_count(digest.window_hours, 'Stunde', 'Stunden')}"
    )
    if failed:
        meta += f" · {_count(failed, 'Quelle', 'Quellen')} nicht erreichbar"

    return (
        '<header class="page"><div class="wrap">'
        "<h1>Nachrichtenüberblick</h1>"
        f'<p class="dateline">{WEEKDAYS[local.weekday()]}, {_long_date(local.date())} · '
        f"Stand {local:%H:%M} Uhr</p>"
        f'<p class="meta">{escape(meta)}</p>'
        f'<nav class="categories">{nav}</nav>'
        "</div></header>"
    )


def _top_section(digest: Digest, tz: ZoneInfo) -> str:
    return (
        '<section class="top" id="top-themen">'
        "<h2>Top-Themen</h2>"
        '<p class="section-note">Meldungen, über die mehrere Quellen gleichzeitig berichten.</p>'
        f"{_story_list(digest.top_stories, tz, show_badge=True)}"
        "</section>"
    )


def _story_list(stories: list[Story], tz: ZoneInfo, *, show_badge: bool = False) -> str:
    items = "\n".join(_story_item(story, tz, show_badge=show_badge) for story in stories)
    return f'<ol class="stories">{items}</ol>'


def _story_item(story: Story, tz: ZoneInfo, *, show_badge: bool) -> str:
    article = story.article
    byline = [f'<span class="source">{escape(article.source_name)}</span>']

    if show_badge and story.source_count > 1:
        byline.append(f'<span class="badge">{story.source_count} Quellen</span>')

    if article.published:
        stamp = article.published.astimezone(tz)
        byline.append(f'<time datetime="{stamp.isoformat()}">{stamp:%H:%M} Uhr</time>')

    others = _other_sources(story)
    if others:
        byline.append(f'<span class="also">auch bei {others}</span>')

    summary = (
        f'<p class="summary">{escape(article.summary)}</p>' if article.summary else ""
    )

    return (
        '<li class="story">'
        f'<h3><a href="{escape(article.link, quote=True)}" rel="noopener">'
        f"{escape(article.title)}</a></h3>"
        f"{summary}"
        f'<div class="byline">{"".join(byline)}</div>'
        "</li>"
    )


def _other_sources(story: Story) -> str:
    """Links auf die übrigen Quellen desselben Themas."""
    seen = {story.article.source_name}
    links = []
    for duplicate in story.duplicates:
        if duplicate.source_name in seen:
            continue
        seen.add(duplicate.source_name)
        links.append(
            f'<a href="{escape(duplicate.link, quote=True)}" rel="noopener">'
            f"{escape(duplicate.source_name)}</a>"
        )
    return ", ".join(links)


def _footer(digest: Digest, local: datetime, tz: ZoneInfo) -> str:
    return (
        '<footer class="page">'
        "<h2>Quellen-Status</h2>"
        f'<ul class="status">{"".join(_status_item(s) for s in digest.sources)}</ul>'
        f"<p>Automatisch erzeugt am {local:%d.%m.%Y um %H:%M} Uhr ({_tz_label(local)}). "
        'Alle Rechte an den verlinkten Inhalten liegen bei den jeweiligen Anbietern. '
        '<a href="archiv/index.html">Archiv</a></p>'
        "</footer>"
    )


def _status_item(status: SourceStatus) -> str:
    if status.ok:
        return f"<li>{escape(status.name)} ({status.article_count})</li>"
    return (
        f'<li class="failed">{escape(status.name)} – {escape(status.error or "Fehler")}</li>'
    )


def _count(amount: int, singular: str, plural: str) -> str:
    return f"{amount} {singular if amount == 1 else plural}"


def _tz_label(moment: datetime) -> str:
    return moment.tzname() or "UTC"


def _long_date(day: date) -> str:
    return f"{day.day}. {MONTHS[day.month - 1]} {day.year}"
