import unittest

from anticipatory.tokens import make_token, normalize, tokenize_text


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


if __name__ == "__main__":
    unittest.main()
