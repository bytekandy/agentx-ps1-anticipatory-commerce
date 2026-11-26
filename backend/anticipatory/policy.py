"""When to search and when to commit.

The agent is rewarded for committing early and punished hard for committing wrongly, so the
default action is always "wait". A commit needs all of these:

  1. the state is settled (no correction on its way, no number still growing);
  2. the category is known, and for categories with sizes the size is known too, because until
     then no single product can match (a vocabulary-level fact, not a catalogue peek);
  3. the risk model says the chance of being wrong is below the break-even risk;
  4. a search with the current filters returns exactly one product.

The break-even risk comes from the score formula. Committing `w` words earlier gains
`0.6 * w / N` points; a wrong commit loses 1.0 plus the earliness it forfeits. So commit when

    P(wrong) < gain / (1 + gain + forfeited)

which is about 4 percent for one word saved and about 14 percent for four.

Searches are not free (the first is, each extra costs 0.02), so a search is made only when it
could lead to a commit: the gates above pass, the risk of committing to a unique match is low
enough, and the filters changed since the last search.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .catalog_port import CatalogPort
from .config import DEFAULT_CONFIG, Config
from .lexicon import Lexicon
from .risk import RiskInput, RiskModel
from .state import Snapshot


def break_even_risk(words_saved: int, config: Config = DEFAULT_CONFIG) -> float:
    """The highest P(wrong) at which committing `words_saved` words earlier still pays."""
    cfg = config.policy
    gain = cfg.earliness_weight * words_saved / cfg.avg_request_words
    forfeited = cfg.earliness_weight * cfg.forfeit_share
    return gain / (1.0 + gain + forfeited)


def search_filters(snapshot: Snapshot, config: Config = DEFAULT_CONFIG) -> Dict[str, Any]:
    """The filters a search should use: every belief that is trusted enough."""
    floor = config.policy.min_search_confidence
    return {slot: belief.value for slot, belief in snapshot.slots.items()
            if belief.confidence >= floor}


def blocked_reason(snapshot: Snapshot, filters: Dict[str, Any], lexicon: Lexicon) -> Optional[str]:
    """Why no commit is possible yet, or None if the gates are open."""
    if not snapshot.settled:
        return "unsettled: correction pending or number still growing"
    category = filters.get("category")
    if category is None:
        return "category not known"
    if lexicon.category_has_sizes(category) and "size" not in filters:
        return "size not known"
    return None


@dataclass(frozen=True)
class Decision:
    action: str                         # "wait" or "commit"
    reason: str
    product_id: Optional[str] = None
    risk: Optional[float] = None
    searched: bool = False
    n_candidates: Optional[int] = None


class CommitPolicy:
    """Decides, after every word, whether to search and whether to commit. One per request."""

    def __init__(self, lexicon: Lexicon, risk_model: RiskModel, config: Config = DEFAULT_CONFIG):
        self.lexicon = lexicon
        self.risk_model = risk_model
        self.config = config
        self.budget = break_even_risk(config.policy.words_saved_assumed, config)
        self.reset()

    def reset(self) -> None:
        self.committed: Optional[str] = None            # product id committed to, if any
        self.last_filters: Optional[Dict[str, Any]] = None       # filters of the latest search
        self.last_hits: List[Dict[str, Any]] = []                # and what it returned

    def step(self, snapshot: Snapshot, catalog: CatalogPort) -> Decision:
        if self.committed:
            return Decision("wait", "already committed")
        filters = search_filters(snapshot, self.config)
        blocked = blocked_reason(snapshot, filters, self.lexicon)
        if blocked:
            return Decision("wait", blocked)

        # Even if exactly one product matches, is committing safe enough to be worth a search?
        risk = self.risk_model.p_wrong(RiskInput.from_snapshot(snapshot, filters, None))
        if risk > self.budget:
            return Decision("wait", f"risk {risk:.2f} above break-even {self.budget:.2f}", risk=risk)

        searched = filters != self.last_filters
        if searched:
            self.last_hits = catalog.find(filters, "", self.config.policy.candidate_k)
            self.last_filters = dict(filters)
        count = len(self.last_hits)
        if count != 1:
            return Decision("wait", f"{count} products match", risk=risk, searched=searched,
                            n_candidates=count)
        product_id = self.last_hits[0]["product_id"]
        self.committed = product_id
        return Decision("commit", "one product matches and the risk is low", product_id, risk,
                        searched, count)
