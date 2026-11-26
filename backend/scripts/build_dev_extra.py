"""Build `data/dev_extra.jsonl`: extra test requests in the same format as `dev.jsonl`.

    cd backend
    python scripts/build_dev_extra.py            # writes data/dev_extra.jsonl
    python evaluate.py --agent agent.py --data data/dev_extra.jsonl

Why it exists. The hidden test set has "some wording not in dev". `dev.jsonl` cannot tell us how
the agent copes with that, and the synthetic generator used for training shares our own
assumptions. These requests are written by hand, as a different author would phrase them: other
openers, cue words the vocabulary has never seen ("not exceeding", "at most"), possessives
("Pacevo's"), price corrections (dev has none), two corrections in one request, markers such as
"correction:" and "scratch that", Hindi-English, typos, odd punctuation, and a few synonyms.

How it is built. Each template below is one hand-written phrasing with placeholders. The script
fills it from a real catalogue product (so every request has a real target), checks that the
slots the text mentions identify exactly that product, and records the gold filters. It also
computes `earliest`: the first word after which the mentioned slots pin the target down for good.

Some templates are expected to FAIL (tag `unseen_synonym`: "sliders", "lowers", "pullover" are not
in the seed lexicon). They are here to measure honestly, not to be passed.

Deterministic: the same seed gives the same file.
"""
import argparse
import json
import random
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from anticipatory.lexicon import Lexicon, load_rows  # noqa: E402
from anticipatory.slots import extract_mentions  # noqa: E402
from anticipatory.tokens import tokenize  # noqa: E402
from make_training_data import number_words, singular, slip  # noqa: E402

SHOES = ("running shoes", "sneakers", "sandals")
TOPS = ("t-shirts", "shirts", "dresses", "kurtas", "hoodies", "jackets", "track pants")
GROUPS = {"shoes": SHOES, "tops": TOPS, "jeans": ("jeans",),
          "unsized": ("backpacks", "caps", "headphones", "watches", "wallets"),
          "any": SHOES + TOPS + ("jeans", "backpacks", "caps", "headphones", "watches", "wallets")}
LONG_SIZE = {"S": "small", "M": "medium", "L": "large", "XL": "extra large", "XS": "extra small",
             "XXL": "double xl"}
HINDI_COLOUR = {"black": "kaala", "red": "laal", "white": "safed", "blue": "neela",
                "green": "hara", "yellow": "peela"}
HINDI_THOUSANDS = {1: "ek", 2: "do", 3: "teen", 4: "chaar", 5: "paanch", 6: "chhe", 7: "saat",
                   8: "aath", 9: "nau"}

