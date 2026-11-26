import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "scripts"))
sys.path.insert(0, str(BACKEND))
import evaluate  # noqa: E402
import report  # noqa: E402


def result(id, tags, correct=True, wrong=0, early=2, n=10, score=0.5, oracle=0.3):
    return {"id": id, "tags": tags, "words": n, "target": "P1", "final": "P1" if correct else "P2",
            "correct": correct, "commits": [], "wrong_commits": wrong, "early_words": early,
            "early_share": early / n, "oracle_share": oracle, "searches": 1, "wasted": 0,
            "score": score, "filters_reported": None, "filters_gold": None}


class PureFunctionTest(unittest.TestCase):
    def test_percentile(self):
        values = list(range(1, 101))
        self.assertEqual(report.percentile(values, 50), 51)
        self.assertEqual(report.percentile(values, 100), 100)
        self.assertEqual(report.percentile(values, 0), 1)
        self.assertEqual(report.percentile([], 95), 0.0)
        self.assertEqual(report.percentile([7], 95), 7)

    def test_by_tag_puts_untagged_requests_under_plain_and_counts_multiple_tags(self):
        results = [result("a", []), result("b", ["correction"]),
                   result("c", ["correction", "code_mixed"])]
        groups = dict(report.by_tag(results))
        self.assertEqual(groups["plain"]["requests"], 1)
        self.assertEqual(groups["correction"]["requests"], 2)
        self.assertEqual(groups["code_mixed"]["requests"], 1)

    def test_oracle_score_follows_the_formula(self):
        self.assertAlmostEqual(report.oracle_score([result("a", [], oracle=0.5)]),
                               100 * (0.4 + 0.6 * 0.5))
        self.assertIsNone(report.oracle_score([result("a", [], oracle=None)]))

    def test_exceptions_lists_wrong_answers_and_wrong_commits_only(self):
        results = [result("ok", []), result("bad", ["typo"], correct=False),
                   result("early", [], wrong=1)]
        requests = [{"id": i, "text": f"text {i}"} for i in ("ok", "bad", "early")]
        found = report.exceptions(results, requests)
        self.assertEqual([f[0] for f in found], ["bad", "early"])
        self.assertEqual(found[0][2], "text bad")

    def test_table_layout(self):
        text = report.table(("a", "b"), [(1, 2), (3, 4)])
        self.assertEqual(text.splitlines(), ["| a | b |", "|---|---|", "| 1 | 2 |", "| 3 | 4 |"])

    def test_write_results_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.jsonl"
            report.write_results([result("a", ["x"]), result("b", [])], path)
            lines = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([r["id"] for r in lines], ["a", "b"])


class EndToEndTest(unittest.TestCase):
    def test_main_writes_the_results_and_the_report_with_the_kits_own_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(report.main(["--outdir", tmp, "--no-variants"]), 0)
            out = Path(tmp)
            logged = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
            text = (out / "report.md").read_text()
        self.assertEqual(len(logged), 300)
        requests = report.load_requests(BACKEND / "dev.jsonl")
        direct, _ = evaluate.run(evaluate.load_agent(str(BACKEND / "agent.py")), requests)
        self.assertEqual([r["final"] for r in logged], [r["final"] for r in direct])
        self.assertEqual(evaluate.summarise(logged)["score"], evaluate.summarise(direct)["score"])
        for heading in ("## dev", "## dev_extra", "## Cost, speed and size", "### By tag"):
            self.assertIn(heading, text)
        self.assertIn(f"{evaluate.summarise(direct)['score']:.1f}", text)
        self.assertIn("Python 3.14, standard library only", text)


if __name__ == "__main__":
    unittest.main()
