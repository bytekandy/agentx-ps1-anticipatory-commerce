import unittest

from anticipatory.policy import InMemoryCatalog
from anticipatory.lexicon import Lexicon, load_rows
from anticipatory.policy import CommitPolicy, blocked_reason, break_even_risk, search_filters
from anticipatory.risk import HeuristicRisk, RiskInput
from anticipatory.state import build_snapshot
from anticipatory.tokens import tokenize_text
from anticipatory.policy import InMemoryCatalog, ToolsCatalog, clean_filters


SMALL = [
    {"product_id": "P1", "title": "Pacevo Court Sneakers, Black", "brand": "Pacevo",
     "category": "sneakers", "colour": "black", "size": "9", "price": "2500", "description": ""},
    {"product_id": "P2", "title": "Pacevo Court Sneakers, Black", "brand": "Pacevo",
     "category": "sneakers", "colour": "black", "size": "10", "price": "2500", "description": ""},
    {"product_id": "P3", "title": "Kudova Flex Sneakers, Black", "brand": "Kudova",
     "category": "sneakers", "colour": "black", "size": "9", "price": "1800", "description": ""},
]


class FixedRisk:
    """A risk model that always gives the same answer."""
    def __init__(self, value):
        self.value = value
        self.calls = []

    def p_wrong(self, features):
        self.calls.append(features)
        return self.value


class PolicyTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_rows()
        cls.lex = Lexicon(cls.rows)

    def snapshot(self, text, final=False):
        return build_snapshot(tokenize_text(text), self.lex, final=final)

    def policy(self, risk=0.0):
        return CommitPolicy(self.lex, FixedRisk(risk))


class BreakEvenTest(unittest.TestCase):
    def test_matches_the_score_formula_notes(self):
        self.assertAlmostEqual(break_even_risk(1), 0.039, places=3)     # about 4 percent
        self.assertAlmostEqual(break_even_risk(4), 0.139, places=3)     # about 14 percent

    def test_more_words_saved_allows_more_risk(self):
        self.assertLess(break_even_risk(1), break_even_risk(2))
        self.assertLess(break_even_risk(2), break_even_risk(8))


class HeuristicRiskTest(unittest.TestCase):
    def features(self, **kw):
        base = dict(words_seen=10, quiet_words=3, at_clause_end=False, settled=True,
                    slots_used=4, weakest_confidence=0.95, revisions=0, markers=0,
                    n_candidates=1)
        base.update(kw)
        return RiskInput(**base)

    def setUp(self):
        self.model = HeuristicRisk()
        self.budget = break_even_risk(1)

    def test_a_calm_clean_unique_match_is_below_break_even(self):
        self.assertLess(self.model.p_wrong(self.features()), self.budget)

    def test_unsettled_is_never_safe(self):
        self.assertEqual(self.model.p_wrong(self.features(settled=False)), 1.0)

    def test_a_fresh_value_is_not_safe(self):
        self.assertGreater(self.model.p_wrong(self.features(quiet_words=0)), self.budget)

    def test_a_pause_is_not_safe(self):
        self.assertGreater(self.model.p_wrong(self.features(at_clause_end=True)), self.budget)

    def test_weak_confidence_raises_the_risk(self):
        strong = self.model.p_wrong(self.features(weakest_confidence=0.95))
        weak = self.model.p_wrong(self.features(weakest_confidence=0.6))
        self.assertGreater(weak, strong)
        self.assertGreater(weak, self.budget)

    def test_risk_stays_a_probability(self):
        self.assertLessEqual(self.model.p_wrong(self.features(quiet_words=0, at_clause_end=True,
                                                              weakest_confidence=0.0)), 1.0)


class SearchFilterTest(PolicyTestCase):
    def test_uses_every_trusted_belief(self):
        snap = self.snapshot("black Pacevo sneakers size 9 under 2000 please")
        self.assertEqual(search_filters(snap), {"category": "sneakers", "colour": "black",
                                                "brand": "Pacevo", "size": "9",
                                                "max_price": 2000})

    def test_leaves_out_weak_beliefs(self):
        snap = self.snapshot("black sneakers 9")           # a bare number is only a guess
        self.assertNotIn("size", search_filters(snap))


