import tempfile
import unittest
from pathlib import Path

from anticipatory.words import DEFAULT_WORDS_PATH, EnglishWords, english_words


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
