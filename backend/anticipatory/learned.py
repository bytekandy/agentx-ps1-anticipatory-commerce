"""Words the agent was taught by earlier requests: a separate, optional file.

The agent itself never writes anything; a harness run is read-only and deterministic. Teaching
happens outside it (`scripts/learn_lexicon.py`, or the server's feedback endpoint), which update
`data/learned_lexicon.json`. When that file is absent, a word the lexicon cannot place is simply
dropped, exactly as before.

Two kinds of evidence, both needing a word nothing else explains ("clogs"):
  * a correction in the request: "clogs, I mean sandals" says clogs = sandals (category);
  * a confirmed answer: the shopper accepted a product, and exactly one of its category, colour
    or brand was never said in the request while exactly one unknown word was.
A word is used only after `learned_min_count` agreeing observations and never once the evidence
against it (an accepted product that disagrees) outweighs half of it. A learned phrase reads with
the confidence of a corrected word, so the agent does not commit early on it lightly.

File format: {"version": 1, "words": {"clogs": {"slot": "category", "value": "sandals",
"count": 3, "against": 0}}}
"""
import json
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Tuple

from .config import DEFAULT_CONFIG
from .lexicon import Lexicon
from .slots import read_words
from .state import find_markers
from .tokens import english_words, tokenize

DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "learned_lexicon.json"
_SLOTS = ("category", "colour", "brand")
_MARKER_REACH = 3          # a replacement starts within this many words after the marker


def _active(record: dict, min_count: int) -> bool:
    return record["count"] >= min_count and record["against"] * 2 <= record["count"] - min_count


def load_active(path: Optional[Path] = None, min_count: int = DEFAULT_CONFIG.vocab.learned_min_count
                ) -> Dict[str, Tuple[str, str]]:
    """The words usable right now: {word: (slot, value)}. Missing or damaged file: nothing."""
    try:
        data = json.loads(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
        return {w: (r["slot"], r["value"]) for w, r in data["words"].items() if _active(r, min_count)}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


class LearnedStore:
    """The evidence collected so far. Offline tool: reads and writes the JSON file."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or DEFAULT_PATH)
        self.words: Dict[str, dict] = {}
        try:
            self.words = json.loads(self.path.read_text(encoding="utf-8"))["words"]
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def add(self, word: str, slot: str, value: str) -> None:
        r = self.words.get(word)
        if r and (r["slot"], r["value"]) == (slot, value):
            r["count"] += 1
        elif r:
            r["against"] += 1                          # the same word, a different meaning
        else:
            self.words[word] = {"slot": slot, "value": value, "count": 1, "against": 0}

    def against(self, word: str) -> None:
        if word in self.words:
            self.words[word]["against"] += 1

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"version": 1, "words": dict(sorted(self.words.items()))},
                                        indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def active(self, min_count: int = DEFAULT_CONFIG.vocab.learned_min_count):
        return {w: (r["slot"], r["value"]) for w, r in self.words.items() if _active(r, min_count)}


def unknown_words(tokens, lexicon: Lexicon, covered=()) -> list:
    """(index, word) of words nothing explains: not in the shop, the lexicon or among the common
    English function words, and not a number."""
    english = english_words()
    rank = DEFAULT_CONFIG.unknown.stopword_rank
    return [(i, t.text) for i, t in enumerate(tokens)
            if i not in covered and t.text.isascii() and t.text.isalpha() and len(t.text) >= 4
            and t.text not in lexicon.known_words and t.text not in lexicon.catalogue_words
            and not english.is_stopword(t.text, rank)]


def learn_from_request(words: Sequence[str], lexicon: Lexicon, store: LearnedStore,
                       product: Optional[Dict[str, str]] = None) -> list:
    """Update `store` from one request; `product` is the catalogue row the shopper accepted, if
    any. Returns what was observed, as (word, slot, value) triples."""
    reading = read_words(tokenize(words), lexicon)
    tokens = reading.tokens
    covered = {i for m in reading.mentions for i in range(m.start, m.end)}
    unknown = unknown_words(tokens, lexicon, covered)
    seen = []
    for marker in find_markers(tokens):                              # "clogs, I mean sandals"
        before = [(i, w) for i, w in unknown if i == marker.start - 1]
        after = [m for m in reading.mentions if m.slot in _SLOTS
                 and 0 <= m.start - marker.end <= _MARKER_REACH]
        if before and after:
            slot, value = after[0].slot, str(after[0].value)
            store.add(before[0][1], slot, value)
            seen.append((before[0][1], slot, value))
    if product:                                                      # a confirmed answer
        for _, word in unknown:                                      # evidence against old words
            if word in store.words and store.words[word]["value"] != product[store.words[word]["slot"]]:
                store.against(word)
        said = {m.slot for m in reading.mentions}
        missing = [s for s in _SLOTS if s not in said]
        if len(unknown) == 1 and len(missing) == 1 and not seen:
            word, slot = unknown[0][1], missing[0]
            store.add(word, slot, product[slot])
            seen.append((word, slot, product[slot]))
    return seen
