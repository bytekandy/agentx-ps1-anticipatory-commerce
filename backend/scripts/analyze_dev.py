"""Analyse dev.jsonl to guide the design of the agent (Stage 1).

    cd backend
    python scripts/analyze_dev.py

Read-only: nothing in the kit is modified. The "lite reader" in this file is an analysis-only
approximation (exact catalogue vocabulary plus a few hand-mined synonym tables). The real
vocabulary and slot extraction are built in Stages 2 and 3; the tables here are the seed.
"""
import collections
import importlib.util
import json
import re
import statistics
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from search import load_catalogue, search  # noqa: E402  (kit module)

SLOTS = ("category", "colour", "size", "brand", "max_price")

# ---------------------------------------------------------------- lite reader tables

CATEGORY_SYNONYMS = {
    "running shoes": ["running sneakers", "jogging shoes", "runners", "running shoe"],
    "sneakers": ["casual shoes", "casual sneakers", "casual shoe"],
    "sandals": ["slides", "floaters"],
    "t-shirts": ["tshirt", "tee", "t shirt", "t-shirt"],
    "jeans": ["denims", "denim"],
    "track pants": ["trackpants", "joggers", "track pant"],
    "hoodies": ["hooded sweatshirt", "sweatshirt"],
    "backpacks": ["bag pack", "rucksack", "bag"],
    "headphones": ["headset"],
    "watches": ["wrist watch", "wristwatch"],
}
COLOUR_SYNONYMS = {
    "grey": ["gray"], "gold": ["golden"], "navy": ["navy blue"], "olive": ["olive green"],
    "black": ["kaala"], "red": ["laal"], "pink": ["gulabi"], "brown": ["bhura"],
}
SIZE_SYNONYMS = {
    "S": ["small"], "M": ["medium"], "L": ["large"], "XL": ["extra large"],
    "XS": ["extra small"], "XXL": ["double xl", "2xl"],
}
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90,
    # Hindi, as seen in dev
    "ek": 1, "do": 2, "teen": 3, "paanch": 5, "das": 10, "pandrah": 15, "satrah": 17,
    "dedh": 1.5, "dhai": 2.5,
}
MULTIPLIERS = {"hundred": 100, "sau": 100, "thousand": 1000, "hazaar": 1000}
SHOE_SIZES = set(range(6, 12))
WAIST_SIZES = set(range(28, 37, 2))


def norm(word):
    """Lower-case, strip edge punctuation, drop thousands commas inside numbers."""
    w = word.lower().strip(".,!?;:()\"'\u20b9")
    return w.replace(",", "") if re.fullmatch(r"[\d,]+", w) else w


def _singulars(plural):
    forms = {plural}
    if plural.endswith("s"):
        forms.add(plural[:-1])
    if plural.endswith("es"):
        forms.add(plural[:-2])
    return forms


