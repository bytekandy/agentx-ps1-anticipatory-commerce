"""How many plausible shop words does the reader understand? An outside check of the synonym lists.

    cd backend && python scripts/coverage_probe.py [--show-misses]

The 150 terms below were written once, before the WordNet lexicon existed, as words a shopper might
use for each catalogue value. They are NOT tuned against: do not add a word to a table because it
shows up here as a miss. About ten are deliberately ambiguous (ivory, khaki, "dark red") or not a
synonym at all ("blue jeans"), so 100% is not the goal; the number is for comparing versions.
A term counts as understood when the reader maps it, whole, to the expected value.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anticipatory.lexicon import Lexicon  # noqa: E402
from anticipatory.tokens import tokenize_text  # noqa: E402

TERMS = {
    ("category", "running shoes"): ["trainers", "kicks", "running trainers", "joggers shoes", "gym shoes", "sports trainers", "track shoes"],
    ("category", "sneakers"): ["sneaker", "canvas shoes", "casual trainers", "kicks", "plimsolls", "sneeks"],
    ("category", "sandals"): ["sandal", "flip-flops", "flipflops", "thongs", "strappy sandals", "open toe", "chappal", "slipper"],
    ("category", "t-shirts"): ["tees", "t shirts", "tshirts", "tee-shirt", "round neck tee", "polo"],
    ("category", "shirts"): ["shirt", "formal shirt", "button down", "button-down"],
    ("category", "jeans"): ["jean", "denim jeans", "denim pants", "blue jeans"],
    ("category", "dresses"): ["dress", "gown", "frocks", "one piece", "sundress"],
    ("category", "kurtas"): ["kurta", "kurti", "kurtis", "kurtha"],
    ("category", "hoodies"): ["hoodie", "hoody", "hooded jacket", "pullover", "jumper", "sweatshirts"],
    ("category", "jackets"): ["jacket", "windbreaker", "bomber", "blazer", "coat", "parka"],
    ("category", "track pants"): ["track pant", "trackpants", "jogger pants", "sweatpants", "lowers", "trackies", "joggers"],
    ("category", "backpacks"): ["backpack", "rucksack", "knapsack", "school bag", "bagpack", "daypack"],
    ("category", "caps"): ["cap", "baseball cap", "hat", "topi", "snapback"],
    ("category", "headphones"): ["headphone", "earphones", "earbuds", "headset", "over-ear", "airpods"],
    ("category", "watches"): ["watch", "wristwatch", "wrist watch", "timepiece", "smartwatch", "ghadi"],
    ("category", "wallets"): ["wallet", "purse", "billfold", "cardholder", "pocketbook"],
    ("colour", "black"): ["jet black", "kaala", "charcoal black", "onyx"],
    ("colour", "white"): ["off white", "snow white", "safed", "ivory", "cream white"],
    ("colour", "blue"): ["sky blue", "royal blue", "neela", "cobalt", "baby blue", "light blue"],
    ("colour", "grey"): ["gray", "charcoal", "ash grey", "silver grey", "slate"],
    ("colour", "red"): ["crimson", "lal", "scarlet", "cherry"],
    ("colour", "green"): ["hara", "emerald", "lime green", "mint"],
    ("colour", "pink"): ["gulabi", "rose", "hot pink", "blush"],
    ("colour", "brown"): ["bhura", "chocolate", "coffee", "mocha"],
    ("colour", "beige"): ["cream", "nude", "sand", "khaki", "off-white"],
    ("colour", "gold"): ["golden", "sunehri", "champagne"],
    ("colour", "navy"): ["navy blue", "dark blue", "midnight blue"],
    ("colour", "maroon"): ["burgundy", "wine", "oxblood", "dark red"],
    ("colour", "olive"): ["olive green", "army green", "khaki green"],
    ("size", "XL"): ["extra large", "xlarge", "x-large"],
    ("size", "M"): ["medium", "med"],
}


def understood(lexicon, term, slot, value):
    tokens = tokenize_text(term)
    match = lexicon.lookup(tokens, 0)
    if match and match.slot == slot and match.value == value and match.length == len(tokens):
        return True
    if len(tokens) == 1:                                   # another romanised spelling
        listed = lexicon.respell(tokens[0].text)
        match = listed and lexicon.lookup(tokenize_text(listed), 0)
        return bool(match and match.slot == slot and match.value == value)
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--show-misses", action="store_true")
    args = parser.parse_args(argv)
    lexicon = Lexicon.from_catalogue()
    total = hit = 0
    misses = []
    for (slot, value), terms in TERMS.items():
        for term in terms:
            total += 1
            if understood(lexicon, term, slot, value):
                hit += 1
            else:
                misses.append(f"{term} ({value})")
    print(f"understood {hit} of {total} ({hit / total:.0%})")
    if args.show_misses:
        print("missed:", ", ".join(misses))
    return 0


if __name__ == "__main__":
    sys.exit(main())
