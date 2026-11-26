import json
import unittest
from pathlib import Path

from anticipatory.lexicon import Lexicon, load_rows
from anticipatory.slots import SlotMention, extract_mentions, latest_filters
from anticipatory.tokens import tokenize, tokenize_text

DEV_PATH = Path(__file__).resolve().parents[1] / "dev.jsonl"


class SlotsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lex = Lexicon(load_rows())

    def read(self, text, final=True):
        return extract_mentions(tokenize_text(text), self.lex, final=final)

    def one(self, text, slot, final=True):
        found = [m for m in self.read(text, final) if m.slot == slot]
        self.assertEqual(len(found), 1, f"{text!r}: expected one {slot} mention, got {found}")
        return found[0]

    def assertSlot(self, text, slot, value, final=True):
        m = self.one(text, slot, final)
        self.assertEqual(m.value, value, text)
        return m

    def filters(self, text):
        return latest_filters(self.read(text), self.lex)


class PhraseSlotTest(SlotsTestCase):
    def test_text_slots(self):
        mentions = {(m.slot, m.value) for m in self.read("black slides from Pacevo")}
        self.assertEqual(mentions, {("colour", "black"), ("category", "sandals"),
                                    ("brand", "Pacevo")})

    def test_positions_are_token_indexes(self):
        m = self.one("get me navy blue Kesar Loom jeans", "brand")
        self.assertEqual((m.start, m.end), (4, 6))

    def test_misspelt_brand_is_low_confidence(self):
        m = self.assertSlot("black shoes from Pacevoo", "brand", "Pacevo")
        self.assertEqual(m.kind, "fuzzy")
        self.assertLess(m.confidence, 0.7)

    def test_misspelt_words_of_every_slot_are_read_at_low_confidence(self):
        for text, slot, value in (("blak cap", "colour", "black"),
                                  ("snekers size 9", "category", "sneakers"),
                                  ("runing shoes", "category", "running shoes"),
                                  ("navy hoodiee", "category", "hoodies")):
            with self.subTest(text=text):
                m = self.assertSlot(text, slot, value)
                self.assertEqual(m.kind, "fuzzy")
                self.assertLess(m.confidence, 0.7)

    def test_a_corrected_phrase_keeps_its_whole_span(self):
        m = self.one("get me runing shoes please", "category")
        self.assertEqual((m.start, m.end), (2, 4))

    def test_correct_words_are_not_marked_fuzzy(self):
        self.assertEqual({m.kind for m in self.read("black sneakers from Pacevo")} & {"fuzzy"}, set())

    def test_ordinary_words_make_no_mentions(self):
        self.assertEqual(self.read("hi do you have any one more thing please"), [])
        self.assertEqual(self.read("mere liye ek aur baat kya aapke paas hai"), [])

    def test_letter_size_beside_a_cue_is_trusted_more(self):
        bare = self.assertSlot("jacket M", "size", "M")
        cued = self.assertSlot("jacket size M", "size", "M")
        after = self.assertSlot("jacket M size", "size", "M")
        self.assertGreater(cued.confidence, bare.confidence)
        self.assertGreater(after.confidence, bare.confidence)

    def test_word_sizes(self):
        self.assertSlot("dress extra large", "size", "XL")
        self.assertSlot("dress small", "size", "S")


