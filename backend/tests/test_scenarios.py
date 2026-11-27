"""Hand-written scenarios for phrasing the dev set does not contain (Stage 8).

Every scenario runs the real default agent (hybrid risk) over an in-memory copy of the catalogue,
word by word, and checks three things: the final answer, that no early commit ever went to the
wrong product, and, where it matters, when the agent held back.
"""
import unittest

from anticipatory.agent import AnticipatoryAgent
from anticipatory.policy import InMemoryCatalog
from anticipatory.lexicon import Lexicon, load_rows
from anticipatory.risk import HybridRisk, LearnedRisk

# Real products used as anchors (checked against catalogue.csv).
LOOMSY_BEIGE_10 = "P0081"        # beige Loomsy sneakers, size 10, 2899
LOOMSY_NAVY_7_CHEAP = "P0086"    # navy Loomsy sneakers, size 7, 4449
LOOMSY_NAVY_7_DEAR = "P0156"     # the same, 7499
HOODIE_S, HOODIE_M, HOODIE_XS = "P0632", "P0633", "P0631"      # navy Urbanyx hoodies, 1249
JEANS_BLUE_32 = "P0405"          # blue Northweft jeans, waist 32, 1699
TIKKRA_WATCH = "P1015"           # silver Tikkra watch, 6099


class ScenarioTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()
        cls.lex = Lexicon(cls.rows)

    def run_request(self, text):
        agent = AnticipatoryAgent(InMemoryCatalog(self.rows), lexicon=self.lex,
                                  risk_model=HybridRisk(LearnedRisk.from_file()))
        agent.start("scenario")
        commits = []
        for i, word in enumerate(text.split(), start=1):
            out = agent.observe(word)
            if out and out.get("commit"):
                commits.append((i, out["commit"]))
        final = agent.finish()
        return commits, final, agent

    def assertAnswers(self, text, target, allow_early=True):
        commits, final, agent = self.run_request(text)
        self.assertEqual(final, target, text)
        self.assertEqual([c for c in commits if c[1] != target], [], f"wrong early commit: {text}")
        if not allow_early:
            self.assertEqual(commits, [], text)
        return commits, agent


class PhrasingTest(ScenarioTestCase):
    def test_possessive_brand(self):
        self.assertAnswers("can I see Loomsy's beige sneakers in size 10 please", LOOMSY_BEIGE_10)

    def test_colloquial_opener_is_not_an_unknown_word(self):
        _, agent = self.assertAnswers("gimme navy Urbanyx hoodies size M thanks", HOODIE_M)
        self.assertEqual(agent.unresolved, [])

    def test_number_words_and_hindi_english(self):
        self.assertAnswers("beige Loomsy sneakers size ten under three thousand", LOOMSY_BEIGE_10)
        self.assertAnswers("mujhe silver Tikkra watch chahiye seven thousand tak", TIKKRA_WATCH)

    def test_price_cues_the_vocabulary_has_not_seen_in_dev(self):
        for cue in ("not exceeding", "at most", "price under", "cheaper than", "or below"):
            text = (f"navy Loomsy sneakers size 7 {cue} 5000" if cue != "or below"
                    else "navy Loomsy sneakers size 7 5000 or below")
            with self.subTest(cue=cue):
                self.assertAnswers(text, LOOMSY_NAVY_7_CHEAP)

    def test_price_separates_two_products_of_the_same_kind(self):
        self.assertAnswers("navy Loomsy sneakers size 7 under 5000", LOOMSY_NAVY_7_CHEAP)

    def test_two_products_still_match_so_nothing_is_committed(self):
        commits, final, _ = self.run_request("navy Loomsy sneakers size 7 max 8000 thanks a lot")
        self.assertEqual(commits, [])                      # the price does not pick one
        self.assertIn(final, (LOOMSY_NAVY_7_CHEAP, LOOMSY_NAVY_7_DEAR))

    def test_price_cap_is_a_budget_not_a_cap(self):
        self.assertAnswers("hello could you look up navy Urbanyx hoodies for me, size M, price cap 3000 "
                           "thank you so much", HOODIE_M)

    def test_glued_sizes(self):
        for glued in ("UK10", "size10", "sz10", "uk10,"):
            with self.subTest(glued=glued):
                self.assertAnswers(f"beige Loomsy sneakers {glued} under 3000", LOOMSY_BEIGE_10)
        self.assertAnswers("blue Northweft jeans w32 under 2000", JEANS_BLUE_32)

    def test_rupee_formats(self):
        for price in ("Rs. 2,899", "₹2899", "2899/-", "Rs.2899", "2.9k"):
            with self.subTest(price=price):
                self.assertAnswers(f"beige Loomsy sneakers size 10 under {price}", LOOMSY_BEIGE_10)

    def test_odd_punctuation_and_case(self):
        self.assertAnswers("BEIGE LOOMSY SNEAKERS, SIZE 10!!! UNDER 3000???", LOOMSY_BEIGE_10)
        self.assertAnswers("  beige   loomsy sneakers ;; size 10 ", LOOMSY_BEIGE_10)

    def test_typos(self):
        self.assertAnswers("beige Loomsy snekers size 10", LOOMSY_BEIGE_10)
        self.assertAnswers("slver Tikkra wacth under 7000", TIKKRA_WATCH)


