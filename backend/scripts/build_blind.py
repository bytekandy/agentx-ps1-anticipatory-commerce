"""Build data/dev_blind.jsonl from the hand-written requests in data/blind_requests.jsonl.

    cd backend && python scripts/build_blind.py
    python scripts/build_blind.py --src data/brutal_requests.jsonl --out data/dev_brutal.jsonl

Each request line holds id, text, filters, tags and a hand-labelled pinned_after: the 1-based word
index after which the words so far settle the target for good. This script splits the text into
words, finds the one catalogue product matching the filters, copies pinned_after into "earliest",
and writes the test set in the same format as dev.jsonl. Requests matching 0 or several products,
or with a bad pinned_after, are rejected and printed. Standard library only; deterministic.
"""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
SRC = BACKEND / "data" / "blind_requests.jsonl"
OUT = BACKEND / "data" / "dev_blind.jsonl"
CATALOGUE = BACKEND / "catalogue.csv"
FIELDS = ("category", "colour", "size", "brand")
FILTER_KEYS = FIELDS + ("max_price",)


def load_catalogue():
    with open(CATALOGUE, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["price"] = int(r["price"])
    return rows


def matching(catalogue, filters):
    hits = []
    for p in catalogue:
        if any(filters.get(f) is not None and p[f].lower() != str(filters[f]).lower() for f in FIELDS):
            continue
        if filters.get("max_price") is not None and p["price"] > filters["max_price"]:
            continue
        hits.append(p["product_id"])
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", default=str(SRC), help="hand-written requests (default data/blind_requests.jsonl)")
    ap.add_argument("--out", default=str(OUT), help="test set to write (default data/dev_blind.jsonl)")
    args = ap.parse_args()
    src, out = Path(args.src).resolve(), Path(args.out).resolve()
    catalogue = load_catalogue()
    with open(src, encoding="utf-8") as fh:
        requests = [json.loads(line) for line in fh if line.strip()]

    kept, rejected, seen = [], [], set()
    for req in requests:
        rid = req["id"]
        if rid in seen:
            rejected.append((rid, "duplicate id"))
            continue
        seen.add(rid)
        words = req["text"].split(" ")
        filters = {k: req["filters"].get(k) for k in FILTER_KEYS}
        unknown = set(req["filters"]) - set(FILTER_KEYS)
        if unknown:
            rejected.append((rid, f"unknown filter keys {sorted(unknown)}"))
            continue
        hits = matching(catalogue, filters)
        if len(hits) != 1:
            rejected.append((rid, f"{len(hits)} matching products" + (f" {hits[:6]}" if hits else "")))
            continue
        pinned = req.get("pinned_after")
        if not isinstance(pinned, int) or not 1 <= pinned <= len(words):
            rejected.append((rid, f"pinned_after {pinned!r} not in 1..{len(words)}"))
            continue
        kept.append({"id": rid, "text": req["text"], "words": words, "filters": filters,
                     "target": hits[0], "earliest": pinned, "tags": list(req.get("tags", []))})

    with open(out, "w", encoding="utf-8") as fh:
        for row in kept:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    for rid, reason in rejected:
        print(f"rejected {rid}: {reason}")
    tags = Counter(t for r in kept for t in r["tags"])
    tags["plain"] = sum(1 for r in kept if not r["tags"])
    print(f"kept {len(kept)}, rejected {len(rejected)}  ->  {out.name}")
    for tag, n in sorted(tags.items()):
        print(f"  {tag:16} {n}")
    return 0 if kept else 1


if __name__ == "__main__":
    sys.exit(main())