class SizeNumberTest(SlotsTestCase):
    def test_cue_before_the_number(self):
        for text in ("size 9", "size nine", "UK 9", "uk 9", "number 9", "Size: 9", "sz 9"):
            with self.subTest(text=text):
                self.assertSlot("sandals " + text, "size", "9")

    def test_cue_after_the_number(self):
        for text in ("9 UK", "size 9 UK", "9 size"):
            with self.subTest(text=text):
                self.assertSlot("sandals " + text, "size", "9")

    def test_waist(self):
        self.assertSlot("jeans waist 32", "size", "32")
        self.assertSlot("jeans 32 waist", "size", "32")
        self.assertSlot("jeans size 28", "size", "28")

    def test_a_size_is_settled_without_waiting_for_the_next_word(self):
        self.assertTrue(self.one("sandals size 9", "size", final=False).complete)
        self.assertTrue(self.one("sandals size nine", "size", final=False).complete)

    def test_thirty_could_still_become_thirty_two(self):
        self.assertFalse(self.one("jeans size thirty", "size", final=False).complete)
        self.assertTrue(self.one("jeans size thirty", "size", final=True).complete)

    def test_numbers_that_are_not_real_sizes_are_dropped(self):
        self.assertEqual([m for m in self.read("size 42") if m.slot == "size"], [])
        self.assertEqual([m for m in self.read("size do") if m.slot == "size"], [])

    def test_bare_number_is_only_a_weak_guess(self):
        m = self.assertSlot("black sandals 9", "size", "9")
        self.assertEqual(m.via, "bare")
        self.assertLess(m.confidence, 0.5)
        self.assertIsNone(self.filters("need it in 10 days")["size"])

    def test_a_size_cue_is_not_shared_with_a_following_price(self):
        text = "sneakers 10 UK 3000 max"
        self.assertSlot(text, "size", "10")
        self.assertSlot(text, "max_price", 3000)
        self.assertSlot("sneakers size 9 UK 3000", "max_price", 3000)

    def test_a_price_cue_that_follows_a_number_is_not_shared_with_the_next_one(self):
        for text in ("2100 se kam 34 waist", "2100 tak 34 waist", "2100 ke andar 34 waist"):
            with self.subTest(text=text):
                self.assertSlot("blue jeans " + text, "max_price", 2100)
                self.assertSlot("blue jeans " + text, "size", "34")

    def test_a_price_cue_before_a_number_that_is_no_price_falls_through(self):
        self.assertSlot("sandals under 9", "size", "9")           # weak, but not thrown away
        self.assertLess(self.one("sandals under 9", "size").confidence, 0.5)

    def test_size_beside_a_price_stays_a_size(self):
        text = "sandals size 9 under 1500"
        self.assertSlot(text, "size", "9")
        self.assertSlot(text, "max_price", 1500)
        text = "sandals under 1500 size 9"
        self.assertSlot(text, "size", "9")
        self.assertSlot(text, "max_price", 1500)


class PriceTest(SlotsTestCase):
    def test_price_cues_before(self):
        for text in ("under 1500", "below 1500", "within 1500", "max 1500", "maximum 1500",
                     "upto 1500", "up to 1500", "less than 1500", "not more than 1500",
                     "no more than 1500", "cheaper than 1500", "budget 1500", "budget of 1500",
                     "budget is 1500", "under Rs. 1500", "under Rs.1,500", "under ₹1,500",
                     "under INR 1500", "for under about 1500"):
            with self.subTest(text=text):
                m = self.assertSlot("shirt " + text, "max_price", 1500)
                self.assertGreaterEqual(m.confidence, 0.9)
                self.assertEqual(m.slot, "max_price")

    def test_price_cues_after(self):
        for text in ("1500 tak", "1500 se kam", "1500 ke andar", "1500 rupees", "1500 or less",
                     "1500 or below", "1500 max"):
            with self.subTest(text=text):
                self.assertSlot("shirt " + text, "max_price", 1500)

    def test_currency_marks_on_the_number_itself(self):
        for text in ("Rs.1500", "Rs.1,500,", "₹1,500", "1500/-", "INR1500"):
            with self.subTest(text=text):
                m = self.assertSlot("black watch " + text, "max_price", 1500)
                self.assertEqual(m.via, "price-cue")

    def test_k_amounts(self):
        self.assertSlot("shirt under 2.5k", "max_price", 2500)
        self.assertSlot("shirt max 1k", "max_price", 1000)
        self.assertSlot("shirt under 1.5 k", "max_price", 1500)

    def test_number_words(self):
        self.assertSlot("shirt under fifteen hundred", "max_price", 1500)
        self.assertSlot("shirt under one thousand five hundred", "max_price", 1500)
        self.assertSlot("shirt below thirty seven hundred please", "max_price", 3700)
        self.assertSlot("shirt 3 hazaar tak", "max_price", 3000)
        self.assertSlot("shirt paanch hazaar tak", "max_price", 5000)

    def test_lower_bound_cues(self):
        self.assertSlot("watch above 2000", "min_price", 2000)
        self.assertSlot("watch at least 2000", "min_price", 2000)
        self.assertEqual([m for m in self.read("watch above 2000") if m.slot == "max_price"], [])

    def test_not_more_than_is_an_upper_bound(self):
        self.assertSlot("watch not more than 2000", "max_price", 2000)
        self.assertSlot("watch more than 2000", "min_price", 2000)

    def test_bare_price_is_a_weaker_max_price(self):
        bare = self.assertSlot("black watch 2000", "max_price", 2000)
        self.assertEqual(bare.via, "bare")
        self.assertLess(bare.confidence, 0.9)
        self.assertGreater(bare.confidence, 0.5)

    def test_a_cue_followed_by_a_pause_does_not_attach(self):
        self.assertEqual([m for m in self.read("watch under, hmm") if m.slot == "max_price"], [])
        self.assertEqual(self.one("watch under, 2000", "max_price").via, "bare")

    def test_out_of_range_numbers_are_not_prices(self):
        self.assertEqual([m for m in self.read("watch under 50") if m.slot == "max_price"], [])
        self.assertEqual([m for m in self.read("watch under 9999999")
                          if m.slot == "max_price"], [])


