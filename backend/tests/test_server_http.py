import http.client
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from server.http_app import MAX_BODY_BYTES, make_server
from server.service import StreamService


class HttpTestCase(unittest.TestCase):
    static_dir = None

    @classmethod
    def setUpClass(cls):
        cls.service = StreamService()
        cls.server = make_server(cls.service, port=0, static_dir=cls.static_dir)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, method, path, body=None, raw=None, headers=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                         method=method, headers=headers or {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                text = response.read()
                return response.status, (json.loads(text) if text else None), response.headers
        except urllib.error.HTTPError as err:
            try:
                text = err.read()
                return err.code, (json.loads(text) if text else None), err.headers
            finally:
                err.close()

    def sse(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers["Content-Type"].startswith("text/event-stream"))
            raw = response.read().decode("utf-8")
        events = []
        for block in raw.split("\n\n"):
            if not block.strip():
                continue
            fields = dict(line.split(": ", 1) for line in block.splitlines())
            events.append((fields.get("event"), json.loads(fields["data"]), fields.get("id")))
        return events


class BasicsTest(HttpTestCase):
    def test_health_and_info(self):
        self.assertEqual(self.call("GET", "/api/health")[:2], (200, {"status": "ok"}))
        status, info, _ = self.call("GET", "/api/info")
        self.assertEqual((status, info["version"], info["products"]), (200, 1, 1074))

    def test_cors_headers_and_preflight(self):
        _, _, headers = self.call("GET", "/api/health")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        status, body, headers = self.call("OPTIONS", "/api/sessions")
        self.assertEqual((status, body), (204, None))
        self.assertIn("POST", headers["Access-Control-Allow-Methods"])
        self.assertIn("Content-Type", headers["Access-Control-Allow-Headers"])

    def test_api_responses_are_not_cached_and_not_sniffed(self):
        _, _, headers = self.call("GET", "/api/info")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_unknown_paths_and_methods(self):
        for method, path in (("GET", "/api/nope"), ("POST", "/api/health"), ("DELETE", "/api/info"),
                             ("GET", "/elsewhere"), ("GET", "/api/sessions/abc/words")):
            with self.subTest(path=path):
                status, body, _ = self.call(method, path)
                self.assertEqual((status, body["error"]["code"]), (404, "not_found"))


class LiveSessionTest(HttpTestCase):
    def test_a_client_can_submit_words_one_by_one_and_receive_trace_records(self):
        status, start, _ = self.call("POST", "/api/sessions", {"agent": "hybrid", "request_id": "r1"})
        self.assertEqual((status, start["type"], start["request_id"]), (201, "start", "r1"))
        sid = start["session"]
        events = []
        for word in "beige Loomsy sneakers size 10 under 3000 please".split():
            status, event, _ = self.call("POST", f"/api/sessions/{sid}/words", {"word": word})
            self.assertEqual(status, 200)
            events.append(event)
        self.assertEqual([e["seq"] for e in events], list(range(1, 9)))
        self.assertEqual(sum(1 for e in events if e["commit"]), 1)
        self.assertEqual(events[0]["trace"]["reason"], "category not known")
        status, final, _ = self.call("POST", f"/api/sessions/{sid}/finish")
        self.assertEqual((status, final["final_product_id"]), (200, "P0081"))
        self.assertEqual(self.call("DELETE", f"/api/sessions/{sid}")[0], 204)
        self.assertEqual(self.call("POST", f"/api/sessions/{sid}/words", {"word": "x"})[0], 404)

    def test_errors_are_json_with_a_code(self):
        sid = self.call("POST", "/api/sessions", {})[1]["session"]
        for body, status, code in (({"word": "two words"}, 400, "bad_word"), ({"word": 5}, 400, "bad_word"),
                                   ({}, 400, "bad_word")):
            with self.subTest(body=body):
                got, payload, _ = self.call("POST", f"/api/sessions/{sid}/words", body)
                self.assertEqual((got, payload["error"]["code"]), (status, code))
        self.assertEqual(self.call("POST", "/api/sessions", {"agent": "nope"})[1]["error"]["code"],
                         "unknown_agent")

    def test_bad_json_and_oversized_bodies(self):
        sid = self.call("POST", "/api/sessions", {})[1]["session"]
        for raw in (b"{not json", b"[1, 2]", b'"word"', b"\xff\xfe"):
            with self.subTest(raw=raw):
                status, payload, _ = self.call("POST", f"/api/sessions/{sid}/words", raw=raw)
                self.assertEqual((status, payload["error"]["code"]), (400, "bad_json"))
        status, payload, _ = self.call("POST", f"/api/sessions/{sid}/words",
                                       raw=b'{"word": "' + b"a" * (MAX_BODY_BYTES + 10) + b'"}')
        self.assertEqual((status, payload["error"]["code"]), (413, "body_too_large"))

    def test_a_body_on_a_route_that_ignores_it_does_not_break_the_connection(self):
        """fetch() often sends '{}' with every POST: it must not be read as the next request."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        headers = {"Content-Type": "application/json"}

        def send(method, path, body=None):
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read() or b"null")

        status, start = send("POST", "/api/sessions", "{}")
        sid = start["session"]
        self.assertEqual(send("POST", f"/api/sessions/{sid}/words", '{"word": "black"}')[0], 200)
        self.assertEqual(send("POST", f"/api/sessions/{sid}/finish", "{}")[0], 200)       # body ignored
        self.assertEqual(send("GET", "/api/health", "ignored body")[0], 200)                # GET with a body
        self.assertEqual(send("DELETE", f"/api/sessions/{sid}", '{"x": 1}')[0], 204)       # DELETE with a body
        self.assertEqual(send("GET", "/api/info")[0], 200)                                  # still in sync
        connection.close()

    def test_an_empty_body_is_an_empty_object(self):
        status, payload, _ = self.call("POST", "/api/sessions", raw=b"")
        self.assertEqual((status, payload["agent"]), (201, "hybrid"))

    def test_unicode_survives_the_round_trip(self):
        sid = self.call("POST", "/api/sessions", {})[1]["session"]
        status, event, _ = self.call("POST", f"/api/sessions/{sid}/words", {"word": "काली"})
        self.assertEqual((status, event["word"]), (200, "काली"))

    def test_parallel_clients(self):
        results, errors = [], []

        def client():
            try:
                sid = self.call("POST", "/api/sessions", {})[1]["session"]
                for word in "beige Loomsy sneakers size 10 under 3000".split():
                    self.call("POST", f"/api/sessions/{sid}/words", {"word": word})
                results.append(self.call("POST", f"/api/sessions/{sid}/finish")[1]["final_product_id"])
            except Exception as err:                       # pragma: no cover
                errors.append(err)

        threads = [threading.Thread(target=client) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((errors, results), ([], ["P0081"] * 12))


class ReplayStreamTest(HttpTestCase):
    def test_an_example_streams_start_words_final_done_in_order(self):
        events = self.sse("/api/replay?example=dev-0004&delay_ms=0")
        names = [e[0] for e in events]
        self.assertEqual(names, ["start"] + ["word"] * 15 + ["final", "done"])
        self.assertEqual([e[2] for e in events[1:16]], [str(i) for i in range(1, 16)])
        self.assertEqual(events[1][1]["trace"]["word"], "I")
        final = events[-2][1]
        self.assertTrue(final["evaluation"]["correct"])
        self.assertAlmostEqual(final["evaluation"]["score"], 0.48)

    def test_free_text_and_agent_choice(self):
        events = self.sse("/api/replay?text=navy%20Urbanyx%20hoodie%20size%20M&agent=heuristic&delay_ms=0")
        self.assertEqual(events[0][1]["agent"], "heuristic")
        self.assertEqual(events[-2][1]["final_product_id"], "P0633")
        self.assertIsNone(events[-2][1]["evaluation"])

    def test_errors_come_before_any_stream_as_plain_json(self):
        for path, status, code in (("/api/replay", 400, "bad_request"),
                                   ("/api/replay?example=nope", 404, "unknown_example"),
                                   ("/api/replay?text=hi&agent=x", 400, "unknown_agent"),
                                   ("/api/replay?text=hi&delay_ms=abc", 400, "bad_request")):
            with self.subTest(path=path):
                got, body, _ = self.call("GET", path)
                self.assertEqual((got, body["error"]["code"]), (status, code))

    def test_the_server_paces_the_stream_and_caps_the_delay(self):
        import time
        started = time.monotonic()
        self.sse("/api/replay?text=black%20cap&delay_ms=60")
        elapsed = time.monotonic() - started
        self.assertGreater(elapsed, 0.1)                   # start + 2 words, 60 ms each
        import server.http_app as http_app
        real_cap, http_app.MAX_REPLAY_DELAY_MS = http_app.MAX_REPLAY_DELAY_MS, 30
        try:
            started = time.monotonic()
            self.sse("/api/replay?text=black&delay_ms=999999")   # asked for 1000 s, capped at 30 ms
            self.assertLess(time.monotonic() - started, 2.0)
        finally:
            http_app.MAX_REPLAY_DELAY_MS = real_cap

    def test_a_client_that_hangs_up_does_not_hurt_the_server(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        connection.request("GET", "/api/replay?example=dev-0001&delay_ms=50")
        response = connection.getresponse()
        response.fp.readline()
        connection.close()                                 # walk away mid-stream
        self.assertEqual(self.call("GET", "/api/health")[0], 200)


class ExamplesAndResultsTest(HttpTestCase):
    def test_examples(self):
        status, page, _ = self.call("GET", "/api/examples?set=dev&tag=correction&limit=3")
        self.assertEqual((status, page["total"], len(page["items"])), (200, 55, 3))
        self.assertEqual(self.call("GET", "/api/examples?limit=x")[0], 400)
        status, detail, _ = self.call("GET", "/api/examples/dev-0004")
        self.assertEqual((status, detail["target"]), (200, "P0206"))
        self.assertEqual(self.call("GET", "/api/examples/zzz")[0], 404)

    def test_results(self):
        status, result, _ = self.call("GET", "/api/results/dev")
        self.assertEqual(status, 200)
        self.assertAlmostEqual(result["summary"]["score"], 43.5, delta=0.05)
        self.assertEqual(self.call("GET", "/api/results/nope")[0], 404)

    def test_an_unexpected_failure_is_a_generic_500(self):
        original = self.service.info
        self.service.info = lambda: 1 / 0
        try:
            status, body, _ = self.call("GET", "/api/info")
        finally:
            self.service.info = original
        self.assertEqual((status, body["error"]["code"], "division" in json.dumps(body)), (500, "internal", False))


class StaticFilesTest(HttpTestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "site").mkdir()
        (root / "site" / "index.html").write_text("<h1>hello</h1>")
        (root / "site" / "app.js").write_text("console.log(1)")
        (root / "secret.txt").write_text("do not serve")
        cls.static_dir = root / "site"
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.tmp.cleanup()

    def get_raw(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, response.getheader("Content-Type"), body

    def test_index_and_files_are_served_with_types(self):
        status, kind, body = self.get_raw("/")
        self.assertEqual((status, body), (200, b"<h1>hello</h1>"))
        self.assertTrue(kind.startswith("text/html"))
        status, kind, _ = self.get_raw("/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", kind)

    def test_nothing_outside_the_folder_is_served(self):
        for path in ("/../secret.txt", "/..%2fsecret.txt", "/%2e%2e/secret.txt", "//etc/passwd",
                     "/site/../../secret.txt"):
            with self.subTest(path=path):
                status, _, body = self.get_raw(path)
                self.assertEqual(status, 404)
                self.assertNotIn(b"do not serve", body)

    def test_the_api_still_works_next_to_the_static_files(self):
        self.assertEqual(self.call("GET", "/api/health")[0], 200)
        self.assertEqual(self.get_raw("/missing.html")[0], 404)


if __name__ == "__main__":
    unittest.main()


class ClientScriptTest(HttpTestCase):
    """The example client in scripts/ works against a real server."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

    def run_client(self, *args):
        import contextlib
        import io
        import stream_client
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = stream_client.main(["--server", f"http://127.0.0.1:{self.port}", *args])
        return code, out.getvalue()

    def test_live_mode_sends_words_one_at_a_time(self):
        code, text = self.run_client("--live", "beige Loomsy sneakers size 10 under 3000 please")
        self.assertEqual(code, 0)
        self.assertIn("COMMIT P0081", text)
        self.assertIn("final: P0081", text)
        self.assertEqual(sum(1 for line in text.splitlines() if line[:3].strip().isdigit()), 8)

    def test_replay_modes(self):
        code, text = self.run_client("--replay-example", "dev-0004", "--delay", "0")
        self.assertEqual(code, 0)
        self.assertIn("scored: correct=True early_words=2", text)
        code, text = self.run_client("--replay", "navy Nike hoodies size M", "--delay", "0")
        self.assertIn("brand: nike", text)

    def test_an_error_is_reported_not_a_traceback(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_client("--replay-example", "nope", "--delay", "0")
        self.assertIn("unknown_example", str(ctx.exception))


class SilentClientTest(unittest.TestCase):
    def test_a_client_that_connects_and_says_nothing_is_dropped(self):
        import socket
        import time
        server = make_server(StreamService(), port=0, timeout=0.3)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            sock = socket.create_connection(("127.0.0.1", server.server_address[1]))
            sock.settimeout(3)
            started = time.monotonic()
            self.assertEqual(sock.recv(1), b"")             # the server closed the connection
            self.assertLess(time.monotonic() - started, 2.0)
            sock.close()
            # and the server still works
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/health") as r:
                self.assertEqual(r.status, 200)
        finally:
            server.shutdown()
            server.server_close()

    def test_a_client_that_sends_half_a_request_is_dropped(self):
        import socket
        server = make_server(StreamService(), port=0, timeout=0.3)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            sock = socket.create_connection(("127.0.0.1", server.server_address[1]))
            sock.settimeout(3)
            sock.sendall(b"POST /api/sessions HTTP/1.1\r\nContent-Length: 100\r\n\r\n{")
            self.assertIn(sock.recv(4096)[:12], (b"", b"HTTP/1.1 400", b"HTTP/1.1 408"))
            sock.close()
        finally:
            server.shutdown()
            server.server_close()
