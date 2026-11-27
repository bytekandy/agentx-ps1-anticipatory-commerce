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


# A second list, written AFTER the first and BEFORE any semantic model was tried, and used only to
# judge a choice made on the first list (the similarity threshold): the held-out probe.
HELD_OUT_TERMS = {
    ("category", "running shoes"): ["marathon shoes", "jogging footwear", "athletic shoes", "running footwear", "cross trainers"],
    ("category", "sneakers"): ["tennis shoes", "skate shoes", "everyday sneakers", "low tops", "high tops"],
    ("category", "sandals"): ["beach sandals", "sliders", "slip ons", "open sandals", "summer sandals", "chappals"],
    ("category", "t-shirts"): ["graphic tee", "crew neck", "tank top", "tshirt", "cotton tee"],
    ("category", "shirts"): ["dress shirt", "oxford shirt", "linen shirt", "collared shirt", "flannel"],
    ("category", "jeans"): ["denim trousers", "slim fit jeans", "straight jeans", "bootcut", "dungarees"],
    ("category", "dresses"): ["maxi dress", "party dress", "midi", "evening gown", "skirt dress"],
    ("category", "kurtas"): ["ethnic top", "kurta set", "festive kurta", "long kurti", "sherwani"],
    ("category", "hoodies"): ["zip up", "hooded top", "fleece hoodie", "hooded pullover", "pullovers"],
    ("category", "jackets"): ["leather jacket", "puffer", "rain jacket", "overcoat", "denim jacket"],
    ("category", "track pants"): ["gym pants", "workout pants", "jogging bottoms", "athletic pants", "lounge pants"],
    ("category", "backpacks"): ["laptop bag", "travel backpack", "hiking pack", "college bag", "satchel"],
    ("category", "caps"): ["baseball hat", "sun cap", "sports cap", "trucker cap", "peak cap"],
    ("category", "headphones"): ["over ear", "wireless headphones", "ear buds", "gaming headset", "neckband"],
    ("category", "watches"): ["wrist timepiece", "analog watch", "digital watch", "chronograph", "fitness watch"],
    ("category", "wallets"): ["card holder", "money clip", "billfold wallet", "leather wallet", "clutch"],
    ("colour", "black"): ["coal", "pitch black", "ebony", "raven"],
    ("colour", "white"): ["pearl white", "bone", "chalk", "milky"],
    ("colour", "blue"): ["azure", "sapphire", "turquoise", "sea blue", "indigo"],
    ("colour", "grey"): ["steel", "graphite", "smoky", "pewter", "stone grey"],
    ("colour", "red"): ["ruby", "tomato", "brick red", "fire engine red"],
    ("colour", "green"): ["forest", "sea green", "jade", "parrot green"],
    ("colour", "pink"): ["salmon", "magenta", "fuchsia", "baby pink"],
    ("colour", "brown"): ["chestnut", "cocoa", "walnut", "coffee brown"],
    ("colour", "beige"): ["buff", "oatmeal", "biscuit", "linen colour"],
    ("colour", "gold"): ["brass", "bronze", "mustard gold", "yellow gold"],
    ("colour", "navy"): ["deep navy", "naval blue", "marine blue", "ink blue"],
    ("colour", "maroon"): ["wine red", "claret", "mahogany", "deep red"],
    ("colour", "olive"): ["moss green", "khaki", "military green", "dark olive"],
    ("colour", "yellow"): ["lemon", "sunflower", "banana", "golden yellow"],
    ("colour", "silver"): ["metallic", "chrome", "platinum", "steel silver"],
    ("colour", "tan"): ["camel", "sand brown", "caramel", "light tan"],
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


def read_as(lexicon, term, slot, value):
    """What the whole reader (lists, WordNet file, word vectors) makes of the term on its own:
    "listed", "semantic" (a guess from the word-vector model) or None."""
    from anticipatory.slots import read_words
    tokens = tokenize_text(term)
    for m in read_words(tokens, lexicon, final=True).mentions:
        if m.slot == slot and m.value == value:
            return "semantic" if m.kind == "semantic" else "listed"
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--show-misses", action="store_true")
    parser.add_argument("--held-out", action="store_true", help="use the second, held-out list")
    args = parser.parse_args(argv)
    lexicon = Lexicon.from_catalogue()
    total = hit = guessed = wrong = 0
    misses = []
    for (slot, value), terms in (HELD_OUT_TERMS if args.held_out else TERMS).items():
        for term in terms:
            total += 1
            how = read_as(lexicon, term, slot, value)
            if how == "listed" or (how is None and understood(lexicon, term, slot, value)):
                hit += 1
            elif how == "semantic":
                guessed += 1
            else:
                misses.append(f"{term} ({value})")
                from anticipatory.slots import read_words
                other = [m for m in read_words(tokenize_text(term), lexicon, final=True).mentions
                         if m.kind == "semantic" and m.slot == slot]
                wrong += bool(other)
    print(f"understood from lists {hit} of {total} ({hit / total:.0%}); "
          f"right by the word-vector guess {guessed}; wrong by the word-vector guess {wrong}; "
          f"left unknown {total - hit - guessed - wrong}")
    if args.show_misses:
        print("missed:", ", ".join(misses))
    return 0


if __name__ == "__main__":
    sys.exit(main())
