"""Word normalisation shared by the lexicon, the number reader and slot extraction, and general
English word frequencies (what is a real word, how common it is).

The agent receives words exactly as typed ("UK.", "Rs.1,500", "M,"). A `Token` keeps the raw
word, a normalised form for matching, and whether the word ended a clause (a pause that often
precedes a correction or an afterthought).
"""
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

_EDGE_CHARS = ".,!?;:()[]{}\"'`…₹"            # includes the ellipsis and rupee sign
_CLAUSE_END = re.compile(r"[.,;!?…]$")
_RUPEE_PREFIX = re.compile(r"^(?:rs|inr)\.?(?=\d)")     # "rs.1500", "inr1500"
_TRAILING_DASH = re.compile(r"/-$")
_GLUED_SIZE = re.compile(r"^(size|sz|uk|waist|w)(\d{1,2})$")        # size9, UK10, sz10, w32
_GLUED_CUES = {"sz": "size", "w": "waist"}                     # "1500/-"
_GLUED_PRICE = re.compile(r"^(under|below|upto|within|max|budget)(\d+(?:\.\d+)?k?)$")   # under1000
# Punctuation inside a word with a letter on one side: "black,size9,Pacevo", "navy/blue".
# Digits on both sides stay together ("1,500", "2/3").
_INNER_BREAK = re.compile(r"(?<=[^\W\d_])[,;:/](?=\w)|(?<=\w)[,;:/](?=[^\W\d_])")
_GROUPED_NUMBER = re.compile(r"^\d{1,3}(?:,\d{2,3})+(?:\.\d+)?k?$")   # 1,500  10,000  1,00,000


@dataclass(frozen=True)
class Token:
    raw: str            # the word as typed
    text: str           # normalised for matching
    clause_end: bool    # the raw word ends with . , ; ! ? (a pause)


def normalize(raw: str) -> str:
    """Lower-case, strip edge punctuation, and reduce rupee and grouped numbers to digits.

    "Rs.1,500," -> "1500"   "UK." -> "uk"   "3.5K" -> "3.5k"   "it's" -> "it's"
    """
    text = unicodedata.normalize("NFKC", raw).replace("’", "'").lower().strip()
    text = text.strip(_EDGE_CHARS)
    text = _TRAILING_DASH.sub("", text)
    text = _RUPEE_PREFIX.sub("", text)
    if _GROUPED_NUMBER.match(text):
        text = text.replace(",", "")
    return text


def make_token(raw: str) -> Token:
    raw = raw.strip()
    text = normalize(raw)
    # "Rs." ends with a period but is an abbreviation, not the end of a clause.
    clause_end = bool(_CLAUSE_END.search(raw)) and text != "rs"
    return Token(raw, text, clause_end)


def make_tokens(raw: str) -> List[Token]:
    """The tokens for one word: usually one. Words glued by punctuation ("black,size9,Pacevo")
    are split, keeping the mark on the left part (a comma still ends a clause). A size or price
    cue glued to its number ("size9", "UK10", "w32", "under1000") is two: the cue, then the
    number."""
    raw = raw.strip()
    cuts = [m.end() for m in _INNER_BREAK.finditer(raw)]
    if cuts:
        parts = [raw[a:b].rstrip("/") for a, b in zip([0] + cuts, cuts + [len(raw)])]
        return [t for part in parts if part.strip(_EDGE_CHARS) for t in make_tokens(part)]
    token = make_token(raw)
    glued = _GLUED_SIZE.match(token.text) or _GLUED_PRICE.match(token.text)
    if not glued:
        return [token]
    cue = _GLUED_CUES.get(glued.group(1), glued.group(1))
    return [Token(raw, cue, False), Token(raw, glued.group(2), token.clause_end)]


def tokenize(words: Iterable[str]) -> List[Token]:
    """Turn the words of a request (already split, as the kit delivers them) into tokens."""
    return [t for w in words for t in make_tokens(w)]


def tokenize_text(text: str) -> List[Token]:
    """Convenience for tests and demos: split on whitespace, then tokenize."""
    return tokenize(text.split())


# ----------------------------------------------------------------------------- English words
# The spelling corrector and the unknown-word detector both need to tell a real English word
# ("short", "skirt", "purple") from a typo ("snekers") or a name. A hand-written list of "words
# not to touch" never ends, so the knowledge comes from data: the 60,000 most frequent words of a
# large web corpus with their counts (`data/english_words.tsv`). Loaded once, about 20 ms.

DEFAULT_WORDS_PATH = Path(__file__).resolve().parent / "data" / "english_words.tsv"


class EnglishWords:
    def __init__(self, counts: Dict[str, int]):
        self._count = counts
        ordered = sorted(counts, key=counts.get, reverse=True)
        self._rank = {w: i for i, w in enumerate(ordered)}

    @classmethod
    def from_file(cls, path: Optional[Path] = None) -> "EnglishWords":
        counts: Dict[str, int] = {}
        with open(path or DEFAULT_WORDS_PATH, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("#") or not line.strip():
                    continue
                word, _, count = line.partition("\t")
                counts[word] = int(count)
        return cls(counts)

    def count(self, word: str) -> int:
        """How often the word occurs in the corpus; 0 if it is not among the top 60,000."""
        return self._count.get(word, 0)

    def rank(self, word: str) -> Optional[int]:
        """0 for the most frequent word, None if not in the list."""
        return self._rank.get(word)

    def __contains__(self, word: str) -> bool:
        return word in self._count

    def is_stopword(self, word: str, top: int = 300) -> bool:
        """One of the `top` most frequent words ("the", "you", "my", "for"...)."""
        rank = self._rank.get(word)
        return rank is not None and rank < top

    def __len__(self) -> int:
        return len(self._count)


_shared: Optional[EnglishWords] = None


def english_words() -> EnglishWords:
    """The shared instance, loaded on first use."""
    global _shared
    if _shared is None:
        _shared = EnglishWords.from_file()
    return _shared
