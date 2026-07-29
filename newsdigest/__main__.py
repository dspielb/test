"""Kommandozeile: python -m newsdigest [Optionen]"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__, config as config_module, digest as digest_module
from .fetch import fetch_all
from .render import render_archive_index, render_digest

log = logging.getLogger("newsdigest")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m newsdigest",
        description="Erzeugt die tägliche Nachrichtenübersicht als HTML-Seite.",
    )
    parser.add_argument(
        "-c", "--config", default="feeds.toml", help="Konfigurationsdatei (Standard: feeds.toml)"
    )
    parser.add_argument(
        "-o", "--out", default="docs", help="Ausgabeverzeichnis (Standard: docs)"
    )
    parser.add_argument(
        "--hours", type=int, help="Zeitfenster in Stunden; überschreibt die Konfiguration"
    )
    parser.add_argument(
        "--offline-dir",
        help="Feeds aus diesem Verzeichnis lesen (<feed-id>.xml) statt über das Netz",
    )
    parser.add_argument(
        "--no-archive", action="store_true", help="Nur index.html schreiben, kein Tagesarchiv"
    )
    parser.add_argument(
        "--date",
        help="Datum des Archiveintrags im Format JJJJ-MM-TT (Standard: heute)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Nur Fehler ausgeben")
    parser.add_argument("-v", "--verbose", action="store_true", help="Ausführliche Ausgabe")
    parser.add_argument("--version", action="version", version=f"newsdigest {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.ERROR if args.quiet else (logging.INFO if args.verbose else logging.WARNING),
        format="%(levelname)s %(message)s",
    )

    try:
        cfg = config_module.load(args.config)
    except config_module.ConfigError as exc:
        print(f"Fehler in der Konfiguration: {exc}", file=sys.stderr)
        return 2

    if args.hours:
        cfg = _with_window(cfg, args.hours)

    log.info("Rufe %d Quellen ab …", len(cfg.feeds))
    results = fetch_all(cfg, offline_dir=args.offline_dir)
    result = digest_module.build(results, cfg)

    if not result.ok_sources:
        print(
            "Keine einzige Quelle war erreichbar - es wurde nichts geschrieben.",
            file=sys.stderr,
        )
        for status in result.failed_sources:
            print(f"  {status.name}: {status.error}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    written = write_output(
        result,
        out_dir,
        timezone_name=cfg.settings.timezone,
        archive=not args.no_archive,
        day=_archive_date(args, cfg.settings.timezone),
    )

    failed = len(result.failed_sources)
    summary = (
        f"{result.total_stories} Meldungen aus {len(result.ok_sources)} Quellen"
        f"{f' ({failed} nicht erreichbar)' if failed else ''}"
    )
    print(f"{summary} → {written[0]}")
    return 0


def write_output(
    result: digest_module.Digest,
    out_dir: Path,
    *,
    timezone_name: str,
    archive: bool,
    day: date,
) -> list[Path]:
    """Schreibt index.html und - falls gewünscht - den Archiveintrag des Tages."""
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_digest(result, timezone=timezone_name)

    index = out_dir / "index.html"
    index.write_text(html, encoding="utf-8")
    written = [index]

    if archive:
        archive_dir = out_dir / "archiv"
        archive_dir.mkdir(parents=True, exist_ok=True)

        entry = archive_dir / f"{day.isoformat()}.html"
        entry.write_text(html, encoding="utf-8")
        written.append(entry)

        listing = archive_dir / "index.html"
        listing.write_text(
            render_archive_index(_archived_days(archive_dir), timezone=timezone_name),
            encoding="utf-8",
        )
        written.append(listing)

    return written


def _archived_days(archive_dir: Path) -> list[date]:
    days = []
    for path in archive_dir.glob("*.html"):
        try:
            days.append(date.fromisoformat(path.stem))
        except ValueError:
            continue  # index.html und alles andere ignorieren
    return days


def _archive_date(args: argparse.Namespace, timezone_name: str) -> date:
    if args.date:
        try:
            return date.fromisoformat(args.date)
        except ValueError:
            raise SystemExit(f"--date erwartet JJJJ-MM-TT, bekam '{args.date}'") from None
    return datetime.now(timezone.utc).astimezone(ZoneInfo(timezone_name)).date()


def _with_window(cfg: config_module.Config, hours: int) -> config_module.Config:
    from dataclasses import replace

    return replace(cfg, settings=replace(cfg.settings, window_hours=hours))


if __name__ == "__main__":
    sys.exit(main())
