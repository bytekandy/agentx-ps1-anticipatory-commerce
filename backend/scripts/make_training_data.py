"""Synthetic shopper requests for training the risk model (Stage 6).

    cd backend
    python scripts/make_training_data.py --count 5 --seed 1      # print a few examples

A request is built from a random catalogue product: pick the filters that identify it, render
each as a phrase (synonyms, number words, "Rs.", sizes as "UK 9" or "M size", Hindi words),
add an opener and a filler tail, then optionally inject the two things that make early commits
risky: a correction (about 18 percent of requests; the wrong value, a marker, the right value,
either at once or after other content) and a late constraint ("oh, and from Pacevo").

The phrasing patterns and rates were read off dev.jsonl by hand (opener list, marker words,
the 58/42 split between immediate and delayed corrections, slot mix of corrections). No dev
request is copied, and dev is never used for training: it is the held-out check.

`build_examples` replays a request word by word through the real state and policy gates and
labels every prefix where the agent could commit to a single product: label 1 if that product
is not the request's target. Those rows are what the risk model learns from.
"""
import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from anticipatory.policy import InMemoryCatalog  # noqa: E402
from anticipatory.config import DEFAULT_CONFIG  # noqa: E402
from anticipatory.lexicon import (CATEGORY_SYNONYMS, COLOUR_SYNONYMS, SIZE_SYNONYMS,  # noqa: E402
                                  Lexicon, load_rows)
from anticipatory.policy import blocked_reason, search_filters  # noqa: E402
from anticipatory.risk import RiskInput  # noqa: E402
from anticipatory.state import FilterState  # noqa: E402

# ----------------------------------------------------------------------------- phrase pools

OPENERS = ["hey, do you have any", "hi, I want", "do you have", "can you find me",
           "I'm looking for", "looking for", "show me", "get me", "I need", "I'd like",
           "I want", "can you show me", "please find", ""]
HINDI_OPENERS = ["kya aapke paas", "mere liye", "bhaiya, dikhao", "dikhao", "mujhe chahiye",
                 "ek uh"]
TAILS = ["for a wedding", "please", "for office", "if you have it", "need it this week",
         "for my dad", "for the gym", "for my brother", "thanks", "as a gift",
         "nothing too flashy", "thank you", "", "", ""]
HINDI_TAILS = ["chahiye", "hai kya?", "dikhao na", "chahiye please", "milega?"]
FILLERS = ["uh", "um", "hmm", "ek"]

PRICE_CUES = ["under", "below", "less than", "max", "not more than", "within", "budget",
              "up to", "upto", "no more than", "budget of", "cheaper than"]
PRICE_CUE_WEIGHTS = [20, 14, 10, 10, 9, 8, 8, 5, 2, 3, 3, 1]

MARKERS = [("oops,", 3), ("sorry,", 9), ("no no,", 5), ("no, change that to", 6),
           ("wait, I meant", 6), ("actually, make it", 4), ("or rather", 3), ("make that", 7),
           ("I mean", 4), ("sorry, I meant", 7), ("nahi,", 2), ("matlab", 2), ("actually,", 4),
           ("no,", 4)]