# (group, tags, text). Placeholders: {cat} plural category, {cat1} singular, {col}, {brand},
# {size} the size value, {size_phrase} "size 9" / "UK 9" / "M size" / "waist 32", {size_long}
# "medium", {size_words} "nine", {price} 1500, {price_comma} 1,500, {price_k} 1.5k,
# {price_words} "fifteen hundred", {price_hi} "paanch hazaar", {hcol} Hindi colour word;
# wrong values for corrections: {wcol} {wbrand} {wsize} {wprice} {wcat}; typos: {cat_t} {col_t}
# {brand_t}. A suffix _t on any of cat col brand puts a typing slip in the word.
TEMPLATES = [
    # ---- plain, phrasing the generator does not use
    ("shoes", [], "yo, got any {col} {brand} {cat1} in {size_phrase}? budget {price}"),
    ("tops", [], "need {cat} from {brand} , {col}, size {size}, within {price}"),
    ("any", [], "{brand} {cat} in {col} please, {size_phrase}, max {price_comma}"),
    ("shoes", [], "what do you have in {col} {cat} for under {price_k}, {size_phrase}"),
    ("any", [], "looking to buy {col} {brand} {cat1}, {size_phrase}, around {price} tops"),
    ("tops", [], "gimme {col} {cat} {size_phrase} {brand} only, {price} max"),
    ("any", [], "{col} {cat1} by {brand}, {size_phrase}, price limit {price}"),
    ("any", [], "can I see {brand}'s {col} {cat} in {size_phrase}? keep it under Rs. {price}"),
    ("any", [], "I am hunting for a {col} {cat1} from {brand}. {size_phrase}. {price_words} rupees max."),
    ("unsized", [], "do you sell {brand} {col} {cat} under {price}?"),
    ("unsized", [], "{col} {cat1}, {brand}, {price_k} budget"),
    ("jeans", [], "{col} jeans, {brand}, waist {size}, upto {price}"),
    ("jeans", [], "jeans in {col} from {brand}, {size} waist, {price_words} max"),
    ("shoes", [], "UK {size} {col} {cat} {brand} below {price}"),
    ("shoes", [], "{brand} {cat} size {size_words} {col} for under {price}"),
    ("tops", [], "{col} {cat1} {size_long} size, {brand}, upto {price}"),
    ("any", [], "quick one: {brand} {col} {cat} {size_phrase} budget is {price}"),
    ("any", [], "my budget is {price}. want {col} {cat} from {brand} in {size_phrase}"),
    ("any", [], "{size_phrase} {col} {cat} {brand} {price} max"),
    ("any", [], "please send {col} {cat} ({brand}) in {size_phrase} costing less than {price}"),
    ("any", [], "anything {col} from {brand}? {cat} in {size_phrase} under {price_k}"),
    ("any", [], "Hello! I'd love {brand} {cat} in {col}, {size_phrase}; budget: {price}"),
    ("any", [], "NEED {col} {cat1} FROM {brand} {size_phrase} UNDER {price}"),
    ("any", [], "{col} {cat} {brand} {size_phrase} under {price} thanks"),
    # ---- number and price styles
    ("any", [], "{col} {brand} {cat} {size_phrase} for {price}/-"),
    ("any", [], "{col} {cat} {brand} {size_phrase} less than {price_words}"),
    ("any", [], "{brand} {col} {cat} {size_phrase} upto ₹{price_comma}"),
    ("any", [], "{brand} {col} {cat} {size_phrase} not exceeding {price}"),
    ("any", [], "{brand} {col} {cat} {size_phrase} at most {price}"),
    ("any", [], "{brand} {col} {cat} {size_phrase} for {price} or below"),
    ("any", [], "{brand} {col} {cat} {size_phrase} price under {price}"),
    ("any", [], "{brand} {col} {cat} {size_phrase} i can spend {price}"),
    ("any", [], "{brand} {col} {cat} {size_phrase} cheaper than {price}"),
    ("any", [], "{brand} {col} {cat} {size_phrase}, budget of Rs {price_comma}"),
    # ---- corrections
    ("any", ["correction"], "{wcol} - no wait, {col} {cat} from {brand}, {size_phrase}, under {price}"),
    ("any", ["correction"], "{brand} {cat} in {wcol}.. sorry {col}.. {size_phrase} max {price}"),
    ("shoes", ["correction"], "{col} {brand} {cat} size {wsize}, actually make that {size}, under {price}"),
    ("tops", ["correction"], "{col} {cat1} size {wsize} scratch that, {size_phrase} {brand} budget {price}"),
    ("any", ["correction"], "{col} {cat} from {wbrand}, no no {brand}, {size_phrase}, {price} tak"),
    ("any", ["correction"], "{col} {brand} {cat} {size_phrase} under {wprice}, no make it {price}"),
    ("tops", ["correction"], "{col} {wcat}, I mean {cat1} from {brand}, {size_phrase}, below {price}"),
    ("any", ["correction"], "{col} {cat} from {wbrand}, {size_phrase}, budget {price}, oh wait I meant {brand}"),
    ("tops", ["correction"], "{wcol} {cat} {brand} size {wsize} no wait {col} actually {size_phrase} too, under {price}"),
    ("any", ["correction", "code_mixed"], "{wcol} nahi {col} {cat} {brand} {size_phrase} {price} tak"),
    ("tops", ["correction"], "{col} {cat} from {brand} in {wsize}, I mean {size_phrase}, {price} max"),
    ("any", ["correction"], "{wcol} or rather {col} {cat} {brand} {size_phrase} upto {price}"),
    ("any", ["correction"], "{col} {cat} {brand} {size_phrase}, under {wprice}. correction: {price}"),
    ("any", ["correction"], "{brand} {cat} in {wcol}, actually {col}, {size_phrase}, {price} budget"),
    ("any", ["correction"], "{wcol} {brand} {cat} {size_phrase}, make it {col}, under {price}"),
    ("any", ["correction"], "{wbrand} {col} {cat}, {size_phrase}, below {price}, sorry I meant {brand}"),
    ("any", ["correction"], "{col} {cat} {size_phrase} {wbrand} uh no {brand} under {price}"),
    ("shoes", ["correction"], "{col} {cat} {brand} size {wsize} wait {size} under {price}"),
    ("any", ["correction"], "{col} {cat} {brand} {size_phrase} under {wprice} no wait, {price}"),
    ("any", ["correction"], "{brand} {wcol} {cat} {size_phrase}, hmm no, {col}, max {price}"),
    # ---- late constraints
    ("any", ["late_constraint"], "{col} {cat} {size_phrase} under {price}. oh and from {brand}"),
    ("any", ["late_constraint"], "{cat} {size_phrase} in {col}, {price} max, also {brand} only"),
    ("any", ["late_constraint"], "{col} {cat1} {brand}. and {size_phrase}. budget {price}"),
    ("any", ["late_constraint"], "{cat} {col} {size_phrase}, one more thing: only {brand}, under {price}"),
    ("any", ["late_constraint"], "{cat} {brand} {price} budget. oh, in {col} please. {size_phrase}"),
    ("any", ["late_constraint", "code_mixed"], "{col} {cat} {size_phrase} {price} tak, aur {brand} ka"),
    ("any", ["late_constraint"], "{col} {brand} {cat} {size_phrase}... and make it under {price}"),
    ("any", ["late_constraint"], "{col} {cat} {brand}, plus {size_phrase}, plus under {price}"),
    # ---- Hindi-English
    ("any", ["code_mixed"], "mujhe {col} {cat} chahiye {brand} ka {size_phrase} {price} tak"),
    ("any", ["code_mixed"], "{brand} ka {col} {cat} dikhao, {size_phrase}, {price} se kam"),
    ("any", ["code_mixed"], "bhaiya ek {col} {cat1} dena {size_phrase} {brand} wala {price} ke andar"),
    ("any", ["code_mixed"], "{col} {cat} milega kya {brand} ka? {size_phrase}, budget {price}"),
    ("any", ["code_mixed"], "{hcol} {cat} chahiye, {brand}, {size_phrase}, {price_hi} tak"),
    ("any", ["code_mixed"], "aapke paas {hcol} {cat} hai? {brand}, {size_phrase}, {price} ke andar"),
    ("any", ["code_mixed"], "mere liye {col} {cat1} {size_phrase} {brand} {price} se kam hai kya"),
    ("any", ["code_mixed"], "{brand} ka {hcol} {cat} {size_phrase} {price} tak dikhao"),
    # ---- typos
    ("any", ["typo"], "{col} {cat_t} from {brand}, {size_phrase}, under {price}"),
    ("any", ["typo"], "{col_t} {cat} {brand} {size_phrase} max {price}"),
    ("any", ["typo"], "{col} {cat} {brand_t} {size_phrase} below {price}"),
    ("any", ["typo"], "need {col} {brand} {cat_t}, {size_phrase}, {price} budget"),
    ("any", ["typo"], "{brand_t} {col_t} {cat} {size_phrase} upto {price}"),
    ("any", ["typo"], "{col} {brand} {cat_t} in {size_phrase} for less than {price_comma}"),
]