class CorrectionScenarioTest(ScenarioTestCase):
    def test_price_correction(self):
        commits, _ = self.assertAnswers("navy Loomsy sneakers size 7 under 8000, no make it 5000",
                                        LOOMSY_NAVY_7_CHEAP)

    def test_a_marker_word_dev_never_had(self):
        for marker in ("correction:", "ignore that,", "disregard that,"):
            with self.subTest(marker=marker):
                self.assertAnswers(f"navy Urbanyx hoodie size S, {marker} size M", HOODIE_M)

    def test_two_corrections_in_one_request(self):
        self.assertAnswers("navy Urbanyx hoodie size XS no wait S sorry M", HOODIE_M)

    def test_size_correction_after_a_pause_never_commits_the_old_size(self):
        commits, _ = self.assertAnswers("navy Urbanyx hoodies size S. oops, size M", HOODIE_M)
        self.assertNotIn(HOODIE_S, [c[1] for c in commits])

    def test_make_that_is_a_marker(self):
        self.assertAnswers("navy Urbanyx hoodies size S make that size M", HOODIE_M)

    def test_bare_number_restates_a_shoe_size(self):
        self.assertAnswers("beige Loomsy sneakers size 11 actually 10", LOOMSY_BEIGE_10)

    def test_brand_correction_long_after_the_brand(self):
        self.assertAnswers("blue Northweft jeans waist 32, under 2000, sorry I meant Northweft",
                           JEANS_BLUE_32)


class HoldingBackTest(ScenarioTestCase):
    def test_nothing_is_committed_for_a_brand_we_do_not_sell(self):
        commits, final, agent = self.run_request("navy Nike hoodies size M please do hurry")
        self.assertEqual(commits, [])
        self.assertEqual([u.kind for u in agent.unresolved], ["brand"])

    def test_nothing_is_committed_for_a_size_that_does_not_exist(self):
        commits, _, agent = self.run_request("navy Urbanyx hoodies size 14 please do hurry now")
        self.assertEqual(commits, [])

    def test_unresolved_words_never_block_the_final_answer(self):
        _, final, _ = self.run_request("navy Urbanyx hoodies size M in teal please")
        self.assertIsNotNone(final)

    def test_a_clear_request_is_committed_before_its_last_word(self):
        text = "beige Loomsy sneakers size 10 under 4000 please do hurry up now my friend"
        commits, _ = self.assertAnswers(text, LOOMSY_BEIGE_10)
        self.assertTrue(commits)
        self.assertLess(commits[0][0], len(text.split()))

    def test_a_request_without_a_budget_is_still_answered_right(self):
        # the learned risk model is more cautious without a budget: it may commit late or not at all
        self.assertAnswers("beige Loomsy sneakers size 10 please do hurry up now my friend",
                           LOOMSY_BEIGE_10)


class EdgeCaseTest(ScenarioTestCase):
    def test_empty_and_single_word_requests(self):
        for text in ("", "hello", "?", "!!!", "9", "Rs.", "size"):
            with self.subTest(text=text):
                commits, final, _ = self.run_request(text)
                self.assertEqual(commits, [])
                self.assertTrue(final is None or isinstance(final, str))

    def test_a_very_long_request_stays_fast_and_correct(self):
        filler = "please do show me whatever you may have in stock today " * 30
        text = filler + "beige Loomsy sneakers size 10 under 3000 " + filler
        commits, final, _ = self.run_request(text)
        self.assertEqual(final, LOOMSY_BEIGE_10)
        self.assertEqual([c for c in commits if c[1] != LOOMSY_BEIGE_10], [])

    def test_repeating_the_same_request_gives_the_same_answer(self):
        text = "navy Urbanyx hoodie size XS no wait S sorry M"
        self.assertEqual(self.run_request(text)[:2], self.run_request(text)[:2])


if __name__ == "__main__":
    unittest.main()
