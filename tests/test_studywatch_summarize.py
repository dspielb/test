import json
import logging
import unittest
from types import SimpleNamespace

from studywatch import config as config_modul
from studywatch import summarize
from studywatch.study import Studie


def setUpModule():
    logging.getLogger("studywatch.summarize").setLevel(logging.CRITICAL)


ABSTRACT = (
    "Background: Die optimale Zielsättigung ist unklar.\n\n"
    "Methods: Randomisierte Studie mit 2140 Patientinnen und Patienten.\n\n"
    "Conclusions: Ein restriktives Ziel senkte die 90-Tage-Sterblichkeit nicht."
)

ANTWORT_JSON = json.dumps({
    "kernaussage": "Kein Unterschied in der 90-Tage-Sterblichkeit.",
    "hintergrund": "Die optimale Zielsättigung ist unklar.",
    "methodik": "Randomisierte Studie, n=2140.",
    "ergebnis": "29,2 % gegenüber 31,8 % (p=0,19).",
    "bedeutung": "Kein Beleg für einen Vorteil; einfach verblindet.",
})


def antwort(text: str, *, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="bio"),
        usage=SimpleNamespace(input_tokens=120, output_tokens=80),
    )


class StubClient:
    """Ein Client, der zählt, welcher Weg genommen wurde."""

    def __init__(self, ergebnis, *, beta_fehler: Exception | None = None):
        self.ergebnis = ergebnis
        self.beta_fehler = beta_fehler
        self.beta_aufrufe = 0
        self.normale_aufrufe = 0
        self.letzte_parameter: dict = {}

        selbst = self

        class _Messages:
            def create(self, **kwargs):
                selbst.letzte_parameter = kwargs
                if "betas" in kwargs:
                    selbst.beta_aufrufe += 1
                    if selbst.beta_fehler is not None:
                        raise selbst.beta_fehler
                else:
                    selbst.normale_aufrufe += 1
                if isinstance(selbst.ergebnis, Exception):
                    raise selbst.ergebnis
                return selbst.ergebnis

        self.messages = _Messages()
        self.beta = SimpleNamespace(messages=_Messages())


def fasser_mit(client, **zusammenfassung):
    cfg = config_modul.from_dict({
        "quelle": {"name": "JW", "url": "https://example.invalid/jw"},
        "zusammenfassung": {"parallel": 1, **zusammenfassung},
    })
    fasser = summarize._Zusammenfasser(cfg.zusammenfassung)
    fasser._client = client
    return fasser


def studie(abstract: str | None = ABSTRACT) -> Studie:
    return Studie(
        titel="Restrictive versus liberal oxygen targets",
        link="https://doi.org/10.1/a",
        journal="N Engl J Med",
        abstract=abstract,
    )


