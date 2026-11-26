import json
import threading
import unittest
from pathlib import Path

from server.events import ServiceError
from server.service import DATASETS, Limits, StreamService

BACKEND = Path(__file__).resolve().parents[1]


def load(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ServiceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = StreamService()

    def run_live(self, service, words, agent="hybrid"):
        sid = service.create_session(agent)["session"]
        events = [service.push_word(sid, w) for w in words]
        return events, service.finish(sid)

    def assertError(self, status, code, call, *args):
        with self.assertRaises(ServiceError) as ctx:
            call(*args)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (status, code))


class LiveSessionTest(ServiceTestCase):
    WORDS = "beige Loomsy sneakers size 10 under 3000 please".split()

    def test_one_event_per_word_with_the_agents_own_trace(self):
        events, final = self.run_live(self.service, self.WORDS)
        self.assertEqual([e["seq"] for e in events], list(range(1, len(self.WORDS) + 1)))
        for event, word in zip(events, self.WORDS):
            self.assertEqual((event["type"], event["version"], event["word"]), ("word", 1, word))
            self.assertEqual(event["trace"]["word"], word)
            for key in ("filters", "confidence", "settled", "action", "reason", "unresolved"):
                self.assertIn(key, event["trace"])

    def test_the_commit_arrives_once_with_the_product(self):
        events, final = self.run_live(self.service, self.WORDS)
        commits = [e for e in events if e["commit"]]
        self.assertEqual(len(commits), 1)
        commit = commits[0]["commit"]
        self.assertEqual(commit["product_id"], "P0081")
        self.assertEqual(commit["product"]["title"], "Loomsy Street Sneakers, Beige")
        self.assertEqual(commit["seq"], commits[0]["seq"])
        self.assertEqual(final["commit"]["product_id"], "P0081")

    def test_the_final_event(self):
        _, final = self.run_live(self.service, self.WORDS)
        self.assertEqual((final["type"], final["words"], final["final_product_id"]),
                         ("final", len(self.WORDS), "P0081"))
        self.assertEqual(final["filters"], {"category": "sneakers", "colour": "beige", "size": "10",
                                            "brand": "Loomsy", "max_price": 3000})
        self.assertEqual(final["product"]["price"], 2899)
        self.assertEqual(final["searches"], 1)
        self.assertIsNone(final["evaluation"])             # free text has no gold answer

    def test_unresolved_constraints_are_reported(self):
        events, final = self.run_live(self.service, "navy Nike hoodies size M please".split())
        self.assertEqual(final["unresolved"], ["brand: nike"])
        self.assertTrue(any(e["trace"]["unresolved"] for e in events))
        self.assertFalse(any(e["commit"] for e in events))

    def test_each_agent_variant_can_be_chosen(self):
        for name in ("hybrid", "heuristic", "learned"):
            with self.subTest(agent=name):
                _, final = self.run_live(self.service, self.WORDS, agent=name)
                self.assertEqual(final["final_product_id"], "P0081")

    def test_unknown_agent(self):
        self.assertError(400, "unknown_agent", self.service.create_session, "gpt")

    def test_request_id_is_echoed(self):
        self.assertEqual(self.service.create_session("hybrid", "demo-1")["request_id"], "demo-1")


class ValidationTest(ServiceTestCase):
    def test_bad_words(self):
        sid = self.service.create_session()["session"]
        for bad in ("", "   ", "two words", "a\tb", 5, None, ["x"], "x" * 101):
            with self.subTest(word=bad):
                self.assertError(400, "bad_word", self.service.push_word, sid, bad)

    def test_punctuation_odd_unicode_and_long_words_are_fine(self):
        sid = self.service.create_session()["session"]
        for word in ("size,", "Rs.", "₹2,500", "\U0001F45F", "काली", "x" * 100):
            self.service.push_word(sid, word)

    def test_a_word_limit_per_session(self):
        service = StreamService(limits=Limits(max_words=5), lexicon=self.service.lexicon,
                                directory=self.service.directory)
        sid = service.create_session()["session"]
        for _ in range(5):
            service.push_word(sid, "hello")
        self.assertError(413, "too_many_words", service.push_word, sid, "hello")

    def test_unknown_session(self):
        self.assertError(404, "unknown_session", self.service.push_word, "nope", "hello")
        self.assertError(404, "unknown_session", self.service.finish, "nope")
        self.assertError(404, "unknown_session", self.service.close, "nope")

    def test_a_finished_session_takes_no_more(self):
        sid = self.service.create_session()["session"]
        self.service.push_word(sid, "black")
        self.service.finish(sid)
        self.assertError(409, "session_finished", self.service.push_word, sid, "cap")
        self.assertError(409, "session_finished", self.service.finish, sid)

    def test_close_forgets_a_session(self):
        sid = self.service.create_session()["session"]
        self.service.close(sid)
        self.assertError(404, "unknown_session", self.service.push_word, sid, "black")