class LiteReader:
    """Finds slot mentions with their word positions. Longest phrase wins."""

    def __init__(self, catalogue):
        self.phrases = {}
        cats = {p["category"] for p in catalogue}
        for c in cats:
            for form in _singulars(c):
                self._add(form, "category", c)
            for syn in CATEGORY_SYNONYMS.get(c, []):
                self._add(syn, "category", c)
        for c in {p["colour"] for p in catalogue}:
            self._add(c, "colour", c)
            for syn in COLOUR_SYNONYMS.get(c, []):
                self._add(syn, "colour", c)
        for b in {p["brand"] for p in catalogue}:
            self._add(b, "brand", b)
        for s in {p["size"] for p in catalogue if p["size"] and not p["size"].isdigit()}:
            self._add(s, "size", s)
            for syn in SIZE_SYNONYMS.get(s, []):
                self._add(syn, "size", s)
        self.max_len = max(len(k) for k in self.phrases)

    def _add(self, text, slot, value):
        self.phrases[tuple(text.lower().split())] = (slot, value)

    def mentions(self, words):
        """Return [(slot, value, start, end)] with 1-based word positions, in order."""
        toks = [norm(w) for w in words]
        self._raw = words
        out, i = [], 0
        while i < len(toks):
            hit = self._phrase_at(toks, i)
            if hit:
                slot, value, n = hit
                out.append((slot, value, i + 1, i + n))
                i += n
                continue
            num = self._number_at(toks, i)
            if num:
                slot, value, n = num
                out.append((slot, value, i + 1, i + n))
                i += n
                continue
            i += 1
        return out

    def _phrase_at(self, toks, i):
        for n in range(min(self.max_len, len(toks) - i), 0, -1):
            hit = self.phrases.get(tuple(toks[i:i + n]))
            if hit:
                return hit[0], hit[1], n
        return None

    def _number_at(self, toks, i):
        t = toks[i]
        m = re.fullmatch(r"(\d+(?:\.\d+)?)k", t)
        if m:
            return "max_price", round(float(m.group(1)) * 1000), 1
        if re.fullmatch(r"\d+", t):
            v = int(t)
            if v >= 100:
                return "max_price", v, 1
            if v in SHOE_SIZES or v in WAIST_SIZES:
                return "size", str(v), 1
            return None
        if t == "saadhe" and i + 2 < len(toks) and toks[i + 1] in NUMBER_WORDS \
                and toks[i + 2] in MULTIPLIERS:
            return "max_price", round((NUMBER_WORDS[toks[i + 1]] + 0.5) * MULTIPLIERS[toks[i + 2]]), 3
        if t in NUMBER_WORDS or t in MULTIPLIERS:
            j, total, cur = i, 0, 0
            last = None
            while j < len(toks) and (toks[j] in NUMBER_WORDS or toks[j] in MULTIPLIERS):
                w = toks[j]
                if last == 100 and w in NUMBER_WORDS:
                    break  # "four thousand five hundred. one more thing"
                last = MULTIPLIERS.get(w)
                if w in NUMBER_WORDS:
                    cur += NUMBER_WORDS[w]
                elif MULTIPLIERS[w] == 100:
                    cur = max(cur, 1) * 100
                else:
                    total += max(cur, 1) * 1000
                    cur = 0
                j += 1
                if re.search(r"[.,;!?]$", self._raw[j - 1]):
                    break  # a sentence or clause ends the number
            value = round(total + cur)
            if value >= 100:
                return "max_price", value, j - i
            if j - i == 1 and (value in SHOE_SIZES or value in WAIST_SIZES):
                return "size", str(value), 1
        return None


def read_prefix(mentions, t):
    """Reading after t words: for each slot, the last mention so far wins."""
    state = {}
    for slot, value, _start, end in mentions:
        if end <= t:
            state[slot] = value
    return state


# ---------------------------------------------------------------- data helpers

