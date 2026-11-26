import json
import sys
import unittest
from pathlib import Path

from anticipatory.agent import AnticipatoryAgent
from anticipatory.catalog_port import InMemoryCatalog
from anticipatory.lexicon import Lexicon, load_rows

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import evaluate  # noqa: E402  (the kit's scorer, used only by this test)

DEV_PATH = BACKEND / "dev.jsonl"


class AgentTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()
        cls.lex = Lexicon(cls.rows)

    def run_request(self, text):
        """Feed a request word by word; return (commits, final, searches, agent)."""
        catalog = InMemoryCatalog(self.rows)
        agent = AnticipatoryAgent(catalog, lexicon=self.lex)
        agent.start("t")
        commits = []
        for word in text.split():
            out = agent.observe(word)
            if out and out.get("commit"):
                commits.append((len(agent.words), out["commit"]))
        return commits, agent.finish(), catalog.searches, agent

    def product(self, pid):
        return next(r for r in self.rows if r["product_id"] == pid)


class AgentFlowTest(AgentTestCase):
    def test_observe_always_reports_the_reading(self):
        agent = AnticipatoryAgent(InMemoryCatalog(self.rows), lexicon=self.lex)
        agent.start("t")
        out = agent.observe("black")
        self.assertEqual(out["filters"]["colour"], "black")
        self.assertGreater(out["confidence"], 0)
        self.assertNotIn("commit", out)

    def unique_row(self, sized):
        """A product that no other product shares (category, colour, brand, size) with."""
        counts = {}
        for r in self.rows:
            key = (r["category"], r["colour"], r["brand"], r["size"])
            counts[key] = counts.get(key, 0) + 1
        return next(r for r in self.rows
                    if bool(r["size"]) == sized
                    and counts[(r["category"], r["colour"], r["brand"], r["size"])] == 1
                    and r["category"] not in ("t-shirts", "track pants", "running shoes"))

    def request_for(self, row, filler):
        size = f"size {row['size']} " if row["size"] else ""
        category = row["category"]
        return f"{row['colour']} {row['brand']} {category} {size}{filler}"

    def test_a_sized_request_commits_before_the_end_and_finishes_on_the_same_product(self):
        row = self.unique_row(sized=True)
        text = self.request_for(row, "please do hurry now my friend")
        commits, final, searches, _ = self.run_request(text)
        self.assertEqual([c for _, c in commits], [row["product_id"]])
        self.assertLess(commits[0][0], len(text.split()))          # before the last word
        self.assertEqual(final, row["product_id"])

    def test_finish_reuses_the_commit_search(self):
        row = self.unique_row(sized=False)
        text = self.request_for(row, "please do hurry now my friend")
        commits, final, searches, _ = self.run_request(text)
        self.assertEqual([c for _, c in commits], [row["product_id"]])
        self.assertEqual(final, row["product_id"])
        self.assertEqual(searches, 1)                  # the commit search also verified it

    def test_an_unpinned_request_never_commits_and_still_answers(self):
        commits, final, searches, _ = self.run_request("black watch")
        self.assertEqual(commits, [])
        self.assertIsNotNone(final)
        self.assertEqual(self.product(final)["category"], "watches")

    def test_no_commit_on_a_value_that_is_about_to_be_corrected(self):
        text = "show me maroon Tanaro kurta size M, oops, XS max 1500 for a wedding"
        commits, final, _, _ = self.run_request(text)
        for position, pid in commits:
            self.assertEqual(self.product(pid)["size"], "XS", f"committed at word {position}")
        self.assertEqual(self.product(final)["size"], "XS")

    def test_final_answer_follows_the_last_correction(self):
        _, final, _, _ = self.run_request("black sorry navy cap under 900 only Urbanyx thanks")
        product = self.product(final)
        self.assertEqual((product["colour"], product["category"]), ("navy", "caps"))

    def test_relaxes_the_filters_when_nothing_matches(self):
        _, final, _, _ = self.run_request("black watch size 9 under 10 thousand rupees please")
        self.assertIsNotNone(final)

    def test_empty_request(self):
        agent = AnticipatoryAgent(InMemoryCatalog(self.rows), lexicon=self.lex)
        agent.start("t")
        self.assertIsNotNone(agent.finish())            # no filters: the cheapest product

    def test_start_resets_everything(self):
        catalog = InMemoryCatalog(self.rows)
        agent = AnticipatoryAgent(catalog, lexicon=self.lex)
        agent.start("a")
        for w in "black watch under 5000 thanks a lot".split():
            agent.observe(w)
        agent.start("b")
        self.assertEqual((agent.words, agent.trace), ([], []))
        self.assertEqual(agent.observe("red")["filters"]["colour"], "red")
        self.assertIsNone(agent.observe("cap")["filters"]["brand"])

    def test_trace_has_one_record_per_word(self):
        records = []
        agent = AnticipatoryAgent(InMemoryCatalog(self.rows), lexicon=self.lex,
                                  on_trace=records.append)
        agent.start("t")
        for w in "black watch under 5000 thanks".split():
            agent.observe(w)
        self.assertEqual([r.index for r in records], [1, 2, 3, 4, 5])
        self.assertEqual(records, agent.trace)
        self.assertEqual(records[0].word, "black")
        self.assertEqual(records[0].filters["colour"], "black")
        self.assertIn("reason", records[0].to_dict())


class KitIntegrationTest(unittest.TestCase):
    """Runs the real agent through the kit's evaluator on dev.jsonl (a test only)."""

    @classmethod
    def setUpClass(cls):
        import agent as entry
        with open(DEV_PATH, encoding="utf-8") as fh:
            requests = [json.loads(line) for line in fh if line.strip()]
        cls.results, _ = evaluate.run(entry.Agent, requests)
        cls.summary = evaluate.summarise(cls.results)

    def test_never_commits_to_the_wrong_product_on_dev(self):
        self.assertEqual(self.summary["wrong_commits"], 0,
                         [r["id"] for r in self.results if r["wrong_commits"]])

    def test_accuracy_is_at_least_the_baseline(self):
        self.assertGreaterEqual(self.summary["accuracy"], 0.527)

    def test_scores_above_the_baseline_and_the_no_early_commit_floor(self):
        self.assertGreater(self.summary["score"], 40.0)

    def test_plain_requests_have_no_wrong_commit(self):
        plain = [r for r in self.results if not r["tags"]]
        self.assertEqual(sum(r["wrong_commits"] for r in plain), 0)

    def test_the_rules_only_variant_is_also_safe(self):
        import agent_heuristic
        with open(DEV_PATH, encoding="utf-8") as fh:
            requests = [json.loads(line) for line in fh if line.strip()]
        results, _ = evaluate.run(agent_heuristic.Agent, requests)
        summary = evaluate.summarise(results)
        self.assertEqual(summary["wrong_commits"], 0)
        self.assertGreater(summary["score"], 40.0)

    def test_the_hybrid_default_is_at_least_as_good_as_the_rules_only_agent(self):
        import agent_heuristic
        with open(DEV_PATH, encoding="utf-8") as fh:
            requests = [json.loads(line) for line in fh if line.strip()]
        rules, _ = evaluate.run(agent_heuristic.Agent, requests)
        self.assertGreaterEqual(self.summary["score"], evaluate.summarise(rules)["score"])

    def test_searches_stay_lean(self):
        self.assertLess(self.summary["searches"], 1.5)


if __name__ == "__main__":
    unittest.main()
