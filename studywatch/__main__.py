"""Kommandozeile: python -m studywatch [Optionen]"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__, config as config_modul, enrich, scrape, state as state_modul, summarize
from .http import AbrufFehler, DateiNetz, Netz
from .render import Bericht, render_archiv_index, render_bericht
from .study import Studie

log = logging.getLogger("studywatch")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m studywatch",
        description="Ruft neue Studien aus dem Journal Watch ab und fasst sie zusammen.",
    )
    parser.add_argument(
        "-c", "--config", default="studies.toml", help="Konfigurationsdatei (Standard: studies.toml)"
    )
    parser.add_argument(
        "-o", "--out", default="docs/studien", help="Ausgabeverzeichnis (Standard: docs/studien)"
    )
    parser.add_argument(
        "--state",
        default="state/gesehen.json",
        help="Merkliste bereits gezeigter Studien (Standard: state/gesehen.json)",
    )
    parser.add_argument("--max", type=int, help="Obergrenze neuer Studien; überschreibt die Konfiguration")
    parser.add_argument("--seite", help="Übersichtsseite aus dieser HTML-Datei lesen statt abrufen")
    parser.add_argument(
        "--offline-dir", help="Alle HTTP-Antworten aus diesem Verzeichnis lesen (für Tests)"
    )
    parser.add_argument(
        "--kein-netz",
        action="store_true",
        help="Keine Netzaufrufe: weder Anreicherung noch Zusammenfassung",
    )
    parser.add_argument(
        "--keine-zusammenfassung", action="store_true", help="Ohne Claude-API, nur Abstracts"
    )
    parser.add_argument(
        "--alle", action="store_true", help="Merkliste ignorieren und alle gefundenen Studien zeigen"
    )
    parser.add_argument(
        "--trockenlauf", action="store_true", help="Nichts schreiben, nur berichten was passieren würde"
    )
    parser.add_argument("--no-archive", action="store_true", help="Kein Tagesarchiv schreiben")
    parser.add_argument("--date", help="Datum des Archiveintrags im Format JJJJ-MM-TT")
    parser.add_argument("-q", "--quiet", action="store_true", help="Nur Fehler ausgeben")
    parser.add_argument("-v", "--verbose", action="store_true", help="Ausführliche Ausgabe")
    parser.add_argument("--version", action="version", version=f"studywatch {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.ERROR if args.quiet else (logging.INFO if args.verbose else logging.WARNING),
        format="%(levelname)s %(message)s",
    )

    try:
        cfg = config_modul.load(args.config)
    except config_modul.ConfigError as exc:
        print(f"Fehler in der Konfiguration: {exc}", file=sys.stderr)
        return 2

    if args.max:
        cfg = config_modul.mit_max_studien(cfg, args.max)
    if args.keine_zusammenfassung or args.kein_netz:
        cfg = config_modul.ohne_zusammenfassung(cfg)

    netz = _netz(args, cfg)
    hinweise: list[str] = []

    try:
        html = _seite_lesen(args, cfg, netz)
    except AbrufFehler as exc:
        print(f"Quelle nicht erreichbar: {exc}", file=sys.stderr)
        return 1

    gefunden = scrape.extrahiere(html, basis_url=cfg.quelle.url, cfg=cfg)
    if not gefunden:
        hinweise.append(
            "Auf der Quellseite wurde kein einziger Studienlink erkannt – "
            "möglicherweise hat sich ihr Aufbau geändert."
        )

    merkliste = state_modul.laden(args.state)
    erstlauf = len(merkliste) == 0
    neue = gefunden if args.alle else state_modul.nur_neue(gefunden, merkliste)

    grenze = cfg.einstellungen.max_studien
    zurueckgestellt = neue[grenze:]
    ausgewaehlt = neue[:grenze]

    if erstlauf and not args.alle:
        hinweise.append(
            f"Erstlauf: die Merkliste war leer. Gezeigt werden die ersten {len(ausgewaehlt)} "
            f"Einträge der Seite; die übrigen {len(zurueckgestellt)} gelten ab sofort als bekannt."
        )
    elif zurueckgestellt:
        hinweise.append(
            f"{len(zurueckgestellt)} weitere neue Studien überschreiten die Obergrenze von "
            f"{grenze} und erscheinen im nächsten Lauf."
        )

    if not args.kein_netz:
        enrich.anreichern(ausgewaehlt, cfg, netz)
    else:
        hinweise.append("Ohne Netzzugriff gestartet: keine Metadaten und keine Kurzfassungen.")

    verbrauch = summarize.zusammenfassen(ausgewaehlt, cfg)
    hinweise.extend(_zusammenfassungs_hinweise(cfg, ausgewaehlt, verbrauch))

    bericht = Bericht(
        studien=ausgewaehlt,
        quelle_name=cfg.quelle.name,
        quelle_url=cfg.quelle.url,
        erzeugt_am=datetime.now(timezone.utc),
        gefunden_gesamt=len(gefunden),
        modell=cfg.zusammenfassung.modell if verbrauch.anfragen else "",
        hinweise=hinweise,
    )

    if args.trockenlauf:
        _trockenlauf_ausgeben(bericht, verbrauch)
        return 0

    geschrieben = schreibe_ausgabe(
        bericht,
        Path(args.out),
        timezone_name=cfg.einstellungen.zeitzone,
        archiv=not args.no_archive,
        tag=_archiv_datum(args, cfg.einstellungen.zeitzone),
    )

    # Erst merken, wenn die Seite steht - sonst verschwindet eine Studie
    # spurlos, wenn das Schreiben scheitert.
    zu_merken = gefunden if erstlauf else ausgewaehlt
    merkliste.eintragen(zu_merken, _archiv_datum(args, cfg.einstellungen.zeitzone))
    state_modul.speichern(merkliste, args.state)

    print(f"{len(ausgewaehlt)} neue Studien von {len(gefunden)} geprüften → {geschrieben[0]}")
    if verbrauch.anfragen:
        print(f"Modellverbrauch: {verbrauch}")
    return 0


def schreibe_ausgabe(
    bericht: Bericht,
    out_dir: Path,
    *,
    timezone_name: str,
    archiv: bool,
    tag: date,
) -> list[Path]:
    """Schreibt index.html und - falls gewünscht - den Archiveintrag des Tages."""
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_bericht(bericht, timezone=timezone_name)

    index = out_dir / "index.html"
    index.write_text(html, encoding="utf-8")
    geschrieben = [index]

    if archiv:
        archiv_dir = out_dir / "archiv"
        archiv_dir.mkdir(parents=True, exist_ok=True)

        eintrag = archiv_dir / f"{tag.isoformat()}.html"
        eintrag.write_text(html, encoding="utf-8")
        geschrieben.append(eintrag)

        uebersicht = archiv_dir / "index.html"
        uebersicht.write_text(render_archiv_index(_archivierte_tage(archiv_dir)), encoding="utf-8")
        geschrieben.append(uebersicht)

    return geschrieben


# --- Bausteine ------------------------------------------------------------


def _netz(args: argparse.Namespace, cfg) -> Netz:
    argumente = {
        "timeout": cfg.einstellungen.timeout_sekunden,
        "wiederholungen": cfg.einstellungen.wiederholungen,
        "kontakt_email": cfg.anreicherung.kontakt_email,
    }
    if args.offline_dir:
        return DateiNetz(args.offline_dir, **argumente)
    return Netz(offline=args.kein_netz, **argumente)


def _seite_lesen(args: argparse.Namespace, cfg, netz: Netz) -> str:
    if args.seite:
        pfad = Path(args.seite)
        if not pfad.exists():
            raise AbrufFehler(f"Datei nicht gefunden: {pfad}")
        return pfad.read_text(encoding="utf-8", errors="replace")
    return scrape.hole_seite(cfg, netz)


def _zusammenfassungs_hinweise(cfg, studien: list[Studie], verbrauch) -> list[str]:
    if not studien or not cfg.zusammenfassung.aktiv:
        return []
    if verbrauch.anfragen:
        return []
    return [
        "Die Claude-API stand nicht zur Verfügung – gezeigt wird der Auszug aus dem Abstract. "
        f"Für Kurzfassungen muss {cfg.zusammenfassung.api_key_env} gesetzt sein."
    ]


def _trockenlauf_ausgeben(bericht: Bericht, verbrauch) -> None:
    print(f"{bericht.anzahl} neue Studien von {bericht.gefunden_gesamt} geprüften (Trockenlauf)")
    for hinweis in bericht.hinweise:
        print(f"  Hinweis: {hinweis}")
    for studie in bericht.studien:
        marke = "✓" if studie.zusammenfassung and studie.zusammenfassung.vom_modell else "·"
        print(f"  {marke} {studie.titel[:96]}")
        print(f"      {studie.journal or 'Journal unbekannt'} · {studie.link}")
    if verbrauch.anfragen:
        print(f"Modellverbrauch: {verbrauch}")


def _archivierte_tage(archiv_dir: Path) -> list[date]:
    tage = []
    for pfad in archiv_dir.glob("*.html"):
        try:
            tage.append(date.fromisoformat(pfad.stem))
        except ValueError:
            continue  # index.html und alles andere ignorieren
    return tage


def _archiv_datum(args: argparse.Namespace, timezone_name: str) -> date:
    if args.date:
        try:
            return date.fromisoformat(args.date)
        except ValueError:
            raise SystemExit(f"--date erwartet JJJJ-MM-TT, bekam '{args.date}'") from None
    return datetime.now(timezone.utc).astimezone(ZoneInfo(timezone_name)).date()


if __name__ == "__main__":
    sys.exit(main())
