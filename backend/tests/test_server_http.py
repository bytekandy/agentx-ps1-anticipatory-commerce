import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

from tests._server_fixture import LiveServer, require_extras

require_extras()

import httpx  # noqa: E402
from httpx_sse import connect_sse  # noqa: E402
from websockets.exceptions import ConnectionClosed, InvalidStatus  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

from server.app import Settings, create_app  # noqa: E402
from server.service import Limits, StreamService  # noqa: E402


def committed_dev_score() -> float:
    """The dev score in outputs/report.md, which scripts/report.py writes with the results."""
    report = (Path(__file__).resolve().parents[1] / "outputs" / "report.md").read_text(encoding="utf-8")
    return float(re.search(r"\| \*\*score\*\* \| \*\*([\d.]+)\*\*", report).group(1))


WORDS = "beige Loomsy sneakers size 10 under 3000 please".split()
SERVICE = StreamService()


class ServerTestCase(unittest.TestCase):
    settings = Settings()
    limits = Limits()

    @classmethod
    def setUpClass(cls):
        service = SERVICE if cls.limits == Limits() else StreamService(
            limits=cls.limits, lexicon=SERVICE.lexicon, directory=SERVICE.directory)
        cls.live = LiveServer(create_app(service, cls.settings)).__enter__()
        cls.client = httpx.Client(base_url=cls.live.url)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.live.__exit__()

    def ws_events(self, words, query="", finish=True):
        """Drive one WebSocket request; return every event received."""
        events = []
        with connect(f"{self.live.ws_url}/api/ws{query}") as ws:
            events.append(json.loads(ws.recv()))
            for word in words:
                ws.send(json.dumps({"word": word}))
                events.append(json.loads(ws.recv()))
            if finish:
                ws.send(json.dumps({"finish": True}))
                events.append(json.loads(ws.recv()))
        return events


class BasicsTest(ServerTestCase):
    def test_health_info_and_the_generated_docs(self):
        self.assertEqual(self.client.get("/api/health").json(), {"status": "ok"})
        info = self.client.get("/api/info").json()
        self.assertEqual((info["version"], info["products"], info["auth_required"]), (1, 1074, False))
        spec = self.client.get("/openapi.json").json()
        self.assertIn("/api/step", spec["paths"])
        self.assertEqual(self.client.get("/docs").status_code, 200)

    def test_security_headers(self):
        response = self.client.get("/api/info")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")

    def test_errors_are_one_json_shape_even_for_unknown_paths_and_methods(self):
        for method, path, status, code in (("GET", "/api/nope", 404, "not_found"),
                                           ("GET", "/elsewhere", 404, "not_found"),
                                           ("POST", "/api/health", 405, "method_not_allowed"),
                                           ("GET", "/api/step", 405, "method_not_allowed")):
            with self.subTest(path=path):
                response = self.client.request(method, path)
                self.assertEqual((response.status_code, response.json()["error"]["code"]), (status, code))


class LatencyTest(ServerTestCase):
    """A keep-alive call must not wait for a delayed ACK (about 40 ms when Nagle's algorithm is on)."""

    def test_keep_alive_calls_are_fast(self):
        import statistics
        import time
        timings = []
        for _ in range(30):
            started = time.perf_counter()
            self.client.get("/api/health")
            timings.append(1000 * (time.perf_counter() - started))
        self.assertLess(statistics.median(timings), 10.0, f"median {statistics.median(timings):.1f} ms")

    def test_a_stateless_step_and_a_websocket_word_are_fast(self):
        import statistics
        import time
        steps = []
        for n in range(1, 9):
            started = time.perf_counter()
            self.client.post("/api/step", json={"words": WORDS[:n]})
            steps.append(1000 * (time.perf_counter() - started))
        self.assertLess(statistics.median(steps), 15.0)
        with connect(f"{self.live.ws_url}/api/ws") as ws:
            ws.recv()
            words = []
            for word in WORDS:
                started = time.perf_counter()
                ws.send(json.dumps({"word": word}))
                ws.recv()
                words.append(1000 * (time.perf_counter() - started))
        self.assertLess(statistics.median(words), 10.0)