def load_dev():
    with open(BACKEND / "dev.jsonl", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def pct(x, n):
    return f"{100 * x / n:5.1f}%" if n else "  n/a"


def heading(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


# ---------------------------------------------------------------- sections

def section_coverage(rows, reader):
    heading("Lite reader coverage: does reading the full request reproduce the gold filters?")
    per_slot = collections.Counter()
    bad = []
    for r in rows:
        final = read_prefix(reader.mentions(r["words"]), len(r["words"]))
        ok = True
        for s in SLOTS:
            same = str(final.get(s)) == str(r["filters"].get(s))
            per_slot[s] += same
            ok &= same
        if not ok:
            bad.append((r, final))
    n = len(rows)
    print(f"all five slots right: {n - len(bad)}/{n}")
    print("per slot:", "  ".join(f"{s} {per_slot[s]}/{n}" for s in SLOTS))
    for r, final in bad[:25]:
        diff = {s: (final.get(s), r["filters"].get(s)) for s in SLOTS
                if str(final.get(s)) != str(r["filters"].get(s))}
        print(f"  {r['id']}: {r['text']}\n      (read, gold): {diff}")


TAGS = ("correction", "late_constraint", "code_mixed")
HINDI_NUMBERS = {"ek", "do", "teen", "paanch", "das", "pandrah", "satrah", "dedh", "dhai",
                 "saadhe", "sau", "hazaar"}
ORDER = ("category", "colour", "brand", "size", "max_price")


def groups(rows):
    out = {"all": rows, "plain": [r for r in rows if not r["tags"]]}
    out.update({t: [r for r in rows if t in r["tags"]] for t in TAGS})
    return out


def ngrams(tokens, nmax=3):
    for n in range(1, nmax + 1):
        for i in range(len(tokens) - n + 1):
            yield tuple(tokens[i:i + n])


def content_tokens(catalogue, reader):
    """Tokens that carry slot meaning (catalogue words, synonyms, numbers)."""
    toks = set(NUMBER_WORDS) | set(MULTIPLIERS) | {"saadhe"}
    for p in catalogue:
        for f in ("title", "brand", "category", "colour", "size"):
            toks.update(re.findall(r"[a-z0-9]+", p[f].lower()))
    for phrase in reader.phrases:
        toks.update(phrase)
    return toks


def is_content(token, content):
    return token in content or bool(re.search(r"\d", token))


def discriminative(rows, tag, content, min_support=2, min_precision=0.75, top=14):
    """Phrases made only of non-content words that (almost) only occur in `tag` requests."""
    in_tag, total = collections.Counter(), collections.Counter()
    for r in rows:
        toks = [norm(w) for w in r["words"]]
        grams = {g for g in ngrams(toks) if all(t and not is_content(t, content) for t in g)}
        for g in grams:
            total[g] += 1
            in_tag[g] += tag in r["tags"]
    cands = [(g, in_tag[g], total[g]) for g in total
             if in_tag[g] >= min_support and in_tag[g] / total[g] >= min_precision]

    def covered(g):
        return any(len(h) > len(g) and in_tag[h] == in_tag[g] and total[h] == total[g]
                   and any(h[i:i + len(g)] == g for i in range(len(h) - len(g) + 1))
                   for h, _a, _b in cands)

    cands = [c for c in cands if not covered(c[0])]
    cands.sort(key=lambda c: (-c[1], -c[1] / c[2], c[0]))
    return [f"{' '.join(g)} ({a}/{b})" for g, a, b in cands[:top]]


def naive_pin(reader, row):
    """First word at which 'last mention wins' leaves exactly one product, and which one."""
    ms = reader.mentions(row["words"])
    for t in range(1, len(row["words"]) + 1):
        f = read_prefix(ms, t)
        if f:
            hits = search("", f, k=2)
            if len(hits) == 1:
                return t, hits[0]["product_id"]
    return None, None


def section_overview(rows):
    heading("1. Overview")
    combos = collections.Counter(" + ".join(r["tags"]) or "plain" for r in rows)
    print("tag combinations:", dict(combos.most_common()))
    print(f"{'group':16}{'n':>5}{'words avg':>11}{'min':>5}{'max':>5}"
          + "".join(f"{s:>11}" for s in SLOTS) + "   (share of requests mentioning the slot)")
    for name, g in groups(rows).items():
        lens = [len(r["words"]) for r in g]
        cells = "".join(f"{pct(sum(r['filters'].get(s) is not None for r in g), len(g)):>11}"
                        for s in SLOTS)
        print(f"{name:16}{len(g):>5}{statistics.mean(lens):>11.1f}{min(lens):>5}{max(lens):>5}{cells}")


def section_ceiling(rows):
    heading("2. Earliness ceiling (the oracle `earliest` label)")
    print("ceiling score = 100 x mean(0.4 + 0.6 x oracle share): perfect accuracy, one search, "
          "no wrong commits")
    print(f"{'group':16}{'n':>5}{'oracle share':>14}{'earliest=n':>12}{'tail words':>12}"
          f"{'ceiling':>10}")
    for name, g in groups(rows).items():
        shares = [(len(r["words"]) - r["earliest"]) / len(r["words"]) for r in g]
        at_end = sum(r["earliest"] == len(r["words"]) for r in g)
        tail = statistics.mean(len(r["words"]) - r["earliest"] for r in g)
        ceiling = 100 * statistics.mean(0.4 + 0.6 * s for s in shares)
        print(f"{name:16}{len(g):>5}{100 * statistics.mean(shares):>13.1f}%{pct(at_end, len(g)):>12}"
              f"{tail:>12.2f}{ceiling:>10.1f}")


def section_pin(rows, reader):
    heading("3. What completes the pin (the word at `earliest`) and what follows it")
    kinds = {name: collections.Counter() for name in groups(rows)}
    tail_slots = collections.Counter()
    tail_requests = 0
    for r in rows:
        ms = reader.mentions(r["words"])
        gold = r["filters"]
        done = sorted({s for s, v, _a, b in ms if b == r["earliest"] and str(v) == str(gold.get(s))})
        label = "+".join(done)
        if not label:
            prev = [m for m in ms if m[3] == r["earliest"] - 1 and str(m[1]) == str(gold.get(m[0]))]
            word = norm(r["words"][r["earliest"] - 1])
            label = f"marker word after {prev[0][0]}" if prev and word.isalpha() else "other"
        for name, g in groups(rows).items():
            if r in g:
                kinds[name][label] += 1
        after = [m for m in ms if m[2] > r["earliest"]]
        tail_requests += bool(after)
        for m in after:
            tail_slots[m[0]] += 1
    for name in ("all", "plain", "correction", "late_constraint", "code_mixed"):
        total = sum(kinds[name].values())
        row = ", ".join(f"{k} {pct(v, total).strip()}" for k, v in kinds[name].most_common())
        print(f"pin completed by [{name}]: {row}")
    print(f"\nrequests with a slot mention AFTER the pin: {tail_requests}/{len(rows)}; "
          f"by slot: {dict(tail_slots.most_common())}")
    print("(those later mentions never change the target; they are consistent extras)")


def section_ladder(rows):
    heading("4. Ambiguity ladder and slot necessity (gold filters, kit search, uncounted)")
    print("Candidates left as gold slots are added in the order category, colour, brand, size, "
          "price (slots not mentioned are skipped).")
    sized = [r for r in rows if r["filters"].get("size")]
    unsized = [r for r in rows if not r["filters"].get("size")]
    for label, subset in (("sized requests", sized), ("requests without size", unsized)):
        print(f"\n{label}: {len(subset)}")
        for k in range(1, len(ORDER) + 1):
            counts = []
            for r in subset:
                f = {s: r["filters"][s] for s in ORDER[:k] if r["filters"].get(s) is not None}
                counts.append(len(search("", f, k=100000)))
            uniq = sum(c == 1 for c in counts)
            print(f"  up to {ORDER[k - 1]:10} mean {statistics.mean(counts):7.1f}  "
                  f"median {statistics.median(counts):5.0f}  unique {pct(uniq, len(counts))}")
    print("\nSlot necessity: removing the slot from the gold filters leaves more than one product")
    for s in ORDER:
        mentioned = [r for r in rows if r["filters"].get(s) is not None]
        needed = 0
        for r in mentioned:
            f = {k: v for k, v in r["filters"].items() if v is not None and k != s}
            needed += len(search("", f, k=100000)) > 1
        print(f"  {s:10} mentioned in {pct(len(mentioned), len(rows)).strip():>6} of requests; "
              f"needed to pin in {pct(needed, len(mentioned)).strip():>6} of those")


def section_corrections(rows, reader, content):
    heading("5. Corrections")
    changed, gaps, remaining = collections.Counter(), [], []
    changed_outside = 0
    before_correction = wrong_pin = 0
    pin_wrong = {name: 0 for name in groups(rows)}
    for r in rows:
        ms = reader.mentions(r["words"])
        by = collections.defaultdict(list)
        for m in ms:
            by[m[0]].append(m)
        flips = [(s, lst) for s, lst in by.items() if len({str(m[1]) for m in lst}) > 1]
        if "correction" not in r["tags"]:
            changed_outside += bool(flips)
        for s, lst in flips:
            if "correction" in r["tags"]:
                changed[s] += 1
                gaps.append(lst[-1][2] - lst[-2][3] - 1)
                remaining.append(len(r["words"]) - lst[-1][3])
        t, cand = naive_pin(reader, r)
        wrong = cand is not None and cand != r["target"]
        for name, g in groups(rows).items():
            if r in g and wrong:
                pin_wrong[name] += 1
        if "correction" in r["tags"] and flips:
            fix_end = max(lst[-1][3] for _s, lst in flips)
            if t is not None and t < fix_end:
                before_correction += 1
                wrong_pin += wrong
    corr = groups(rows)["correction"]
    print(f"slots whose value changed inside correction requests: {dict(changed.most_common())}")
    print(f"requests WITHOUT the correction tag that still change a slot value: {changed_outside}")

    def hist(values, edges):
        out = []
        for lo, hi in edges:
            label = f"{lo}" if lo == hi else (f"{lo}+" if hi is None else f"{lo}-{hi}")
            out.append(f"{label}: {sum(lo <= v and (hi is None or v <= hi) for v in values)}")
        return ", ".join(out)

    print("words between the wrong value and its replacement:",
          hist(gaps, [(0, 0), (1, 1), (2, 2), (3, 4), (5, 8), (9, None)]))
    print("words still to come after the replacement:",
          hist(remaining, [(0, 0), (1, 2), (3, 5), (6, None)]))
    print(f"naive 'unique under last-mention-wins' pin lands BEFORE the replacement finishes: "
          f"{before_correction}/{len(corr)} correction requests, of which on a wrong product: "
          f"{wrong_pin}")
    print("requests where the naive first unique product is NOT the target, by group: "
          + ", ".join(f"{k} {v}/{len(groups(rows)[k])}" for k, v in pin_wrong.items()))
    print("\ncorrection markers (phrase (in correction requests / in all requests)):")
    print("  " + " | ".join(discriminative(rows, "correction", content, top=26)))


def section_late(rows, reader, content):
    heading("6. Late constraints")
    for name in ("late_constraint", "plain"):
        g = groups(rows)[name]
        last_slot, openers, decisive = collections.Counter(), collections.Counter(), 0
        for r in g:
            ms = reader.mentions(r["words"])
            last = max(ms, key=lambda m: m[3])
            last_slot[last[0]] += 1
            decisive += last[3] == r["earliest"]
            toks = [norm(w) for w in r["words"]]
            openers[" ".join(toks[max(0, last[2] - 4):last[2] - 1])] += 1
        print(f"[{name}] slot mentioned last: {dict(last_slot.most_common())}; "
              f"last mention completes the pin in {pct(decisive, len(g)).strip()}")
        if name == "late_constraint":
            print("  3 words before the last mention: "
                  + " | ".join(f"{k} ({v})" for k, v in openers.most_common(12)))
    print("\nlate-constraint markers (phrase (in late requests / in all requests)):")
    print("  " + " | ".join(discriminative(rows, "late_constraint", content)))


def section_vocab(rows, reader, content):
    heading("7. Vocabulary seen in dev")
    surface = collections.defaultdict(collections.Counter)
    price_kinds, price_prev = collections.Counter(), collections.Counter()
    size_prev, covered = collections.Counter(), {}
    for r in rows:
        toks = [norm(w) for w in r["words"]]
        covered[r["id"]] = set()
        for slot, value, a, b in reader.mentions(r["words"]):
            covered[r["id"]].update(range(a, b + 1))
            text = " ".join(toks[a - 1:b])
            raw = " ".join(r["words"][a - 1:b])
            if slot == "max_price":
                if "₹" in raw:
                    kind = "with rupee sign"
                elif re.fullmatch(r"[\d.]+k", text):
                    kind = "k form"
                elif re.fullmatch(r"\d+", text):
                    kind = "digits with comma" if "," in raw.strip(",.") else "plain digits"
                elif any(t in HINDI_NUMBERS for t in text.split()):
                    kind = "Hindi words"
                else:
                    kind = "English words"
                price_kinds[kind] += 1
                price_prev[" ".join(toks[max(0, a - 3):a - 1])[-18:].strip()] += 1
            elif slot == "size":
                size_prev[(toks[a - 2] if a > 1 else "") + " _ " + (toks[b] if b < len(toks) else "")] += 1
            if text != str(value).lower() and text not in {f for f in _singulars(str(value))}:
                surface[slot][(str(value), text)] += 1
    for slot in ("category", "colour", "size", "brand"):
        by_value = collections.defaultdict(list)
        for (value, text), n in surface[slot].items():
            by_value[value].append(f"{text} ({n})")
        print(f"\nnon-catalogue wording for {slot}:")
        for value in sorted(by_value):
            print(f"  {value}: " + ", ".join(sorted(by_value[value])))
    print("\nprice wording kinds:", dict(price_kinds.most_common()))
    print("words before a price (top):",
          " | ".join(f"{k} ({v})" for k, v in price_prev.most_common(40) if v and k)[:600])
    print("word before / after a size mention (top):",
          " | ".join(f"{k} ({v})" for k, v in size_prev.most_common(14)))
    residual = collections.Counter()
    for r in rows:
        for i, w in enumerate(r["words"], 1):
            if i not in covered[r["id"]] and norm(w):
                residual[norm(w)] += 1
    print(f"\nwords outside any slot mention: {len(residual)} distinct; those seen 2+ times:")
    print("  " + ", ".join(f"{w} ({n})" for w, n in residual.most_common() if n >= 2))
    print("\ncode-mixed (Hindi-English) markers (phrase (in code_mixed / in all requests)):")
    print("  " + " | ".join(discriminative(rows, "code_mixed", content, min_precision=0.85, top=40)))


READER = None
UNSIZED = set()
FIX_MARKERS = {"oops", "sorry", "actually", "wait", "meant", "mean", "change", "rather",
               "matlab", "nahi", "no"}


class NaiveEagerAgent:
    """Analysis reference, not our agent: commits once the reading leaves exactly one product.

    It reads with 'last mention wins'. `hold` is how many unchanged words it waits first.
    With `aware`, a correction marker cancels a pending commit until a new reading arrives,
    and it only searches when a pin is possible (size known, or the category has no sizes).
    """

    hold = 0
    aware = False

    def __init__(self, tools):
        self.tools = tools

    def start(self, request_id):
        self.words, self.filters = [], None
        self.candidate, self.stable, self.committed = None, 0, None

    def _worth_searching(self, filters):
        if not self.aware:
            return bool(filters)
        return "size" in filters or filters.get("category") in UNSIZED

    def observe(self, word):
        self.words.append(word)
        if self.aware and norm(word) in FIX_MARKERS:
            self.candidate = None
        filters = read_prefix(READER.mentions(self.words), len(self.words))
        if filters != self.filters:
            self.filters, self.stable, self.candidate = filters, 0, None
            if self._worth_searching(filters):
                hits = self.tools.search("", filters, k=2)
                if len(hits) == 1:
                    self.candidate = hits[0]["product_id"]
        else:
            self.stable += 1
        out = {"filters": dict(filters), "confidence": 1.0 if self.candidate else 0.0}
        if self.candidate and self.stable >= self.hold and self.candidate != self.committed:
            self.committed = self.candidate
            out["commit"] = self.candidate
        return out

    def finish(self):
        filters = read_prefix(READER.mentions(self.words), len(self.words))
        hits = self.tools.search("", filters, k=1)
        return hits[0]["product_id"] if hits else None


def load_kit_evaluate():
    spec = importlib.util.spec_from_file_location("kit_evaluate", BACKEND / "evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def section_naive(rows):
    heading("8. Naive early-commit reference, scored with the kit's own evaluate.py")
    kit = load_kit_evaluate()
    print("Reader: last mention wins. Commits when exactly one product matches the reading.")
    print("hold = unchanged words to wait before committing.\n")
    head = (f"{'agent':22}{'accuracy':>10}{'wrong req':>11}{'wrong commits':>15}"
            f"{'earliness':>11}{'searches':>10}{'score':>8}")
    print(head)
    base, _ = kit.run(kit.BaselineAgent, rows)
    show("kit baseline", kit.summarise(base))
    runs = {}
    for aware in (False, True):
        for hold in (0, 1, 2, 3):
            agent = type(f"Naive{hold}{aware}", (NaiveEagerAgent,), {"hold": hold, "aware": aware})
            results, _ = kit.run(agent, rows)
            runs[(aware, hold)] = results
            show(f"{'aware' if aware else 'naive'}, hold {hold}", kit.summarise(results))
    print("\nby group, naive hold 0 (first block) and aware hold 1 (second block):")
    print(f"{'group':22}{'accuracy':>10}{'wrong req':>11}{'wrong commits':>15}"
          f"{'earliness':>11}{'searches':>10}{'score':>8}")
    for key in ((False, 0), (True, 1)):
        for name, g in groups(rows).items():
            ids = {r["id"] for r in g}
            show(name, kit.summarise([x for x in runs[key] if x["id"] in ids]))
        print()
    by_id = {r["id"]: r for r in rows}
    for key, limit in (((False, 0), 5), ((True, 1), 8)):
        label = f"{'aware' if key[0] else 'naive'}, hold {key[1]}"
        print(f"examples of wrong commits ({label}):")
        shown = 0
        for x in runs[key]:
            if x["wrong_commits"] and shown < limit:
                r = by_id[x["id"]]
                t, c = x["commits"][0]
                print(f"  {x['id']} {r['tags']}: commit at word {t} of {len(r['words'])} "
                      f"('{r['words'][t - 1]}') {c}, target {x['target']}\n      {r['text']}")
                shown += 1
        print()


def show(label, s):
    print(f"{label:22}{s['accuracy']:>10.3f}{s['requests_with_wrong_commit']:>11}"
          f"{s['wrong_commits']:>15}{100 * s['early_share']:>10.1f}%{s['searches']:>10.2f}"
          f"{s['score']:>8.1f}")


def main():
    global READER
    rows = load_dev()
    catalogue = load_catalogue()
    reader = READER = LiteReader(catalogue)
    UNSIZED.update(p["category"] for p in catalogue if not p["size"])
    content = content_tokens(catalogue, reader)
    section_coverage(rows, reader)
    section_overview(rows)
    section_ceiling(rows)
    section_pin(rows, reader)
    section_ladder(rows)
    section_corrections(rows, reader, content)
    section_late(rows, reader, content)
    section_vocab(rows, reader, content)
    section_naive(rows)


if __name__ == "__main__":
    main()
