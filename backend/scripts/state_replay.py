"""Replay dev.jsonl word by word through the filter state (Stage 4 exit check).

    cd backend
    python scripts/state_replay.py            # summary
    python scripts/state_replay.py --show 10  # also list up to 10 requests read wrongly

Each request is fed to `FilterState` one word at a time, exactly as the agent will receive it,
and the reading after the last word (`finish()`) is compared with the gold `filters`. No
agent, no search and no early commit here. It also reports signals the decision policy will
rely on:

  * false alarms: words at which `correction_pending` was raised in a request that has no
    correction (expected: only the short "no more than" ambiguity);
  * announced revisions: revisions that follow a correction marker;
  * exposure: how many words a value that is later replaced stayed visible before the first
    marker warned about it. A policy that holds a new value for N words covers every
    revision whose exposure is at most N.

This is an offline analysis script: the agent itself never reads dev.jsonl.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from anticipatory.lexicon import Lexicon  # noqa: E402
from anticipatory.state import FilterState  # noqa: E402

SLOTS = ("category", "colour", "size", "brand", "max_price")
TARGET = 0.95


def load_dev(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def group_of(row):
    return row["tags"] or ["plain"]


def replay(state, words):
    """Feed the words one by one; return the per-word snapshots and the final one."""
    state.reset()
    snapshots = [state.push(w) for w in words]
    return snapshots, state.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default=str(BACKEND / "dev.jsonl"))
    parser.add_argument("--show", type=int, default=0, help="list this many wrong requests")
    args = parser.parse_args()

    state = FilterState(Lexicon.from_catalogue())
    rows = load_dev(args.data)

    right = Counter()
    total = Counter()
    wrong_rows = []
    false_alarm_words = Counter()          # group -> words with correction_pending
    false_alarm_requests = Counter()
    revisions = Counter()                  # "marked" / "unmarked"
    exposure = Counter()
    for row in rows:
        snapshots, final = replay(state, row["words"])
        ok = all(final.filters[s] == row["filters"][s] for s in SLOTS)
        for group in group_of(row) + ["all"]:
            total[group] += 1
            right[group] += ok
        if not ok:
            wrong_rows.append((row, final.filters))

        if "correction" not in row["tags"]:
            alarms = sum(s.correction_pending for s in snapshots)
            false_alarm_words["non-correction"] += alarms
            false_alarm_requests["non-correction"] += bool(alarms)
        for belief in final.slots.values():
            if belief.revisions:
                revisions["marked" if belief.marked else "unmarked"] += 1
                markers_before = [m for m in final.markers if m.end <= belief.start]
                if markers_before:
                    old_end = belief.history[-1][2]
                    exposure[max(0, markers_before[-1].start - old_end)] += 1

    print(f"{'group':<18}{'requests':>9}{'read right':>12}")
    for group in ["plain", "correction", "late_constraint", "code_mixed", "all"]:
        if total[group]:
            print(f"{group:<18}{total[group]:>9}{right[group] / total[group]:>12.1%}")

    print(f"\nrevisions: {dict(revisions)}")
    print("exposure (words a later-replaced value was shown before the marker): "
          f"{dict(sorted(exposure.items()))}")
    print(f"false alarms in requests without a correction: "
          f"{false_alarm_requests['non-correction']} requests, "
          f"{false_alarm_words['non-correction']} words with correction_pending")

    for row, got in wrong_rows[:args.show]:
        print(f"\n{row['id']} {row['tags']}\n  {row['text']}")
        for slot in SLOTS:
            if got[slot] != row["filters"][slot]:
                print(f"  {slot}: gold={row['filters'][slot]!r} read={got[slot]!r}")

    both = right["plain"] + right["correction"]
    n = total["plain"] + total["correction"]
    rate = both / n
    print(f"\nplain + correction read right at the last word: {rate:.1%} "
          f"(target {TARGET:.0%}): {'PASS' if rate >= TARGET else 'FAIL'}")
    return 0 if rate >= TARGET else 1


if __name__ == "__main__":
    sys.exit(main())
