"""The contract document (docs/stream-contract.md) is checked against the running system, so
the two cannot drift apart: examples, error table, endpoint table and limits."""
import json
import re
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from server import http_app
from server.http_app import MAX_BODY_BYTES, MAX_REPLAY_DELAY_MS, make_server
from server.service import Limits, StreamService

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "stream-contract.md").read_text(encoding="utf-8")
SOURCE = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "backend" / "server").glob("*.py")}


def json_blocks():
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", DOC, flags=re.S)]


def keys(value):
    return set(value)


class ExampleShapesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = StreamService()
        session = cls.service.create_session("hybrid", "demo-1")["session"]
        cls.words = [cls.service.push_word(session, w)
                     for w in "beige Loomsy sneakers size 10 under 3000 please".split()]
        cls.final = cls.service.finish(session)
        cls.start = cls.service.create_session("hybrid", "x")
        cls.replay_final = list(cls.service.replay(example="dev-0004"))[-1]
        cls.blocks = {b["type"] if "type" in b else ("evaluation" if "gold_filters" in b else "other"): b
                      for b in json_blocks()}
        cls.by_type = {}
        for block in json_blocks():
            cls.by_type.setdefault(block.get("type", "evaluation" if "gold_filters" in block else "x"), []).append(block)

    def test_start_event(self):
        self.assertEqual(keys(self.by_type["start"][0]), keys(self.start))

    def test_word_events_and_their_trace(self):
        documented = self.by_type["word"]
        self.assertEqual(len(documented), 2)               # an ordinary word and the commit word
        for doc, real in zip(documented, (self.words[2], self.words[7])):
            self.assertEqual(keys(doc), keys(real))
            self.assertEqual(keys(doc["trace"]), keys(real["trace"]))
            self.assertEqual(keys(doc["trace"]["filters"]), keys(real["trace"]["filters"]))
        commit = documented[1]["commit"]
        self.assertEqual(keys(commit), keys(self.words[7]["commit"]))
        self.assertEqual(keys(commit["product"]), keys(self.words[7]["commit"]["product"]))

    def test_the_documented_values_are_the_real_ones(self):
        """Not just the keys: the examples are real output (apart from rounding the risk)."""
        doc = self.by_type["word"][1]
        real = self.words[7]
        self.assertEqual((doc["seq"], doc["word"], doc["searches"]), (real["seq"], real["word"], real["searches"]))
        self.assertEqual(doc["trace"]["filters"], real["trace"]["filters"])
        self.assertEqual(doc["trace"]["reason"], real["trace"]["reason"])
        self.assertAlmostEqual(doc["trace"]["risk"], real["trace"]["risk"], places=3)
        self.assertEqual(doc["commit"]["product"], real["commit"]["product"])

    def test_final_event_and_its_evaluation(self):
        doc = self.by_type["final"][0]
        self.assertEqual(keys(doc), keys(self.final))
        self.assertEqual(doc["filters"], self.final["filters"])
        self.assertEqual(keys(doc["commit"]), keys(self.final["commit"]))
        evaluation = self.by_type["evaluation"][0]
        self.assertEqual(keys(evaluation), keys(self.replay_final["evaluation"]))
        self.assertAlmostEqual(evaluation["score"], self.replay_final["evaluation"]["score"], places=6)

    def test_every_documented_trace_field_has_a_row_in_the_field_table(self):
        table = DOC[DOC.index("| `trace` field |"):DOC.index("`searches` on the event")]
        for name in self.words[0]["trace"]:
            if name not in ("index", "word", "product_id"):           # shown elsewhere in the doc
                self.assertIn(f"`{name}`", table, name)

    def test_info_keys_are_the_documented_ones(self):
        info = self.service.info()
        for name in ("version", "agents", "default_agent", "products", "datasets",
                     "break_even_risk", "limits"):
            self.assertIn(name, info)
        self.assertIn("break_even_risk", DOC)