# (category, tags, template): the category word is written into the template, so the product
# must be of that category. The first eight are in the seed lexicon but never occurred in dev.
SYNONYM_TEMPLATES = [
    ("sandals", [], "{col} flip flops {brand} {size_phrase} under {price}"),
    ("kurtas", [], "{col} kurti from {brand}, size {size}, within {price}"),
    ("headphones", [], "{col} earbuds {brand} under {price}"),
    ("watches", [], "{brand} {col} smartwatch below {price}"),
    ("jackets", [], "{col} windcheater {brand} {size_phrase} max {price}"),
    ("track pants", [], "{col} sweatpants {brand} {size_phrase} under {price}"),
    ("dresses", [], "{col} frock by {brand}, {size_phrase}, budget {price}"),
    ("sandals", [], "{col} chappals {brand} {size_phrase} under {price}"),
    ("sandals", ["unseen_synonym"], "{col} sliders {brand} {size_phrase} under {price}"),
    ("track pants", ["unseen_synonym"], "{col} lowers {brand} {size_phrase} under {price}"),
    ("hoodies", ["unseen_synonym"], "{col} pullover {brand} {size_phrase} under {price}"),
]


class Builder:
    def __init__(self, rows, seed):
        self.rows = rows
        self.rng = random.Random(seed)
        self.lex = Lexicon(rows)
        self.by_cat = {}
        for r in rows:
            self.by_cat.setdefault(r["category"], []).append(r)
        self.brands = sorted({r["brand"] for r in rows})
        self.colours = sorted({r["colour"] for r in rows})

    # -- catalogue helpers ------------------------------------------------------------------

    def find(self, filters):
        out = []
        for r in self.rows:
            if any(r[k].lower() != str(v).lower() for k, v in filters.items() if k != "max_price"):
                continue
            if "max_price" in filters and int(r["price"]) > filters["max_price"]:
                continue
            out.append(r)
        return out

    def budget_for(self, product, filters):
        """A round budget at or above the product's price that rules out dearer rivals."""
        price = int(product["price"])
        rivals = [int(r["price"]) for r in self.find({k: v for k, v in filters.items()
                                                      if k != "max_price"})
                  if int(r["price"]) > price]
        step = self.rng.choice([100, 100, 500])
        ceiling = min(rivals) - 1 if rivals else price + 2500
        top = max(price, (ceiling // step) * step)
        options = list(range(((price + step - 1) // step) * step, top + 1, step))
        return self.rng.choice(options[:5]) if options else None

    def other(self, pool, current):
        return self.rng.choice([x for x in pool if x != current])

    # -- one request ------------------------------------------------------------------------

    def values(self, product, with_price):
        rng = self.rng
        cat = product["category"]
        size = product["size"]
        v = {"cat": cat, "cat1": singular(cat), "col": product["colour"], "brand": product["brand"],
             "size": size}
        if size:
            if size.isdigit():
                n = int(size)
                v["size_phrase"] = rng.choice([f"size {size}", f"UK {size}", f"size {size} UK"]) \
                    if cat != "jeans" else rng.choice([f"waist {size}", f"{size} waist"])
                v["size_words"] = {6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
                                   11: "eleven"}.get(n, size)
            else:
                v["size_phrase"] = rng.choice([f"size {size}", f"{size} size"])
                v["size_long"] = LONG_SIZE.get(size, size)
            sizes = sorted({r["size"] for r in self.by_cat[cat]} - {size})
            v["wsize"] = rng.choice(sizes) if sizes else size
        v["wcol"] = self.other(self.colours, product["colour"])
        v["wbrand"] = self.other(self.brands, product["brand"])
        group = next(g for g in (SHOES, TOPS, ("jeans",), GROUPS["unsized"]) if cat in g)
        rivals = [c for c in group if c != cat and not (cat in TOPS and c == "track pants")]
        v["wcat"] = self.rng.choice(rivals) if rivals else cat      # only used by tops templates
        v["hcol"] = HINDI_COLOUR.get(product["colour"], product["colour"])
        if with_price is not None:
            p = with_price
            v.update(price=p, price_comma=f"{p:,}", price_words=number_words(p, rng) if p % 100 == 0 and p < 10000 else str(p),
                     price_k=f"{p / 1000:g}k", price_hi=(f"{HINDI_THOUSANDS[p // 1000]} hazaar" if p % 1000 == 0 and p // 1000 in HINDI_THOUSANDS else str(p)))
            v["wprice"] = self.rng.choice([x for x in (p + 500, p + 1000, max(100, p - 300), p + 300)
                                           if x != p])
        for key in ("cat", "col", "brand"):
            word = v[key if key != "cat" else "cat1"]
            parts = word.split(" ")
            i = max(range(len(parts)), key=lambda k: len(parts[k]))
            if len(parts[i]) >= 5:
                parts[i] = slip(parts[i], rng)
            v[f"{key}_t"] = " ".join(parts)
        return v

    def build(self, group, tags, template, forced_category=None, tries=400):
        slots = set(re.findall(r"\{(\w+)\}", template))
        uses = {"category"}
        if slots & {"col", "wcol", "col_t", "hcol"}:
            uses.add("colour")
        if slots & {"brand", "wbrand", "brand_t"}:
            uses.add("brand")
        if slots & {"size", "size_phrase", "size_long", "size_words", "wsize"}:
            uses.add("size")
        wants_price = bool(slots & {"price", "price_comma", "price_k", "price_words", "price_hi"})
        categories = (forced_category,) if forced_category else GROUPS[group]
        for _ in range(tries):
            product = self.rng.choice([r for c in categories for r in self.by_cat[c]])
            if "size" in uses and not product["size"]:
                continue
            filters = {"category": product["category"]}
            if "colour" in uses:
                filters["colour"] = product["colour"]
            if "brand" in uses:
                filters["brand"] = product["brand"]
            if "size" in uses:
                filters["size"] = product["size"]
            price = None
            if wants_price:
                price = self.budget_for(product, filters)
                if price is None:
                    continue
                filters["max_price"] = price
            hits = self.find(filters)
            if len(hits) != 1 or hits[0]["product_id"] != product["product_id"]:
                continue
            values = self.values(product, price)
            if "wsize" in slots and values.get("wsize") == product["size"]:
                continue
            text = template.format(**values)
            return text, filters, product
        return None

    def earliest(self, words, filters, target_id):
        """First word after which the mentioned slots pin the target down for good."""
        end = {}
        for m in extract_mentions(tokenize(words), self.lex, final=True):
            slot = m.slot
            if slot in filters and m.value == filters[slot]:
                end[slot] = m.end            # the last matching mention wins
        for t in range(1, len(words) + 1):
            known = {s: v for s, v in filters.items() if end.get(s, len(words)) <= t}
            if "category" not in known:
                continue
            hits = self.find(known)
            if len(hits) == 1 and hits[0]["product_id"] == target_id:
                return t
        return len(words)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=20261126)
    parser.add_argument("--out", default=str(BACKEND / "data" / "dev_extra.jsonl"))
    args = parser.parse_args()
    builder = Builder(load_rows(), args.seed)
    requests = []
    plan = [(g, t, tpl, None) for g, t, tpl in TEMPLATES]
    plan += [("any", t, tpl, cat) for cat, t, tpl in SYNONYM_TEMPLATES]
    for group, tags, template, category in plan:
        made = builder.build(group, tags, template, category)
        if not made:
            print("skipped (no unique product):", template, file=sys.stderr)
            continue
        text, filters, product = made
        words = text.split()
        full = {"category": None, "colour": None, "size": None, "brand": None, "max_price": None}
        full.update(filters)
        requests.append({"id": f"extra-{len(requests) + 1:04d}", "text": text, "words": words,
                         "filters": full, "target": product["product_id"],
                         "earliest": builder.earliest(words, filters, product["product_id"]),
                         "tags": list(tags)})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in requests:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    tags = {}
    for r in requests:
        for tag in r["tags"] or ["plain"]:
            tags[tag] = tags.get(tag, 0) + 1
    print(f"wrote {len(requests)} requests to {args.out}: {tags}")


if __name__ == "__main__":
    main()
