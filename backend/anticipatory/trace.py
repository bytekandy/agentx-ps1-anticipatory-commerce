"""One record per word: what the agent read, what it did, and why.

Used for debugging, the evaluation report and, later, the UI and the demo video. Plain data
with `to_dict()` so it can be written as JSON.
"""
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class TraceRecord:
    index: int                              # 1-based position of the word
    word: str
    filters: Dict[str, Any]                 # the reading after this word
    confidence: float
    settled: bool
    correction_pending: bool
    pending_slots: Tuple[str, ...]
    searched: bool                          # a search was made after this word
    n_candidates: Optional[int]             # products that matched, if searched
    action: str                             # "wait" or "commit"
    product_id: Optional[str]               # set when committing
    risk: Optional[float]                   # the risk the policy weighed, if it got that far
    reason: str                             # a short human-readable why
    unresolved: Tuple[str, ...] = ()        # constraints we could not match, e.g. ("brand: nike",)

    def to_dict(self) -> Dict[str, Any]:
        record = asdict(self)
        record["pending_slots"] = list(self.pending_slots)
        record["unresolved"] = list(self.unresolved)
        return record
