"""Constraints the shopper stated that we cannot represent: unknown brand, size, colour or style.

Our vocabulary comes from the catalogue, so "black running shoes from Nike, size 14, in purple"
holds three constraints nothing in the shop answers to. If the agent simply ignores them it may
commit to a pair of black running shoes from another brand: the shopper asked for something we
do not sell and the agent pretends not to have noticed. This module finds such words, so the
agent holds back and can say what it did not understand.

No list of brands, colours or sizes is used. A word is flagged from STRUCTURE plus two kinds of
data we already have:

  * what the shop knows: every word in the catalogue (titles and descriptions) and every word
    the lexicon understands is "explained" and never flagged ("casual", "linen", "court");
  * what English knows: the word-frequency list (`words.py`) separates function words ("my",
    "the", "for": never flagged) from names and content words.

Three patterns, each needing an unexplained word:

  brand     after "from", "by" or "brand" (when it is capitalised or not an English word at all),
            before "brand", "ka", "wala", or any capitalised word in the middle of a sentence
            ("I want Nike shoes"). Not after "for", "on", "this" ("for Diwali", "by Friday").
  size      after a size cue ("size", "UK", "waist") when it reads as a number that is no
            catalogue size ("size 14") or as an extra-large or extra-small size ("size 4XL");
            also a size that exists but not for the category ("size 32 sandals", "size M cap").
  colour, style or brand
            a word right before a category, colour or brand word that nothing explains
            ("purple shirt", "nike sneakers", "purple Mehrin dress", "sky blue"), a word after "in" that nothing explains ("sneakers in purple"),
            or a word next to "colour" ("purple colour").

Every pattern is cautious on purpose: a false flag only costs a little earliness (the agent
waits), while a miss means committing to something the shopper did not ask for.
"""
import re
from dataclasses import dataclass
from typing import FrozenSet, List, Sequence, Set

from .config import DEFAULT_CONFIG, Config
from .lexicon import SIZE_CUES, Lexicon
from .numbers import read_number
from .slots import Reading
from .tokens import Token
from .words import EnglishWords, english_words

_EXTRA_SIZE = re.compile(r"^(\d*x+[sl]|\d+x[sl])$")        # xxxl, xxs, 4xl, 3xs
_COLOUR_WORDS = frozenset({"colour", "color", "colours", "colors", "rang"})


@dataclass(frozen=True)
class Unresolved:
    kind: str        # "brand", "size" or "colour or style"
    text: str        # the word as understood (lower-cased)
    start: int       # token index
    end: int
    reason: str

    def label(self) -> str:
        return f"{self.kind}: {self.text}"


def find_unresolved(reading: Reading, lexicon: Lexicon, config: Config = DEFAULT_CONFIG,
                    english: EnglishWords = None) -> List[Unresolved]:
    """Words in the reading that state a constraint nothing in the shop answers to."""
    cfg = config.unknown
    if not cfg.enabled:
        return []
    english = english or english_words()
    tokens = reading.tokens
    covered: Set[int] = {i for m in reading.mentions for i in range(m.start, m.end)}
    product_starts = {m.start for m in reading.mentions
                      if m.slot in ("category", "colour", "brand")}
    out: List[Unresolved] = []

    def plain(i: int) -> bool:
        """A word nothing explains: not understood by the lexicon, not in the shop's own text,
        not a function word, not a number."""
        text = tokens[i].text
        return (i not in covered and text.isascii() and text.isalpha()
                and len(text) >= cfg.min_length and text not in lexicon.known_words
                and text not in cfg.brand_cues and text not in cfg.brand_postfix
                and text not in lexicon.catalogue_words
                and not english.is_stopword(text, cfg.stopword_rank)
                and not _EXTRA_SIZE.match(text) and read_number(tokens, i) is None)

    def uncommon(i: int) -> bool:
        """Rarer than an ordinary word. "friday", "nice" and "new" are no unknown colour or
        style; "purple", "teal" and "violet" are."""
        rank = english.rank(tokens[i].text)
        return rank is None or rank >= cfg.name_min_rank

    def name_like(i: int) -> bool:
        """What a brand looks like: capitalised or not an English word at all, and rarer than an
        ordinary word (so "Friday" and "December" are not brands)."""
        rank = english.rank(tokens[i].text)
        if rank is not None and rank < cfg.name_min_rank:
            return False
        return tokens[i].raw[:1].isupper() or rank is None

    for i, token in enumerate(tokens):
        before = tokens[i - 1] if i > 0 and not tokens[i - 1].clause_end else None
        after = tokens[i + 1] if i + 1 < len(tokens) and not token.clause_end else None

        if plain(i):
            brand = None
            if before and before.text in cfg.brand_cues and name_like(i):
                brand = f"after '{before.text}'"
            elif after and after.text in cfg.brand_postfix and name_like(i):
                brand = f"before '{after.text}'"
            elif (before and token.raw[:1].isupper() and name_like(i)
                  and before.text not in cfg.not_a_name_after):
                brand = "capitalised in mid-sentence"
            if brand:
                out.append(Unresolved("brand", token.text, i, i + 1, brand))
                continue
            if before and before.text in _COLOUR_WORDS or after and after.text in _COLOUR_WORDS:
                out.append(Unresolved("colour", token.text, i, i + 1, "next to 'colour'"))
                continue
            if (i + 1) in product_starts and after is not None and uncommon(i):
                kind = "brand" if token.raw[:1].isupper() and name_like(i) else "brand, colour or style"
                out.append(Unresolved(kind, token.text, i, i + 1, "before a product word"))
                continue
            if before and before.text == "in" and uncommon(i):        # "in purple"
                out.append(Unresolved("colour or style", token.text, i, i + 1, "after 'in'"))
                continue

        # sizes: a cue next to a size nothing answers to
        cue_before = before is not None and before.text in SIZE_CUES
        cue_after = after is not None and after.text in SIZE_CUES
        if (cue_before or cue_after) and i not in covered:
            reading_n = read_number(tokens, i)
            if reading_n and reading_n.value < 100 and lexicon.size_from_number(reading_n.value) is None:
                out.append(Unresolved("size", token.text, i, i + 1, "no such size in the shop"))
            elif _EXTRA_SIZE.match(token.text):
                out.append(Unresolved("size", token.text, i, i + 1, "no such size in the shop"))
    return out
