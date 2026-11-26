import unittest

from anticipatory.tokens import make_token, make_tokens, normalize, tokenize, tokenize_text
import tempfile
from pathlib import Path
from anticipatory.tokens import DEFAULT_WORDS_PATH, EnglishWords, english_words


class GluedSizeTest(unittest.TestCase):
    def test_a_size_cue_glued_to_its_number_becomes_two_tokens(self):
        for raw, cue, number in (("size9", "size", "9"), ("UK10", "uk", "10"), ("sz10", "size", "10"),
                                 ("w32", "waist", "32"), ("Size9,", "size", "9")):
            with self.subTest(raw=raw):
                tokens = make_tokens(raw)
                self.assertEqual([t.text for t in tokens], [cue, number])
                self.assertEqual(tokens[1].clause_end, raw.endswith(","))
                self.assertFalse(tokens[0].clause_end)

    def test_other_words_stay_one_token(self):
        for raw in ("size", "9", "uk", "sizes", "w", "w5x", "uk100", "wallet2", "size9x"):
            with self.subTest(raw=raw):
                self.assertEqual(len(make_tokens(raw)), 1)

    def test_tokenize_expands_them_in_place(self):
        self.assertEqual([t.text for t in tokenize(["black", "UK10", "shoes"])],
                         ["black", "uk", "10", "shoes"])


class NormalizeTest(unittest.TestCase):
    def test_table(self):
        cases = {
            "UK.": "uk",
            "M,": "m",
            "Navy": "navy",
            "it's": "it's",
            "it’s": "it's",
            "(black)": "black",
            "t-shirt": "t-shirt",
            "4,500": "4500",
            "1,500,": "1500",
            "10,000": "10000",
            "1,00,000": "100000",
            "₹1500.": "1500",
            "₹1,500": "1500",
            "Rs.1500": "1500",
            "Rs.1,500": "1500",
            "INR2000": "2000",
            "1500/-": "1500",
            "3.5K": "3.5k",
            "0.8k,": "0.8k",
            "Rs.": "rs",
            "...": "",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize(raw), expected)

    def test_non_grouped_commas_are_left_alone(self):
        self.assertEqual(normalize("1,5"), "1,5")


class ClauseEndTest(unittest.TestCase):
    def test_punctuation_marks_clause_end(self):
        for raw in ("UK.", "M,", "done!", "why?", "so;", "wait…"):
            with self.subTest(raw=raw):
                self.assertTrue(make_token(raw).clause_end)

    def test_plain_words_do_not(self):
        for raw in ("UK", "navy", "3.5k", "it's"):
            with self.subTest(raw=raw):
                self.assertFalse(make_token(raw).clause_end)

    def test_rupee_abbreviation_is_not_a_clause_end(self):
        self.assertFalse(make_token("Rs.").clause_end)

    def test_tokenize_text_keeps_raw_and_order(self):
        tokens = tokenize_text("black UK 10. actually,")
        self.assertEqual([t.raw for t in tokens], ["black", "UK", "10.", "actually,"])
        self.assertEqual([t.text for t in tokens], ["black", "uk", "10", "actually"])
        self.assertEqual([t.clause_end for t in tokens], [False, False, True, True])


class EnglishWordsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.words = english_words()

    def test_the_shipped_list_is_large_and_ordered_by_frequency(self):
        self.assertGreaterEqual(len(self.words), 50000)
        self.assertEqual(self.words.rank("the"), 0)
        self.assertLess(self.words.rank("the"), self.words.rank("short"))
        self.assertLess(self.words.rank("short"), self.words.rank("skirt"))

    def test_real_words_are_in_and_typos_are_not(self):
        for word in ("short", "skirt", "purple", "friday", "nike", "casual"):
            self.assertIn(word, self.words)
        for typo in ("snekers", "blak", "hoodiee"):
            self.assertNotIn(typo, self.words)

    def test_counts(self):
        self.assertGreater(self.words.count("short"), self.words.count("skirt"))
        self.assertEqual(self.words.count("snekers"), 0)

    def test_stopwords_are_the_most_common_words(self):
        for word in ("the", "you", "my", "for", "and"):
            self.assertTrue(self.words.is_stopword(word), word)
        for word in ("purple", "nike", "skirt", "snekers"):
            self.assertFalse(self.words.is_stopword(word), word)

    def test_days_and_months_are_commoner_than_brands(self):
        self.assertLess(self.words.rank("friday"), 2000)
        self.assertLess(self.words.rank("december"), 2000)
        self.assertGreater(self.words.rank("nike"), 2000)
        self.assertGreater(self.words.rank("adidas"), 2000)

    def test_loading_from_a_file_skips_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.tsv"
            path.write_text("# comment\nhello\t100\nworld\t50\n\n")
            small = EnglishWords.from_file(path)
        self.assertEqual((len(small), small.rank("hello"), small.count("world")), (2, 0, 50))

    def test_the_shared_instance_is_loaded_once(self):
        self.assertIs(english_words(), english_words())

    def test_the_file_is_in_the_package(self):
        self.assertTrue(DEFAULT_WORDS_PATH.exists())


if __name__ == "__main__":
    unittest.main()
