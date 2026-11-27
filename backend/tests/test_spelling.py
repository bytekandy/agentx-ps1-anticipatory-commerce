import json
import random
import unittest
from pathlib import Path

from anticipatory.config import SpellingConfig
from anticipatory.lexicon import Lexicon, load_rows
from anticipatory.spelling import NEIGHBOURS, SpellingCorrector, edit_cost
from anticipatory.state import build_snapshot
from anticipatory.tokens import tokenize, tokenize_text

DEV_PATH = Path(__file__).resolve().parents[1] / "dev.jsonl"
CFG = SpellingConfig()


class EditCostTest(unittest.TestCase):
    def cost(self, typed, word, limit=2.0):
        return edit_cost(typed, word, CFG, limit)

    def test_exact_is_free(self):
        self.assertEqual(self.cost("black", "black"), 0.0)

    def test_a_swap_is_cheap(self):
        self.assertEqual(self.cost("blcak", "black"), CFG.cost_transposition)

    def test_a_neighbouring_key_is_cheap(self):
        self.assertEqual(self.cost("blsck", "black"), CFG.cost_neighbour_key)   # s is next to a
        self.assertEqual(self.cost("blpck", "black"), CFG.cost_substitution)    # p is far from a

    def test_a_doubled_letter_is_cheap(self):
        self.assertEqual(self.cost("blaack", "black"), CFG.cost_doubled)
        self.assertEqual(self.cost("hoodis", "hoodies"), CFG.cost_indel)
        self.assertEqual(self.cost("shoess", "shoes"), CFG.cost_doubled)

    def test_other_edits_cost_a_full_unit(self):
        self.assertEqual(self.cost("blck", "black"), CFG.cost_indel)
        self.assertEqual(self.cost("blaqk", "black"), CFG.cost_substitution)

    def test_above_the_limit_is_none(self):
        self.assertIsNone(self.cost("blxxk", "black", limit=1.0))
        self.assertIsNone(self.cost("bl", "black"))

    def test_the_keyboard_map(self):
        self.assertIn("s", NEIGHBOURS["a"])
        self.assertIn("q", NEIGHBOURS["a"])
        self.assertIn("z", NEIGHBOURS["a"])
        self.assertNotIn("p", NEIGHBOURS["a"])
        self.assertTrue(all(k not in NEIGHBOURS[k] for k in NEIGHBOURS))
        self.assertTrue(all(a in NEIGHBOURS[b] for a in NEIGHBOURS for b in NEIGHBOURS[a]))


class CorrectorTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lex = Lexicon(load_rows())
        cls.fix = cls.lex.corrector.correct


class CorrectionTest(CorrectorTestCase):
    def test_typos_in_every_kind_of_word(self):
        cases = {"snekers": "sneakers", "sandels": "sandals", "backpak": "backpack",
                 "jackt": "jacket", "hoodiee": "hoodies", "runing": "running", "blak": "black",
                 "gren": "green", "wite": "white", "nvay": "navy", "navvy": "navy",
                 "pacvo": "pacevo", "kudva": "kudova", "tikra": "tikkra", "northwft": "northweft",
                 "zentaril": "zentrail", "wallt": "wallet"}
        for typed, word in cases.items():
            with self.subTest(typed=typed):
                self.assertEqual(self.fix(typed), word)

    def test_known_and_ordinary_words_are_left_alone(self):
        for word in ("black", "pacevo", "sneakers", "than", "while", "tanned", "gold", "good",
                     "cold", "pick", "alive", "wavy", "glue", "short", "shorts", "skirt",
                     "belt", "beans", "press", "match", "write", "looking", "budget", "please",
                     "breathable", "cotton", "monsoon", "hurry"):
            with self.subTest(word=word):
                self.assertIsNone(self.fix(word))

    def test_short_words_are_never_corrected(self):
        for word in ("gry", "pik", "ble", "tna", "re", "x", "nvy"):
            with self.subTest(word=word):
                self.assertIsNone(self.fix(word))

    def test_the_first_letter_must_match(self):
        self.assertIsNone(self.fix("slack"))                 # not "black"
        self.assertIsNone(self.fix("rlack"))

    def test_numbers_and_punctuation_are_ignored(self):
        for word in ("size9", "2xl", "rs.", "1,500", "t-shirt", "it's"):
            self.assertIsNone(self.fix(word))

    def test_a_word_two_slips_away_in_a_short_word_is_left_alone(self):
        self.assertIsNone(self.fix("bxxck"))

    def test_two_good_candidates_mean_we_do_not_know(self):
        corrector = SpellingCorrector({"abcdq": 10.0, "abcdp": 10.0}, config=CFG)
        self.assertIsNone(corrector.correct("abcdz"))       # z is far from both: a tie
        corrector = SpellingCorrector({"abcdq": 10.0, "abcdp": 1000.0}, config=CFG)
        self.assertEqual(corrector.correct("abcdz"), "abcdp")   # clearly the commoner word
        corrector = SpellingCorrector({"abcde": 10.0, "abcdf": 10.0}, config=CFG)
        self.assertEqual(corrector.correct("abcdg"), "abcdf")   # g sits next to f, not to e

    def test_the_commoner_word_wins_a_close_call(self):
        corrector = SpellingCorrector({"plate": 500.0, "slate": 2.0}, config=CFG)
        self.assertIsNone(corrector.correct("alate"))     # first letter differs from both
        self.assertEqual(corrector.correct("plare"), "plate")

    def test_words_from_the_catalogue_text_are_guarded_automatically(self):
        self.assertIn("breathable", self.lex.catalogue_words)
        self.assertIsNone(self.fix("breathable"))

    def test_it_can_be_switched_off(self):
        corrector = SpellingCorrector({"black": 10.0}, config=SpellingConfig(enabled=False))
        self.assertIsNone(corrector.correct("blak"))

    def test_results_are_cached(self):
        corrector = SpellingCorrector({"black": 10.0}, config=CFG)
        self.assertEqual(corrector.correct("blak"), "black")
        corrector.weights.clear()
        self.assertEqual(corrector.correct("blak"), "black")

    def test_correct_tokens_replaces_text_and_reports_indexes(self):
        tokens = tokenize_text("blak snekers, size 9")
        fixed, changed = self.lex.corrector.correct_tokens(tokens)
        self.assertEqual([t.text for t in fixed], ["black", "sneakers", "size", "9"])
        self.assertEqual(changed, frozenset({0, 1}))
        self.assertTrue(fixed[1].clause_end)                  # the pause survives
        self.assertEqual(fixed[1].raw, "snekers,")


