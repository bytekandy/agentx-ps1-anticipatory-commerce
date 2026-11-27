"""Build `anticipatory/data/generated_lexicon.json`: synonyms taken from WordNet, not typed by hand.

    pip install -r requirements-build.txt          # nltk (build time only; the agent never imports it)
    python -c "import nltk; nltk.download('wordnet')"
    cd backend && python scripts/build_wordnet_lexicon.py [--check]

Why: the hand-written synonym tables in `lexicon.py` hold only the words someone thought of, and
part of them were read off dev.jsonl. WordNet (Princeton, a public-domain-style licence that allows
redistribution with its notice) lists the words English itself puts under the same meaning.

How: for each catalogue category and colour one WordNet meaning (a "synset") is named below, 32
small, checkable choices. The candidates are that meaning's own words plus its direct
specialisations ("sandal" gives flip-flop, huarache, espadrille; "blue" gives azure, cerulean,
royal blue). Then rules throw out the noisy ones:

  * a word whose commonest meaning is something else ("cherry" is a fruit tree, "ticker" a tape
    machine, "sack" a bag) is dropped: only words whose commonest noun meaning is one of the
    accepted ones stay;
  * a word that two of our values both claim ("shirt" and "jersey") is dropped;
  * a word that is already a catalogue colour, brand, or category name, or contains one of another
    value ("blue jean" would hide the colour blue) is dropped;
  * proper nouns, words with digits or apostrophes, and short words are dropped;
  * abstract "-ness" nouns ("blackness") and intensity phrases ("dark red", "light brown") are
    dropped: the shop has maroon next to red and tan next to brown, so "dark red" is not simply red;
  * `NOT_SOLD` lists garments WordNet files under a category that the shop does not sell as
    that category (a sari is not a dress), so they stay unknown instead of being answered wrongly.

The file records what was kept, its source and the seeds. The reader loads it at a lower
confidence than a hand-written synonym and never commits early on such a word (see
`Lexicon` and `Snapshot.guessed`): a wrong pairing can cost earliness, not a wrong commit.

`--check` rebuilds in memory and fails if the committed file differs (so it cannot drift).
Hindi and Hinglish words are NOT in WordNet and stay in the hand-written tables.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from anticipatory.lexicon import load_rows  # noqa: E402

OUT = BACKEND / "anticipatory" / "data" / "generated_lexicon.json"

# slot value -> (WordNet meaning, how many levels of specialisation to include)
CATEGORY_SEEDS = {
    "running shoes": ("running_shoe.n.01", 1),
    "sneakers": ("gym_shoe.n.01", 1),
    "sandals": ("sandal.n.01", 1),
    "t-shirts": ("jersey.n.03", 0),
    "shirts": ("shirt.n.01", 0),
    "jeans": ("jean.n.01", 0),
    "dresses": ("dress.n.01", 1),
    "kurtas": ("kurta.n.01", 0),
    "hoodies": ("sweatshirt.n.01", 0),
    "jackets": ("jacket.n.01", 1),
    "track pants": ("sweat_pants.n.01", 0),
    "backpacks": ("backpack.n.01", 0),
    "caps": ("cap.n.01", 1),
    "headphones": ("earphone.n.01", 0),
    "watches": ("watch.n.01", 1),
    "wallets": ("wallet.n.01", 0),
}
COLOUR_SEEDS = {
    "black": ("black.n.01", 1), "white": ("white.n.02", 1), "blue": ("blue.n.01", 1),
    "grey": ("gray.n.01", 1), "red": ("red.n.01", 1), "green": ("green.n.01", 1),
    "pink": ("pink.n.01", 1), "brown": ("brown.n.01", 1), "beige": ("beige.n.01", 0),
    "gold": ("amber.n.01", 0), "navy": ("dark_blue.n.01", 0), "maroon": ("maroon.n.02", 0),
    "olive": ("olive.n.05", 1), "yellow": ("yellow.n.01", 1), "tan": ("tan.n.02", 0),
}
# Words that WordNet puts under a category but that name something else in a shop: they must stay
# unknown (the agent then holds back) instead of being answered with the wrong product.
NOT_SOLD = frozenset({"sari", "saree", "caftan", "kaftan", "muumuu", "polonaise", "dirndl"})
INTENSITY = frozenset({"dark", "light", "deep", "pale", "bright", "dull"})
# silver has no clean WordNet meaning of its own (it hangs under grey), so it gets no seed.


def closure(synset, depth):
    found, level = {synset}, [synset]
    for _ in range(depth):
        level = [h for s in level for h in s.hyponyms()]
        found.update(level)
    return found


def candidates(seeds, wn) -> Dict[str, Dict[str, Set[str]]]:
    """value -> {lemma text: {the seed's synset name}} after the sense rule."""
    out: Dict[str, Set[str]] = {}
    for value, (name, depth) in seeds.items():
        accepted = closure(wn.synset(name), depth)
        words: Set[str] = set()
        for synset in accepted:
            for lemma in synset.lemmas():
                text = lemma.name()
                if "'" in text or any(c.isdigit() for c in text) or text[:1].isupper() \
                        and text.lower() != "t-shirt":
                    continue
                senses = wn.synsets(text, pos="n")
                if not senses or senses[0] not in accepted:      # commonest meaning must be ours
                    continue
                words.add(text.replace("_", " ").lower())
        out[value] = words
    return out


def build(wn) -> dict:
    rows = load_rows()
    categories = {r["category"] for r in rows}
    colours = {r["colour"] for r in rows}
    brands = {w for r in rows for w in r["brand"].lower().split()}
    own = {s: {w for v in vs for w in v.replace("-", " ").split()} for s, vs in
           (("category", categories), ("colour", colours))}
    names = {n.lower() for n in categories | colours}
    names |= {n + "s" for n in names} | {n[:-1] for n in names if n.endswith("s")}

    result = {}
    for slot, seeds in (("category", CATEGORY_SEEDS), ("colour", COLOUR_SEEDS)):
        cand = candidates(seeds, wn)
        claims: Dict[str, List[str]] = {}
        for value, words in cand.items():
            for w in words:
                claims.setdefault(w, []).append(value)
        kept = {}
        for value, words in cand.items():
            good = []
            for w in sorted(words):
                parts = w.replace("-", " ").split()
                if len(w) < 3 or len(claims[w]) > 1 or w in names or w in NOT_SOLD:
                    continue
                if w.endswith("ness") or parts[0] in INTENSITY:
                    continue
                if any(p in brands for p in parts):
                    continue
                # a word holding a catalogue colour hides that colour ("blue jean"); the family
                # word of the value itself is fine ("royal blue" is blue)
                other_colours = colours - {value}
                if slot == "category" and any(p in colours for p in parts):
                    continue
                if slot == "colour" and any(p in other_colours for p in parts):
                    continue
                if slot == "colour" and any(p in categories or p + "s" in categories for p in parts):
                    continue
                good.append(w)
            kept[value] = good
        result[slot] = kept
    seeds = {"category": {k: v[0] for k, v in CATEGORY_SEEDS.items()},
             "colour": {k: v[0] for k, v in COLOUR_SEEDS.items()}}
    return {"source": "Princeton WordNet 3.0 through nltk, built by scripts/build_wordnet_lexicon.py",
            "seeds": seeds, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if the committed file differs")
    args = parser.parse_args()
    from nltk.corpus import wordnet as wn
    data = build(wn)
    text = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    total = sum(len(v) for slot in ("category", "colour") for v in data[slot].values())
    if args.check:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("generated lexicon is up to date" if same else "generated lexicon DIFFERS")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({total} words)")
    for slot in ("category", "colour"):
        for value, words in data[slot].items():
            print(f"  {slot:8} {value:14} {len(words):3}  {', '.join(words[:12])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
