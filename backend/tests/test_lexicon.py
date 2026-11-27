import json
import unittest
from pathlib import Path

from anticipatory.config import VocabConfig
from anticipatory.lexicon import (CORRECTION_WORDS, LATE_WORDS, PRICE_CUES, SIZE_CUES, Lexicon,
                                  load_rows)
from anticipatory.numbers import read_number
from anticipatory.tokens import tokenize, tokenize_text

DEV_PATH = Path(__file__).resolve().parents[1] / "dev.jsonl"


def first_match(lex, text):
    return lex.lookup(tokenize_text(text), 0)


class LexiconTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()
        cls.lex = Lexicon(cls.rows)

    def assertMatch(self, text, slot, value, length=None):
        m = first_match(self.lex, text)
        self.assertIsNotNone(m, f"no match for {text!r}")
        self.assertEqual((m.slot, m.value), (slot, value), text)
        self.assertEqual(m.length, length or len(text.split()), text)

    def test_every_catalogue_value_resolves_to_itself(self):
        for slot, values in (("category", self.lex.categories), ("colour", self.lex.colours),
                             ("brand", self.lex.brands), ("size", self.lex.letter_sizes)):
            for value in values:
                with self.subTest(slot=slot, value=value):
                    self.assertMatch(value, slot, value)
                    self.assertEqual(first_match(self.lex, value).kind, "exact")

    def test_no_conflicting_synonyms(self):
        self.assertEqual(self.lex.conflicts, [])

    def test_synonyms_seen_in_dev(self):
        table = {
            "bag pack": ("category", "backpacks"), "rucksack": ("category", "backpacks"),
            "headset": ("category", "headphones"),
            "hooded sweatshirt": ("category", "hoodies"), "sweatshirt": ("category", "hoodies"),
            "denims": ("category", "jeans"),
            "jogging shoes": ("category", "running shoes"), "runners": ("category", "running shoes"),
            "running sneakers": ("category", "running shoes"),
            "floaters": ("category", "sandals"), "slides": ("category", "sandals"),
            "casual shoes": ("category", "sneakers"), "casual sneakers": ("category", "sneakers"),
            "t shirt": ("category", "t-shirts"), "tee": ("category", "t-shirts"),
            "tshirt": ("category", "t-shirts"),
            "joggers": ("category", "track pants"), "trackpants": ("category", "track pants"),
            "wrist watch": ("category", "watches"), "wristwatch": ("category", "watches"),
            "gray": ("colour", "grey"), "golden": ("colour", "gold"),
            "navy blue": ("colour", "navy"), "olive green": ("colour", "olive"),
            "kaala": ("colour", "black"), "laal": ("colour", "red"),
            "gulabi": ("colour", "pink"), "bhura": ("colour", "brown"),
            "small": ("size", "S"), "medium": ("size", "M"), "large": ("size", "L"),
            "extra large": ("size", "XL"), "extra small": ("size", "XS"),
            "double xl": ("size", "XXL"), "2xl": ("size", "XXL"), "xxl": ("size", "XXL"),
        }
        for text, (slot, value) in table.items():
            with self.subTest(text=text):
                self.assertMatch(text, slot, value)

    def test_unseen_synonyms_we_expect_in_the_hidden_set(self):
        table = {
            "flip flops": ("category", "sandals"), "chappals": ("category", "sandals"),
            "sports shoes": ("category", "running shoes"), "kurti": ("category", "kurtas"),
            "earphones": ("category", "headphones"), "smartwatch": ("category", "watches"),
            "safed": ("colour", "white"), "neela": ("colour", "blue"), "hara": ("colour", "green"),
            "peela": ("colour", "yellow"), "x large": ("size", "XL"),
        }
        for text, (slot, value) in table.items():
            with self.subTest(text=text):
                self.assertMatch(text, slot, value)

    def test_plural_and_singular(self):
        for text, value in {"shirt": "shirts", "shirts": "shirts", "dress": "dresses",
                            "dresses": "dresses", "watch": "watches", "watches": "watches",
                            "sneaker": "sneakers", "hoodie": "hoodies", "jean": "jeans",
                            "wallet": "wallets", "cap": "caps", "backpack": "backpacks",
                            "jacket": "jackets", "kurta": "kurtas", "sandal": "sandals",
                            "bags": "backpacks", "tees": "t-shirts", "denim": "jeans"}.items():
            with self.subTest(text=text):
                self.assertMatch(text, "category", value)

    def test_hyphen_and_spacing_variants(self):
        for text, value in {"t-shirt": "t-shirts", "t shirts": "t-shirts", "tshirts": "t-shirts",
                            "tee shirt": "t-shirts", "back pack": "backpacks",
                            "bagpack": "backpacks", "track-pants": "track pants",
                            "trackpants": "track pants", "track pant": "track pants",
                            "running shoe": "running shoes"}.items():
            with self.subTest(text=text):
                self.assertMatch(text, "category", value)
        self.assertMatch("kesarloom", "brand", "Kesar Loom")
        self.assertMatch("kesar-loom", "brand", "Kesar Loom")
        self.assertMatch("navy-blue", "colour", "navy")

    def test_longest_phrase_wins(self):
        self.assertMatch("navy blue", "colour", "navy", length=2)
        self.assertMatch("olive green shirt", "colour", "olive", length=2)
        self.assertMatch("running sneakers", "category", "running shoes", length=2)
        self.assertMatch("sneakers", "category", "sneakers", length=1)
        self.assertMatch("casual sneakers size", "category", "sneakers", length=2)
        self.assertMatch("extra large", "size", "XL", length=2)
        self.assertMatch("kesar loom brand", "brand", "Kesar Loom", length=2)
        self.assertMatch("hooded sweatshirt", "category", "hoodies", length=2)

    def test_a_known_phrase_survives_a_comma_inside_it(self):
        for text, value in (("navy, blue", "navy"), ("extra, large", "XL"), ("t, shirt", "t-shirts")):
            m = first_match(self.lex, text)
            self.assertEqual((m.value, m.length), (value, 2), text)

    def test_two_separate_values_are_not_merged_by_a_comma(self):
        m = first_match(self.lex, "navy, black")
        self.assertEqual((m.value, m.length), ("navy", 1))

    def test_whole_tokens_only(self):
        for text in ("than", "tanned", "capital", "bagel", "shirty", "navys", "xlarges", "hat"):
            with self.subTest(text=text):
                self.assertIsNone(first_match(self.lex, text))

    def test_case_is_ignored(self):
        self.assertMatch("NAVY", "colour", "navy")
        self.assertMatch("Pacevo", "brand", "Pacevo")
        self.assertMatch("XL", "size", "XL")

    def test_ambiguous_or_generic_words_do_not_match(self):
        for text in ("shoes", "pants", "lower", "lowers", "do", "one", "size", "hey", "casual",
                     "brand", "uk", "extra"):
            with self.subTest(text=text):
                self.assertIsNone(first_match(self.lex, text))

    def test_lookup_at_an_offset(self):
        tokens = tokenize_text("show me maroon size M, oops, XS")
        self.assertEqual(self.lex.lookup(tokens, 2).value, "maroon")
        self.assertIsNone(self.lex.lookup(tokens, 3))
        self.assertEqual(self.lex.lookup(tokens, 4).value, "M")
        self.assertEqual(self.lex.lookup(tokens, 6).value, "XS")

    def test_confidence_follows_how_the_word_was_found(self):
        cfg = self.lex.config
        self.assertEqual(first_match(self.lex, "navy").confidence, cfg.confidence_exact)
        self.assertEqual(first_match(self.lex, "shirt").confidence, cfg.confidence_variant)
        self.assertEqual(first_match(self.lex, "slides").confidence, cfg.confidence_synonym)

    def test_confidence_comes_from_config(self):
        lex = Lexicon(self.rows, VocabConfig(confidence_synonym=0.5))
        self.assertEqual(first_match(lex, "slides").confidence, 0.5)


class SizeFactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lex = Lexicon(load_rows())

    def test_unsized_categories(self):
        self.assertEqual(self.lex.unsized_categories,
                         {"backpacks", "caps", "headphones", "watches", "wallets"})
        for c in self.lex.unsized_categories:
            self.assertFalse(self.lex.category_has_sizes(c))
        for c in ("jeans", "kurtas", "sandals", "running shoes", "t-shirts"):
            self.assertTrue(self.lex.category_has_sizes(c))

    def test_size_from_number(self):
        lex = self.lex
        self.assertEqual(lex.size_from_number(9), "9")
        self.assertEqual(lex.size_from_number(32), "32")
        self.assertIsNone(lex.size_from_number(12))
        self.assertIsNone(lex.size_from_number(30000))
        self.assertEqual(lex.size_from_number(9, "sandals"), "9")
        self.assertIsNone(lex.size_from_number(9, "jeans"))
        self.assertEqual(lex.size_from_number(32, "jeans"), "32")
        self.assertIsNone(lex.size_from_number(32, "sandals"))
        self.assertIsNone(lex.size_from_number(9, "backpacks"))

    def test_sizes_for_category(self):
        self.assertEqual(self.lex.sizes_for_category("jeans"), {"28", "30", "32", "34", "36"})
        self.assertEqual(self.lex.sizes_for_category("dresses"), {"XS", "S", "M", "L", "XL"})
        self.assertEqual(self.lex.sizes_for_category("caps"), frozenset())