class ErrorTableTest(unittest.TestCase):
    def test_every_error_the_code_can_raise_is_documented_with_its_status(self):
        documented = {}
        for status, codes in re.findall(r"^\| (\d{3}) \| ([^|]+) \|", DOC, flags=re.M):
            for code in re.findall(r"`([a-z_]+)`", codes):
                documented[code] = int(status)
        raised = {}
        for text in SOURCE.values():
            for status, code in re.findall(r'ServiceError\((\d{3}), "([a-z_]+)"', text):
                raised[code] = int(status)
        raised["internal"] = 500                                       # sent by the HTTP layer
        self.assertEqual(raised, {k: documented[k] for k in raised if k in documented})
        self.assertEqual(set(raised) - set(documented), set())          # nothing undocumented
        self.assertEqual(set(documented) - set(raised) - {"not_found", "internal"}, set())


class LimitsAndDefaultsTest(unittest.TestCase):
    def test_documented_numbers_match_the_defaults(self):
        limits = Limits()
        self.assertEqual((limits.max_sessions, limits.max_words, limits.max_word_chars,
                          limits.max_text_chars), (200, 500, 100, 4000))
        self.assertEqual((limits.idle_seconds, limits.finished_seconds), (600.0, 30.0))
        self.assertEqual((MAX_BODY_BYTES, MAX_REPLAY_DELAY_MS), (16 * 1024, 2000))
        for text in ("200 open sessions", "500 words", "100 characters", "4000 characters", "16 KB",
                     "**10 minutes**", "**30 seconds**", "capped at 2000", "default 30"):
            self.assertIn(text, DOC)
        self.assertIn('default=30.0', SOURCE["__main__.py"])
        self.assertIn('default="127.0.0.1"', SOURCE["__main__.py"])
        self.assertIn('default=8765', SOURCE["__main__.py"])


class EndpointTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(StreamService(), port=0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as response:
                response.read()
                return response.status
        except urllib.error.HTTPError as err:
            err.read()
            err.close()
            return err.code

    def new_session(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/sessions", data=b"{}", method="POST")
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read())["session"]

    def concrete(self, method, template):
        """A real URL and body for a documented endpoint template."""
        path = template.split("?")[0]
        if "/api/sessions/{id}" in path:
            path = path.replace("{id}", self.new_session())
            return path, ({"word": "black"} if path.endswith("/words") else {})
        if path == "/api/replay":
            return "/api/replay?text=black&delay_ms=0", None
        if path == "/api/examples/{id}":
            return "/api/examples/dev-0004", None
        if path == "/api/results/{set}":
            return "/api/results/dev", None
        return path + ("?set=dev&limit=2" if path == "/api/examples" else ""), ({} if method == "POST" else None)

    def test_every_documented_endpoint_exists_and_answers_with_the_documented_status(self):
        rows = re.findall(r"^\| `(GET|POST|DELETE) (/api/[^`]*)`[^|]*\|.*\| (`?\d{3}`?)", DOC, flags=re.M)
        documented = {(m, p.split("?")[0]) for m, p, _ in rows}
        self.assertEqual(documented, {
            ("GET", "/api/health"), ("GET", "/api/info"), ("POST", "/api/sessions"),
            ("POST", "/api/sessions/{id}/words"), ("POST", "/api/sessions/{id}/finish"),
            ("DELETE", "/api/sessions/{id}"), ("GET", "/api/replay"), ("GET", "/api/examples"),
            ("GET", "/api/examples/{id}"), ("GET", "/api/results/{set}")})
        for method, template, success in rows:
            with self.subTest(endpoint=f"{method} {template}"):
                path, body = self.concrete(method, template)
                self.assertEqual(self.request(method, path, body), int(success.strip("`")))

    def test_the_documented_agents_are_the_real_ones(self):
        from server.service import AGENT_NAMES
        for name in AGENT_NAMES:
            self.assertIn(f"`{name}`", DOC)


class DocumentHygieneTest(unittest.TestCase):
    def test_no_em_or_en_dashes(self):
        self.assertNotRegex(DOC, "[–—]")

    def test_every_json_block_parses(self):
        self.assertEqual(len(json_blocks()), 5)       # start, word, commit word, final, evaluation


if __name__ == "__main__":
    unittest.main()
