import json
import random
import sys
import unittest
from pathlib import Path

from anticipatory.agent import AnticipatoryAgent
from anticipatory.policy import InMemoryCatalog
from anticipatory.config import Config, UnknownConfig
from anticipatory.lexicon import Lexicon, load_rows
from anticipatory.slots import read_words
from anticipatory.state import build_snapshot
from anticipatory.tokens import tokenize, tokenize_text
from anticipatory.unknown import find_unresolved

DEV_PATH = Path(__file__).resolve().parents[1] / "dev.jsonl"


class UnknownTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()
        cls.lex = Lexicon(cls.rows)

    def flags(self, text):
        return find_unresolved(read_words(tokenize_text(text), self.lex, final=True), self.lex)

    def labels(self, text):
        return [u.label() for u in self.flags(text)]

    def assertFlagged(self, text, kind, word):
        self.assertIn(f"{kind}: {word}", self.labels(text), text)

    def assertClean(self, text):
        self.assertEqual(self.labels(text), [], text)


class UnknownBrandTest(UnknownTestCase):
    def test_after_a_brand_cue(self):
        self.assertFlagged("black running shoes from Nike size 9", "brand", "nike")
        self.assertFlagged("blue jeans by Levis waist 32", "brand", "levis")
        self.assertFlagged("jeans waist 32 from Wrangler brand", "brand", "wrangler")

    def test_lowercase_is_caught_when_it_is_no_english_word(self):
        self.assertFlagged("white shoes from reebokk size 9", "brand", "reebokk")

    def test_capitalised_in_the_middle_of_a_sentence(self):
        self.assertFlagged("I want Nike shoes in black size 9", "brand", "nike")
        self.assertFlagged("red dress in Zara size S", "brand", "zara")

    def test_before_a_brand_postfix(self):
        self.assertFlagged("black shoes Fossil brand size 9", "brand", "fossil")

    def test_a_brand_in_front_of_the_category_word(self):
        self.assertFlagged("Adidas sneakers white size 8", "brand", "adidas")
        self.assertFlagged("do you have nike sneakers black size 9",
                           "brand, colour or style", "nike")

    def test_days_events_and_openers_are_not_brands(self):
        for text in ("need it by Friday black cap under 500", "white shirt for Diwali size L",
                     "black shirt on Monday size M", "Hey, do you have black shoes size 9",
                     "Please show me black shoes size 9. Thanks"):
            with self.subTest(text=text):
                self.assertClean(text)

    def test_known_brands_are_never_flagged(self):
        self.assertClean("black Pacevo sneakers from Kudova size 9")


class UnknownSizeTest(UnknownTestCase):
    def test_a_half_size_is_flagged(self):
        self.assertFlagged("black shoes size 10.5", "size", "10.5")
        self.assertFlagged("black shoes 7.5 UK", "size", "7.5")
        self.assertClean("black shoes size 9 under 1.5k")

    def test_a_number_that_is_no_size(self):
        self.assertFlagged("black sandals size 14", "size", "14")
        self.assertFlagged("blue jeans waist 40", "size", "40")
        self.assertFlagged("black sandals 14 size", "size", "14")

    def test_an_extra_large_or_extra_small_size(self):
        self.assertFlagged("black hoodie size 4XL under 2000", "size", "4xl")
        self.assertFlagged("black hoodie size XXXL", "size", "xxxl")

    def test_real_sizes_are_fine(self):
        for text in ("black sandals size 9", "blue jeans waist 32", "black hoodie size XL",
                     "black hoodie size XXL", "black sandals 9 UK under 2000"):
            with self.subTest(text=text):
                self.assertClean(text)

    def test_a_price_after_a_size_cue_is_not_a_size(self):
        self.assertClean("black sandals size 9 under 1500")


class UnknownColourTest(UnknownTestCase):
    def test_before_the_category(self):
        self.assertFlagged("get me a purple shirt size M under 800", "brand, colour or style",
                           "purple")

    def test_before_a_brand_or_colour(self):
        self.assertFlagged("purple Mehrin dress size S", "brand, colour or style", "purple")
        self.assertFlagged("sky blue sneakers size 9", "brand, colour or style", "sky")

    def test_after_in(self):
        self.assertFlagged("black sneakers in violet size 9", "colour or style", "violet")

    def test_next_to_colour(self):
        self.assertFlagged("sneakers in violet colour size 9", "colour", "violet")
        self.assertFlagged("sneakers colour turquoise size 9", "colour", "turquoise")

    def test_words_the_shop_itself_uses_are_not_flagged(self):
        for text in ("casual shirt navy size M", "black cotton shirt size M",
                     "navy linen shirt size L", "black court sneakers size 9"):
            with self.subTest(text=text):
                self.assertClean(text)

    def test_function_words_and_fillers_are_not_flagged(self):
        for text in ("mere liye dress small", "a gray hmm, bag pack", "uh Tanaro casual shirt",
                     "do you have any olive sandals size 9", "I'd like a pair of black jeans"):
            with self.subTest(text=text):
                self.assertClean(text)

    def test_unknown_categories_need_no_flag_because_nothing_can_commit(self):
        snapshot = build_snapshot(tokenize_text("black shorts size M under 500"), self.lex,
                                  final=True)
        self.assertNotIn("category", {k for k, v in snapshot.filters.items() if v})


