"""The learned lexicon: taught by corrections and accepted products, optional, never trusted early."""
import json
import tempfile
import unittest
from pathlib import Path

from anticipatory.learned import LearnedStore, learn_from_request, load_active
from anticipatory.lexicon import Lexicon, load_rows
from anticipatory.state import build_snapshot
from anticipatory.tokens import tokenize_text

ROWS = load_rows()
LEX = Lexicon(ROWS)
FIX = "show me black sliders sorry I meant sandals size 8".split()


def filters(lexicon, text):
    return build_snapshot(tokenize_text(text), lexicon, final=True).filters


class LearnedTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "learned.json"
        self.store = LearnedStore(self.path)

    def test_a_correction_teaches_the_unknown_word(self):
        self.assertEqual(learn_from_request(FIX, LEX, self.store), [("sliders", "category", "sandals")])

    def test_one_observation_is_not_enough_two_are(self):
        learn_from_request(FIX, LEX, self.store)
        self.assertEqual(self.store.active(), {})
        learn_from_request(FIX, LEX, self.store)
        self.assertEqual(self.store.active(), {"sliders": ("category", "sandals")})

    def test_without_the_file_the_word_is_dropped_as_before(self):
        self.assertEqual(load_active(self.path), {})
        self.assertIsNone(filters(LEX, "black sliders size 8")["category"])

    def test_with_the_file_the_word_is_understood_at_lower_confidence(self):
        for _ in range(2):
            learn_from_request(FIX, LEX, self.store)
        self.store.save()
        lex = Lexicon(ROWS, learned=load_active(self.path))
        self.assertEqual(filters(lex, "black sliders size 8")["category"], "sandals")
        mention = lex.lookup(tokenize_text("sliders"), 0)
        self.assertEqual(mention.kind, "learned")
        self.assertLess(mention.confidence, 0.85)

    def test_it_never_overrides_a_catalogue_word_or_names_a_value_the_shop_lacks(self):
        lex = Lexicon(ROWS, learned={"sandals": ("category", "shirts"), "zorbas": ("category", "spaceships")})
        self.assertEqual(filters(lex, "sandals")["category"], "sandals")
        self.assertIsNone(filters(lex, "zorbas")["category"])

    def test_an_accepted_product_teaches_the_one_missing_value(self):
        product = next(r for r in ROWS if r["category"] == "sandals" and r["colour"] == "black")
        words = f"{product['brand']} black zorbas size {product['size']}".split()
        self.assertEqual(learn_from_request(words, LEX, self.store, product), [("zorbas", "category", "sandals")])

    def test_two_unknown_words_are_ambiguous_so_nothing_is_learned(self):
        product = next(r for r in ROWS if r["category"] == "sandals" and r["colour"] == "black")
        self.assertEqual(learn_from_request("black zorbas blurbs".split(), LEX, self.store, product), [])

    def test_evidence_against_switches_a_word_off(self):
        for _ in range(3):
            learn_from_request(FIX, LEX, self.store)
        self.assertIn("sliders", self.store.active())
        for _ in range(2):
            self.store.against("sliders")
        self.assertNotIn("sliders", self.store.active())

    def test_a_damaged_file_is_ignored(self):
        self.path.write_text("not json")
        self.assertEqual(load_active(self.path), {})
        self.path.write_text(json.dumps({"words": {"x": {"slot": "category"}}}))
        self.assertEqual(load_active(self.path), {})


if __name__ == "__main__":
    unittest.main()
