import json
import re
import threading
import unittest
from pathlib import Path

from server.events import ServiceError
from server.service import DATASETS, Limits, StreamService


def committed_dev_score() -> float:
    """The dev score in outputs/report.md, which scripts/report.py writes with the results."""
    report = (Path(__file__).resolve().parents[1] / "outputs" / "report.md").read_text(encoding="utf-8")
    return float(re.search(r"\| \*\*score\*\* \| \*\*([\d.]+)\*\*", report).group(1))


BACKEND = Path(__file__).resolve().parents[1]
WORDS = "beige Loomsy sneakers size 10 under 3000 please".split()


def load(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


class ServiceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = StreamService()

    def assertError(self, status, code, call, *args, **kwargs):
        with self.assertRaises(ServiceError) as ctx:
            call(*args, **kwargs)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (status, code))


class RunTest(ServiceTestCase):
    def feed(self, words, agent="hybrid"):
        run = self.service.new_run(agent, "r1")
        return run, [run.push(w) for w in words]

    def test_one_event_per_word_with_the_agents_own_trace(self):
        _, events = self.feed(WORDS)
        self.assertEqual([e["seq"] for e in events], list(range(1, 9)))
        for event, word in zip(events, WORDS):
            self.assertEqual((event["type"], event["version"], event["word"]), ("word", 1, word))
            self.assertEqual(event["trace"]["word"], word)
            self.assertNotIn("session", event)             # there are no sessions

    def test_the_commit_comes_once_and_the_latest_event_always_knows_about_it(self):
        _, events = self.feed(WORDS + ["thanks", "a", "lot"])
        self.assertEqual([e["seq"] for e in events if e["commit"]], [8])
        commit = events[7]["commit"]
        self.assertEqual((commit["product_id"], commit["seq"]), ("P0081", 8))
        self.assertEqual(commit["product"]["title"], "Loomsy Street Sneakers, Beige")
        self.assertTrue(all(e["committed"] is None for e in events[:7]))
        self.assertTrue(all(e["committed"]["product_id"] == "P0081" for e in events[7:]))

    def test_the_final_event(self):
        run, _ = self.feed(WORDS)
        final = run.finish()
        self.assertEqual((final["type"], final["words"], final["final_product_id"]), ("final", 8, "P0081"))
        self.assertEqual(final["filters"], {"category": "sneakers", "colour": "beige", "size": "10",
                                            "brand": "Loomsy", "max_price": 3000})
        self.assertEqual((final["searches"], final["evaluation"]), (1, None))
        self.assertEqual(final["commit"]["product_id"], "P0081")

    def test_unresolved_constraints_are_reported_and_block_the_commit(self):
        run, events = self.feed("navy Nike hoodies size M please".split())
        final = run.finish()
        self.assertEqual(final["unresolved"], ["brand: nike"])
        self.assertTrue(any(e["trace"]["unresolved"] for e in events))
        self.assertFalse(any(e["commit"] for e in events))

    def test_each_agent_variant(self):
        for name in ("hybrid", "heuristic", "learned"):
            with self.subTest(agent=name):
                run, _ = self.feed(WORDS, agent=name)
                self.assertEqual(run.finish()["final_product_id"], "P0081")

    def test_unknown_agent(self):
        self.assertError(400, "unknown_agent", self.service.new_run, "gpt")

    def test_a_finished_run_takes_no_more(self):
        run, _ = self.feed(["black"])
        run.finish()
        self.assertError(409, "run_finished", run.push, "cap")
        self.assertError(409, "run_finished", run.finish)

    def test_words_are_validated(self):
        run = self.service.new_run()
        for bad in ("", "   ", "two words", "a\tb", 5, None, ["x"], "x" * 101):
            with self.subTest(word=bad):
                self.assertError(400, "bad_word", run.push, bad)

    def test_odd_words_are_fine(self):
        run = self.service.new_run()
        for word in ("size,", "Rs.", "₹2,500", "\U0001F45F", "काली", "x" * 100):
            run.push(word)

    def test_the_word_limit(self):
        service = StreamService(limits=Limits(max_words=5), lexicon=self.service.lexicon,
                                directory=self.service.directory)
        run = service.new_run()
        for _ in range(5):
            run.push("hello")
        self.assertError(413, "too_many_words", run.push, "hello")