class SmallCatalogueTest(unittest.TestCase):
    """The lexicon depends only on the rows it is given, not on the real catalogue."""

    def test_vocabulary_comes_from_the_rows(self):
        rows = [{"category": "hats", "colour": "red", "brand": "Acme", "size": "M"},
                {"category": "hats", "colour": "blue", "brand": "Acme", "size": "L"},
                {"category": "mugs", "colour": "red", "brand": "Zed", "size": ""}]
        lex = Lexicon(rows)
        self.assertEqual(first_match(lex, "hat").value, "hats")
        self.assertEqual(first_match(lex, "acme").value, "Acme")
        self.assertEqual(first_match(lex, "m").value, "M")
        self.assertIsNone(first_match(lex, "slides"))        # sandals are not in these rows
        self.assertIsNone(first_match(lex, "gray"))          # grey is not in these rows
        self.assertEqual(lex.unsized_categories, {"mugs"})


class CueWordsTest(unittest.TestCase):
    def test_cue_words_are_not_slot_vocabulary(self):
        lex = Lexicon(load_rows())
        words = set(SIZE_CUES) | set(CORRECTION_WORDS) | set(LATE_WORDS)
        words |= {w for cue in PRICE_CUES for w in cue}
        words -= {"cap"}        # a category that ends the cues "price cap" and "budget cap"; the
                                # slot reader lets those cues claim it (see test_slots)
        for word in sorted(words):
            with self.subTest(word=word):
                self.assertIsNone(first_match(lex, word))


def scan(lex, tokens):
    """Walk a request like a reader: phrase matches and number readings, left to right."""
    phrases, numbers, i = set(), [], 0
    while i < len(tokens):
        match = lex.lookup(tokens, i)
        if match:
            phrases.add((match.slot, match.value))
            i += match.length
            continue
        number = read_number(tokens, i)
        if number:
            numbers.append(number.value)
            i += number.length
            continue
        i += 1
    return phrases, numbers


class DevCoverageTest(unittest.TestCase):
    """Checks the vocabulary against dev.jsonl. This is a test only: the agent never reads it."""

    @classmethod
    def setUpClass(cls):
        cls.lex = Lexicon(load_rows())
        with open(DEV_PATH, encoding="utf-8") as fh:
            cls.rows = [json.loads(line) for line in fh if line.strip()]

    def test_every_gold_value_is_reachable(self):
        missing = []
        for row in self.rows:
            phrases, numbers = scan(self.lex, tokenize(row["words"]))
            gold = row["filters"]
            for slot in ("category", "colour", "brand"):
                if gold[slot] is not None and (slot, gold[slot]) not in phrases:
                    missing.append((row["id"], slot, gold[slot]))
            size = gold["size"]
            if size is not None:
                found = ("size", size) in phrases or any(
                    self.lex.size_from_number(n, gold["category"]) == size for n in numbers)
                if not found:
                    missing.append((row["id"], "size", size))
            if gold["max_price"] is not None and gold["max_price"] not in numbers:
                missing.append((row["id"], "max_price", gold["max_price"]))
        self.assertEqual(missing, [], f"{len(missing)} gold values not found")

    def test_uncorrected_requests_contain_no_stray_phrase_matches(self):
        stray = []
        for row in self.rows:
            if "correction" in row["tags"]:
                continue
            phrases, _ = scan(self.lex, tokenize(row["words"]))
            gold = row["filters"]
            allowed = {(s, gold[s]) for s in ("category", "colour", "brand", "size")
                       if gold[s] is not None}
            extra = phrases - allowed
            if extra:
                stray.append((row["id"], sorted(extra)))
        self.assertEqual(stray, [], f"{len(stray)} requests with stray matches")


