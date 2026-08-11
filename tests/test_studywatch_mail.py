import imaplib
import logging
import unittest
from datetime import datetime, timezone
from unittest import mock

from studywatch import config as config_modul
from studywatch import mail
from studywatch.render import Bericht, render_mail_html, render_mail_text
from studywatch.study import Studie, Zusammenfassung


def setUpModule():
    logging.getLogger("studywatch.mail").setLevel(logging.CRITICAL)


GMAIL_ORDNER = [
    b'(\\HasNoChildren) "/" "INBOX"',
    b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"',
    b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Entw&APw-rfe"',
    b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Gesendet"',
]


class FakeIMAP:
    """Ein IMAP-Server, der mitschreibt statt zu verbinden."""

    def __init__(self, *, ordner=None, login_fehler=False, append_antwort=("OK", [b"APPENDUID"])):
        self.ordner = GMAIL_ORDNER if ordner is None else ordner
        self.login_fehler = login_fehler
        self.append_antwort = append_antwort
        self.angemeldet_als = None
        self.abgemeldet = False
        self.appends: list[tuple] = []

    def login(self, benutzer, passwort):
        if self.login_fehler:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED Invalid credentials")
        self.angemeldet_als = (benutzer, passwort)
        return ("OK", [b"LOGIN completed"])

    def list(self):
        return ("OK", self.ordner)

    def append(self, ordner, flags, datum, nachricht):
        self.appends.append((ordner, flags, datum, nachricht))
        return self.append_antwort

    def logout(self):
        self.abgemeldet = True
        return ("BYE", [b""])


def config(**entwurf):
    return config_modul.from_dict({
        "quelle": {"name": "JW", "url": "https://example.invalid/jw"},
        "entwurf": entwurf,
    })


def bericht(studien=None) -> Bericht:
    return Bericht(
        studien=studien if studien is not None else [studie()],
        quelle_name="Critical Care Reviews – Journal Watch",
        quelle_url="https://example.invalid/jw",
        erzeugt_am=datetime(2026, 8, 11, 5, 30, tzinfo=timezone.utc),
        gefunden_gesamt=7,
    )


def studie() -> Studie:
    return Studie(
        titel="Restrictive versus liberal oxygen targets",
        link="https://doi.org/10.1/a",
        doi="10.1/a",
        pmid="40000001",
        journal="N Engl J Med",
        abstract="Background: Eins.\n\nConclusions: Zwei.",
        zusammenfassung=Zusammenfassung(
            kernaussage="Kein Unterschied in der Sterblichkeit.",
            methodik="Randomisiert, n=2140.",
        ),
    )


def zugang() -> mail.Zugang:
    return mail.Zugang(benutzer="ich@gmail.invalid", passwort="abcdefghijklmnop")


class ZugangAusUmgebung(unittest.TestCase):
    def test_both_variables_present(self):
        with mock.patch.dict(
            "os.environ",
            {"GMAIL_BENUTZER": "ich@gmail.invalid", "GMAIL_APP_PASSWORT": "abcd efgh ijkl mnop"},
        ):
            gefunden = mail.zugang_aus_umgebung(config())

        self.assertEqual(gefunden.benutzer, "ich@gmail.invalid")
        # Google zeigt App-Passwörter in Vierergruppen - die Leerzeichen müssen weg.
        self.assertEqual(gefunden.passwort, "abcdefghijklmnop")

    def test_missing_variable_yields_none(self):
        with mock.patch.dict("os.environ", {"GMAIL_BENUTZER": "ich@gmail.invalid"}, clear=True):
            self.assertIsNone(mail.zugang_aus_umgebung(config()))

    def test_variable_names_are_configurable(self):
        with mock.patch.dict("os.environ", {"MEIN_USER": "du@gmail.invalid", "MEIN_PW": "x"}):
            gefunden = mail.zugang_aus_umgebung(
                config(benutzer_env="MEIN_USER", passwort_env="MEIN_PW")
            )
        self.assertEqual(gefunden.benutzer, "du@gmail.invalid")


class Nachricht(unittest.TestCase):
    def setUp(self):
        self.nachricht = mail.baue_nachricht(
            bericht(),
            config(),
            html=render_mail_html(bericht()),
            text=render_mail_text(bericht()),
            absender="ich@gmail.invalid",
        )

    def test_subject_carries_the_local_date(self):
        # 05:30 UTC ist der 11. August in Europe/Berlin.
        self.assertEqual(self.nachricht["Subject"], "Neue Studien – 11.08.2026")

    def test_subject_placeholders(self):
        nachricht = mail.baue_nachricht(
            bericht(),
            config(betreff="{anzahl} Studien am {datum}"),
            html="<p>x</p>",
            text="x",
            absender="ich@gmail.invalid",
        )
        self.assertEqual(nachricht["Subject"], "1 Studien am 11.08.2026")

    def test_defaults_to_sending_to_yourself(self):
        self.assertEqual(self.nachricht["To"], "ich@gmail.invalid")

    def test_explicit_recipient_is_used(self):
        nachricht = mail.baue_nachricht(
            bericht(), config(an="anders@example.invalid"), html="<p>x</p>", text="x",
            absender="ich@gmail.invalid",
        )
        self.assertEqual(nachricht["To"], "anders@example.invalid")

    def test_has_text_and_html_part(self):
        typen = {teil.get_content_type() for teil in self.nachricht.walk()}
        self.assertIn("text/plain", typen)
        self.assertIn("text/html", typen)

    def test_content_survives_into_both_parts(self):
        text = self.nachricht.get_body(("plain",)).get_content()
        html = self.nachricht.get_body(("html",)).get_content()
        for teil in (text, html):
            self.assertIn("Restrictive versus liberal oxygen targets", teil)
            self.assertIn("Kein Unterschied in der Sterblichkeit.", teil)


