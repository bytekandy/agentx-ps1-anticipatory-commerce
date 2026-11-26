"""Word normalisation shared by the lexicon, the number reader and slot extraction.

The agent receives words exactly as typed ("UK.", "Rs.1,500", "M,"). A `Token` keeps the raw
word, a normalised form for matching, and whether the word ended a clause (a pause that often
precedes a correction or an afterthought).
"""
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, List

_EDGE_CHARS = ".,!?;:()[]{}\"'`…₹"            # includes the ellipsis and rupee sign
_CLAUSE_END = re.compile(r"[.,;!?…]$")
_RUPEE_PREFIX = re.compile(r"^(?:rs|inr)\.?(?=\d)")     # "rs.1500", "inr1500"
_TRAILING_DASH = re.compile(r"/-$")
_GLUED_SIZE = re.compile(r"^(size|sz|uk|waist|w)(\d{1,2})$")        # size9, UK10, sz10, w32
_GLUED_CUES = {"sz": "size", "w": "waist"}                     # "1500/-"
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
    """The tokens for one word: usually one. A size cue glued to its number ("size9", "UK10",
    "sz10", "w32") is two: the cue, then the number."""
    token = make_token(raw)
    glued = _GLUED_SIZE.match(token.text)
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