class CueAwaitingNumberTest(SlotsTestCase):
    def test_cues_at_the_end(self):
        from anticipatory.slots import cue_awaiting_number
        for text in ("under", "budget of", "within Rs.", "size", "UK", "up to"):
            with self.subTest(text=text):
                self.assertTrue(cue_awaiting_number(tokenize_text("black cap " + text)))
        for text in ("up", "not more", "less", "no more"):          # partway through a cue
            with self.subTest(text=text):
                self.assertTrue(cue_awaiting_number(tokenize_text("black cap " + text)))
        for text in ("under 500", "black cap", "size 9", "", "under,"):
            with self.subTest(text=text):
                self.assertFalse(cue_awaiting_number(tokenize_text(text)))


class IncompleteNumberTest(SlotsTestCase):
    def test_a_price_at_the_end_may_still_grow(self):
        m = self.one("shirt under two thousand", "max_price", final=False)
        self.assertEqual(m.value, 2000)
        self.assertFalse(m.complete)

    def test_the_next_word_settles_it(self):
        m = self.one("shirt under two thousand please", "max_price", final=False)
        self.assertTrue(m.complete)

    def test_it_really_grows(self):
        self.assertEqual(self.one("shirt under two thousand five", "max_price",
                                  final=False).value, 2005)
        self.assertEqual(self.one("shirt under two thousand five hundred", "max_price",
                                  final=False).value, 2500)

    def test_final_settles_a_number_at_the_end(self):
        self.assertTrue(self.one("shirt under two thousand", "max_price", final=True).complete)

    def test_pending_hundreds_are_kept_but_not_trusted(self):
        m = self.one("shirt under 15", "max_price", final=False)
        self.assertFalse(m.complete)
        self.assertEqual(self.one("shirt under 15 hundred", "max_price", final=False).value, 1500)
        self.assertEqual([m for m in self.read("shirt under 15", final=True)
                          if m.slot == "max_price"], [])

    def test_incomplete_mentions_are_ignored_by_latest_filters(self):
        mentions = extract_mentions(tokenize_text("shirt under two thousand"), self.lex)
        self.assertIsNone(latest_filters(mentions, self.lex)["max_price"])


