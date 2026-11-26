import json
import tempfile
import unittest
from pathlib import Path

from anticipatory.config import Config, LearnedRiskConfig
from anticipatory.risk import (DEFAULT_MODEL_PATH, FEATURE_NAMES, HeuristicRisk, HybridRisk,
                               LearnedRisk, RiskInput, risk_features, sigmoid)


def features(**kw):
    base = dict(words_seen=10, quiet_words=3, at_clause_end=False, settled=True, slots_used=4,
                weakest_confidence=0.95, revisions=0, markers=0, n_candidates=1,
                has_brand=True, has_size=True, has_price=True, oldest_age=4, last_slot="size")
    base.update(kw)
    return RiskInput(**base)


class FeatureTest(unittest.TestCase):
    def test_every_feature_has_a_name_and_a_number(self):
        x = risk_features(features())
        self.assertEqual(tuple(x), FEATURE_NAMES)
        self.assertEqual(x["bias"], 1.0)

    def test_quiet_words_are_bucketed(self):
        self.assertEqual(risk_features(features(quiet_words=0))["quiet=0"], 1.0)
        self.assertEqual(risk_features(features(quiet_words=2))["quiet=2"], 1.0)
        x = risk_features(features(quiet_words=5))
        self.assertEqual([x["quiet=0"], x["quiet=1"], x["quiet=2"]], [0.0, 0.0, 0.0])

    def test_last_slot_is_one_hot(self):
        x = risk_features(features(last_slot="brand"))
        self.assertEqual(x["last=brand"], 1.0)
        self.assertEqual(x["last=size"], 0.0)

    def test_values_stay_small(self):
        x = risk_features(features(words_seen=500, oldest_age=500, slots_used=9))
        self.assertLessEqual(x["words_seen"], 1.0)
        self.assertLessEqual(x["oldest_age"], 1.0)

    def test_sigmoid_is_stable_at_the_extremes(self):
        self.assertEqual(sigmoid(0.0), 0.5)
        self.assertAlmostEqual(sigmoid(800.0), 1.0)
        self.assertAlmostEqual(sigmoid(-800.0), 0.0)


class LearnedRiskTest(unittest.TestCase):
    def test_the_shipped_model_loads_and_covers_every_feature(self):
        model = LearnedRisk.from_file()
        self.assertEqual(set(model.weights), set(FEATURE_NAMES))
        self.assertGreaterEqual(model.multiplier, 1.0)

    def test_probabilities_are_probabilities(self):
        model = LearnedRisk.from_file()
        for q in (0, 1, 3):
            for pause in (False, True):
                p = model.p_wrong(features(quiet_words=q, at_clause_end=pause))
                self.assertTrue(0.0 <= p <= 1.0)

    def test_unsettled_is_never_safe(self):
        self.assertEqual(LearnedRisk.from_file().p_wrong(features(settled=False)), 1.0)

    def test_a_weakly_read_value_is_riskier(self):
        model = LearnedRisk.from_file()
        self.assertGreater(model.p_wrong(features(weakest_confidence=0.6)),
                           model.p_wrong(features(weakest_confidence=0.95)))

    def test_a_pause_is_riskier_than_none(self):
        model = LearnedRisk.from_file()
        self.assertGreater(model.p_wrong(features(at_clause_end=True)),
                           model.p_wrong(features(at_clause_end=False)))

    def test_the_multiplier_comes_from_the_file_unless_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "m.json"
            path.write_text(json.dumps({"features": ["bias"], "weights": [-2.0],
                                        "meta": {"safety_multiplier": 2.0}}))
            model = LearnedRisk.from_file(path)
            self.assertEqual(model.multiplier, 2.0)
            self.assertAlmostEqual(model.p_wrong(features()), 2 * sigmoid(-2.0))
            override = LearnedRisk.from_file(
                path, Config(learned=LearnedRiskConfig(safety_multiplier=1.0)))
            self.assertAlmostEqual(override.p_wrong(features()), sigmoid(-2.0))

    def test_unknown_features_are_rejected(self):
        with self.assertRaises(ValueError):
            LearnedRisk({"not_a_feature": 1.0})

    def test_the_model_file_is_small_json(self):
        data = json.loads(DEFAULT_MODEL_PATH.read_text())
        self.assertEqual(data["features"], list(FEATURE_NAMES))
        self.assertEqual(len(data["weights"]), len(FEATURE_NAMES))
        self.assertLess(DEFAULT_MODEL_PATH.stat().st_size, 5000)


class HybridRiskTest(unittest.TestCase):
    """The rules keep control of fresh and just-paused states; the model decides calm ones."""

    class Fixed:
        def __init__(self, value):
            self.value = value

        def p_wrong(self, features):
            return self.value

    def hybrid(self, learned_value):
        hybrid = HybridRisk(LearnedRisk.from_file())
        hybrid.learned = self.Fixed(learned_value)
        return hybrid

    def test_a_fresh_value_keeps_the_rules_caution_even_if_the_model_says_safe(self):
        risk = self.hybrid(0.0).p_wrong(features(quiet_words=0))
        self.assertEqual(risk, HeuristicRisk().p_wrong(features(quiet_words=0)))
        self.assertGreater(risk, 0.04)

    def test_a_pause_keeps_the_rules_caution(self):
        self.assertGreater(self.hybrid(0.0).p_wrong(features(at_clause_end=True)), 0.04)

    def test_a_calm_state_is_left_to_the_model(self):
        calm = features(quiet_words=3, at_clause_end=False)
        self.assertEqual(self.hybrid(0.01).p_wrong(calm), 0.01)
        self.assertEqual(self.hybrid(0.3).p_wrong(calm), 0.3)

    def test_a_cautious_model_also_blocks_a_fresh_state(self):
        self.assertEqual(self.hybrid(1.0).p_wrong(features(quiet_words=0)), 1.0)

    def test_a_value_read_with_low_confidence_keeps_the_rules_caution(self):
        calm_but_shaky = features(quiet_words=5, weakest_confidence=0.6)
        self.assertEqual(self.hybrid(0.0).p_wrong(calm_but_shaky),
                         HeuristicRisk().p_wrong(calm_but_shaky))
        self.assertGreater(self.hybrid(0.0).p_wrong(calm_but_shaky), 0.04)

    def test_unsettled_is_never_safe_even_when_calm(self):
        self.assertEqual(self.hybrid(0.0).p_wrong(features(quiet_words=5, settled=False)), 1.0)


class HeuristicStillDefaultTest(unittest.TestCase):
    def test_extra_features_do_not_change_the_heuristic(self):
        a = HeuristicRisk().p_wrong(features(has_brand=True, last_slot="size", oldest_age=9))
        b = HeuristicRisk().p_wrong(features(has_brand=False, last_slot="brand", oldest_age=0))
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
