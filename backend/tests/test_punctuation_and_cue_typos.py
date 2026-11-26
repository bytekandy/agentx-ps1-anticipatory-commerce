"""A comma inside a phrase, and a typo in a cue word, must not change what the agent reads."""
import unittest

from anticipatory.lexicon import Lexicon, load_rows
from anticipatory.state import build_snapshot, find_markers
from anticipatory.tokens import tokenize_text

LEX = Lexicon(load_rows())


def filters(text):
    return build_snapshot(tokenize_text(text), LEX, final=True).filters


class CommaInsidePhraseTest(unittest.TestCase):
    def test_commas_inside_phrases_change_nothing(self):
        for plain, commas in (("navy blue t shirt size M", "navy, blue t, shirt size M"),
                              ("black shirt extra large", "black shirt extra, large")):
            self.assertEqual(filters(plain), filters(commas), commas)

    def test_a_comma_between_two_values_still_separates_them(self):
        self.assertEqual(filters("shirt, size M, in black")["colour"], "black")


class CueTypoTest(unittest.TestCase):
    def test_typos_in_size_and_price_cues_are_read(self):
        for plain, typo in (("black shoes size 9", "black shoes sise 9"),
                            ("black shoes size 9", "black shoes saiz 9"),
                            ("black shoes under 2000", "black shoes unedr 2000"),
                            ("black shoes budget 2000", "black shoes budgte 2000")):
            self.assertEqual(filters(plain), filters(typo), typo)

    def test_a_typo_in_a_correction_marker_is_still_a_marker(self):
        words = tokenize_text("black shoes sorey I meant white")
        self.assertGreaterEqual(len(find_markers(words)), 1)
        self.assertEqual(filters("black shoes sorey I meant white")["colour"], "white")

    def test_ordinary_words_are_not_pulled_into_cues(self):
        for word in ("sized", "shirt", "short", "wait", "want", "number"):
            self.assertNotIn(LEX.corrector.correct(word), ("size", "under", "sorry"), word)


if __name__ == "__main__":
    unittest.main()
