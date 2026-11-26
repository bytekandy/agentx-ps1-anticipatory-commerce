"""Teach the agent words from logged requests (offline; the agent never writes).

    cd backend
    python scripts/learn_lexicon.py requests.jsonl            # update anticipatory/data/learned_lexicon.json
    python scripts/learn_lexicon.py requests.jsonl --out /tmp/learned.json --show

Each line of the log is {"text": "..."} or {"words": [...]}, and optionally "product_id" when the
shopper accepted a product. Evidence: a correction ("sliders, I mean sandals") and an accepted
product (see `anticipatory/learned.py`). A word is used by the agent after 2 agreeing observations.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from anticipatory.learned import LearnedStore, learn_from_request  # noqa: E402
from anticipatory.lexicon import Lexicon, load_rows  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="the learned lexicon file (default: the one the agent reads)")
    ap.add_argument("--show", action="store_true", help="print the words that are in use afterwards")
    args = ap.parse_args(argv)
    rows = load_rows()
    by_id = {r["product_id"]: r for r in rows}
    lexicon = Lexicon(rows)                       # the catalogue alone: what counts as "unknown"
    store = LearnedStore(args.out)
    seen = 0
    for line in args.log.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        words = item.get("words") or item.get("text", "").split()
        seen += len(learn_from_request(words, lexicon, store, by_id.get(item.get("product_id"))))
    store.save()
    print(f"{seen} observations; {len(store.active())} words in use -> {store.path}")
    if args.show:
        for word, (slot, value) in sorted(store.active().items()):
            print(f"  {word} = {slot}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
