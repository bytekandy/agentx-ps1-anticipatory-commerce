import math
import random
import sys
import unittest
from pathlib import Path

from anticipatory.lexicon import Lexicon, load_rows
from anticipatory.numbers import read_number
from anticipatory.risk import FEATURE_NAMES, RiskInput, risk_features, sigmoid
from anticipatory.slots import extract_mentions, latest_filters
from anticipatory.state import find_markers
from anticipatory.tokens import tokenize, tokenize_text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from make_training_data import (Generator, build_examples, number_words,  # noqa: E402
                                singular, slip)
from train_risk import fit, group, simulate, to_input, vector  # noqa: E402

SLOTS = ("category", "colour", "size", "brand", "max_price")


class TrainingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()
        cls.lex = Lexicon(cls.rows)
        generator = Generator(cls.rows, 7)
        cls.requests = [generator.request() for _ in range(1500)]


class GeneratorTest(TrainingTestCase):
    def test_same_seed_same_requests(self):
        a = [Generator(self.rows, 3).request()["text"] for _ in range(1)]
        b = [Generator(self.rows, 3).request()["text"] for _ in range(1)]
        self.assertEqual(a, b)
        g1, g2 = Generator(self.rows, 9), Generator(self.rows, 9)
        self.assertEqual([g1.request()["text"] for _ in range(20)],
                         [g2.request()["text"] for _ in range(20)])

    def test_the_filters_pin_exactly_the_target(self):
        generator = Generator(self.rows, 11)
        for _ in range(100):
            req = generator.request()
            hits = generator.catalog.find(req["filters"], "", 50)
            self.assertEqual([h["product_id"] for h in hits], [req["target"]])

    def test_requests_without_a_correction_read_back_as_their_filters(self):
        """The reader must understand what the generator writes, or labels are polluted."""
        bad = []
        for req in self.requests:
            if "correction" in req["tags"]:
                continue
            got = latest_filters(extract_mentions(tokenize(req["words"]), self.lex, final=True),
                                 self.lex)
            if any(got[s] != req["filters"].get(s) for s in SLOTS):
                bad.append(req["text"])
        self.assertEqual(bad, [])

    def test_corrections_end_on_the_right_value(self):
        wrong = []
        for req in self.requests:
            if "correction" not in req["tags"]:
                continue
            got = latest_filters(extract_mentions(tokenize(req["words"]), self.lex, final=True),
                                 self.lex)
            if any(got[s] != req["filters"].get(s) for s in SLOTS):
                wrong.append(req["text"])
        self.assertLessEqual(len(wrong), 0.03 * sum("correction" in r["tags"] for r in self.requests),
                             wrong[:5])

    def test_rates_match_what_was_read_off_dev(self):
        n = len(self.requests)
        corrected = sum("correction" in r["tags"] for r in self.requests) / n
        late = sum("late_constraint" in r["tags"] for r in self.requests) / n
        self.assertTrue(0.14 <= corrected <= 0.24, corrected)       # dev: 18.3 percent
        self.assertTrue(0.10 <= late <= 0.24, late)                 # dev: 16.7 percent

    def test_pauses_follow_the_dev_pattern(self):
        before = total = base = bases = 0
        for req in self.requests:
            tokens = tokenize(req["words"])
            markers = find_markers(tokens)
            starts = {m.start for m in markers}
            if "correction" in req["tags"] and markers and markers[0].start > 0:
                total += 1
                before += tokens[markers[0].start - 1].clause_end
            for m in extract_mentions(tokens, self.lex, final=True):
                if m.confidence >= 0.5 and m.end not in starts:
                    bases += 1
                    base += tokens[m.end - 1].clause_end
        self.assertTrue(0.45 <= before / total <= 0.8, before / total)     # dev: 64 percent
        self.assertTrue(0.08 <= base / bases <= 0.25, base / bases)        # dev: 16 percent

    def test_number_words_round_trip_through_the_reader(self):
        rng = random.Random(1)
        for value in range(100, 10000, 100):
            text = number_words(value, rng)
            reading = read_number(tokenize_text(text + " please"), 0)
            self.assertEqual(reading.value, value, text)

    def test_singular(self):
        self.assertEqual([singular(w) for w in ("watches", "dresses", "shirts", "jeans")],
                         ["watch", "dress", "shirt", "jean"])


class TypoGeneratorTest(TrainingTestCase):
    def test_default_generator_writes_no_typos(self):
        from anticipatory.spelling import SpellingCorrector  # noqa: F401
        fixes = 0
        for req in self.requests[:400]:
            fixes += sum(bool(self.lex.corrector.correct(t.text)) for t in tokenize(req["words"]))
        self.assertEqual(fixes, 0)

    def test_typo_rate_puts_typos_in_product_words_only(self):
        generator = Generator(self.rows, 5, typo_rate=1.0)
        fixed = numbers = 0
        for _ in range(200):
            req = generator.request()
            for t in tokenize(req["words"]):
                fixed += bool(self.lex.corrector.correct(t.text))
                numbers += t.text.isdigit() and self.lex.corrector.correct(t.text) is not None
        self.assertGreater(fixed, 100)
        self.assertEqual(numbers, 0)

    def test_slip_changes_a_word_but_keeps_its_first_letter(self):
        rng = random.Random(1)
        for word in ("sneakers", "running", "backpack", "northweft"):
            for _ in range(20):
                typed = slip(word, rng)
                self.assertEqual(typed[0], word[0])