CORRECTION_SLOT_WEIGHTS = [("size", 23), ("colour", 18), ("brand", 13), ("category", 1)]

ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
         "seventeen", "eighteen", "nineteen"]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def below_hundred(n: int) -> str:
    if n < 10:
        return ONES[n]
    if n < 20:
        return TEENS[n - 10]
    return TENS[n // 10] + (" " + ONES[n % 10] if n % 10 else "")


def number_words(n: int, rng: random.Random) -> str:
    """English words for a multiple of 100 between 100 and 9900."""
    hundreds, thousands = (n // 100) % 10, n // 1000
    if thousands == 0:
        return f"{ONES[hundreds]} hundred"
    if rng.random() < 0.5 and n % 1000 and 11 <= n // 100 <= 99:        # "fifteen hundred"
        return f"{below_hundred(n // 100)} hundred"
    head = f"{below_hundred(thousands)} thousand"
    return head + (f" {ONES[hundreds]} hundred" if hundreds else "")


HINDI_THOUSANDS = {1: "ek", 2: "do", 3: "teen", 4: "chaar", 5: "paanch", 6: "chhe", 7: "saat",
                   8: "aath", 9: "nau"}


def slip(word: str, rng: random.Random) -> str:
    """One common typing slip in a word of five letters or more: two letters swapped, a
    neighbouring key pressed, a letter doubled or a middle letter dropped."""
    from anticipatory.spelling import NEIGHBOURS
    i = rng.randrange(1, len(word) - 1)
    kind = rng.choice(["swap", "neighbour", "double", "drop"])
    if kind == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if kind == "neighbour" and word[i] in NEIGHBOURS:
        return word[:i] + rng.choice(sorted(NEIGHBOURS[word[i]])) + word[i + 1:]
    if kind == "double":
        return word[:i] + word[i] + word[i:]
    return word[:i] + word[i + 1:]


class Generator:
    def __init__(self, rows: List[Dict[str, str]], seed: int = 0, typo_rate: float = 0.0):
        """`typo_rate` is the chance that a category, colour or brand phrase contains a typo.
        Dev has none, so training leaves it at 0; robustness checks raise it."""
        self.rows = rows
        self.typo_rate = typo_rate
        self.rng = random.Random(seed)
        self.catalog = InMemoryCatalog(rows)
        self.by_category: Dict[str, List[Dict[str, str]]] = {}
        for r in rows:
            self.by_category.setdefault(r["category"], []).append(r)
        self.brands = sorted({r["brand"] for r in rows})
        self.colours = sorted({r["colour"] for r in rows})
        self.categories = sorted({r["category"] for r in rows})

    # -- choosing what the shopper wants ----------------------------------------------------

    def pick_filters(self) -> Tuple[Dict[str, Any], Dict[str, str]]:
        """A target product and the filters that identify it uniquely."""
        rng = self.rng
        while True:
            target = rng.choice(self.rows)
            filters: Dict[str, Any] = {"category": target["category"], "colour": target["colour"]}
            if rng.random() < 0.89:
                filters["brand"] = target["brand"]
            if target["size"]:
                filters["size"] = target["size"]
            if rng.random() < 0.79:
                filters["max_price"] = self.budget_for(target, filters)
            for slot in ("brand", "max_price"):                  # add what is needed to pin it
                if len(self.catalog.find(filters, "", 50)) == 1:
                    break
                if slot == "brand":
                    filters["brand"] = target["brand"]
                elif "max_price" not in filters:
                    filters["max_price"] = self.budget_for(target, filters)
            hits = self.catalog.find(filters, "", 50)
            if len(hits) == 1 and hits[0]["product_id"] == target["product_id"]:
                return filters, target

    def budget_for(self, target, filters) -> int:
        """A round budget at or above the target's price that rules out dearer products."""
        rng = self.rng
        price = int(target["price"])
        step = rng.choice([100, 100, 100, 500])
        others = [int(h["price"]) for h in self.catalog.find(
            {k: v for k, v in filters.items() if k != "max_price"}, "", 50)
            if int(h["price"]) > price]
        ceiling = min(others) - 1 if others else price + 3000
        top = max(price, (ceiling // step) * step)
        choices = [n for n in range(((price + step - 1) // step) * step, top + 1, step)]
        return rng.choice(choices[:6]) if choices else price

    # -- surface forms ----------------------------------------------------------------------

    def category_phrase(self, value: str) -> str:
        rng = self.rng
        pool = [value] * 6 + [singular(value)] * 2 + CATEGORY_SYNONYMS.get(value, [])
        return rng.choice(pool)

    def colour_phrase(self, value: str, standalone: bool) -> str:
        rng = self.rng
        pool = [value] * 7 + COLOUR_SYNONYMS.get(value, [])
        phrase = rng.choice(pool)
        return ("in " + phrase) if standalone and rng.random() < 0.6 else phrase

    def brand_phrase(self, value: str, attached: bool) -> str:
        rng = self.rng
        if attached:
            return value
        return rng.choice([f"from {value}", f"by {value}", f"only {value}", f"{value} brand",
                           f"{value} ka", value])

    def size_phrase(self, value: str, category: str) -> str:
        rng = self.rng
        if value.isdigit():
            if category == "jeans":
                return rng.choice([f"waist {value}", f"{value} waist", f"size {value}",
                                   f"size {value}", f"{value} waist"])
            word = number_words_small(int(value))
            return rng.choice([f"size {value}", f"size {value}", f"size {word}",
                               f"size {value} UK", f"UK {value}", f"{value} UK",
                               f"size {word} UK"])
        pool = [f"size {value}"] * 4 + [f"{value} size", f"{value} size", value]
        for alias in SIZE_SYNONYMS.get(value, []):
            pool.append(alias)
            pool.append(f"size {alias}")
        return rng.choice(pool)

    def price_phrase(self, value: int) -> str:
        rng = self.rng
        cue = rng.choices(PRICE_CUES, PRICE_CUE_WEIGHTS)[0]
        style = rng.choices(["digits", "comma", "rs", "k", "words", "hindi"],
                            [30, 20, 14, 14, 16, 6])[0]
        if style == "hindi" and value % 1000 == 0 and value // 1000 in HINDI_THOUSANDS:
            return f"{HINDI_THOUSANDS[value // 1000]} hazaar tak"
        if style == "words" and value % 100 == 0 and 100 <= value < 10000:
            return f"{cue} {number_words(value, rng)}"
        if style == "k" and value % 100 == 0:
            amount = value / 1000
            return f"{cue} {amount:g}k"
        if style == "rs":
            return f"{cue} Rs. {value}" if rng.random() < 0.5 else f"{cue} ₹{value:,}"
        if style == "comma":
            return f"{cue} {value:,}"
        if rng.random() < 0.08:
            return f"{value} se kam"
        return f"{cue} {value}"

    # -- assembling a request ---------------------------------------------------------------

    def request(self) -> Dict[str, Any]:
        rng = self.rng
        filters, target = self.pick_filters()
        category = filters["category"]
        hindi = rng.random() < 0.08
        tags: List[str] = []

        late_slot = None
        if rng.random() < 0.17:
            late_slot = rng.choices(["brand", "colour", "size", "max_price"], [50, 20, 20, 10])[0]
            if late_slot not in filters:
                late_slot = None
            else:
                tags.append("late_constraint")

        corrected = None
        if rng.random() < 0.185:
            options = [(s, w) for s, w in CORRECTION_SLOT_WEIGHTS if s in filters
                       and s != late_slot]
            if options:
                corrected = rng.choices([s for s, _ in options], [w for _, w in options])[0]
                tags.append("correction")

        def phrase(slot: str, value: Any, attached: bool = False) -> str:
            if slot == "category":
                text = self.category_phrase(value)
            elif slot == "colour":
                text = self.colour_phrase(value, standalone=not attached)
            elif slot == "brand":
                text = self.brand_phrase(value, attached)
            elif slot == "size":
                return self.size_phrase(value, category)
            else:
                return self.price_phrase(value)
            return self.with_typo(text)

        wrong_value = self.wrong_value(corrected, filters) if corrected else None
        delayed = bool(corrected) and rng.random() < 0.42

        def shown_value(slot: str) -> Any:
            return wrong_value if corrected == slot else filters[slot]

        # the noun phrase: [brand] [colour] category, brand and colour sometimes detached
        attach_brand = rng.random() < 0.55
        attach_colour = rng.random() < 0.65
        head: List[str] = []
        detached: List[str] = []
        for slot in ("brand", "colour"):
            if slot in filters and slot != late_slot:
                attached = attach_brand if slot == "brand" else attach_colour
                (head if attached else detached).append(slot)
        rng.shuffle(head)
        body: List[Tuple[str, str]] = []                 # (slot, text) in spoken order
        for slot in head:
            body.append((slot, phrase(slot, shown_value(slot), attached=True)
                         + self.pause(0.03)))
        body.append(("category", phrase("category", shown_value("category")) + self.pause(0.16)))
        later = [slot for slot in ("size", "max_price") if slot in filters and slot != late_slot]
        later += detached
        rng.shuffle(later)
        for slot in later:
            body.append((slot, phrase(slot, shown_value(slot)) + self.pause(0.25)))

        # the correction: right after the wrong value, or after other content
        if corrected:
            right = phrase(corrected, filters[corrected])
            marker = rng.choices([m for m, _ in MARKERS], [w for _, w in MARKERS])[0]
            index = next(i for i, (slot, _) in enumerate(body) if slot == corrected)
            if delayed and index < len(body) - 1:
                insert_at = rng.randint(index + 2, len(body))
            else:
                insert_at = index + 1
            # in dev 35 of 55 corrections follow a pause (comma or period), against a base rate
            # of about 16 percent after any other mention
            slot_before, text_before = body[insert_at - 1]
            text_before = text_before.rstrip(",.")
            if rng.random() < 0.64:
                text_before += "," if rng.random() < 0.7 else "."
            body[insert_at - 1] = (slot_before, text_before)
            body.insert(insert_at, ("correction", f"{marker} {right}" + self.pause(0.15)))
        parts_body = [text for _, text in body]

        if late_slot:
            value = filters[late_slot]
            lead = rng.choice(["and", "also", "oh, and", "and", "oh and"]) if not hindi \
                else rng.choice(["aur", "ek aur baat,"])
            parts_body[-1] = parts_body[-1].rstrip(",") + rng.choice([".", ",", ""])
            parts_body.append(f"{lead} {phrase(late_slot, value)}")

        opener = rng.choice(HINDI_OPENERS if hindi else OPENERS)
        tail = rng.choice(HINDI_TAILS if hindi else TAILS)
        filler = rng.choice(FILLERS) if rng.random() < 0.08 else ""
        parts = [opener, filler] + parts_body + [tail]
        text = " ".join(p for p in parts if p).replace(" ,", ",").strip()
        return {"words": text.split(), "text": text, "target": target["product_id"],
                "filters": filters, "tags": tags}

    def with_typo(self, text: str) -> str:
        """Maybe put a typo in the longest word of a phrase (only words of 5 letters or more)."""
        if self.typo_rate <= 0 or self.rng.random() >= self.typo_rate:
            return text
        words = text.split(" ")
        i = max(range(len(words)), key=lambda k: len(words[k]))
        if len(words[i]) < 5 or not words[i].isalpha():
            return text
        words[i] = slip(words[i], self.rng)
        return " ".join(words)

    def pause(self, p: float) -> str:
        return "," if self.rng.random() < p else ""

    def wrong_value(self, slot: str, filters) -> Any:
        rng = self.rng
        value = filters[slot]
        if slot == "size":
            pool = sorted({r["size"] for r in self.by_category[filters["category"]]} - {value})
        elif slot == "colour":
            pool = [c for c in self.colours if c != value]
        elif slot == "brand":
            pool = [b for b in self.brands if b != value]
        else:
            pool = [c for c in self.categories if c != value]
        return rng.choice(pool)


def singular(plural: str) -> str:
    """"watches" -> "watch", "dresses" -> "dress", "shirts" -> "shirt" (last word only)."""
    if plural.endswith(("ches", "shes", "sses")):
        return plural[:-2]
    return plural[:-1] if plural.endswith("s") else plural


def number_words_small(n: int) -> str:
    return (ONES[n] if n < 10 else TEENS[n - 10]) if n < 20 else str(n)


# ----------------------------------------------------------------------------- examples

def build_examples(words: List[str], target: str, lexicon: Lexicon,
                   rows: List[Dict[str, str]], catalog: Optional[InMemoryCatalog] = None,
                   config=DEFAULT_CONFIG) -> List[Dict[str, Any]]:
    """Replay a request word by word; one row per prefix where a commit could happen.

    A row is the `RiskInput` fields plus `label` (1 = the unique match is not the target),
    `index` and `n_words`.
    """
    catalog = catalog or InMemoryCatalog(rows)
    state = FilterState(lexicon, config)
    cache: Dict[Tuple, List[Dict[str, Any]]] = {}
    out = []
    for i, word in enumerate(words, start=1):
        snapshot = state.push(word)
        filters = search_filters(snapshot, config)
        if blocked_reason(snapshot, filters, lexicon):
            continue
        key = tuple(sorted(filters.items()))
        if key not in cache:
            cache[key] = catalog.find(filters, "", config.policy.candidate_k)
        hits = cache[key]
        if len(hits) != 1:
            continue
        features = RiskInput.from_snapshot(snapshot, filters, 1)
        row = dict(features.__dict__)
        row.update(label=int(hits[0]["product_id"] != target), index=i, n_words=len(words))
        out.append(row)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--typo-rate", type=float, default=0.0)
    args = parser.parse_args()
    rows = load_rows()
    generator = Generator(rows, args.seed, args.typo_rate)
    for _ in range(args.count):
        req = generator.request()
        print(json.dumps({k: req[k] for k in ("text", "filters", "tags")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