class StatelessTest(ServiceTestCase):
    """The agent is causal, so a stateless call that replays the words gives the live answer."""

    def test_step_equals_feeding_the_words_one_by_one_at_every_prefix(self):
        run = self.service.new_run()
        for n, word in enumerate(WORDS, start=1):
            live = run.push(word)
            self.assertEqual(self.service.step(WORDS[:n]), live, f"after {n} words")

    def test_step_knows_about_a_commit_made_earlier(self):
        event = self.service.step(WORDS + ["thanks"])
        self.assertIsNone(event["commit"])
        self.assertEqual(event["committed"]["product_id"], "P0081")

    def test_answer_and_run(self):
        self.assertEqual(self.service.answer(WORDS)["final_product_id"], "P0081")
        events = self.service.run(WORDS)
        self.assertEqual([e["type"] for e in events], ["start"] + ["word"] * 8 + ["final"])
        self.assertEqual(events[0]["words"], WORDS)

    def test_bad_input(self):
        for bad in (None, [], "text", 5):
            with self.subTest(words=bad):
                self.assertError(400, "bad_request", self.service.step, bad)
        self.assertError(400, "bad_word", self.service.step, ["two words"])
        self.assertError(413, "too_many_words", self.service.step, ["w"] * 501)
        self.assertError(400, "unknown_agent", self.service.step, ["w"], "x")

    def test_calls_are_independent(self):
        a = self.service.step("black cap".split())
        self.service.step("navy hoodie size M".split())
        self.assertEqual(self.service.step("black cap".split()), a)

    def test_many_threads_at_once(self):
        words = "navy Urbanyx hoodie size XS no wait S sorry M".split()
        expected = self.service.answer(words)["final_product_id"]
        results, errors = [], []

        def work():
            try:
                results.append(self.service.answer(words)["final_product_id"])
            except Exception as err:                       # pragma: no cover
                errors.append(err)

        threads = [threading.Thread(target=work) for _ in range(32)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((errors, results), ([], [expected] * 32))


class EquivalenceTest(ServiceTestCase):
    """The interface must not change what the agent decides: it must match the kit harness."""

    def check(self, set_name, results_file):
        logged = {r["id"]: r for r in load(BACKEND / "outputs" / results_file)}
        differences = []
        for request in load(DATASETS[set_name][0]):
            events = list(self.service.replay(example=request["id"]))
            final = events[-1]
            commits = [[e["seq"], e["commit"]["product_id"]] for e in events
                       if e["type"] == "word" and e["commit"]]
            want = logged[request["id"]]
            if (final["final_product_id"] != want["final"]
                    or commits != [list(c) for c in want["commits"]]
                    or final["searches"] != want["searches"]
                    or abs(final["evaluation"]["score"] - want["score"]) > 1e-12):
                differences.append(request["id"])
        self.assertEqual(differences, [])

    def test_dev_through_the_interface_equals_the_committed_results(self):
        self.check("dev", "results.jsonl")

    def test_dev_extra_through_the_interface_equals_the_committed_results(self):
        self.check("dev_extra", "results_dev_extra.jsonl")

    def test_stateless_answers_equal_the_committed_results_too(self):
        logged = {r["id"]: r for r in load(BACKEND / "outputs" / "results.jsonl")}
        for request in load(BACKEND / "dev.jsonl")[:60]:
            self.assertEqual(self.service.answer(request["words"])["final_product_id"],
                             logged[request["id"]]["final"], request["id"])


class ReplayTest(ServiceTestCase):
    def test_free_text(self):
        events = list(self.service.replay(text="beige Loomsy sneakers size 10 under 3000 please"))
        self.assertEqual([e["type"] for e in events], ["start"] + ["word"] * 8 + ["final"])
        self.assertEqual(events[-1]["final_product_id"], "P0081")

    def test_an_example_is_scored_with_the_kits_scorer(self):
        events = list(self.service.replay(example="dev-0004"))
        evaluation = events[-1]["evaluation"]
        self.assertEqual(events[0]["request_id"], "dev-0004")
        self.assertTrue(evaluation["correct"])
        self.assertEqual((evaluation["early_words"], evaluation["wrong_commits"]), (2, 0))
        self.assertAlmostEqual(evaluation["score"], 0.4 + 0.6 * 2 / 15)

    def test_bad_requests_are_rejected_before_anything_streams(self):
        self.assertError(400, "bad_request", self.service.replay)
        self.assertError(400, "bad_request", self.service.replay, "a", "dev-0001")
        self.assertError(400, "bad_request", self.service.replay, "   ")
        self.assertError(404, "unknown_example", self.service.replay, None, "nope")
        self.assertError(400, "unknown_agent", self.service.replay, "black", None, "x")
        self.assertError(400, "text_too_long", self.service.replay, "word " * 2000)
        self.assertError(413, "too_many_words", self.service.replay, "w " * 600)


class ExamplesAndResultsTest(ServiceTestCase):
    def test_listing_filtering_and_paging(self):
        page = self.service.examples("dev", limit=5)
        self.assertEqual((page["total"], len(page["items"])), (300, 5))
        self.assertEqual(self.service.examples("dev", tag="correction", limit=500)["total"], 55)
        self.assertEqual(self.service.examples("dev", tag="plain", limit=500)["total"], 177)
        self.assertEqual(self.service.examples("dev_extra")["total"], 87)
        first = self.service.examples("dev", limit=3)["items"]
        second = self.service.examples("dev", limit=3, offset=3)["items"]
        self.assertEqual(len({e["id"] for e in first + second}), 6)
        self.assertLessEqual(len(self.service.examples("dev", limit=99999)["items"]), 500)
        self.assertEqual(self.service.examples("dev", offset=-5)["offset"], 0)

    def test_unknown_set(self):
        self.assertError(404, "unknown_set", self.service.examples, "nope")
        self.assertError(404, "unknown_set", self.service.results, "nope")

    def test_example_detail_has_the_gold_answer(self):
        detail = self.service.example_detail("dev-0004")
        self.assertEqual((detail["target"], detail["gold_filters"]["brand"]), ("P0206", "Strydo"))
        self.assertEqual(detail["target_product"]["product_id"], "P0206")

    def test_results_match_the_committed_report(self):
        result = self.service.results("dev")
        self.assertAlmostEqual(result["summary"]["score"], committed_dev_score(), delta=0.05)
        self.assertEqual(result["summary"]["wrong_commits"], 0)
        self.assertAlmostEqual(result["baseline"]["score"], 20.0, delta=0.05)
        self.assertEqual(len(result["requests"]), 300)
        json.dumps(result)

    def test_info(self):
        info = self.service.info()
        self.assertEqual((info["version"], info["products"]), (1, 1074))
        self.assertEqual(info["datasets"], {"dev": 300, "dev_extra": 87})
        self.assertAlmostEqual(info["break_even_risk"], 0.0387, places=3)


if __name__ == "__main__":
    unittest.main()
