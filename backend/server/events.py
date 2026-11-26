"""The shapes of what the interface sends, and the product directory.

Every event is a plain dict with `type` and `version`, so it is the same JSON on the wire and in
Python. See `docs/stream-contract.md` for the full description of each.
"""
import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from anticipatory.trace import TraceRecord

VERSION = 1
BACKEND = Path(__file__).resolve().parents[1]


class ProductDirectory:
    """Read-only product details for display (title, brand, price...).

    This is for the UI only. The agent never uses it: the agent finds products through the
    counted search tool, as the competition requires.
    """

    def __init__(self, rows: Iterable[Dict[str, str]]):
        self._by_id = {r["product_id"]: self._shape(r) for r in rows}

    @classmethod
    def from_catalogue(cls, path: Optional[Path] = None) -> "ProductDirectory":
        with open(path or BACKEND / "catalogue.csv", newline="", encoding="utf-8") as fh:
            return cls(csv.DictReader(fh))

    @staticmethod
    def _shape(row: Dict[str, str]) -> Dict[str, Any]:
        return {"product_id": row["product_id"], "title": row["title"], "brand": row["brand"],
                "category": row["category"], "colour": row["colour"], "size": row["size"] or None,
                "price": int(row["price"]), "description": row.get("description", "")}

    def get(self, product_id: Optional[str]) -> Optional[Dict[str, Any]]:
        return self._by_id.get(product_id) if product_id else None

    def __len__(self) -> int:
        return len(self._by_id)


def start_event(agent: str, request_id: Any, text: Optional[str] = None,
                words: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "start", "version": VERSION, "agent": agent, "request_id": request_id,
            "text": text, "words": words}


def word_event(record: TraceRecord, commit: Optional[Dict[str, Any]],
               committed: Optional[Dict[str, Any]], searches: int) -> Dict[str, Any]:
    """One per word: the agent's full trace record.

    `commit` is set only on the word where the agent commits; `committed` is set on that word
    and every later one, so the latest event alone tells a client whether and where it committed.
    """
    return {"type": "word", "version": VERSION, "seq": record.index, "word": record.word,
            "trace": record.to_dict(), "commit": commit, "committed": committed,
            "searches": searches}


def final_event(words: int, final_id: Optional[str], product: Optional[Dict[str, Any]],
                filters: Dict[str, Any], unresolved: List[str], commit: Optional[Dict[str, Any]],
                searches: int, evaluation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"type": "final", "version": VERSION, "words": words, "final_product_id": final_id,
            "product": product, "filters": filters, "unresolved": unresolved, "commit": commit,
            "searches": searches, "evaluation": evaluation}


def error_body(code: str, message: str) -> Dict[str, Any]:
    return {"error": {"code": code, "message": message}}


class ServiceError(Exception):
    """A problem the client caused, with the HTTP status it maps to."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def body(self) -> Dict[str, Any]:
        return error_body(self.code, self.message)