class ExamplesTest(TrainingTestCase):
    def examples(self, text, target):
        return build_examples(text.split(), target, self.lex, self.rows)

    def unique_product(self):
        counts = {}
        for r in self.rows:
            key = (r["category"], r["colour"], r["brand"], r["size"])
            counts[key] = counts.get(key, 0) + 1
        return next(r for r in self.rows if r["size"]
                    and counts[(r["category"], r["colour"], r["brand"], r["size"])] == 1)

    def test_rows_exist_only_where_one_product_matches(self):
        row = self.unique_product()
        text = (f"{row['colour']} {row['brand']} {row['category']} size {row['size']} "
                f"please do hurry now")
        examples = self.examples(text, row["product_id"])
        self.assertTrue(examples)
        self.assertTrue(all(e["label"] == 0 for e in examples))
        self.assertTrue(all(e["n_words"] == len(text.split()) for e in examples))

    def test_the_label_is_one_when_the_unique_match_is_not_the_target(self):
        row = self.unique_product()
        other = next(r for r in self.rows if r["product_id"] != row["product_id"])
        text = f"{row['colour']} {row['brand']} {row['category']} size {row['size']} please now"
        examples = self.examples(text, other["product_id"])
        self.assertTrue(all(e["label"] == 1 for e in examples))

    def test_a_correction_after_a_commit_candidate_is_labelled_wrong(self):
        generator = Generator(self.rows, 21)
        saw_wrong = saw_right = False
        for _ in range(400):
            req = generator.request()
            for e in build_examples(req["words"], req["target"], self.lex, self.rows,
                                    generator.catalog):
                saw_wrong |= bool(e["label"])
                saw_right |= not e["label"]
        self.assertTrue(saw_wrong and saw_right)

    def test_rows_carry_every_risk_input_field(self):
        row = self.unique_product()
        text = f"{row['colour']} {row['brand']} {row['category']} size {row['size']} now please"
        example = self.examples(text, row["product_id"])[0]
        features = to_input(example)
        self.assertIsInstance(features, RiskInput)
        self.assertEqual(len(vector(example)), len(FEATURE_NAMES))
        self.assertEqual(features.n_candidates, 1)


class FitTest(unittest.TestCase):
    def test_recovers_known_weights(self):
        rng = random.Random(0)
        d = len(FEATURE_NAMES)
        truth = [rng.uniform(-1.5, 1.5) for _ in range(d)]
        truth[0] = -3.0
        groups = []
        for _ in range(400):
            vec = tuple([1.0] + [float(rng.random() < 0.5) for _ in range(d - 1)])
            n = 4000
            p = sigmoid(sum(t * v for t, v in zip(truth, vec)))
            groups.append((vec, n, round(n * p)))
        w = fit(groups, ridge=1e-3)
        for got, want in zip(w, truth):
            self.assertAlmostEqual(got, want, delta=0.25)

    def test_grouping_counts_identical_vectors_once(self):
        rows = [dict(RiskInput(5, 2, False, True, 3, 0.95, 0, 0, 1).__dict__, label=lab)
                for lab in (0, 0, 1)]
        groups = group(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][1:], (3, 1))
        self.assertEqual(groups[0][0], tuple(risk_features(to_input(rows[0])).values()))


class SimulateTest(unittest.TestCase):
    def row(self, index, label, n=10):
        return {"index": index, "n_words": n, "label": label}

    def test_scores_follow_the_kit_formula(self):
        never = [[self.row(3, 0)]]
        right_early = [[self.row(5, 0)]]
        wrong = [[self.row(5, 1)]]
        always = lambda r: 0.0
        nope = lambda r: 1.0
        self.assertAlmostEqual(simulate(never, nope, 0.04)["score"], 40.0)
        self.assertAlmostEqual(simulate(right_early, always, 0.04)["score"], 100 * (0.4 + 0.6 * 0.5))
        self.assertAlmostEqual(simulate(wrong, always, 0.04)["score"], -60.0)
        self.assertEqual(simulate(wrong, always, 0.04)["wrong"], 1)

    def test_commits_at_the_first_prefix_below_the_budget(self):
        request = [[self.row(2, 1), self.row(6, 0)]]
        risk = lambda r: 0.5 if r["index"] == 2 else 0.01
        result = simulate(request, risk, 0.04)
        self.assertEqual(result["wrong"], 0)
        self.assertAlmostEqual(result["early_share"], 0.4)


if __name__ == "__main__":
    unittest.main()
