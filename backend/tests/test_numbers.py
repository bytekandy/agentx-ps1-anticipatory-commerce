import unittest

from anticipatory.numbers import read_number
from anticipatory.tokens import tokenize_text


def read(text, start=0):
    return read_number(tokenize_text(text), start)


class ValueTest(unittest.TestCase):
    def check(self, table):
        for text, expected in table.items():
            with self.subTest(text=text):
                reading = read(text)
                self.assertIsNotNone(reading, text)
                self.assertEqual(reading.value, expected)

    def test_digits_and_forms(self):
        self.check({
            "1500": 1500, "4,500": 4500, "Rs.1,500": 1500, "₹2000": 2000, "900": 900,
            "3.5k": 3500, "0.8k": 800, "5K": 5000, "2k": 2000, "1.5k": 1500, "4.5k": 4500,
            "9": 9, "10": 10, "32": 32,
        })

    def test_english_words(self):
        self.check({
            "eight hundred": 800, "forty five hundred": 4500, "thirty seven hundred": 3700,
            "four thousand five hundred": 4500, "one thousand seven hundred": 1700,
            "fifteen hundred": 1500, "sixteen hundred": 1600, "twenty five hundred": 2500,
            "two thousand five hundred": 2500, "five hundred fifty": 550, "two thousand": 2000,
            "nine hundred": 900, "seven": 7, "nine": 9, "eleven": 11, "twenty-five hundred": 2500,
            "hundred": 100, "thousand": 1000, "ten thousand": 10000,
        })

    def test_hindi_words(self):
        self.check({
            "satrah sau": 1700, "paanch hazaar": 5000, "dhai hazaar": 2500, "pandrah sau": 1500,
            "saadhe teen hazaar": 3500, "do hazaar paanch sau": 2500, "dedh hazaar": 1500,
            "das": 10,
        })

    def test_digit_with_unit_word(self):
        self.check({"2 thousand": 2000, "15 hundred": 1500, "1.5 k": 1500, "2 hazaar": 2000})

    def test_length_is_tokens_used(self):
        self.assertEqual(read("forty five hundred rupees").length, 3)
        self.assertEqual(read("1.5 k please").length, 2)
        self.assertEqual(read("saadhe teen hazaar tak").length, 3)
        self.assertEqual(read("3.5k").length, 1)

    def test_reading_starts_where_asked(self):
        reading = read("under four thousand five hundred", start=1)
        self.assertEqual((reading.value, reading.length), (4500, 4))

    def test_not_numbers(self):
        for text in ("navy", "size", "3.5", "under", "kurta"):
            with self.subTest(text=text):
                self.assertIsNone(read(text))


class BoundaryTest(unittest.TestCase):
    def test_clause_end_stops_a_number(self):
        reading = read("four thousand five hundred. one more thing")
        self.assertEqual((reading.value, reading.length), (4500, 4))

    def test_unit_after_hundred_is_not_merged(self):
        reading = read("seven hundred seven")
        self.assertEqual((reading.value, reading.length), (700, 2))

    def test_size_after_price_stays_separate(self):
        tokens = tokenize_text("eight hundred size 7")
        self.assertEqual(read_number(tokens, 0).value, 800)
        self.assertEqual(read_number(tokens, 3).value, 7)

    def test_lone_hindi_or_english_small_words_are_still_read(self):
        # "do you have" starts with the Hindi word for two. The reading is harmless: slot
        # extraction ignores values that are neither prices nor valid sizes.
        reading = read("do you have")
        self.assertEqual((reading.value, reading.length, reading.complete), (2, 1, True))

    def test_dangling_saadhe_is_not_consumed(self):
        self.assertIsNone(read("saadhe"))


class CompletenessTest(unittest.TestCase):
    """A number is complete only when nothing the next word brings could extend it."""

    def test_number_words_at_the_end_are_open(self):
        for text in ("eight", "eight hundred", "four thousand", "satrah", "paanch hazaar"):
            with self.subTest(text=text):
                self.assertFalse(read(text).complete)

    def test_a_following_non_number_word_closes_it(self):
        for text in ("eight size", "eight hundred rupees", "four thousand five hundred in navy"):
            with self.subTest(text=text):
                self.assertTrue(read(text).complete)

    def test_clause_punctuation_closes_it(self):
        self.assertTrue(read("eight, size nine").complete)
        self.assertTrue(read("9.").complete)

    def test_big_digits_and_k_forms_are_always_complete(self):
        for text in ("1500", "900", "3.5k", "2k", "1.5 k"):
            with self.subTest(text=text):
                self.assertTrue(read(text).complete)

    def test_small_digits_at_the_end_are_open_until_a_word_follows(self):
        self.assertFalse(read("9").complete)
        self.assertTrue(read("9 uk").complete)

    def test_a_rejected_following_word_closes_it(self):
        # "seven hundred seven": the second "seven" cannot extend it
        self.assertTrue(read("seven hundred seven").complete)


if __name__ == "__main__":
    unittest.main()
