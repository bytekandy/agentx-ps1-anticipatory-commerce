"""The orchestrator: reads each word, keeps the filter state, and acts through the policy.

    word -> FilterState.push -> CommitPolicy.step -> {wait | commit} + a trace record
    finish(): read the whole request again, verify with one search, answer

It implements the kit's agent interface (`start`, `observe`, `finish`). All thinking lives in
the modules below it; this class only wires them together and keeps the per-request memory.
"""
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import DEFAULT_CONFIG, Config
from .lexicon import Lexicon
from .policy import CatalogPort, CommitPolicy, allowed, search_filters
from .risk import HeuristicRisk, RiskModel
from .state import FilterState

# ---- the trace: one record per word, what the agent read, did and why (for debugging, the
# evaluation report, the UI and the demo video; plain data with `to_dict()` for JSON)

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


# When the full filters match nothing, relax them in this order (like the kit's baseline).
_RELAX_ORDER = ("min_price", "max_price", "size", "brand", "colour", "category")


class AnticipatoryAgent:
    def __init__(self, catalog: CatalogPort, config: Config = DEFAULT_CONFIG,
                 risk_model: Optional[RiskModel] = None, lexicon: Optional[Lexicon] = None,
                 on_trace: Optional[Callable[[TraceRecord], None]] = None):
        self.catalog = catalog
        self.config = config
        self.lexicon = lexicon or Lexicon.from_catalogue(config=config.vocab)
        self.state = FilterState(self.lexicon, config)
        self.policy = CommitPolicy(self.lexicon, risk_model or HeuristicRisk(config), config)
        self.on_trace = on_trace
        self.trace: List[TraceRecord] = []
        self.words: List[str] = []

    @property
    def unresolved(self):
        """What the shopper asked for that nothing in the shop answers to, as of the last word."""
        return list(self.state.snapshot.unresolved)

    # -- the kit's interface -----------------------------------------------------------------

    def start(self, request_id) -> None:
        self.request_id = request_id
        self.state.reset()
        self.policy.reset()
        self.trace = []
        self.words = []

    def observe(self, word: str) -> Optional[Dict[str, Any]]:
        self.words.append(word)
        snapshot = self.state.push(word)
        decision = self.policy.step(snapshot, self.catalog)
        record = TraceRecord(
            index=len(self.words), word=word, filters=snapshot.filters,
            confidence=snapshot.confidence, settled=snapshot.settled,
            correction_pending=snapshot.correction_pending,
            pending_slots=snapshot.pending_slots, searched=decision.searched,
            n_candidates=decision.n_candidates, action=decision.action,
            product_id=decision.product_id, risk=decision.risk, reason=decision.reason,
            unresolved=tuple(u.label() for u in snapshot.unresolved))
        self.trace.append(record)
        if self.on_trace:
            self.on_trace(record)
        out: Dict[str, Any] = {"filters": snapshot.filters, "confidence": snapshot.confidence}
        if decision.action == "commit":
            out["commit"] = decision.product_id
        return out

    def finish(self) -> Optional[str]:
        """Re-read the whole request, check it with a search, and return the final product."""
        snapshot = self.state.finish()
        filters = search_filters(snapshot, self.config)
        policy = self.policy

        # The commit (or the latest search) already checked these exact filters: no new search.
        last = allowed(policy.last_hits, snapshot.excluded)
        if filters == policy.last_filters and len(last) == 1:
            return last[0]["product_id"]

        query = " ".join(self.words)
        k = self.config.policy.final_k
        # Every value the shopper stated fits the target, so when nothing matches, something was
        # misread: most likely the value read least surely. Drop the weakest first; between equal
        # confidences keep the kit's order.
        order = sorted((slot for slot in filters),
                       key=lambda s: (snapshot.slots[s].confidence, _RELAX_ORDER.index(s)))
        while True:
            hits = allowed(self.catalog.find(filters, query, k), snapshot.excluded)
            if hits:
                return hits[0]["product_id"]
            if not order:
                return None
            droppable = order.pop(0)
            filters = {slot: v for slot, v in filters.items() if slot != droppable}
