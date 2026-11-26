"""Check how well the reader understands dev.jsonl (offline; the agent itself never reads dev).

    cd backend
    python scripts/check_reader.py slots            # slot extraction on whole requests
    python scripts/check_reader.py slots --show 20  # also list up to 20 mismatching requests
    python scripts/check_reader.py state            # the filter state, word by word
    python scripts/check_reader.py state --show 10  # also list up to 10 requests read wrongly

slots: each request is read in full (`extract_mentions(final=True)`, last trusted mention per slot
wins) and compared with the gold `filters`. There is no agent, no search, no early commit.
Corrections score lower here, because understanding them is the filter state's job.

state: each request is fed to `FilterState` one word at a time, as the agent receives it, and the
reading after the last word is compared with the gold `filters`. It also reports false alarms of
`correction_pending`, announced revisions and exposure (how many words a value that is later
replaced stayed visible before the first marker warned about it).
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from anticipatory.lexicon import Lexicon  # noqa: E402
from anticipatory.slots import extract_mentions, latest_filters  # noqa: E402
from anticipatory.state import FilterState  # noqa: E402
from anticipatory.tokens import tokenize  # noqa: E402

SLOTS = ("category", "colour", "size", "brand", "max_price")
TARGET = 0.95

def load_dev(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def group_of(row):
    """Plain requests have no tag; others are listed under each of their tags."""
    return row["tags"] or ["plain"]


def slots_main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default=str(BACKEND / "dev.jsonl"))
    parser.add_argument("--show", type=int, default=0, help="list this many mismatching requests")
    args = parser.parse_args(argv)

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


def replay(state, words):
    """Feed the words one by one; return the per-word snapshots and the final one."""
    state.reset()
    snapshots = [state.push(w) for w in words]
    return snapshots, state.finish()


def state_main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default=str(BACKEND / "dev.jsonl"))
    parser.add_argument("--show", type=int, default=0, help="list this many wrong requests")
    args = parser.parse_args(argv)

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


def main():
    commands = {"slots": slots_main, "state": state_main}
    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        sys.exit("usage: python scripts/check_reader.py {slots|state} [--show N] [--data FILE]")
    commands[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
