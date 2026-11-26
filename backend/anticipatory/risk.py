"""How likely is a commit to be wrong? The `RiskModel` interface and the first estimate.

The commit policy asks one question: "if I commit to the single product that matches what I
have heard, what is the probability that the finished request points somewhere else?" Anything
that answers it can be plugged in behind `RiskModel`. This stage ships a hand-coded
`HeuristicRisk`; Stage 6 adds a learned model that must be calibrated against it.

Rules every implementation follows
  * Return a probability between 0 and 1. Higher means more dangerous.
  * An unsettled state (a correction is on its way, or a number is still growing) is never
    safe: the answer is at least `RiskConfig.unsettled_risk`.
  * `n_candidates=None` means "assume the best case, exactly one match". The policy uses it to
    decide whether a search is worth making before it spends one.
"""
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Sequence

from .config import DEFAULT_CONFIG, Config
from .state import Snapshot


@dataclass(frozen=True)
class RiskInput:
    """What a risk model may look at. Plain numbers and flags, so a model is easy to train."""
    words_seen: int
    quiet_words: int                # words since the last mention ended
    at_clause_end: bool             # the last word ended with , . ; ! ?
    settled: bool                   # no correction pending, no number still growing
    slots_used: int                 # how many filters the search uses
    weakest_confidence: float       # of the beliefs the search uses (1.0 if none)
    revisions: int                  # corrections already applied in this request
    markers: int                    # correction markers heard so far
    n_candidates: Optional[int]     # products matching now; None = assume exactly one
    # How complete the request looks: a shopper who has given brand, size and budget is
    # probably nearly done, one who has given only a category is not. Added for Stage 6.
    has_brand: bool = False
    has_size: bool = False
    has_price: bool = False
    oldest_age: int = 0             # words since the oldest value the search uses ended
    last_slot: str = ""             # the slot mentioned most recently ("" if none)

    @classmethod
    def from_snapshot(cls, snapshot: Snapshot, used_slots,
                      n_candidates: Optional[int] = None) -> "RiskInput":
        beliefs = [snapshot.slots[s] for s in used_slots if s in snapshot.slots]
        return cls(
            words_seen=snapshot.words_seen,
            quiet_words=snapshot.quiet_words,
            at_clause_end=snapshot.at_clause_end,
            settled=snapshot.settled,
            slots_used=len(beliefs),
            weakest_confidence=min((b.confidence for b in beliefs), default=1.0),
            revisions=sum(b.revisions for b in beliefs),
            markers=len(snapshot.markers),
            n_candidates=n_candidates,
            has_brand="brand" in snapshot.slots,
            has_size="size" in snapshot.slots,
            has_price="max_price" in snapshot.slots or "min_price" in snapshot.slots,
            oldest_age=max((snapshot.words_seen - b.end for b in beliefs), default=0),
            last_slot=max(beliefs, key=lambda b: b.end).slot if beliefs else "",
        )


class RiskModel(Protocol):
    def p_wrong(self, features: RiskInput) -> float:
        """Probability that committing now ends up pointing at the wrong product."""


class HeuristicRisk:
    """Hand-coded estimate from the Stage 1 and Stage 4 findings on dev.

    * Corrections follow the value they replace within one to three words, so a mention that
      is still fresh is dangerous (`hold_words`, `fresh_penalty`).
    * A pause right after the last word (a comma or period) is where corrections begin
      (`clause_end_penalty`).
    * A weakly read value (a synonym, a misspelt brand, an unmarked revision) is more likely
      to be wrong (`confidence_weight`).
    * An unsettled state is never safe.

    It cannot see a correction that targets an old slot long after it was mentioned ("... size
    L, from Loomsy, sorry, I meant size M"); closing that gap is what the learned model is for.
    """

    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.cfg = config.risk

    def p_wrong(self, features: RiskInput) -> float:
        cfg = self.cfg
        if not features.settled:
            return cfg.unsettled_risk
        risk = cfg.base_risk + (1.0 - features.weakest_confidence) * cfg.confidence_weight
        if features.quiet_words < cfg.hold_words:
            risk += cfg.fresh_penalty
        if features.at_clause_end:
            risk += cfg.clause_end_penalty
        return min(1.0, risk)


# ----------------------------------------------------------------------------- learned model

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "data" / "risk_model.json"
_SLOTS = ("category", "colour", "brand", "size", "max_price")


def risk_features(f: RiskInput) -> Dict[str, float]:
    """The numbers a risk model sees, by name. Training and runtime share this function.

    Mostly yes/no flags and small buckets, so identical states group together and the model
    stays tiny and easy to explain.
    """
    q = f.quiet_words
    x: Dict[str, float] = {"bias": 1.0}
    for bucket in (0, 1, 2):
        x[f"quiet={bucket}"] = float(q == bucket)               # 3 or more words is the baseline
    x["clause_end"] = float(f.at_clause_end)
    x["clause_end*quiet=0"] = float(f.at_clause_end and q == 0)
    x["conf_gap"] = 1.0 - f.weakest_confidence
    x["revised"] = float(f.revisions > 0)
    x["marker_seen"] = float(f.markers > 0)
    x["slots_used"] = f.slots_used / 5.0
    x["has_brand"] = float(f.has_brand)
    x["has_size"] = float(f.has_size)
    x["has_price"] = float(f.has_price)
    x["has_all_three"] = float(f.has_brand and f.has_size and f.has_price)
    for slot in _SLOTS:
        x[f"last={slot}"] = float(f.last_slot == slot)
    x["words_seen"] = min(f.words_seen, 25) / 25.0
    x["oldest_age"] = min(f.oldest_age, 15) / 15.0
    x["oldest_age>=4"] = float(f.oldest_age >= 4)
    return x


FEATURE_NAMES = tuple(risk_features(RiskInput(0, 0, False, True, 0, 1.0, 0, 0, 1)))


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


class LearnedRisk:
    """Logistic regression over `risk_features`, trained offline (`scripts/train_risk.py`).

    Standard library only: the weights are a small JSON file next to the code. The one rule
    kept from the hand-coded model is that an unsettled state is never safe: a correction on
    its way or a number still growing is not something a probability should talk away.
    """

    def __init__(self, weights: Dict[str, float], config: Config = DEFAULT_CONFIG,
                 multiplier: float = 1.0):
        unknown = set(weights) - set(FEATURE_NAMES)
        if unknown:
            raise ValueError(f"model has features this code does not know: {sorted(unknown)}")
        self.weights = dict(weights)
        self.config = config
        configured = config.learned.safety_multiplier
        self.multiplier = multiplier if configured is None else configured

    @classmethod
    def from_file(cls, path: Optional[Path] = None, config: Config = DEFAULT_CONFIG) -> "LearnedRisk":
        with open(path or DEFAULT_MODEL_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        multiplier = float(data.get("meta", {}).get("safety_multiplier", 1.0))
        return cls(dict(zip(data["features"], data["weights"])), config, multiplier)

    def probability(self, features: RiskInput) -> float:
        x = risk_features(features)
        return sigmoid(sum(self.weights.get(name, 0.0) * value for name, value in x.items()))

    def p_wrong(self, features: RiskInput) -> float:
        if not features.settled:
            return self.config.risk.unsettled_risk
        return min(1.0, self.probability(features) * self.multiplier)
