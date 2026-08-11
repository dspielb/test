"""Die Übersicht als Entwurf im Gmail-Postfach ablegen.

Es wird nichts verschickt: die Nachricht wird per IMAP in den Entwürfe-Ordner
gelegt (`APPEND` mit dem Merkmal `\\Draft`). Der Zugang läuft über ein
App-Passwort, das in einer Umgebungsvariablen steht - `imaplib` bringt die
Standardbibliothek mit, es kommt keine Abhängigkeit dazu.
"""

from __future__ import annotations

import imaplib
import logging
import os
import re
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate

from .config import Config
from .render import Bericht

log = logging.getLogger(__name__)

#: Reihenfolge der Notnägel, falls der Server kein \Drafts-Merkmal meldet.
_ORDNER_KANDIDATEN = ("[Gmail]/Drafts", "[Gmail]/Entw&APw-rfe", "Drafts", "Entwürfe", "INBOX.Drafts")

_LIST_ZEILE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+"(?P<trenner>[^"]*)"\s+(?P<name>.+)$')


class EntwurfFehler(Exception):
    """Der Entwurf konnte nicht abgelegt werden."""


@dataclass(frozen=True)
class Zugang:
    benutzer: str
    passwort: str
    server: str = "imap.gmail.com"
    port: int = 993


def zugang_aus_umgebung(cfg: Config) -> Zugang | None:
    """Liest Benutzer und App-Passwort. Fehlt eins davon, gibt es keinen Zugang."""
    benutzer = os.environ.get(cfg.entwurf.benutzer_env, "").strip()
    # Google zeigt App-Passwörter in Vierergruppen an; die Leerzeichen gehören nicht dazu.
    passwort = os.environ.get(cfg.entwurf.passwort_env, "").replace(" ", "").strip()
    if not benutzer or not passwort:
        return None
    return Zugang(
        benutzer=benutzer,
        passwort=passwort,
        server=cfg.entwurf.imap_server,
        port=cfg.entwurf.imap_port,
    )


def baue_nachricht(bericht: Bericht, cfg: Config, *, html: str, text: str, absender: str) -> EmailMessage:
    """Eine Mail mit Text- und HTML-Teil - so liest sie jedes Programm."""
    nachricht = EmailMessage()
    nachricht["Subject"] = cfg.entwurf.betreff.format(
        datum=f"{bericht.erzeugt_am_lokal:%d.%m.%Y}", anzahl=bericht.anzahl
    )
    nachricht["From"] = absender
    nachricht["To"] = cfg.entwurf.an.strip() or absender
    nachricht["Date"] = formatdate(localtime=True)
    nachricht.set_content(text)
    nachricht.add_alternative(html, subtype="html")
    return nachricht


def lege_entwurf_ab(
    nachricht: EmailMessage,
    zugang: Zugang,
    *,
    ordner: str = "",
    verbinden=None,
) -> str:
    """Legt die Nachricht als Entwurf ab und gibt den benutzten Ordner zurück."""
    try:
        imap = (verbinden or _verbinden)(zugang)
    except EntwurfFehler:
        raise
    except OSError as exc:
        raise EntwurfFehler(
            f"Verbindung zu {zugang.server}:{zugang.port} fehlgeschlagen: {exc}"
        ) from None

    try:
        try:
            imap.login(zugang.benutzer, zugang.passwort)
        except imaplib.IMAP4.error as exc:
            raise EntwurfFehler(
                f"Anmeldung als {zugang.benutzer} abgelehnt ({_kurz(exc)}). "
                "Bei Gmail braucht es ein App-Passwort, nicht das Kontopasswort."
            ) from None

        ziel = ordner.strip() or _entwuerfe_ordner(imap)
        antwort, daten = imap.append(
            ziel,
            r"(\Draft)",
            imaplib.Time2Internaldate(time.time()),
            nachricht.as_bytes(),
        )
        if antwort != "OK":
            raise EntwurfFehler(f"Server lehnte den Entwurf ab: {_kurz(daten)}")

        log.info("Entwurf in '%s' abgelegt", ziel)
        return ziel
    except imaplib.IMAP4.error as exc:
        raise EntwurfFehler(f"IMAP-Fehler: {_kurz(exc)}") from None
    except OSError as exc:
        raise EntwurfFehler(f"Verbindung zu {zugang.server} fehlgeschlagen: {exc}") from None
    finally:
        _abmelden(imap)


def _verbinden(zugang: Zugang):
    try:
        return imaplib.IMAP4_SSL(zugang.server, zugang.port)
    except OSError as exc:
        raise EntwurfFehler(f"Verbindung zu {zugang.server}:{zugang.port} fehlgeschlagen: {exc}") from None


def _entwuerfe_ordner(imap) -> str:
    """Sucht den Entwürfe-Ordner über das IMAP-Merkmal \\Drafts.

    Der Name ist je nach Kontosprache anders ("[Gmail]/Drafts", "[Gmail]/Entwürfe"),
    das Merkmal nicht - deshalb wird danach gesucht statt nach dem Namen.
    """
    try:
        antwort, zeilen = imap.list()
    except imaplib.IMAP4.error as exc:
        raise EntwurfFehler(f"Ordnerliste nicht lesbar: {_kurz(exc)}") from None

    bekannt: list[str] = []
    if antwort == "OK":
        for zeile in zeilen or []:
            if not isinstance(zeile, bytes):
                continue
            treffer = _LIST_ZEILE.match(zeile.strip())
            if not treffer:
                continue
            name = treffer.group("name").decode("ascii", errors="replace").strip().strip('"')
            bekannt.append(name)
            if rb"\Drafts" in treffer.group("flags").replace(b"\\\\", b"\\"):
                return name

    for kandidat in _ORDNER_KANDIDATEN:
        if kandidat in bekannt:
            return kandidat

    raise EntwurfFehler(
        "Kein Entwürfe-Ordner gefunden. Ist IMAP im Gmail-Konto aktiviert? "
        "Notfalls den Namen unter [entwurf].ordner fest eintragen. "
        f"Gefundene Ordner: {', '.join(bekannt) or 'keine'}"
    )


def _abmelden(imap) -> None:
    try:
        imap.logout()
    except Exception:  # noqa: BLE001 - beim Aufräumen ist jeder Fehler egal
        pass


def _kurz(wert: object) -> str:
    text = " ".join(str(wert).split())
    return text[:200]