class LimitsTest(ServiceTestCase):
    def make(self, **limits):
        clock = FakeClock()
        service = StreamService(limits=Limits(**limits), clock=clock, lexicon=self.service.lexicon,
                                directory=self.service.directory)
        return service, clock

    def test_too_many_sessions(self):
        service, _ = self.make(max_sessions=3)
        for _ in range(3):
            service.create_session()
        self.assertError(429, "too_many_sessions", service.create_session)

    def test_idle_sessions_expire_and_free_their_place(self):
        service, clock = self.make(max_sessions=2, idle_seconds=60)
        first = service.create_session()["session"]
        service.create_session()
        clock.now += 61
        self.assertEqual(service.open_sessions(), 0)
        self.assertError(404, "unknown_session", service.push_word, first, "black")
        service.create_session()                           # there is room again

    def test_finished_sessions_do_not_count_against_the_limit_and_are_dropped_quickly(self):
        service, clock = self.make(max_sessions=2, finished_seconds=30)
        for _ in range(10):                                # far more than the limit, one after another
            sid = service.create_session()["session"]
            service.push_word(sid, "black")
            service.finish(sid)
        self.assertEqual(service.open_sessions(), 0)
        clock.now += 31
        self.assertError(404, "unknown_session", service.push_word, sid, "x")   # long finished: gone

    def test_open_sessions_still_hit_the_limit(self):
        service, _ = self.make(max_sessions=2)
        a = service.create_session()["session"]
        service.create_session()
        service.finish(a)                                  # frees a place
        service.create_session()
        self.assertError(429, "too_many_sessions", service.create_session)

    def test_activity_keeps_a_session_alive(self):
        service, clock = self.make(idle_seconds=60)
        sid = service.create_session()["session"]
        for _ in range(5):
            clock.now += 40
            service.push_word(sid, "black")
        service.finish(sid)

    def test_session_ids_are_unguessable_and_unique(self):
        ids = {self.service.create_session()["session"] for _ in range(200)}
        self.assertEqual(len(ids), 200)
        self.assertTrue(all(len(i) >= 12 for i in ids))
        for sid in ids:
            self.service.close(sid)


