"""Measure slot extraction on dev.jsonl (Stage 3 exit check).

    cd backend
    python scripts/slot_accuracy.py            # summary tables
    python scripts/slot_accuracy.py --show 20  # also list up to 20 mismatching requests

Each request is read in full with `extract_mentions(final=True)` and the naive `latest_filters`
(last trusted mention per slot wins), then compared with the gold `filters` of the request.
There is no agent, no search and no early commit here. Corrections are expected to score lower,
because understanding them is Stage 4's job; the exit target is the *plain* requests.

This is an offline analysis script: the agent itself never reads dev.jsonl.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from anticipatory.lexicon import Lexicon  # noqa: E402
from anticipatory.slots import extract_mentions, latest_filters  # noqa: E402
from anticipatory.tokens import tokenize  # noqa: E402

SLOTS = ("category", "colour", "size", "brand", "max_price")
TARGET = 0.95


def load_dev(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def group_of(row):
    """Plain requests have no tag; others are listed under each of their tags."""
    return row["tags"] or ["plain"]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default=str(BACKEND / "dev.jsonl"))
    parser.add_argument("--show", type=int, default=0, help="list this many mismatching requests")
    args = parser.parse_args()

    lexicon = Lexicon.from_catalogue()
    rows = load_dev(args.data)

    slot_hits = defaultdict(lambda: defaultdict(int))     # group -> slot -> correct
    slot_total = defaultdict(int)                          # group -> requests
    exact = defaultdict(int)
    misses = []
    for row in rows:
        mentions = extract_mentions(tokenize(row["words"]), lexicon, final=True)
        read = latest_filters(mentions, lexicon)
        wrong = []
        for slot in SLOTS:
            ok = read.get(slot) == row["filters"].get(slot)
            for group in group_of(row) + ["all"]:
                slot_hits[group][slot] += ok
            if not ok:
                wrong.append((slot, row["filters"].get(slot), read.get(slot)))
        for group in group_of(row) + ["all"]:
            slot_total[group] += 1
            exact[group] += not wrong
        if wrong:
            misses.append((row, wrong))

    print(f"{'group':<18}{'requests':>9}{'slot acc':>10}{'all slots right':>17}   per slot")
    for group in ["plain", "correction", "late_constraint", "code_mixed", "all"]:
        n = slot_total[group]
        if not n:
            continue
        hits = sum(slot_hits[group].values())
        per_slot = "  ".join(f"{s}={slot_hits[group][s] / n:.1%}" for s in SLOTS)
        print(f"{group:<18}{n:>9}{hits / (n * len(SLOTS)):>10.1%}{exact[group] / n:>17.1%}   "
              f"{per_slot}")

    for row, wrong in misses[:args.show]:
        print(f"\n{row['id']} {row['tags']}\n  {row['text']}")
        for slot, gold, got in wrong:
            print(f"  {slot}: gold={gold!r} read={got!r}")

    plain = slot_hits["plain"]
    plain_acc = sum(plain.values()) / (slot_total["plain"] * len(SLOTS))
    print(f"\nplain slot accuracy {plain_acc:.1%} (target {TARGET:.0%}): "
          f"{'PASS' if plain_acc >= TARGET else 'FAIL'}")
    return 0 if plain_acc >= TARGET else 1


if __name__ == "__main__":
    sys.exit(main())