class VomModell(unittest.TestCase):
    def test_structured_answer_is_parsed(self):
        fasser = fasser_mit(StubClient(antwort(ANTWORT_JSON)))
        s = studie()
        fasser.fasse(s)

        self.assertTrue(s.zusammenfassung.vom_modell)
        self.assertEqual(s.zusammenfassung.kernaussage, "Kein Unterschied in der 90-Tage-Sterblichkeit.")
        self.assertEqual(s.zusammenfassung.methodik, "Randomisierte Studie, n=2140.")

    def test_request_carries_schema_and_effort(self):
        client = StubClient(antwort(ANTWORT_JSON))
        fasser_mit(client, effort="medium", modell="claude-opus-5").fasse(studie())

        parameter = client.letzte_parameter
        self.assertEqual(parameter["model"], "claude-opus-5")
        self.assertEqual(parameter["output_config"]["effort"], "medium")
        self.assertEqual(parameter["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(parameter["extra_body"], {"fallbacks": "default"})

    def test_prompt_contains_only_known_facts(self):
        client = StubClient(antwort(ANTWORT_JSON))
        fasser_mit(client).fasse(studie())

        text = client.letzte_parameter["messages"][0]["content"]
        self.assertIn("Restrictive versus liberal oxygen targets", text)
        self.assertIn("N Engl J Med", text)
        self.assertIn(ABSTRACT, text)

    def test_token_usage_is_counted(self):
        fasser = fasser_mit(StubClient(antwort(ANTWORT_JSON)))
        fasser.fasse(studie())
        self.assertEqual(fasser.verbrauch.anfragen, 1)
        self.assertEqual(fasser.verbrauch.eingabe_tokens, 120)
        self.assertEqual(fasser.verbrauch.ausgabe_tokens, 80)


class Rueckfall(unittest.TestCase):
    def test_refusal_falls_back_to_the_abstract(self):
        fasser = fasser_mit(StubClient(antwort("{}", stop_reason="refusal")))
        s = studie()
        fasser.fasse(s)

        self.assertFalse(s.zusammenfassung.vom_modell)
        self.assertIn("restriktives Ziel", s.zusammenfassung.kernaussage)

    def test_unparsable_answer_falls_back(self):
        fasser = fasser_mit(StubClient(antwort("kein JSON")))
        s = studie()
        fasser.fasse(s)
        self.assertFalse(s.zusammenfassung.vom_modell)

    def test_api_error_falls_back(self):
        fasser = fasser_mit(StubClient(RuntimeError("API weg")))
        s = studie()
        fasser.fasse(s)
        self.assertFalse(s.zusammenfassung.vom_modell)

    def test_study_without_abstract_has_no_summary(self):
        fasser = fasser_mit(StubClient(antwort(ANTWORT_JSON)))
        s = studie(abstract=None)
        fasser.fasse(s)
        self.assertIsNone(s.zusammenfassung)


class Ausweichmodelle(unittest.TestCase):
    def test_rejected_fallback_parameter_switches_to_the_plain_call(self):
        client = StubClient(antwort(ANTWORT_JSON), beta_fehler=TypeError("unexpected 'fallbacks'"))
        fasser = fasser_mit(client)

        erste, zweite = studie(), studie()
        fasser.fasse(erste)
        fasser.fasse(zweite)

        self.assertTrue(erste.zusammenfassung.vom_modell)
        self.assertTrue(zweite.zusammenfassung.vom_modell)
        # Nur der erste Versuch geht über den Beta-Weg, danach ist er abgeschaltet.
        self.assertEqual(client.beta_aufrufe, 1)
        self.assertEqual(client.normale_aufrufe, 2)

    def test_other_errors_are_not_swallowed(self):
        client = StubClient(antwort(ANTWORT_JSON), beta_fehler=RuntimeError("Zeitüberschreitung"))
        fasser = fasser_mit(client)
        s = studie()
        fasser.fasse(s)

        self.assertFalse(s.zusammenfassung.vom_modell)
        self.assertEqual(client.normale_aufrufe, 0)


class AusAbstract(unittest.TestCase):
    def test_conclusion_section_is_preferred(self):
        s = studie()
        self.assertEqual(
            summarize.aus_abstract(s).kernaussage,
            "Ein restriktives Ziel senkte die 90-Tage-Sterblichkeit nicht.",
        )

    def test_without_conclusion_the_first_sentences_are_used(self):
        s = studie("Erster Satz. Zweiter Satz. Dritter Satz.")
        self.assertEqual(summarize.aus_abstract(s).kernaussage, "Erster Satz. Zweiter Satz.")

    def test_no_abstract_means_no_summary(self):
        self.assertIsNone(summarize.aus_abstract(studie(abstract=None)))


class Abschaltung(unittest.TestCase):
    def test_disabled_summaries_use_the_abstract(self):
        cfg = config_modul.from_dict({
            "quelle": {"name": "JW", "url": "https://example.invalid/jw"},
            "zusammenfassung": {"aktiv": False},
        })
        studien = [studie()]
        verbrauch = summarize.zusammenfassen(studien, cfg)

        self.assertEqual(verbrauch.anfragen, 0)
        self.assertFalse(studien[0].zusammenfassung.vom_modell)

    def test_fallback_detection(self):
        self.assertTrue(summarize._betrifft_fallback(TypeError("unexpected keyword")))
        self.assertTrue(summarize._betrifft_fallback(ValueError("unknown beta header")))
        self.assertFalse(summarize._betrifft_fallback(ValueError("connection reset")))


if __name__ == "__main__":
    unittest.main()