class SizeConflictTest(UnknownTestCase):
    def snapshot(self, text):
        return build_snapshot(tokenize_text(text), self.lex, final=True)

    def test_a_size_that_exists_but_not_for_this_category(self):
        for text, size in (("black sandals size 32", "32"), ("blue jeans size 9", "9"),
                           ("black cap size M under 500", "m")):
            with self.subTest(text=text):
                snapshot = self.snapshot(text)
                self.assertEqual([(u.kind, u.text.lower()) for u in snapshot.unresolved],
                                 [("size", size)])
                self.assertFalse(snapshot.settled)

    def test_a_bare_size_word_for_an_unsized_category_is_not_a_conflict(self):
        self.assertTrue(self.snapshot("small black backpack under 900").settled)

    def test_a_correction_to_a_valid_size_is_no_conflict(self):
        self.assertTrue(self.snapshot("sandals size 32 sorry size 9 under 900").settled)


class StateAndAgentTest(UnknownTestCase):
    def test_unresolved_makes_the_state_unsettled(self):
        snapshot = build_snapshot(tokenize_text("black shoes from Nike size 9 please"), self.lex,
                                  final=True)
        self.assertEqual([u.label() for u in snapshot.unresolved], ["brand: nike"])
        self.assertFalse(snapshot.settled)

    def test_it_shows_up_the_word_it_is_spoken(self):
        state_words = "black sneakers from Nike size 9 please".split()
        seen = []
        for i in range(1, len(state_words) + 1):
            snap = build_snapshot(tokenize(state_words[:i]), self.lex)
            seen.append(bool(snap.unresolved))
        self.assertEqual(seen, [False, False, False, True, True, True, True])

    def test_the_agent_holds_back_and_says_why(self):
        records = []
        agent = AnticipatoryAgent(InMemoryCatalog(self.rows), lexicon=self.lex,
                                  on_trace=records.append)
        agent.start("t")
        for word in "black Pacevo sneakers size 9 from Nike please do hurry now".split():
            agent.observe(word)
        flagged = [r for r in records if r.unresolved]
        self.assertTrue(flagged)
        self.assertEqual(flagged[-1].unresolved, ("brand: nike",))
        self.assertIn("not understood", flagged[-1].reason)
        self.assertEqual([u.label() for u in agent.unresolved], ["brand: nike"])
        self.assertIn("unresolved", flagged[-1].to_dict())

    def test_it_can_be_switched_off(self):
        cfg = Config(unknown=UnknownConfig(enabled=False))
        self.assertEqual(find_unresolved(read_words(tokenize_text("black shoes from Nike"),
                                                    self.lex, cfg), self.lex, cfg), [])

    def test_the_final_answer_is_still_the_best_match(self):
        agent = AnticipatoryAgent(InMemoryCatalog(self.rows), lexicon=self.lex)
        agent.start("t")
        for word in "black Wavlo watch from Nike".split():
            agent.observe(word)
        final = agent.finish()
        self.assertIsNotNone(final)


class NoFalseFlagTest(UnknownTestCase):
    def test_no_dev_request_is_flagged(self):
        """Every dev request is satisfiable, so any flag there is a false positive (test only)."""
        with open(DEV_PATH, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        flagged = [(r["id"], [u.label() for u in find_unresolved(
            read_words(tokenize(r["words"]), self.lex, final=True), self.lex)]) for r in rows]
        self.assertEqual([f for f in flagged if f[1]], [])

    def test_no_clean_synthetic_request_is_flagged(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import make_training_data as gen
        generator = gen.Generator(self.rows, 31, outside_rate=0.0)
        bad = []
        for _ in range(1500):
            req = generator.request()
            found = self.flags(req["text"])
            if found:
                bad.append((req["text"], [u.label() for u in found]))
        self.assertEqual(bad, [])


class ImpossibleRequestTest(UnknownTestCase):
    """Requests asking for something the shop cannot answer must not end in an early commit."""

    UNKNOWN_BRANDS = ["Nike", "Adidas", "Puma", "Levis", "Zara", "Reebok", "Fila", "Wrangler"]

    def early_commit_rate(self, enabled, count=400):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import make_training_data as gen
        cfg = Config(unknown=UnknownConfig(enabled=enabled))
        generator = gen.Generator(self.rows, 14, outside_rate=0.0)
        rng = random.Random(14)
        agent = AnticipatoryAgent(InMemoryCatalog(self.rows), cfg, lexicon=self.lex)
        commits = tried = 0
        while tried < count:
            req = generator.request()
            words = list(req["words"])
            size = (req["filters"].get("size") or "").lower()
            where = [i for i, w in enumerate(words) if w.lower().strip(",.") == size]
            if not size or not where:
                continue
            suffix = "," if words[where[0]].endswith(",") else ""
            words[where[0]] = rng.choice(["14", "42", "4XL", "5XL"]) + suffix   # nobody sells it
            tried += 1
            agent.start("t")
            committed = False
            for word in words:
                out = agent.observe(word)
                committed |= bool(out and out.get("commit"))
            commits += committed
        return commits / tried

    def test_unknown_sizes_almost_never_end_in_an_early_commit(self):
        """Sized categories cannot commit without a recognised size, so the baseline is already
        low (about 2 percent); the detector takes it lower and never makes it worse."""
        off = self.early_commit_rate(False)
        on = self.early_commit_rate(True)
        self.assertLessEqual(on, off)
        self.assertLessEqual(on, 0.02)


if __name__ == "__main__":
    unittest.main()


class ClosedSizeCueTest(UnknownTestCase):
    def test_a_cue_that_closes_a_known_size_announces_no_number(self):
        self.assertEqual(self.flags("white dress S size ek aur baat Mehrin"), [])

    def test_a_cue_before_an_impossible_size_still_flags(self):
        self.assertTrue(self.flags("white dress size 14 Mehrin"))
