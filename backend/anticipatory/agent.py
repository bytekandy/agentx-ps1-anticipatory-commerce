"""The orchestrator: reads each word, keeps the filter state, and acts through the policy.

    word -> FilterState.push -> CommitPolicy.step -> {wait | commit} + a trace record
    finish(): read the whole request again, verify with one search, answer

It implements the kit's agent interface (`start`, `observe`, `finish`). All thinking lives in
the modules below it; this class only wires them together and keeps the per-request memory.
"""
from typing import Any, Callable, Dict, List, Optional

from .catalog_port import CatalogPort, ToolsCatalog
from .config import DEFAULT_CONFIG, Config
from .lexicon import Lexicon
from .policy import CommitPolicy, search_filters
from .risk import HeuristicRisk, RiskModel
from .state import FilterState
from .trace import TraceRecord

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
        if filters == policy.last_filters and len(policy.last_hits) == 1:
            return policy.last_hits[0]["product_id"]

        query = " ".join(self.words)
        k = self.config.policy.final_k
        while True:
            hits = self.catalog.find(filters, query, k)
            if hits:
                return hits[0]["product_id"]
            droppable = next((slot for slot in _RELAX_ORDER if slot in filters), None)
            if droppable is None:
                return None
            filters = {slot: v for slot, v in filters.items() if slot != droppable}