class IsolationAndThreadsTest(ServiceTestCase):
    def test_interleaved_sessions_do_not_interfere(self):
        a = "beige Loomsy sneakers size 10 under 3000".split()
        b = "navy Urbanyx hoodie size XS no wait S sorry M".split()
        solo_a = self.run_live(self.service, a)[1]["final_product_id"]
        solo_b = self.run_live(self.service, b)[1]["final_product_id"]
        sa, sb = (self.service.create_session()["session"] for _ in range(2))
        for i in range(max(len(a), len(b))):
            if i < len(a):
                self.service.push_word(sa, a[i])
            if i < len(b):
                self.service.push_word(sb, b[i])
        self.assertEqual(self.service.finish(sa)["final_product_id"], solo_a)
        self.assertEqual(self.service.finish(sb)["final_product_id"], solo_b)

    def test_many_threads_at_once(self):
        words = "navy Urbanyx hoodie size XS no wait S sorry M".split()
        expected = self.run_live(self.service, words)[1]["final_product_id"]
        results, errors = [], []

        def work():
            try:
                results.append(self.run_live(self.service, words)[1]["final_product_id"])
            except Exception as err:                       # pragma: no cover
                errors.append(err)

        threads = [threading.Thread(target=work) for _ in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(results, [expected] * 24)


class EquivalenceTest(ServiceTestCase):
    """The interface must not change what the agent decides: it must match the kit harness."""

    def check(self, set_name, results_file):
        requests = load(DATASETS[set_name][0])
        logged = {r["id"]: r for r in load(BACKEND / "outputs" / results_file)}
        differences = []
        for request in requests:
            events = list(self.service.replay(example=request["id"]))
            final = events[-1]
            commits = [(e["seq"], e["commit"]["product_id"]) for e in events if e["type"] == "word" and e["commit"]]
            want = logged[request["id"]]
            if (final["final_product_id"] != want["final"]
                    or [list(c) for c in commits] != [list(c) for c in want["commits"]]
                    or final["searches"] != want["searches"]
                    or abs(final["evaluation"]["score"] - want["score"]) > 1e-12):
                differences.append(request["id"])
        self.assertEqual(differences, [])

    def test_dev_through_the_interface_equals_the_committed_results(self):
        self.check("dev", "results.jsonl")

    def test_dev_extra_through_the_interface_equals_the_committed_results(self):
        self.check("dev_extra", "results_dev_extra.jsonl")


class ReplayTest(ServiceTestCase):
    def test_free_text(self):
        events = list(self.service.replay(text="beige Loomsy sneakers size 10 under 3000 please"))
        self.assertEqual([e["type"] for e in events], ["start"] + ["word"] * 8 + ["final"])
        self.assertEqual(events[0]["words"][:2], ["beige", "Loomsy"])
        self.assertEqual(events[-1]["final_product_id"], "P0081")

    def test_an_example_is_scored_with_the_kits_scorer(self):
        events = list(self.service.replay(example="dev-0004"))
        evaluation = events[-1]["evaluation"]
        self.assertEqual(events[0]["request_id"], "dev-0004")
        self.assertTrue(evaluation["correct"])
        self.assertEqual((evaluation["early_words"], evaluation["wrong_commits"]), (2, 0))
        self.assertAlmostEqual(evaluation["score"], 0.4 + 0.6 * 2 / 15)
        self.assertEqual(evaluation["target"], events[-1]["final_product_id"])

    def test_bad_requests_are_rejected_before_anything_streams(self):
        self.assertError(400, "bad_request", self.service.replay)
        self.assertError(400, "bad_request", lambda: self.service.replay(text="a", example="dev-0001"))
        self.assertError(400, "bad_request", self.service.replay, "   ")
        self.assertError(404, "unknown_example", lambda: self.service.replay(example="nope"))
        self.assertError(400, "unknown_agent", lambda: self.service.replay(text="black", agent="x"))
        self.assertError(400, "text_too_long", self.service.replay, "word " * 2000)
        self.assertError(413, "too_many_words", self.service.replay, "w " * 600)


class ExamplesAndResultsTest(ServiceTestCase):
    def test_listing_and_filtering(self):
        page = self.service.examples("dev", limit=5)
        self.assertEqual((page["total"], len(page["items"])), (300, 5))
        self.assertEqual(set(page["items"][0]), {"id", "text", "tags", "words"})
        corrections = self.service.examples("dev", tag="correction", limit=500)
        self.assertEqual(corrections["total"], 55)
        self.assertEqual(self.service.examples("dev", tag="plain", limit=500)["total"], 177)
        self.assertEqual(self.service.examples("dev_extra")["total"], 87)

    def test_paging_and_the_limit_cap(self):
        first = self.service.examples("dev", limit=3, offset=0)["items"]
        second = self.service.examples("dev", limit=3, offset=3)["items"]
        self.assertEqual(len({e["id"] for e in first + second}), 6)
        self.assertLessEqual(len(self.service.examples("dev", limit=99999)["items"]), 500)

    def test_unknown_set(self):
        self.assertError(404, "unknown_set", self.service.examples, "nope")
        self.assertError(404, "unknown_set", self.service.results, "nope")

    def test_example_detail_has_the_gold_answer(self):
        detail = self.service.example_detail("dev-0004")
        self.assertEqual(detail["target"], "P0206")
        self.assertEqual(detail["gold_filters"]["brand"], "Strydo")
        self.assertEqual(detail["target_product"]["product_id"], "P0206")
        self.assertEqual(detail["words"][0], "I")

    def test_results_match_the_committed_report(self):
        result = self.service.results("dev")
        self.assertAlmostEqual(result["summary"]["score"], 43.5, delta=0.05)
        self.assertEqual(result["summary"]["wrong_commits"], 0)
        self.assertAlmostEqual(result["baseline"]["score"], 20.0, delta=0.05)
        self.assertEqual(set(result["by_tag"]), {"code_mixed", "correction", "late_constraint", "plain"})
        self.assertEqual(len(result["requests"]), 300)
        json.dumps(result)                                  # must be plain JSON

    def test_info(self):
        info = self.service.info()
        self.assertEqual((info["version"], info["products"]), (1, 1074))
        self.assertEqual(info["datasets"], {"dev": 300, "dev_extra": 87})
        self.assertAlmostEqual(info["break_even_risk"], 0.0387, places=3)


if __name__ == "__main__":
    unittest.main()