class RecoveryRateTest(CorrectorTestCase):
    """Slip every word that names a product in the four common ways and see what comes back."""

    def slips(self, word, rng):
        i = rng.randrange(1, len(word) - 1)
        return {
            "swap": word[:i] + word[i + 1] + word[i] + word[i + 2:],
            "neighbour": word[:i] + rng.choice(sorted(NEIGHBOURS[word[i]])) + word[i + 1:],
            "double": word[:i] + word[i] + word[i:],
        }

    def test_common_slips_are_recovered_at_least_90_percent(self):
        rng = random.Random(4)
        words = sorted(w for w in self.lex.corrector.weights if w.isalpha()
                       and w in self.lex.known_words)
        tried = hit = bad = 0
        for word in words:
            for typed in self.slips(word, rng).values():
                if typed == word or typed in self.lex.known_words:
                    continue
                tried += 1
                got = self.fix(typed)
                hit += got == word
                bad += bool(got) and got != word
        self.assertGreater(tried, 400)
        self.assertGreaterEqual(hit / tried, 0.90, f"{hit}/{tried}")
        self.assertLessEqual(bad / tried, 0.06, f"{bad}/{tried} corrected to the wrong word")


class NoFalseCorrectionTest(CorrectorTestCase):
    def test_no_word_in_dev_is_corrected(self):
        """Dev has no typos, so any correction there would be a false one (test only)."""
        with open(DEV_PATH, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
        fixed = {(t.text, self.fix(t.text)) for r in rows for t in tokenize(r["words"])
                 if self.fix(t.text)}
        self.assertEqual(fixed, set())

    def test_no_word_the_generator_writes_is_corrected(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import make_training_data as gen
        words = set()
        for pool in (gen.OPENERS, gen.HINDI_OPENERS, gen.TAILS, gen.HINDI_TAILS, gen.FILLERS,
                     gen.PRICE_CUES, [m for m, _ in gen.MARKERS]):
            for phrase in pool:
                words.update(tokenize_text(phrase))
        self.assertEqual({(t.text, self.fix(t.text)) for t in words if self.fix(t.text)}, set())


class PipelineRobustnessTest(unittest.TestCase):
    """Typed requests with typos through the whole agent (generator typos, in-memory catalogue)."""

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        cls.rows = load_rows()

    def accuracy(self, spelling_on, typo_rate=0.15, count=300):
        import make_training_data as gen
        from anticipatory.agent import AnticipatoryAgent
        from anticipatory.policy import InMemoryCatalog
        from anticipatory.config import Config
        cfg = Config(spelling=SpellingConfig(enabled=spelling_on))
        lexicon = Lexicon(self.rows, spelling=cfg.spelling)
        generator = gen.Generator(self.rows, 12, typo_rate)
        agent = AnticipatoryAgent(InMemoryCatalog(self.rows), cfg, lexicon=lexicon)
        right = 0
        for _ in range(count):
            req = generator.request()
            agent.start("t")
            for word in req["words"]:
                agent.observe(word)
            right += agent.finish() == req["target"]
        return right / count

    def test_spelling_recovers_most_of_what_typos_cost(self):
        without = self.accuracy(False)
        with_spelling = self.accuracy(True)
        self.assertGreaterEqual(with_spelling, 0.97)
        self.assertGreaterEqual(with_spelling - without, 0.05)


class BrandModeTest(unittest.TestCase):
    """A capitalised word nothing explains is checked against the brand names alone."""

    @classmethod
    def setUpClass(cls):
        lex = Lexicon(load_rows())
        cls.read = staticmethod(lambda text: build_snapshot(tokenize_text(text), lex, final=True))

    def test_a_misspelt_brand_that_is_an_english_word_is_read(self):
        s = self.read("Northwest beige shirt L")
        self.assertEqual(s.filters["brand"], "Northweft")
        self.assertIn("brand: Northweft", s.guessed)            # never an early commit

    def test_one_more_edit_for_a_long_brand(self):
        self.assertEqual(self.read("Zentrale black running shoes 8").filters["brand"], "Zentrail")

    def test_common_or_lower_case_words_are_left_alone(self):
        for text in ("Looking for Strong black sneakers", "Need Northern shirt",
                     "northwest beige shirt L"):
            with self.subTest(text=text):
                self.assertIsNone(self.read(text).filters["brand"])


if __name__ == "__main__":
    unittest.main()