class Ablegen(unittest.TestCase):
    def test_draft_lands_in_the_flagged_folder(self):
        server = FakeIMAP()
        ordner = mail.lege_entwurf_ab(
            mail.baue_nachricht(bericht(), config(), html="<p>x</p>", text="x", absender="a@b.invalid"),
            zugang(),
            verbinden=lambda _: server,
        )

        self.assertEqual(ordner, "[Gmail]/Entw&APw-rfe")
        self.assertEqual(server.appends[0][0], "[Gmail]/Entw&APw-rfe")
        self.assertEqual(server.appends[0][1], r"(\Draft)")
        self.assertTrue(server.abgemeldet)

    def test_credentials_are_used(self):
        server = FakeIMAP()
        mail.lege_entwurf_ab(
            mail.baue_nachricht(bericht(), config(), html="<p>x</p>", text="x", absender="a@b.invalid"),
            zugang(),
            verbinden=lambda _: server,
        )
        self.assertEqual(server.angemeldet_als, ("ich@gmail.invalid", "abcdefghijklmnop"))

    def test_configured_folder_skips_the_lookup(self):
        server = FakeIMAP(ordner=[])
        ordner = mail.lege_entwurf_ab(
            mail.baue_nachricht(bericht(), config(), html="<p>x</p>", text="x", absender="a@b.invalid"),
            zugang(),
            ordner="Meine Entwürfe",
            verbinden=lambda _: server,
        )
        self.assertEqual(ordner, "Meine Entwürfe")

    def test_known_folder_name_without_the_flag(self):
        server = FakeIMAP(ordner=[b'(\\HasNoChildren) "/" "[Gmail]/Drafts"'])
        ordner = mail.lege_entwurf_ab(
            mail.baue_nachricht(bericht(), config(), html="<p>x</p>", text="x", absender="a@b.invalid"),
            zugang(),
            verbinden=lambda _: server,
        )
        self.assertEqual(ordner, "[Gmail]/Drafts")


class Fehlerfaelle(unittest.TestCase):
    def nachricht(self):
        return mail.baue_nachricht(
            bericht(), config(), html="<p>x</p>", text="x", absender="a@b.invalid"
        )

    def test_login_failure_points_at_the_app_password(self):
        server = FakeIMAP(login_fehler=True)
        with self.assertRaises(mail.EntwurfFehler) as fehler:
            mail.lege_entwurf_ab(self.nachricht(), zugang(), verbinden=lambda _: server)

        self.assertIn("App-Passwort", str(fehler.exception))
        self.assertTrue(server.abgemeldet)

    def test_no_drafts_folder_is_reported(self):
        server = FakeIMAP(ordner=[b'(\\HasNoChildren) "/" "INBOX"'])
        with self.assertRaisesRegex(mail.EntwurfFehler, "Entwürfe-Ordner"):
            mail.lege_entwurf_ab(self.nachricht(), zugang(), verbinden=lambda _: server)

    def test_rejected_append_is_reported(self):
        server = FakeIMAP(append_antwort=("NO", [b"Over quota"]))
        with self.assertRaisesRegex(mail.EntwurfFehler, "Over quota"):
            mail.lege_entwurf_ab(self.nachricht(), zugang(), verbinden=lambda _: server)

    def test_network_failure_is_wrapped(self):
        def verbinden(_):
            raise OSError("Name or service not known")

        with self.assertRaises(mail.EntwurfFehler):
            mail.lege_entwurf_ab(self.nachricht(), zugang(), verbinden=verbinden)


class MailFassung(unittest.TestCase):
    def test_html_has_no_style_block_or_details(self):
        html = render_mail_html(bericht())
        # Beides unterstützen Mail-Programme nicht verlässlich.
        self.assertNotIn("<style", html)
        self.assertNotIn("<details", html)
        self.assertIn('style="', html)

    def test_abstract_is_left_out_by_default(self):
        self.assertNotIn("Background: Eins.", render_mail_html(bericht()))
        self.assertIn("Background: Eins.", render_mail_html(bericht(), mit_abstract=True))

    def test_text_version_is_readable(self):
        text = render_mail_text(bericht())
        self.assertIn("NEUE STUDIEN", text)
        self.assertIn("1. Restrictive versus liberal oxygen targets", text)
        self.assertIn("https://doi.org/10.1/a", text)
        self.assertIn("METHODIK", text)
        self.assertNotIn("<", text)

    def test_empty_day_is_stated_in_both_parts(self):
        self.assertIn("Heute keine neuen Studien", render_mail_html(bericht([])))
        self.assertIn("Heute keine neuen Studien", render_mail_text(bericht([])))

    def test_disclaimer_is_carried_along(self):
        self.assertIn("keine ärztliche Empfehlung", render_mail_html(bericht()))
        self.assertIn("keine ärztliche Empfehlung", render_mail_text(bericht()))


if __name__ == "__main__":
    unittest.main()
