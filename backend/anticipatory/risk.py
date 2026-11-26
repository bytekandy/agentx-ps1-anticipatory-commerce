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
from dataclasses import dataclass
from typing import Optional, Protocol

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
