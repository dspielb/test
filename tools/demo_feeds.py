#!/usr/bin/env python3
"""Erzeugt Beispiel-Feeds mit aktuellen Zeitstempeln.

Damit lässt sich die Übersicht ohne Netzzugang ansehen:

    python3 tools/demo_feeds.py /tmp/demo
    python3 -m newsdigest --offline-dir /tmp/demo --out /tmp/vorschau

Die Inhalte sind frei erfunden.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from newsdigest import config as config_module  # noqa: E402

#: (Stunden alt, Schlagzeile, Anriss) - je Kategorie.
#: Einige Themen tauchen bewusst in mehreren Quellen auf, damit die
#: Top-Themen-Erkennung sichtbar wird.
STORIES: dict[str, list[tuple[int, str, str]]] = {
    "agenturen": [
        (1, "Bundestag beschließt Reform der Pflegeversicherung",
         "Die Abgeordneten stimmten am Vormittag mit breiter Mehrheit für das Gesetz."),
        (2, "EU-Kommission legt Vorschlag für Zölle vor",
         "Betroffen wären vor allem Einfuhren aus dem Bereich der Elektromobilität."),
        (4, "Erdbeben der Stärke 6,1 erschüttert Küstenregion",
         "Über Schäden ist bislang wenig bekannt, Rettungskräfte sind im Einsatz."),
        (6, "Tarifverhandlungen im öffentlichen Dienst vertagt",
         "Die Gewerkschaft kündigte weitere Warnstreiks an."),
    ],
    "deutschland": [
        (1, "Bundestag beschließt Reform der Pflegeversicherung mit großer Mehrheit",
         "Kritik kommt von den Sozialverbänden, die die Finanzierung bemängeln."),
        (3, "Hochwasserlage im Süden entspannt sich langsam",
         "Die Pegelstände sinken, die Aufräumarbeiten haben begonnen."),
        (5, "Deutlich mehr Fahrgäste im Regionalverkehr",
         "Der Verband meldet ein Plus von acht Prozent gegenüber dem Vorjahr."),
        (7, "Streit über Grundsteuer geht in die nächste Runde",
         "Mehrere Kommunen kündigen an, die Hebesätze anzupassen."),
        (9, "Wetterdienst warnt vor schweren Gewittern",
         "Betroffen sind vor allem der Westen und die Mitte des Landes."),
    ],
    "wirtschaft": [
        (2, "EU-Kommission legt Vorschlag für neue Zölle vor",
         "Die Industrie warnt vor Gegenmaßnahmen und steigenden Preisen."),
        (3, "Inflationsrate sinkt auf 2,1 Prozent",
         "Vor allem Energiepreise dämpften den Anstieg der Lebenshaltungskosten."),
        (5, "Autobauer meldet Rückgang beim Absatz",
         "Das Unternehmen begründet die Zahlen mit der schwachen Nachfrage in Asien."),
        (8, "Zentralbank belässt Leitzins unverändert",
         "Die Notenbank verweist auf die unsichere Konjunkturlage."),
    ],
    "tech": [
        (1, "Kritische Sicherheitslücke in verbreiteter Server-Software",
         "Ein Update steht bereit, Administratoren sollten zügig einspielen."),
        (4, "Neues Rechenzentrum soll mit Abwärme heizen",
         "Der Betreiber will damit mehrere tausend Haushalte versorgen."),
        (6, "Behörden setzen künftig stärker auf offene Software",
         "Ein Pilotprojekt läuft bereits in zwei Bundesländern."),
        (10, "Studie: Elektroschrott wächst schneller als das Recycling",
         "Nur ein Fünftel der Altgeräte wird fachgerecht verwertet."),
    ],
}


def build_feed(feed_name: str, stories: list[tuple[int, str, str]], now: datetime) -> str:
    items = []
    for hours_ago, title, summary in stories:
        published = now - timedelta(hours=hours_ago)
        slug = abs(hash(title)) % 10**7
        items.append(
            "  <item>\n"
            f"    <title>{escape(title)}</title>\n"
            f"    <link>https://beispiel.invalid/{slug}</link>\n"
            f"    <description>{escape(summary)}</description>\n"
            f"    <pubDate>{published.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>\n"
            "  </item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>\n'
        f"  <title>{escape(feed_name)}</title>\n"
        "  <link>https://beispiel.invalid/</link>\n"
        "  <description>Beispieldaten</description>\n"
        + "\n".join(items)
        + "\n</channel></rss>\n"
    )


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else Path("demo-feeds")
    target.mkdir(parents=True, exist_ok=True)

    cfg = config_module.load(Path(__file__).resolve().parent.parent / "feeds.toml")
    now = datetime.now(timezone.utc)

    for index, feed in enumerate(cfg.feeds):
        pool = STORIES.get(feed.category, [])
        # Jede Quelle bekommt einen leicht versetzten Ausschnitt, damit sich
        # Überschneidungen und Unterschiede zwischen den Quellen zeigen.
        selection = pool[index % 2 :] if len(pool) > 2 else pool
        (target / f"{feed.id}.xml").write_text(
            build_feed(feed.name, selection, now), encoding="utf-8"
        )

    print(f"{len(cfg.feeds)} Beispiel-Feeds geschrieben nach {target}")
    print(f"Weiter mit: python3 -m newsdigest --offline-dir {target} --out vorschau")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
