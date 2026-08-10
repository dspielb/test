"""Tägliche Übersicht neuer Studien aus dem Critical Care Reviews Journal Watch.

Der Ablauf besteht aus fünf Schritten, die sich einzeln testen lassen:

1. ``scrape``    – die Übersichtsseite holen und Studienlinks herausziehen
2. ``state``     – bereits gesehene Studien aussortieren
3. ``enrich``    – Metadaten und Abstract über Crossref und PubMed nachladen
4. ``summarize`` – deutsche Zusammenfassung über die Claude-API erzeugen
5. ``render``    – HTML-Seite und Tagesarchiv schreiben
"""

__version__ = "1.0.0"