class GateTest(PolicyTestCase):
    def reason(self, text):
        snap = self.snapshot(text)
        return blocked_reason(snap, search_filters(snap), self.lex)

    def test_needs_a_category(self):
        self.assertEqual(self.reason("black Pacevo size 9 please"), "category not known")

    def test_a_sized_category_needs_its_size(self):
        self.assertEqual(self.reason("black Pacevo sneakers please"), "size not known")

    def test_an_unsized_category_does_not(self):
        self.assertIsNone(self.reason("black Wavlo watch please"))

    def test_open_when_category_and_size_are_known(self):
        self.assertIsNone(self.reason("black sneakers size 9 please"))

    def test_unsettled_blocks(self):
        self.assertIn("unsettled", self.reason("black sneakers size 9 oops"))
        self.assertIn("unsettled", self.reason("black sneakers size 9 under two thousand"))

    def test_a_guessed_value_blocks(self):
        # a number with no cue beside it, and a spell-corrected brand
        self.assertIn("guessed", self.reason("black Pacevo sneakers size 9 but grey 8 please"))
        self.assertIn("guessed", self.reason("black Pacvo sneakers size 9 please"))

    def test_a_restated_number_is_no_guess(self):
        self.assertIsNone(self.reason("black sneakers size eight, actually nine, please"))


class StepTest(PolicyTestCase):
    """Small catalogues, so uniqueness is easy to reason about."""

    def catalog(self):
        rows = [r for r in self.rows if r["category"] == "watches"]
        return InMemoryCatalog(rows), rows

    def test_commits_to_a_unique_match(self):
        catalog = InMemoryCatalog(SMALL)
        decision = self.policy(0.0).step(
            self.snapshot("black Pacevo sneakers size 9 please"), catalog)
        self.assertEqual((decision.action, decision.product_id), ("commit", "P1"))
        self.assertEqual(decision.n_candidates, 1)
        self.assertTrue(decision.searched)

    def test_waits_when_the_price_still_separates_two_products(self):
        catalog = InMemoryCatalog(SMALL)
        decision = self.policy(0.0).step(self.snapshot("black sneakers size 9 please"), catalog)
        self.assertEqual((decision.action, decision.n_candidates), ("wait", 2))

    def test_a_budget_then_pins_the_product(self):
        catalog = InMemoryCatalog(SMALL)
        policy = self.policy(0.0)
        policy.step(self.snapshot("black sneakers size 9 please"), catalog)
        decision = policy.step(self.snapshot("black sneakers size 9 under 2000 please"), catalog)
        self.assertEqual((decision.action, decision.product_id), ("commit", "P3"))
        self.assertEqual(catalog.searches, 2)

    def test_waits_when_more_than_one_product_matches(self):
        catalog, _ = self.catalog()
        decision = self.policy(0.0).step(self.snapshot("black watch please"), catalog)
        self.assertEqual(decision.action, "wait")
        self.assertTrue(decision.searched)
        self.assertGreater(decision.n_candidates, 1)

    def test_no_search_when_the_risk_is_above_break_even(self):
        catalog, _ = self.catalog()
        decision = self.policy(0.5).step(self.snapshot("black watch please"), catalog)
        self.assertEqual(decision.action, "wait")
        self.assertFalse(decision.searched)
        self.assertEqual(catalog.searches, 0)

    def test_no_search_when_a_gate_is_closed(self):
        catalog, _ = self.catalog()
        self.policy(0.0).step(self.snapshot("watch under two thousand"), catalog)
        self.assertEqual(catalog.searches, 0)

    def test_same_filters_are_not_searched_twice(self):
        catalog, _ = self.catalog()
        policy = self.policy(0.0)
        policy.step(self.snapshot("black watch please"), catalog)
        policy.step(self.snapshot("black watch please thanks"), catalog)
        self.assertEqual(catalog.searches, 1)

    def test_new_filters_are_searched_again(self):
        catalog, _ = self.catalog()
        policy = self.policy(0.0)
        policy.step(self.snapshot("black watch please"), catalog)
        policy.step(self.snapshot("black watch under 9000 please"), catalog)
        self.assertEqual(catalog.searches, 2)

    def test_the_risk_model_is_asked_with_the_best_case(self):
        catalog, _ = self.catalog()
        risk = FixedRisk(0.0)
        CommitPolicy(self.lex, risk).step(self.snapshot("black watch please"), catalog)
        self.assertIsNone(risk.calls[0].n_candidates)

    def test_nothing_happens_after_a_commit(self):
        catalog, rows = self.catalog()
        snap = self.snapshot("black watch please")
        policy = self.policy(0.0)
        policy.committed = "P0001"
        decision = policy.step(snap, catalog)
        self.assertEqual((decision.action, decision.reason), ("wait", "already committed"))
        self.assertEqual(catalog.searches, 0)

    def test_reset_forgets_the_request(self):
        catalog, _ = self.catalog()
        policy = self.policy(0.0)
        policy.step(self.snapshot("black watch please"), catalog)
        policy.committed = "P1"
        policy.reset()
        self.assertIsNone(policy.committed)
        self.assertIsNone(policy.last_filters)


