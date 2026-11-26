"""The agent's only door to the product catalogue.

The agent depends on the small `CatalogPort` interface, not on the kit. At run time the adapter
`ToolsCatalog` forwards to the counted `tools.search` of the harness, so every lookup is a
search that costs points. Tests use `InMemoryCatalog`, which applies the same filter rules as
the kit's `search.py` over rows you give it and counts its calls the same way.

Reading `catalogue.csv` to build vocabularies is fine (see `lexicon.py`); looking products up
must go through this port.
"""
from typing import Any, Dict, Iterable, List, Optional, Protocol

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