class StatelessRestTest(ServerTestCase):
    def test_step_answer_and_run(self):
        step = self.client.post("/api/step", json={"words": WORDS}).json()
        self.assertEqual((step["type"], step["seq"], step["commit"]["product_id"]), ("word", 8, "P0081"))
        answer = self.client.post("/api/answer", json={"words": WORDS}).json()
        self.assertEqual((answer["type"], answer["final_product_id"]), ("final", "P0081"))
        run = self.client.post("/api/run", json={"words": WORDS, "request_id": "r1"}).json()["events"]
        self.assertEqual([e["type"] for e in run], ["start"] + ["word"] * 8 + ["final"])
        self.assertEqual(run[0]["request_id"], "r1")

    def test_agent_choice(self):
        for name in ("hybrid", "heuristic", "learned"):
            answer = self.client.post("/api/answer", json={"words": WORDS, "agent": name}).json()
            self.assertEqual(answer["final_product_id"], "P0081", name)

    def test_bad_input_is_a_400_in_the_project_error_shape(self):
        for body in ({}, {"words": []}, {"words": "text"}, {"words": [5]}, {"words": ["two words"]},
                     {"words": ["x"], "agent": "nope"}, {"words": ["x" * 101]}):
            with self.subTest(body=body):
                response = self.client.post("/api/step", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertIn(response.json()["error"]["code"], ("bad_request", "bad_word", "unknown_agent"))
        self.assertEqual(self.client.post("/api/step", content=b"{not json",
                                          headers={"content-type": "application/json"}).status_code, 400)

    def test_too_many_words_and_too_big_a_body(self):
        response = self.client.post("/api/step", json={"words": ["w"] * 501})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (413, "too_many_words"))
        response = self.client.post("/api/step", content=b'{"words": ["' + b"a" * 20000 + b'"]}',
                                    headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 413)

    def test_unicode_survives(self):
        step = self.client.post("/api/step", json={"words": ["काली"]}).json()
        self.assertEqual(step["word"], "काली")

    def test_parallel_clients(self):
        results, errors = [], []

        def client():
            try:
                with httpx.Client(base_url=self.live.url) as c:
                    for n in range(1, 9):
                        c.post("/api/step", json={"words": WORDS[:n]})
                    results.append(c.post("/api/answer", json={"words": WORDS}).json()["final_product_id"])
            except Exception as err:                       # pragma: no cover
                errors.append(err)

        threads = [threading.Thread(target=client) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((errors, results), ([], ["P0081"] * 12))


class WebSocketTest(ServerTestCase):
    def test_words_in_events_pushed_out(self):
        events = self.ws_events(WORDS)
        self.assertEqual([e["type"] for e in events], ["start"] + ["word"] * 8 + ["final"])
        self.assertEqual(events[8]["commit"]["product_id"], "P0081")
        self.assertEqual(events[-1]["final_product_id"], "P0081")

    def test_the_websocket_and_the_stateless_rest_agree_at_every_word(self):
        events = self.ws_events(WORDS)
        for n in range(1, len(WORDS) + 1):
            self.assertEqual(self.client.post("/api/step", json={"words": WORDS[:n]}).json(), events[n])

    def test_agent_and_request_id_come_from_the_query(self):
        start = self.ws_events(["black"], "?agent=heuristic&request_id=abc")[0]
        self.assertEqual((start["agent"], start["request_id"]), ("heuristic", "abc"))

    def test_a_bad_word_is_an_error_message_and_the_run_goes_on(self):
        with connect(f"{self.live.ws_url}/api/ws") as ws:
            ws.recv()
            for message, code in (({"word": "two words"}, "bad_word"), ("not json", "bad_json"),
                                  ([1, 2], "bad_request"), ({"word": ""}, "bad_word")):
                ws.send(message if isinstance(message, str) else json.dumps(message))
                error = json.loads(ws.recv())
                self.assertEqual((error["type"], error["error"]["code"]), ("error", code))
            ws.send(json.dumps({"word": "black"}))
            self.assertEqual(json.loads(ws.recv())["word"], "black")

    def test_an_unknown_agent_is_rejected(self):
        with connect(f"{self.live.ws_url}/api/ws?agent=nope") as ws:
            self.assertEqual(json.loads(ws.recv())["error"]["code"], "unknown_agent")
            with self.assertRaises(ConnectionClosed):
                ws.recv()

    def test_the_run_ends_after_the_final_event(self):
        with connect(f"{self.live.ws_url}/api/ws") as ws:
            ws.recv()
            ws.send(json.dumps({"word": "black"}))
            ws.recv()
            ws.send(json.dumps({"finish": True}))
            self.assertEqual(json.loads(ws.recv())["type"], "final")
            with self.assertRaises(ConnectionClosed) as ctx:
                ws.recv()
            self.assertEqual(ctx.exception.rcvd.code, 1000)

    def test_a_client_that_vanishes_mid_run_does_not_hurt_the_server(self):
        with connect(f"{self.live.ws_url}/api/ws") as ws:
            ws.recv()
            ws.send(json.dumps({"word": "black"}))
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_an_oversized_message_closes_the_connection(self):
        with connect(f"{self.live.ws_url}/api/ws", max_size=None) as ws:
            ws.recv()
            ws.send(json.dumps({"word": "a" * 40000}))
            with self.assertRaises(ConnectionClosed):
                ws.recv()


class TooManyWordsOverWebSocketTest(ServerTestCase):
    limits = Limits(max_words=3)

    def test_the_run_is_closed_at_the_word_limit(self):
        with connect(f"{self.live.ws_url}/api/ws") as ws:
            ws.recv()
            for _ in range(3):
                ws.send(json.dumps({"word": "hello"}))
                ws.recv()
            ws.send(json.dumps({"word": "hello"}))
            self.assertEqual(json.loads(ws.recv())["error"]["code"], "too_many_words")
            with self.assertRaises(ConnectionClosed):
                ws.recv()


class IdleWebSocketTest(ServerTestCase):
    settings = Settings(ws_idle_seconds=0.3)

    def test_an_idle_connection_is_closed(self):
        with connect(f"{self.live.ws_url}/api/ws") as ws:
            ws.recv()
            with self.assertRaises(ConnectionClosed) as ctx:
                ws.recv()
            self.assertEqual(ctx.exception.rcvd.code, 1001)


class ReplayStreamTest(ServerTestCase):
    def sse(self, **params):
        with httpx.Client(base_url=self.live.url, timeout=30) as client:
            with connect_sse(client, "GET", "/api/replay", params=params) as source:
                self.assertEqual(source.response.status_code, 200)
                self.assertTrue(source.response.headers["content-type"].startswith("text/event-stream"))
                return [(e.event, e.id, json.loads(e.data)) for e in source.iter_sse()]

    def test_an_example_streams_start_words_final_done_in_order(self):
        events = self.sse(example="dev-0004", delay_ms=0)
        self.assertEqual([e[0] for e in events], ["start"] + ["word"] * 15 + ["final", "done"])
        self.assertEqual([e[1] for e in events[1:16]], [str(i) for i in range(1, 16)])
        self.assertEqual(events[1][2]["trace"]["word"], "I")
        final = events[-2][2]
        self.assertTrue(final["evaluation"]["correct"])
        self.assertAlmostEqual(final["evaluation"]["score"], 0.48)
        self.assertEqual(events[-1][2], {"type": "done", "version": 1})

    def test_free_text_and_agent_choice(self):
        events = self.sse(text="navy Urbanyx hoodie size M", agent="heuristic", delay_ms=0)
        self.assertEqual(events[0][2]["agent"], "heuristic")
        self.assertEqual(events[-2][2]["final_product_id"], "P0633")
        self.assertIsNone(events[-2][2]["evaluation"])

    def test_errors_come_before_streaming_as_plain_json(self):
        for params, status, code in (({}, 400, "bad_request"), ({"example": "nope"}, 404, "unknown_example"),
                                     ({"text": "hi", "agent": "x"}, 400, "unknown_agent"),
                                     ({"text": "hi", "delay_ms": "abc"}, 400, "bad_request"),
                                     ({"text": "a", "example": "dev-0001"}, 400, "bad_request")):
            with self.subTest(params=params):
                response = self.client.get("/api/replay", params=params)
                self.assertEqual((response.status_code, response.json()["error"]["code"]), (status, code))

    def test_the_server_paces_the_stream(self):
        import time
        started = time.monotonic()
        self.sse(text="black cap", delay_ms=80)
        self.assertGreater(time.monotonic() - started, 0.15)      # the start and two words

    def test_a_client_that_hangs_up_does_not_hurt_the_server(self):
        with httpx.Client(base_url=self.live.url, timeout=30) as client:
            with connect_sse(client, "GET", "/api/replay", params={"example": "dev-0001", "delay_ms": 100}) as s:
                next(s.iter_sse())
        self.assertEqual(self.client.get("/api/health").status_code, 200)


class ExamplesAndResultsTest(ServerTestCase):
    def test_examples(self):
        page = self.client.get("/api/examples", params={"set": "dev", "tag": "correction", "limit": 3}).json()
        self.assertEqual((page["total"], len(page["items"])), (55, 3))
        self.assertEqual(self.client.get("/api/examples", params={"limit": "x"}).status_code, 400)
        detail = self.client.get("/api/examples/dev-0004").json()
        self.assertEqual(detail["target"], "P0206")
        self.assertEqual(self.client.get("/api/examples/zzz").status_code, 404)

    def test_results(self):
        result = self.client.get("/api/results/dev").json()
        self.assertAlmostEqual(result["summary"]["score"], committed_dev_score(), delta=0.05)
        self.assertEqual(self.client.get("/api/results/nope").status_code, 404)


class CrashTest(ServerTestCase):
    def test_an_unexpected_failure_is_a_generic_500(self):
        original = SERVICE.info
        SERVICE.info = lambda: 1 / 0
        try:
            with httpx.Client(base_url=self.live.url) as c:
                response = c.get("/api/info")
        finally:
            SERVICE.info = original
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (500, "internal"))
        self.assertNotIn("division", response.text)