class LatestFiltersTest(SlotsTestCase):
    def test_full_request(self):
        got = self.filters("show me Tanaro shirt less than 900 in navy blue small please")
        self.assertEqual(got, {"category": "shirts", "colour": "navy", "size": "S",
                               "brand": "Tanaro", "max_price": 900})

    def test_missing_slots_are_none(self):
        got = self.filters("black cap")
        self.assertEqual(got, {"category": "caps", "colour": "black", "size": None,
                               "brand": None, "max_price": None})

    def test_number_size_must_fit_the_category(self):
        self.assertEqual(self.filters("jeans size 32")["size"], "32")
        self.assertIsNone(self.filters("jeans size 9")["size"])
        self.assertEqual(self.filters("sandals size 9")["size"], "9")
        self.assertIsNone(self.filters("sandals size 32")["size"])

    def test_unsized_category_has_no_size(self):
        self.assertIsNone(self.filters("small backpack")["size"])
        self.assertIsNone(self.filters("black cap size M")["size"])

    def test_last_mention_wins(self):
        self.assertEqual(self.filters("white dress large from Loomsy sorry I meant size M")["size"],
                         "M")

    def test_min_price_appears_only_when_present(self):
        self.assertNotIn("min_price", self.filters("black watch"))
        self.assertEqual(self.filters("black watch above 2000")["min_price"], 2000)

    def test_weak_guesses_are_ignored(self):
        got = self.filters("black sandals 9")
        self.assertIsNone(got["size"])


class StreamingTest(SlotsTestCase):
    """The reader is fed one word at a time, so what it says early must still be true later."""

    def test_extraction_is_pure(self):
        tokens = tokenize_text("black slides size nine under Rs.1,500 oops white")
        self.assertEqual(extract_mentions(tokens, self.lex), extract_mentions(tokens, self.lex))

    def test_mentions_are_dataclasses_with_a_span(self):
        for m in self.read("black slides size nine under Rs.1,500"):
            self.assertIsInstance(m, SlotMention)
            self.assertLess(m.start, m.end)


class DevSlotTest(unittest.TestCase):
    """Checks extraction against dev.jsonl. This is a test only: the agent never reads it."""

    SLOTS = ("category", "colour", "size", "brand", "max_price")

    @classmethod
    def setUpClass(cls):
        cls.lex = Lexicon(load_rows())
        with open(DEV_PATH, encoding="utf-8") as fh:
            cls.rows = [json.loads(line) for line in fh if line.strip()]

    def test_plain_requests_are_read_at_least_95_percent_right(self):
        plain = [r for r in self.rows if not r["tags"]]
        right = total = 0
        for row in plain:
            got = latest_filters(extract_mentions(tokenize(row["words"]), self.lex, final=True),
                                 self.lex)
            for slot in self.SLOTS:
                total += 1
                right += got[slot] == row["filters"][slot]
        self.assertGreaterEqual(right / total, 0.95, f"{right}/{total}")

    def test_every_plain_request_is_read_exactly(self):
        wrong = []
        for row in self.rows:
            if row["tags"]:
                continue
            got = latest_filters(extract_mentions(tokenize(row["words"]), self.lex, final=True),
                                 self.lex)
            if any(got[s] != row["filters"][s] for s in self.SLOTS):
                wrong.append(row["id"])
        self.assertEqual(wrong, [])

    def test_completed_mentions_never_change_as_words_arrive(self):
        """What a complete mention says at word t is still said once the whole request is in."""
        broken = []
        for row in self.rows:
            tokens = tokenize(row["words"])
            full = {(m.slot, m.value) for m in extract_mentions(tokens, self.lex, final=True)}
            for t in range(1, len(tokens) + 1):
                early = extract_mentions(tokens[:t], self.lex)
                for m in early:
                    if m.complete and m.confidence >= 0.5 and (m.slot, m.value) not in full:
                        broken.append((row["id"], t, m.slot, m.value))
        self.assertEqual(broken, [])

    def test_no_trusted_mention_is_invented(self):
        """In uncorrected requests every trusted mention is a gold value."""
        stray = []
        for row in self.rows:
            if "correction" in row["tags"]:
                continue
            gold = {(s, row["filters"][s]) for s in self.SLOTS if row["filters"][s] is not None}
            for m in extract_mentions(tokenize(row["words"]), self.lex, final=True):
                if m.confidence >= 0.5 and (m.slot, m.value) not in gold:
                    stray.append((row["id"], m.slot, m.value))
        self.assertEqual(stray, [])


if __name__ == "__main__":
    unittest.main()