class GeneratedPhrasesTest(unittest.TestCase):
    """Shades, Hindi endings, sport-qualified shoe words and Hindi sizes, made by rule."""

    @classmethod
    def setUpClass(cls):
        cls.lex = Lexicon(load_rows())

    def meaning(self, text):
        tokens = tokenize_text(text)
        match = self.lex.lookup(tokens, 0)
        return (match.slot, match.value) if match and match.length == len(tokens) else None

    def test_shades_map_to_their_family(self):
        for text, colour in (("charcoal", "grey"), ("burgundy", "maroon"), ("crimson", "red"),
                             ("mustard", "yellow"), ("wine coloured", "maroon"),
                             ("ash colour", "grey"), ("blk", "black")):
            with self.subTest(text=text):
                self.assertEqual(self.meaning(text), ("colour", colour))

    def test_ordinary_words_need_a_colour_word(self):
        for text in ("wine", "ash", "coffee", "cream"):
            with self.subTest(text=text):
                self.assertIsNone(self.meaning(text))

    def test_every_hindi_ending_but_not_english_words(self):
        for text, colour in (("neele", "blue"), ("kaale", "black"), ("peele", "yellow"),
                             ("bhure", "brown"), ("neela", "blue")):
            with self.subTest(text=text):
                self.assertEqual(self.meaning(text), ("colour", colour))
        for text in ("nile", "pile", "hare"):
            with self.subTest(text=text):
                self.assertIsNone(self.meaning(text))

    def test_a_sport_word_makes_a_shoe_word_a_running_shoe(self):
        for text in ("running wale joote", "sports joota", "jogging shoe"):
            with self.subTest(text=text):
                self.assertEqual(self.meaning(text), ("category", "running shoes"))
        self.assertIsNone(self.meaning("joote"))

    def test_hindi_sizes_only_beside_a_cue(self):
        self.assertEqual(self.meaning("chhota size"), ("size", "S"))
        self.assertEqual(self.meaning("size bada"), ("size", "L"))
        self.assertIsNone(self.meaning("chhota"))

    def test_no_generated_phrase_conflicts(self):
        self.assertEqual(self.lex.conflicts, [])


if __name__ == "__main__":
    unittest.main()


class TransliterationTest(unittest.TestCase):
    """Another romanised spelling of a listed Hindi word is the same word."""

    @classmethod
    def setUpClass(cls):
        cls.lex = Lexicon(load_rows())

    def test_key_ignores_what_writers_vary(self):
        from anticipatory.lexicon import transliteration_key
        self.assertEqual(transliteration_key("neelaa"), transliteration_key("nila"))
        self.assertEqual(transliteration_key("kaalaa"), transliteration_key("kala"))
        self.assertEqual(transliteration_key("bhooraa"), transliteration_key("bhura"))
        self.assertNotEqual(transliteration_key("neela"), transliteration_key("peela"))

    def test_other_spellings_find_the_listed_word(self):
        for spelt, listed in (("neelaa", "neela"), ("kaalaa", "kaala"), ("haraa", "hara"),
                              ("gulaabi", "gulabi"), ("chandee", "chandi"), ("topee", "topi"),
                              ("chapals", "chappals")):
            with self.subTest(spelt=spelt):
                self.assertEqual(self.lex.respell(spelt), listed)

    def test_known_and_english_words_are_left_alone(self):
        for word in ("neela", "hare", "nile", "pile", "peel", "nikla", "red", "blue", "kal", "bag"):
            with self.subTest(word=word):
                self.assertIsNone(self.lex.respell(word))

    def test_no_ordinary_english_word_is_respelt(self):
        from anticipatory.tokens import english_words
        changed = [w for w in english_words()._rank if self.lex.respell(w)]
        self.assertEqual(changed, [])

    def test_colliding_keys_are_dropped(self):
        # no two listed words of different meaning may share a key
        from anticipatory.lexicon import transliteration_key
        seen = {}
        for key, entry in self.lex._table.items():
            if len(key) == 1 and entry.kind == "synonym":
                seen.setdefault(transliteration_key(key[0]), set()).add((entry.slot, entry.value))
        for key in self.lex._respell:
            self.assertEqual(len(seen[key]), 1, key)
