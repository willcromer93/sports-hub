"""
Tests for scripts/http_client.py against a small local web server that we can
make misbehave on purpose. Run from the project root:

    venv/bin/python -m unittest discover -s tests -v
"""

import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import http_client  # noqa: E402


class FakeAPI(BaseHTTPRequestHandler):
    """Replies from a script: each request pops the next (status, body, delay)."""

    script = []
    hits = 0

    def do_GET(self):
        cls = type(self)
        cls.hits += 1
        status, body, delay = cls.script.pop(0) if cls.script else (200, "{}", 0)
        time.sleep(delay)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):  # keep test output quiet
        pass


class FetchJsonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Threaded, so a request left sleeping by the timeout test can't block others
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/x"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        # Fast settings so retries don't make the tests slow; fresh session each time
        http_client.BACKOFF = 0.01
        http_client.PAUSE_BETWEEN_CALLS = 0
        http_client.READ_TIMEOUT = 30
        http_client._session = None
        FakeAPI.script, FakeAPI.hits = [], 0

    def test_success_returns_parsed_json(self):
        FakeAPI.script = [(200, '{"ok": true}', 0)]
        self.assertEqual(http_client.fetch_json(self.url), {"ok": True})
        self.assertEqual(FakeAPI.hits, 1)

    def test_temporary_server_errors_are_retried(self):
        FakeAPI.script = [(500, "{}", 0), (503, "{}", 0), (200, '{"n": 1}', 0)]
        self.assertEqual(http_client.fetch_json(self.url), {"n": 1})
        self.assertEqual(FakeAPI.hits, 3)

    def test_gives_up_after_retries_with_a_clear_error(self):
        FakeAPI.script = [(500, "{}", 0)] * 10
        with self.assertRaises(http_client.FetchError) as ctx:
            http_client.fetch_json(self.url)
        self.assertIn(self.url, str(ctx.exception))
        self.assertEqual(FakeAPI.hits, 1 + http_client.RETRIES)  # first try + retries

    def test_404_is_not_retried(self):
        FakeAPI.script = [(404, "{}", 0)]
        with self.assertRaises(http_client.FetchError):
            http_client.fetch_json(self.url)
        self.assertEqual(FakeAPI.hits, 1)

    def test_invalid_json_is_an_error(self):
        FakeAPI.script = [(200, "<html>oops</html>", 0)]
        with self.assertRaises(http_client.FetchError):
            http_client.fetch_json(self.url)

    def test_slow_server_times_out_instead_of_hanging(self):
        http_client.READ_TIMEOUT = 0.2
        FakeAPI.script = [(200, "{}", 1)] * 10
        start = time.monotonic()
        with self.assertRaises(http_client.FetchError):
            http_client.fetch_json(self.url)
        self.assertLess(time.monotonic() - start, 15)  # bounded, not forever
        time.sleep(1.5)  # let the server's abandoned, sleeping handlers finish


if __name__ == "__main__":
    unittest.main()
