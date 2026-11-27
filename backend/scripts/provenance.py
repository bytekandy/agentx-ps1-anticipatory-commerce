"""Where did each hand-written word list come from, and does it earn its place?

    cd backend && python scripts/provenance.py              # provenance table only (fast)
    python scripts/provenance.py --ablate                   # also score the agent with each group removed
    python scripts/provenance.py --ablate --out outputs/provenance.md

Provenance: for every group of hand-written words (synonym tables, cue and word sets) it counts
the entries and how many of them occur in the text of each test set (dev, dev_extra, dev_blind,
dev_brutal). An entry that occurs in no set is a guess about the hidden set; an entry that occurs
only in dev_blind or dev_brutal was written after those sets were read, so it is fitted to them.

Ablation: for each group, switch it off (the tables are module-level, so the script empties them
before the agent is built), score dev, dev_extra, dev_blind and dev_brutal, and print the change
in score, accuracy and wrong early commits against the full agent. A group whose removal changes
nothing on any set is dead weight; a group that matters only on dev_blind or dev_brutal is fitted
to them. This is an offline analysis: the agent itself never reads a test file.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import evaluate  # noqa: E402  (the kit's scorer)
from anticipatory import lexicon, slots, state  # noqa: E402

SETS = (("dev", BACKEND / "dev.jsonl"),
        ("dev_extra", BACKEND / "data" / "dev_extra.jsonl"),
        ("dev_blind", BACKEND / "data" / "dev_blind.jsonl"),
        ("dev_brutal", BACKEND / "data" / "dev_brutal.jsonl"))


def load(path: Path) -> List[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ----------------------------------------------------------------------------- the groups

def _flat(table: Dict[str, Sequence[str]]) -> List[str]:
    return [p for phrases in table.values() for p in phrases]


def entries() -> Dict[str, List[str]]:
    """group name -> its phrases, read from the live tables."""
    generated = lexicon._generated_phrases()

    def gen(slot, value_in=None):
        return [p for p, s, v in generated if s == slot and (value_in is None or v in value_in)]

    return {
        "seed synonyms (category, colour, size)": (_flat(lexicon.CATEGORY_SYNONYMS)
                                                   + _flat(lexicon.COLOUR_SYNONYMS)
                                                   + _flat(lexicon.SIZE_SYNONYMS)),
        "WordNet-generated words (generated_lexicon.json)": [
            w for slot in ("category", "colour") for ws in lexicon.load_generated().get(slot, {}).values()
            for w in ws],
        "sandal words added later (sliders, slippers, chappal)": ["sliders", "slippers", "chappal"],
        "shade names (SHADE_SYNONYMS)": _flat(lexicon.SHADE_SYNONYMS),
        "shade + colour word (COLOUR_WORD_SHADES)": [p for p, s, _ in generated
                                                     if s == "colour" and p.split()[-1] in lexicon._COLOUR_WORDS],
        "Hindi colour stems + endings": [p for p, s, v in generated if s == "colour"
                                         and p not in _flat(lexicon.SHADE_SYNONYMS)
                                         and p.split()[-1] not in lexicon._COLOUR_WORDS],
        "sport + shoe word (footwear)": gen("category"),
        "Hindi size words (chhota, bada)": gen("size"),
        "not-a-size-after words (year, pairs...)": sorted(slots.NOT_A_SIZE_AFTER),
        "contrast words (but, so, same...)": sorted(state.CONTRAST_WORDS),
        "negation words and phrases": sorted(state.NEGATION_WORDS) + [" ".join(p) for p in state.NEGATION_PHRASES],
        "slot words (colour, brand... 'doesn't matter')": sorted(state.SLOT_WORDS),
        "material words (denim)": sorted(state.MATERIAL_CATEGORY_WORDS),
        "connector words (in, and, but...)": sorted(state.CONNECTORS),
        "filler words (Hindi and English)": sorted(lexicon.FILLER_WORDS),
        "correction words": sorted(lexicon.CORRECTION_WORDS),
    }


def _texts(requests: Sequence[dict]) -> str:
    return " " + " ".join(" ".join(r["words"]).lower() for r in requests) + " "


def seen_in(phrase: str, text: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])", text) is not None


def provenance_table() -> str:
    corpora = {name: _texts(load(path)) for name, path in SETS}
    names = [n for n, _ in SETS]
    rows = ["| group | entries | " + " | ".join(f"in {n}" for n in names) + " | in no set (a guess) |",
            "|---|---|" + "---|" * (len(names) + 1)]
    for group, phrases in entries().items():
        phrases = sorted(set(phrases))
        counts = [sum(seen_in(p, corpora[n]) for p in phrases) for n in names]
        none = sum(not any(seen_in(p, corpora[n]) for n in names) for p in phrases)
        rows.append(f"| {group} | {len(phrases)} | " + " | ".join(map(str, counts)) + f" | {none} |")
    return "\n".join(rows)


# ----------------------------------------------------------------------------- ablation

def _empty_table(table):
    saved = {k: list(v) for k, v in table.items()}
    table.clear()
    return saved


def _switches() -> List[Tuple[str, callable]]:
    """(group, apply) where apply() switches the group off and returns an undo function."""
    def patch(module, name, empty):
        def apply():
            old = getattr(module, name)
            setattr(module, name, empty)
            return lambda: setattr(module, name, old)
        return apply

    def sandal_extra():
        table = lexicon.CATEGORY_SYNONYMS["sandals"]
        saved = list(table)
        table[:] = [p for p in table if p not in ("sliders", "slippers", "chappal")]
        return lambda: table.__setitem__(slice(None), saved)

    def brand_mode():
        old = slots._correct_brands
        slots._correct_brands = lambda tokens, corrected, lex: (tokens, corrected)
        return lambda: setattr(slots, "_correct_brands", old)

    return [
        ("WordNet-generated words", patch(lexicon, "load_generated", lambda path=None: {})),
        ("sandal words added later", sandal_extra),
        ("shade names", patch(lexicon, "SHADE_SYNONYMS", {})),
        ("shade + colour word", patch(lexicon, "COLOUR_WORD_SHADES", {})),
        ("Hindi colour stems", patch(lexicon, "HINDI_COLOUR_STEMS", {})),
        ("footwear qualifiers", patch(lexicon, "FOOTWEAR_QUALIFIERS", ())),
        ("Hindi size words", patch(lexicon, "HINDI_SIZE_WORDS", {})),
        ("not-a-size-after", patch(slots, "NOT_A_SIZE_AFTER", frozenset())),
        ("contrast words", patch(state, "CONTRAST_WORDS", frozenset())),
        ("negation", patch(state, "NEGATION_WORDS", frozenset())),
        ("slot words", patch(state, "SLOT_WORDS", {})),
        ("material words (denim)", patch(state, "MATERIAL_CATEGORY_WORDS", frozenset())),
        ("connector wait", patch(state, "CONNECTORS", frozenset())),
        ("brand spelling mode", brand_mode),
    ]


def score_all(datasets) -> Dict[str, dict]:
    from agent import Agent
    out = {}
    for name, requests in datasets.items():
        results, _ = evaluate.run(Agent, requests)
        out[name] = evaluate.summarise(results)
    return out


def ablation_table() -> str:
    datasets = {name: load(path) for name, path in SETS}
    full = score_all(datasets)
    names = list(datasets)
    head = "| group switched off | " + " | ".join(f"{n} score / acc / wrong" for n in names) + " |"
    rows = [head, "|---|" + "---|" * len(names),
            "| (nothing: full agent) | " + " | ".join(
                f"{full[n]['score']:.1f} / {full[n]['accuracy']:.3f} / {full[n]['wrong_commits']}"
                for n in names) + " |"]
    for group, apply in _switches():
        undo = apply()
        try:
            cur = score_all(datasets)
        finally:
            undo()
        cells = []
        for n in names:
            d_score = cur[n]["score"] - full[n]["score"]
            d_acc = cur[n]["accuracy"] - full[n]["accuracy"]
            mark = "" if abs(d_score) < 0.05 and abs(d_acc) < 1e-9 else f" ({d_score:+.1f}, acc {d_acc:+.3f})"
            cells.append(f"{cur[n]['score']:.1f} / {cur[n]['accuracy']:.3f} / {cur[n]['wrong_commits']}{mark}")
        rows.append(f"| {group} | " + " | ".join(cells) + " |")
        print(f"done: {group}", file=sys.stderr)
    return "\n".join(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ablate", action="store_true", help="also score the agent with each group off")
    parser.add_argument("--out", help="write the report to this file (relative to backend/)")
    args = parser.parse_args(argv)
    parts = ["# Provenance and ablation of the hand-written word lists\n",
             "Generated by `backend/scripts/provenance.py`.\n",
             "## Where each group occurs\n", provenance_table(), ""]
    if args.ablate:
        parts += ["\n## Score with each group switched off (cells: score / accuracy / wrong early commits)\n",
                  ablation_table(), ""]
    text = "\n".join(parts)
    if args.out:
        (BACKEND / args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
