"""The contract document (docs/stream-contract.md) is checked against the running system, so the
two cannot drift apart: examples, endpoint table, OpenAPI document, error table, limits, models."""
import json
import re
import unittest
from pathlib import Path

from tests._server_fixture import LiveServer, require_extras

require_extras()

import httpx  # noqa: E402

from server import app as app_module  # noqa: E402
from server import models  # noqa: E402
from server.app import Settings, create_app  # noqa: E402
from server.service import AGENT_NAMES, Limits, StreamService  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "stream-contract.md").read_text(encoding="utf-8")
SOURCE = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "backend" / "server").glob("*.py")}
REQUIREMENTS = (ROOT / "backend" / "requirements-server.txt").read_text(encoding="utf-8")
SERVICE = StreamService()


def json_blocks():
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", DOC, flags=re.S)]


def normal(path):
    return re.sub(r"\{[^}]*\}", "{}", path)


class ExampleShapesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events = SERVICE.run("beige Loomsy sneakers size 10 under 3000 please".split(), request_id="demo-1")
        cls.replayed_final = list(SERVICE.replay(example="dev-0004"))[-1]
        cls.by_type = {}
        for block in json_blocks():
            cls.by_type.setdefault(block.get("type", "evaluation" if "gold_filters" in block else "x"), []).append(block)

    def test_there_is_one_example_of_each_event(self):
        self.assertEqual({k: len(v) for k, v in self.by_type.items()},
                         {"start": 1, "word": 2, "final": 1, "evaluation": 1})

    def test_start_event_is_exactly_the_real_one(self):
        self.assertEqual(self.by_type["start"][0], self.events[0])

    def test_word_events_have_the_real_keys_and_values(self):
        ordinary, commit_word = self.by_type["word"]
        for doc, real in ((ordinary, self.events[3]), (commit_word, self.events[8])):
            self.assertEqual(set(doc), set(real))
            self.assertEqual(set(doc["trace"]), set(real["trace"]))
            self.assertEqual(doc["trace"]["filters"], real["trace"]["filters"])
            self.assertEqual((doc["seq"], doc["word"], doc["searches"]), (real["seq"], real["word"], real["searches"]))
            self.assertEqual(doc["trace"]["reason"], real["trace"]["reason"])
        self.assertEqual(ordinary, dict(self.events[3]))                 # the ordinary one is exact
        self.assertAlmostEqual(commit_word["trace"]["risk"], self.events[8]["trace"]["risk"], places=3)
        self.assertEqual(commit_word["commit"], self.events[8]["commit"])
        self.assertEqual(set(commit_word["committed"]), set(self.events[8]["committed"]))

    def test_final_event_and_evaluation(self):
        doc = self.by_type["final"][0]
        self.assertEqual(set(doc), set(self.events[-1]))
        self.assertEqual(doc["filters"], self.events[-1]["filters"])
        evaluation = self.by_type["evaluation"][0]
        self.assertEqual(set(evaluation), set(self.replayed_final["evaluation"]))
        self.assertAlmostEqual(evaluation["score"], self.replayed_final["evaluation"]["score"], places=6)
        self.assertEqual(evaluation["gold_filters"], self.replayed_final["evaluation"]["gold_filters"])

    def test_every_trace_field_has_a_row_in_the_field_table(self):
        table = DOC[DOC.index("| `trace` field |"):DOC.index("`searches` on the event")]
        for name in models.Trace.model_fields:
            if name not in ("index", "word", "product_id"):             # shown in the examples
                self.assertIn(f"`{name}`", table, name)


class EndpointsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(SERVICE)
        cls.rows = re.findall(r"^\| `(GET|POST|WS) (/api/[^`]*)`[^|]*\|.*\| (`?\d{3}`?|upgrade)", DOC, flags=re.M)
        cls.live = LiveServer(cls.app).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.live.__exit__()

    def test_the_documented_rest_endpoints_are_exactly_the_openapi_paths(self):
        documented = {(m, normal(p.split("?")[0])) for m, p, _ in self.rows if m != "WS"}
        spec = {(method.upper(), normal(path)) for path, ops in self.app.openapi()["paths"].items() for method in ops}
        self.assertEqual(documented, spec)

    def test_the_websocket_endpoint_is_documented_and_exists(self):
        self.assertIn(("WS", "/api/ws"), [(m, p.split("?")[0]) for m, p, _ in self.rows])
        self.assertIn("/api/ws", [getattr(r, "path", None) for r in self.app.routes])

    def test_every_documented_endpoint_answers_with_the_documented_status(self):
        concrete = {"/api/info": None, "/api/health": None,
                    "/api/step": {"words": ["black"]}, "/api/answer": {"words": ["black"]},
                    "/api/run": {"words": ["black"]},
                    "/api/replay": None, "/api/examples": None, "/api/examples/{id}": None,
                    "/api/results/{set}": None}
        paths = {"/api/replay": "/api/replay?text=black&delay_ms=0", "/api/examples/{id}": "/api/examples/dev-0004",
                 "/api/results/{set}": "/api/results/dev", "/api/examples": "/api/examples?limit=2"}
        with httpx.Client(base_url=self.live.url) as client:
            for method, path, success in self.rows:
                if method == "WS":
                    continue
                path = path.split("?")[0]
                with self.subTest(endpoint=f"{method} {path}"):
                    body = concrete[path]
                    response = client.request(method, paths.get(path, path), json=body)
                    self.assertEqual(response.status_code, int(success.strip("`")))

    def test_the_documented_agents_are_the_real_ones(self):
        for name in AGENT_NAMES:
            self.assertIn(f"`{name}`", DOC)
        self.assertEqual(models.RunRequest.model_fields["agent"].annotation.__args__, tuple(AGENT_NAMES))


class ErrorTableTest(unittest.TestCase):
    def test_every_error_the_code_can_send_is_documented_with_its_status(self):
        documented = {}
        for status, codes in re.findall(r"^\| (\d{3}) \| ([^|]+) \|", DOC, flags=re.M):
            for code in re.findall(r"`([a-z_]+)`", codes):
                documented[code] = int(status)
        raised = {}
        for text in SOURCE.values():
            for status, code in re.findall(r'ServiceError\((\d{3}), "([a-z_]+)"', text):
                raised[code] = int(status)
            for status, code in re.findall(r'fail\((\d{3}), "([a-z_]+)"', text):
                raised[code] = int(status)
        raised.update({"not_found": 404, "method_not_allowed": 405, "body_too_large": 413})   # from the HTTP handler
        self.assertEqual(raised, documented)


class LimitsTest(unittest.TestCase):
    def test_documented_numbers_match_the_defaults(self):
        limits = Limits()
        self.assertEqual((limits.max_words, limits.max_word_chars, limits.max_text_chars, limits.max_body_bytes),
                         (500, 100, 4000, 16 * 1024))
        self.assertEqual((app_module.MAX_REPLAY_DELAY_MS, app_module.WS_IDLE_SECONDS), (2000, 300.0))
        for text in ("500 words", "100 characters", "4000 characters", "16 KB", "capped at 2000",
                     "5 minutes", "30 second idle limit"):
            self.assertIn(text, DOC)
        self.assertIn("default=30", SOURCE["__main__.py"])
        self.assertIn("ws_max_size=16 * 1024", SOURCE["__main__.py"])
        self.assertIn('default="127.0.0.1"', SOURCE["__main__.py"])
        self.assertIn("default=8765", SOURCE["__main__.py"])

    def test_the_cors_default_matches_the_document(self):
        for host in ("localhost", "127.0.0.1"):
            self.assertRegex(f"http://{host}:5173", app_module.LOCAL_ORIGINS)
        self.assertNotRegex("http://evil.example", app_module.LOCAL_ORIGINS)
        self.assertIn("`localhost`, `127.0.0.1` or `[::1]`", DOC)
        self.assertIsNone(Settings().api_key)


class LibrariesAndHygieneTest(unittest.TestCase):
    def test_every_required_package_is_explained_in_the_document(self):
        for package in ("fastapi", "uvicorn", "websockets", "httpx", "httpx-sse"):
            self.assertRegex(REQUIREMENTS, rf"(?m)^{re.escape(package)}>=")
            self.assertIn(package, DOC.lower())
        self.assertIn("Python 3.11", REQUIREMENTS)
        self.assertIn("Python 3.11 or newer", DOC)

    def test_the_agent_package_does_not_depend_on_any_of_them(self):
        for path in (ROOT / "backend" / "anticipatory").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)^\s*(import|from)\s+(fastapi|uvicorn|httpx|httpx_sse|websockets|pydantic|starlette)\b", path.name)

    def test_no_em_or_en_dashes_and_every_json_block_parses(self):
        self.assertNotRegex(DOC, "[" + chr(0x2013) + chr(0x2014) + "]")
        self.assertEqual(len(json_blocks()), 5)


if __name__ == "__main__":
    unittest.main()