ROWS = [
    {"product_id": "P1", "title": "Pacevo Court Sneakers, Black", "brand": "Pacevo",
     "category": "sneakers", "colour": "black", "size": "9", "price": "2500", "description": ""},
    {"product_id": "P2", "title": "Pacevo Court Sneakers, Black", "brand": "Pacevo",
     "category": "sneakers", "colour": "black", "size": "10", "price": "2500", "description": ""},
    {"product_id": "P3", "title": "Kudova Flex Sneakers, Black", "brand": "Kudova",
     "category": "sneakers", "colour": "black", "size": "9", "price": "1800", "description": ""},
]


class InMemoryCatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = InMemoryCatalog(ROWS)

    def ids(self, filters, query="", k=10):
        return [p["product_id"] for p in self.catalog.find(filters, query, k)]

    def test_exact_filters_are_case_insensitive(self):
        self.assertEqual(self.ids({"brand": "pacevo", "size": "9"}), ["P1"])

    def test_price_bounds(self):
        self.assertEqual(self.ids({"max_price": 2000}), ["P3"])
        self.assertEqual(self.ids({"min_price": 2000}), ["P1", "P2"])

    def test_cheaper_first_on_a_tie_and_query_overlap_first(self):
        self.assertEqual(self.ids({"size": "9"}), ["P3", "P1"])
        self.assertEqual(self.ids({"size": "9"}, "pacevo"), ["P1", "P3"])

    def test_k_limits_the_results_and_every_call_is_counted(self):
        self.assertEqual(len(self.ids({}, k=2)), 2)
        self.assertEqual(self.catalog.searches, 1)
        self.ids({})
        self.assertEqual(self.catalog.searches, 2)

    def test_none_filters_are_ignored(self):
        self.assertEqual(len(self.ids({"brand": None, "size": None})), 3)


class ToolsCatalogTest(unittest.TestCase):
    def test_forwards_to_the_counted_tools_search(self):
        calls = []

        class FakeTools:
            def search(self, query="", filters=None, k=10):
                calls.append((query, filters, k))
                return [{"product_id": "P9"}]

        hits = ToolsCatalog(FakeTools()).find({"colour": "black", "size": None}, "black", 5)
        self.assertEqual(hits, [{"product_id": "P9"}])
        self.assertEqual(calls, [("black", {"colour": "black"}, 5)])

    def test_clean_filters(self):
        self.assertEqual(clean_filters({"a": 1, "b": None}), {"a": 1})
        self.assertEqual(clean_filters(None), {})


if __name__ == "__main__":
    unittest.main()