class ApiKeyTest(ServerTestCase):
    settings = Settings(api_key="s3cret-key")

    def test_a_key_is_required_everywhere_except_health(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        for method, path in (("GET", "/api/info"), ("POST", "/api/step"), ("GET", "/api/examples"),
                             ("GET", "/api/replay"), ("GET", "/api/results/dev")):
            with self.subTest(path=path):
                response = self.client.request(method, path, json={"words": ["x"]} if method == "POST" else None)
                self.assertEqual((response.status_code, response.json()["error"]["code"]), (401, "unauthorized"))

    def test_wrong_keys_are_rejected(self):
        for headers in ({"X-API-Key": "nope"}, {"X-API-Key": ""}, {"Authorization": "Bearer nope"},
                        {"Authorization": "Basic s3cret-key"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.get("/api/info", headers=headers).status_code, 401)

    def test_the_key_works_as_a_header_a_bearer_token_or_a_query_parameter(self):
        for kwargs in ({"headers": {"X-API-Key": "s3cret-key"}}, {"headers": {"Authorization": "Bearer s3cret-key"}},
                       {"params": {"api_key": "s3cret-key"}}):
            with self.subTest(kwargs=kwargs):
                response = self.client.get("/api/info", **kwargs)
                self.assertEqual((response.status_code, response.json()["auth_required"]), (200, True))
        response = self.client.post("/api/step", json={"words": WORDS}, headers={"X-API-Key": "s3cret-key"})
        self.assertEqual(response.json()["commit"]["product_id"], "P0081")

    def test_the_replay_stream_takes_the_key_in_the_query_for_browsers(self):
        with httpx.Client(base_url=self.live.url, timeout=30) as client:
            with connect_sse(client, "GET", "/api/replay",
                             params={"text": "black cap", "delay_ms": 0, "api_key": "s3cret-key"}) as s:
                self.assertEqual([e.event for e in s.iter_sse()][-1], "done")

    def test_the_websocket_needs_the_key_too(self):
        for query in ("", "?api_key=wrong"):                 # refused during the handshake: HTTP 403
            with self.assertRaises(InvalidStatus) as ctx:
                connect(f"{self.live.ws_url}/api/ws{query}")
            self.assertEqual(ctx.exception.response.status_code, 403)
        events = self.ws_events(["black"], "?api_key=s3cret-key")
        self.assertEqual(events[0]["type"], "start")
        with connect(f"{self.live.ws_url}/api/ws", additional_headers={"X-API-Key": "s3cret-key"}) as ws:
            self.assertEqual(json.loads(ws.recv())["type"], "start")


class CorsTest(ServerTestCase):
    def origin(self, origin, method="GET"):
        headers = {"Origin": origin}
        if method == "OPTIONS":
            headers["Access-Control-Request-Method"] = "POST"
        return self.client.request(method, "/api/health", headers=headers).headers.get(
            "access-control-allow-origin")

    def test_pages_served_from_this_machine_are_allowed_by_default_and_others_are_not(self):
        for origin in ("http://localhost:5173", "http://127.0.0.1:3000", "https://localhost"):
            self.assertEqual(self.origin(origin), origin, origin)
        for origin in ("http://evil.example", "http://localhost.evil.example", "http://127.0.0.1.evil.com:80"):
            self.assertIsNone(self.origin(origin), origin)

    def test_the_preflight_names_the_methods_and_headers(self):
        response = self.client.options("/api/step", headers={
            "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-api-key"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("POST", response.headers["access-control-allow-methods"])
        self.assertIn("x-api-key", response.headers["access-control-allow-headers"].lower())


class ExplicitCorsTest(ServerTestCase):
    settings = Settings(cors_origins=("https://ui.example",), cors_origin_regex=None)

    def test_only_the_listed_origin_is_allowed(self):
        def allowed(origin):
            return self.client.get("/api/health", headers={"Origin": origin}).headers.get("access-control-allow-origin")
        self.assertEqual(allowed("https://ui.example"), "https://ui.example")
        self.assertIsNone(allowed("http://localhost:5173"))
        self.assertIsNone(allowed("https://other.example"))


class AnyOriginCorsTest(ServerTestCase):
    settings = Settings(cors_origins=("*",))

    def test_star_allows_any_origin_when_asked_for_explicitly(self):
        response = self.client.get("/api/health", headers={"Origin": "https://anything.example"})
        self.assertIn(response.headers.get("access-control-allow-origin"), ("*", "https://anything.example"))


class StaticFilesTest(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "site").mkdir()
        (root / "site" / "index.html").write_text("<h1>hello</h1>")
        (root / "site" / "app.js").write_text("console.log(1)")
        (root / "secret.txt").write_text("do not serve")
        cls.settings = Settings(static_dir=root / "site")
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.tmp.cleanup()

    def test_index_and_files_with_their_types(self):
        response = self.client.get("/")
        self.assertEqual((response.status_code, response.text), (200, "<h1>hello</h1>"))
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertIn("javascript", self.client.get("/app.js").headers["content-type"])

    def test_nothing_outside_the_folder_is_served(self):
        for path in ("/../secret.txt", "/..%2fsecret.txt", "/%2e%2e/secret.txt", "//etc/passwd",
                     "/site/../../secret.txt", "/%2e%2e%2fsecret.txt"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertNotEqual(response.status_code, 200)
                self.assertNotIn("do not serve", response.text)

    def test_the_api_still_works_next_to_the_files(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/missing.html").status_code, 404)


if __name__ == "__main__":
    unittest.main()
