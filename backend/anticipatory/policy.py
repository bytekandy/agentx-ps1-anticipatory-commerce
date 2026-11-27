"""The door to the catalogue, and when to search and when to commit.

Part 1 is `CatalogPort`: the agent's only way to look products up (counted searches), with a
stand-in for tests. Part 2 is the commit policy.

The agent is rewarded for committing early and punished hard for committing wrongly, so the
default action is always "wait". A commit needs all of these:

  1. the state is settled (no correction on its way, no number still growing), and no value
     in it was guessed (a number with no cue, a spell-corrected word);
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
from typing import Any, Dict, Iterable, List, Optional, Protocol

from .config import DEFAULT_CONFIG, Config
from .lexicon import Lexicon
from .risk import RiskInput, RiskModel
from .state import Snapshot


# ---- the catalogue port: reading catalogue.csv to build vocabularies is fine (`lexicon.py`);
# looking products up must go through this port. At run time `ToolsCatalog` forwards to the counted
# `tools.search` of the harness; tests use `InMemoryCatalog`, which applies the same filter rules as
# the kit's search.py and counts its calls the same way.

Product = Dict[str, Any]
Filters = Dict[str, Any]

_EXACT_FIELDS = ("category", "colour", "size", "brand")


class CatalogPort(Protocol):
    def find(self, filters: Filters, query: str = "", k: int = 10) -> List[Product]:
        """Products that pass every filter, best match for `query` first. One counted search."""


def clean_filters(filters: Optional[Filters]) -> Filters:
    """Drop empty values; the kit's search rejects nothing but ignores None."""
    return {key: value for key, value in (filters or {}).items() if value is not None}


class ToolsCatalog:
    """Adapter over the harness `tools` object (`tools.search` counts every call)."""

    def __init__(self, tools):
        self._tools = tools

    def find(self, filters: Filters, query: str = "", k: int = 10) -> List[Product]:
        return self._tools.search(query, clean_filters(filters), k)


class InMemoryCatalog:
    """A stand-in catalogue for tests, with the kit's filter semantics and a call counter."""

    def __init__(self, rows: Iterable[Product]):
        self.rows = [dict(r, price=int(r["price"])) for r in rows]
        self.searches = 0

    def find(self, filters: Filters, query: str = "", k: int = 10) -> List[Product]:
        self.searches += 1
        filters = clean_filters(filters)
        want = {key: str(filters[key]).lower() for key in _EXACT_FIELDS if key in filters}
        words = set(query.lower().split())
        hits = []
        for row in self.rows:
            if any(row[key].lower() != value for key, value in want.items()):
                continue
            if "max_price" in filters and row["price"] > filters["max_price"]:
                continue
            if "min_price" in filters and row["price"] < filters["min_price"]:
                continue
            overlap = len(words & set(row["title"].lower().replace(",", "").split()))
            hits.append((-overlap, row["price"], row))
        hits.sort(key=lambda h: h[:2])
        return [dict(row) for _, _, row in hits[:k]]


# ---- the commit policy


def break_even_risk(words_saved: int, config: Config = DEFAULT_CONFIG) -> float:
    """The highest P(wrong) at which committing `words_saved` words earlier still pays."""
    cfg = config.policy
    gain = cfg.earliness_weight * words_saved / cfg.avg_request_words
    forfeited = cfg.earliness_weight * cfg.forfeit_share
    return gain / (1.0 + gain + forfeited)


def allowed(hits: List[Product], excluded) -> List[Product]:
    """The hits that have none of the values the shopper ruled out ("not a t-shirt")."""
    return [h for h in hits
            if not any(str(h.get(slot, "")).lower() == str(value).lower() for slot, value in excluded)]


def search_filters(snapshot: Snapshot, config: Config = DEFAULT_CONFIG) -> Dict[str, Any]:
    """The filters a search should use: every belief that is trusted enough."""
    floor = config.policy.min_search_confidence
    return {slot: belief.value for slot, belief in snapshot.slots.items()
            if belief.confidence >= floor}


def blocked_reason(snapshot: Snapshot, filters: Dict[str, Any], lexicon: Lexicon) -> Optional[str]:
    """Why no commit is possible yet, or None if the gates are open."""
    if snapshot.unresolved:
        words = ", ".join(u.label() for u in snapshot.unresolved)
        return f"not understood, so no early commit: {words}"
    if not snapshot.settled:
        return "unsettled: correction pending, number still growing or a cue awaiting its number"
    if snapshot.guessed:
        # A hard rule, not left to the risk model: in a calm state the learned model barely
        # weighs confidence, so a weak guess could otherwise slip under the break-even risk.
        return f"guessed, so no early commit: {', '.join(snapshot.guessed)}"
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
        hits = allowed(self.last_hits, snapshot.excluded)
        count = len(hits)
        if count != 1:
            return Decision("wait", f"{count} products match", risk=risk, searched=searched,
                            n_candidates=count)
        product_id = hits[0]["product_id"]
        self.committed = product_id
        return Decision("commit", "one product matches and the risk is low", product_id, risk,
                        searched, count)
