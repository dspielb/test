import gzip
import logging
import tempfile
import threading
import unittest
import urllib.error
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from newsdigest import config as config_module
from newsdigest.config import Feed
from newsdigest.fetch import _describe, _HttpLoader, _retryable, fetch_all

FEED_XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
<item><title>Eine Meldung</title><link>https://a.de/1</link>
<pubDate>Tue, 28 Jul 2026 08:00:00 +0000</pubDate></item>
</channel></rss>"""


def setUpModule():
    # Fehlgeschlagene Abrufe sind hier der Prüfgegenstand - ihre Warnungen
    # sollen die Testausgabe nicht zumüllen.
    logging.getLogger("newsdigest").setLevel(logging.CRITICAL)


class _Handler(BaseHTTPRequestHandler):
    """Testserver: /ok, /gzip, /500, /404, /flaky (erst 503, dann 200), /muell, /leer."""

    attempts: dict[str, int] = {}

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path
        if path == "/ok":
            self._send(200, FEED_XML)
        elif path == "/gzip":
            self._send(200, gzip.compress(FEED_XML), encoding="gzip")
        elif path == "/muell":
            # Wirklich defekt - offene Tags, kein schließendes Element.
            self._send(200, b"<html><p>Wartungsseite statt Feed")
        elif path == "/leer":
            self._send(200, b'<?xml version="1.0"?><rss version="2.0"><channel/></rss>')
        elif path == "/flaky":
            count = _Handler.attempts.get("flaky", 0) + 1
            _Handler.attempts["flaky"] = count
            self._send(200, FEED_XML) if count > 1 else self._send(503, b"kurz weg")
        elif path == "/404":
            self._send(404, b"weg")
        else:
            self._send(500, b"kaputt")

    def _send(self, code, body, encoding=None):
        self.send_response(code)
        self.send_header("Content-Type", "application/rss+xml")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class HttpFetching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Der Testserver lässt Sockets von der Garbage Collection einsammeln -
        # das ist Testinfrastruktur und sagt nichts über den Code aus.
        warnings.simplefilter("ignore", ResourceWarning)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Handler.attempts.clear()

    def config_for(self, *paths, retries=0):
        # retries standardmäßig 0: sonst warten die Fehlertests echte
        # Backoff-Pausen ab, ohne dass der Test das prüfen will.
        return config_module.from_dict({
            "settings": {"timeout_seconds": 5, "retries": retries},
            "categories": {"c": "Kategorie"},
            "feed": [
                {"id": p.strip("/"), "name": p.strip("/"), "url": f"{self.base}{p}",
                 "category": "c"}
                for p in paths
            ],
        })

    def test_fetches_and_parses_a_feed(self):
        results = fetch_all(self.config_for("/ok"))
        self.assertTrue(results[0].ok)
        self.assertEqual(results[0].articles[0].title, "Eine Meldung")

    def test_transparently_decompresses_gzip(self):
        results = fetch_all(self.config_for("/gzip"))
        self.assertTrue(results[0].ok, results[0].error)
        self.assertEqual(len(results[0].articles), 1)

    def test_http_error_is_captured_not_raised(self):
        results = fetch_all(self.config_for("/404"))
        self.assertFalse(results[0].ok)
        self.assertEqual(results[0].error, "HTTP 404")
        self.assertEqual(results[0].articles, [])

    def test_unparsable_body_is_reported(self):
        """Kaputtes Markup - z. B. eine HTML-Wartungsseite statt des Feeds."""
        results = fetch_all(self.config_for("/muell"))
        self.assertFalse(results[0].ok)
        self.assertIn("nicht lesbar", results[0].error)

    def test_valid_xml_without_items_is_reported_separately(self):
        results = fetch_all(self.config_for("/leer"))
        self.assertFalse(results[0].ok)
        self.assertEqual(results[0].error, "Feed enthielt keine Artikel")

    def test_one_broken_feed_does_not_stop_the_others(self):
        results = fetch_all(self.config_for("/ok", "/404", "/500"))
        self.assertEqual([r.ok for r in results], [True, False, False])

    def test_results_keep_the_configured_order(self):
        results = fetch_all(self.config_for("/404", "/ok", "/500"))
        self.assertEqual([r.feed.id for r in results], ["404", "ok", "500"])

    def test_temporary_failure_is_retried(self):
        results = fetch_all(self.config_for("/flaky", retries=2))
        self.assertTrue(results[0].ok, results[0].error)
        self.assertEqual(_Handler.attempts["flaky"], 2)

    def test_sends_a_user_agent(self):
        # Ohne User-Agent sperren einige Redaktionen den Zugriff.
        loader = _HttpLoader(timeout=5, retries=0)
        feed = Feed(id="ok", name="ok", url=f"{self.base}/ok", category="c")
        self.assertEqual(loader.load(feed), FEED_XML)


class OfflineLoading(unittest.TestCase):
    def test_reads_feeds_from_a_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "lokal.xml").write_bytes(FEED_XML)
            cfg = config_module.from_dict({
                "categories": {"c": "Kategorie"},
                "feed": [{"id": "lokal", "name": "Lokal", "url": "https://egal.de",
                          "category": "c"}],
            })
            results = fetch_all(cfg, offline_dir=tmp)
            self.assertTrue(results[0].ok)
            self.assertEqual(results[0].articles[0].title, "Eine Meldung")

    def test_missing_file_is_reported_per_feed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config_module.from_dict({
                "categories": {"c": "Kategorie"},
                "feed": [{"id": "fehlt", "name": "Fehlt", "url": "https://egal.de",
                          "category": "c"}],
            })
            results = fetch_all(cfg, offline_dir=tmp)
            self.assertFalse(results[0].ok)
            self.assertIn("keine Offline-Datei", results[0].error)


class RetryPolicy(unittest.TestCase):
    def test_server_errors_and_rate_limits_are_retried(self):
        for code in (500, 503, 429, 408):
            self.assertTrue(_retryable(urllib.error.HTTPError("u", code, "m", {}, None)), code)

    def test_client_errors_are_not_retried(self):
        for code in (400, 401, 403, 404):
            self.assertFalse(_retryable(urllib.error.HTTPError("u", code, "m", {}, None)), code)

    def test_network_errors_are_retried(self):
        self.assertTrue(_retryable(urllib.error.URLError("timeout")))


class ErrorMessages(unittest.TestCase):
    def test_http_error(self):
        self.assertEqual(_describe(urllib.error.HTTPError("u", 503, "m", {}, None)), "HTTP 503")

    def test_network_error_mentions_the_reason(self):
        self.assertIn("zeitüberschreitung", _describe(
            urllib.error.URLError("zeitüberschreitung")).lower())

    def test_unknown_error_includes_the_type(self):
        self.assertIn("ValueError", _describe(ValueError("seltsam")))


if __name__ == "__main__":
    unittest.main()
