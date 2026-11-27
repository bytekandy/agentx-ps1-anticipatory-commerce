"""Slot extraction: turn the words heard so far into slot mentions.

A *mention* says "words i to j mean slot S has value V, with this confidence". This module is a
pure function of the words so far: no memory, no search, no decisions. Whether a mention
replaces an earlier one (a correction) or is only an afterthought is the job of the filter
state in Stage 4; this module only reports what the words say.

Slots: category, colour, brand, size, max_price, min_price.

How a word becomes a mention
  * Phrases (category, colour, brand, letter or word sizes) come from `Lexicon.lookup`. A
    letter size right beside a size cue ("size M", "M size") is trusted more than a bare "M".
  * A misspelt word is corrected first (`spelling.py`); a mention that rests on a corrected
    word has `kind="fuzzy"` and lower confidence.
  * Numbers come from `read_number`. A number is a *size* if a size cue sits beside it
    ("size 9", "UK 10", "32 waist"), a *price* if a price cue does ("under 1500", "1500 tak"),
    and a cue before the number beats a cue after it. A number with no cue at all is a price
    if it is large ("Rs.1500"), and a weak size guess if it is small and a real size.

Words arrive one at a time, so a mention can be `complete=False`: "two thousand" may still
become "two thousand five hundred". Callers treat incomplete mentions as "wait", never as
facts.
"""
from dataclasses import dataclass, replace
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from .config import DEFAULT_CONFIG, Config
from .lexicon import PRICE_CUES, SIZE_CUES, Lexicon
from .numbers import NumberReading, read_number
from .tokens import Token

SLOTS = ("category", "colour", "brand", "size", "max_price", "min_price")

# Words that sit between a price cue and its number: "budget of 800", "under about 1500".
_PRICE_FILLER = frozenset({"of", "is", "around", "about", "approx"})

# Cues that make the number *after* them a lower bound ("above 2000"). The upper-bound cues are
# `lexicon.PRICE_CUES`; "not more than" must beat "more than", so the longest match wins.
_MIN_PRICE_CUES = frozenset({
    ("above",), ("over",), ("atleast",), ("at", "least"), ("minimum",), ("min",),
    ("more", "than"), ("starting", "at"), ("starting", "from"),
})

# Cues that follow the number: "1500 tak", "1500 or less". The cues that precede a number
# ("under", "budget") are deliberately absent, or "size 9 under 1500" would make 9 a price.
# A number followed by one of these counts something else: "my 8 year old", "2 pairs", "10th".
NOT_A_SIZE_AFTER = frozenset({"year", "years", "yr", "yrs", "old", "pair", "pairs", "pcs", "pieces",
                              "th", "st", "nd", "rd", "days", "day", "baje", "saal", "kg", "percent"})

_POSTFIX_ONLY = frozenset({("tak",), ("se", "kam"), ("ke", "andar")})   # never a cue BEFORE a number
_POSTFIX_PRICE_CUES = frozenset({
    ("tak",), ("se", "kam"), ("ke", "andar"), ("rupees",), ("rupee",), ("rs",), ("inr",),
    ("max",), ("maximum",), ("or", "less"), ("or", "below"), ("or", "under"),
    ("and", "below"), ("and", "under"),
})


@dataclass(frozen=True)
class SlotMention:
    slot: str            # one of SLOTS
    value: object        # catalogue string for text slots and sizes ("9", "XL"); int for prices
    start: int           # index of the first token
    end: int             # index after the last token
    confidence: float
    complete: bool       # False while the next word could still change the value
    kind: str            # "exact", "variant", "synonym", "fuzzy", "digits", "k" or "words"
    via: str             # the clue: "phrase", "size-cue", "size-after", "price-cue",
                         # "price-after" or "bare"


# ----------------------------------------------------------------------------- public API

@dataclass(frozen=True)
class Reading:
    """What slot extraction saw: the (spell-corrected) words, which of them were corrected, and
    the mentions found. The unknown-word detector needs the words as well as the mentions."""
    tokens: Tuple[Token, ...]
    corrected: FrozenSet[int]
    mentions: Tuple["SlotMention", ...]


def _drop_possessives(tokens: Sequence[Token], lexicon: Lexicon) -> List[Token]:
    """"Pacevo's black shoes": drop the 's when what is left is a word the lexicon knows.
    ("it's" stays as it is: "it" names nothing.)"""
    out = []
    for token in tokens:
        stem = token.text[:-2] if token.text.endswith(("'s", "\u2019s")) else None
        out.append(replace(token, text=stem) if stem and stem in lexicon.known_words else token)
    return out


def extract_mentions(tokens: Sequence[Token], lexicon: Lexicon,
                     config: Config = DEFAULT_CONFIG, final: bool = False) -> List[SlotMention]:
    """All slot mentions in the words so far; see `read_words` for the full reading."""
    return list(read_words(tokens, lexicon, config, final).mentions)


def read_words(tokens: Sequence[Token], lexicon: Lexicon, config: Config = DEFAULT_CONFIG,
               final: bool = False) -> Reading:
    """All slot mentions in the words so far, in order of position.

    Deterministic and stateless: the result depends only on `tokens`. A mention that is
    `complete` never changes value when more words arrive (a test enforces this).

    Pass `final=True` when the request has ended (`finish()`): no word can follow, so a number
    that was only waiting for a possible next word ("under two thousand") is settled.
    """
    mentions: List[SlotMention] = []
    tokens = _drop_possessives(tokens, lexicon)
    tokens, corrected = lexicon.corrector.correct_tokens(tokens)
    corrected_tokens = tuple(tokens)
    i = 0
    while i < len(tokens):
        if _ends_multiword_price_cue(tokens, i):         # "price cap": the cue claims "cap"
            i += 1
            continue
        phrase = lexicon.lookup(tokens, i)
        if phrase:
            mention = _phrase_mention(tokens, i, phrase, config)
            if any(j in corrected for j in range(mention.start, mention.end)):
                mention = replace(mention, kind="fuzzy",
                                  confidence=min(mention.confidence, config.vocab.confidence_fuzzy))
            mentions.append(mention)
            i += phrase.length
            continue
        reading = read_number(tokens, i)
        if reading:
            if final:
                reading = replace(reading, complete=True)
            mention = _number_mention(tokens, i, reading, lexicon, config)
            if mention:
                mentions.append(mention)
            i += reading.length
            continue
        i += 1
    return Reading(corrected_tokens, corrected, tuple(mentions))


def latest_filters(mentions: Sequence[SlotMention], lexicon: Lexicon,
                   config: Config = DEFAULT_CONFIG) -> Dict[str, object]:
    """A naive reading: for each slot, the last trusted and complete mention wins.

    Used to measure extraction on its own (`scripts/check_reader.py slots`). It does not understand
    corrections or afterthoughts; Stage 4's filter state replaces it. The keys match the
    `filters` of a dev request; `min_price` appears only when the request has one.
    """
    floor = config.slots.min_trusted_confidence
    trusted = sorted((m for m in mentions if m.complete and m.confidence >= floor),
                     key=lambda m: m.start)
    filters: Dict[str, object] = {slot: None for slot in
                                  ("category", "colour", "size", "brand", "max_price")}
    for m in trusted:
        if m.slot != "size":
            filters[m.slot] = m.value
    category = filters["category"]
    for m in trusted:
        if m.slot == "size" and size_fits_category(str(m.value), category, lexicon):
            filters["size"] = m.value
    return filters


# ----------------------------------------------------------------------------- phrases

def _phrase_mention(tokens, i, phrase, config) -> SlotMention:
    confidence, via = phrase.confidence, "phrase"
    if phrase.slot == "size" and _size_cue_beside(tokens, i, i + phrase.length):
        confidence, via = max(confidence, config.slots.confidence_size_cued), "size-cue"
    return SlotMention(phrase.slot, phrase.value, i, i + phrase.length, confidence, True,
                       phrase.kind, via)


def _size_cue_beside(tokens, start, end) -> bool:
    before = start > 0 and tokens[start - 1].text in SIZE_CUES
    after = end < len(tokens) and tokens[end].text in SIZE_CUES and not tokens[end - 1].clause_end
    return before or after


def size_fits_category(size: str, category, lexicon: Lexicon) -> bool:
    """Can this size belong to this category? Unknown category: anything goes.

    A number size must be one of the category's sizes (9 for sandals, 32 for jeans) and a
    category without sizes (backpacks, caps, ...) takes none.
    """
    if category is None:
        return True
    if category in lexicon.unsized_categories:
        return False
    if size.isdigit():
        return lexicon.size_from_number(int(size), category) is not None
    # A letter size needs a category sold in letter sizes: "runs small" says nothing about a
    # sneaker's size.
    return size in lexicon.sizes_for_category(category)


# ----------------------------------------------------------------------------- numbers

def _number_mention(tokens, start, reading: NumberReading, lexicon: Lexicon,
                    config: Config) -> Optional[SlotMention]:
    end = start + reading.length
    size = lexicon.size_from_number(reading.value)        # None unless a catalogue number size
    before = _cue_before(tokens, start)
    if before:
        kind, slot = before
        if kind == "price":
            mention = _price(slot, start, end, reading, config.slots.confidence_price_cued,
                             "price-cue", config)
        else:
            mention = (_size(start, end, reading, size, config.slots.confidence_size_cued,
                             "size-cue") if size else None)
        if mention:
            return mention
        # The cue does not fit this number ("under 50" is no price, "10 UK 3000 max": the UK
        # belongs to the 10), so look at the other clues.

    if _has_currency_mark(tokens[start]):               # "Rs.1500", "₹3,000", "1500/-"
        return _price("max_price", start, end, reading, config.slots.confidence_price_cued,
                      "price-cue", config)

    if size and not tokens[end - 1].clause_end and end < len(tokens) \
            and tokens[end].text in SIZE_CUES:
        return _size(start, end, reading, size, config.slots.confidence_size_postfix,
                     "size-after")
    after = _postfix_price_slot(tokens, end)
    if after:
        return _price(after, start, end, reading, config.slots.confidence_price_postfix,
                      "price-after", config)

    if reading.value >= config.vocab.min_price:
        bare = (config.slots.confidence_price_bare_digits if reading.form != "words"
                else config.slots.confidence_price_bare_words)
        return _price("max_price", start, end, reading, bare, "bare", config)
    if size and not (end < len(tokens) and tokens[end].text in NOT_A_SIZE_AFTER):
        return _size(start, end, reading, size, config.slots.confidence_size_bare_number, "bare")
    return None


def _has_currency_mark(token: Token) -> bool:
    """Normalisation strips "Rs." and "₹" from a number; the raw word still shows them."""
    raw = token.raw.lower().lstrip("(")
    return raw.startswith(("rs", "inr", "₹")) or raw.rstrip(".,;!?").endswith("/-")


def _size(start, end, reading, size, confidence, via) -> Optional[SlotMention]:
    if size is None:
        return None
    return SlotMention("size", size, start, end, confidence, _size_is_final(reading),
                       reading.form, via)


def _size_is_final(reading: NumberReading) -> bool:
    """A size number is settled early: "9" or "eight" cannot grow into another real size.

    Only a tens word can ("thirty" may become "thirty two"), and a number word is always
    settled once the next word shows it is over.
    """
    return reading.complete or reading.form == "digits" or reading.value < 20


def _price(slot, start, end, reading, confidence, via, config) -> Optional[SlotMention]:
    vocab = config.vocab
    if reading.value > vocab.max_price:
        return None
    in_range = reading.value >= vocab.min_price
    if not in_range and reading.complete:
        return None                                   # "under 50": not a price in this shop
    # Below the minimum but still growing ("under 15" may become "15 hundred"): keep it, but
    # mark it incomplete so nobody acts on it.
    return SlotMention(slot, reading.value, start, end, confidence,
                       reading.complete and in_range, reading.form, via)


# ----------------------------------------------------------------------------- cues

def _build_cue_table() -> Dict[str, List[Tuple[Tuple[str, ...], str]]]:
    """Price cues indexed by their last word, each with the slot a following number fills."""
    table: Dict[str, List[Tuple[Tuple[str, ...], str]]] = {}
    for cues, slot in ((PRICE_CUES, "max_price"), (_MIN_PRICE_CUES, "min_price")):
        for cue in cues:
            if cue not in _POSTFIX_ONLY:       # "1500 tak 34 waist": tak belongs to the 1500
                table.setdefault(cue[-1], []).append((cue, slot))
    return table


_CUES_BY_LAST_WORD = _build_cue_table()
_MULTIWORD_CUES = tuple(cue for cue in set(PRICE_CUES) | _MIN_PRICE_CUES
                        if len(cue) > 1 and cue not in _POSTFIX_ONLY)


def _cue_before(tokens, start) -> Optional[Tuple[str, Optional[str]]]:
    """The cue just before the number at `start`: ("size", None), ("price", slot) or None.

    A pause after the cue ("size, nine", "under, 1500") does not detach it. Filler words such
    as "of" are skipped ("budget of 800").
    """
    j = start - 1
    while j >= 0 and tokens[j].text in _PRICE_FILLER and not tokens[j].clause_end:
        j -= 1
    if j < 0:
        return None
    if tokens[j].text in SIZE_CUES:
        return "size", None
    best: Optional[Tuple[Tuple[str, ...], str]] = None
    for cue, slot in _CUES_BY_LAST_WORD.get(tokens[j].text, ()):
        n = len(cue)
        if j + 1 >= n and tuple(t.text for t in tokens[j + 1 - n:j + 1]) == cue \
                and (best is None or n > len(best[0])):
            best = (cue, slot)
    return ("price", best[1]) if best else None


def cue_awaiting_number(tokens: Sequence[Token]) -> bool:
    """True if the words so far end on a size or price cue that has not met its number yet.

    "within Rs.", "up to", "budget of", "size": the shopper is mid-phrase and a value is
    on its way. ("9 UK" also counts for one word: that cue closes a number already heard.)
    """
    if not tokens:
        return False
    return _cue_before(tokens, len(tokens)) is not None or _inside_cue(tokens)


def _inside_cue(tokens: Sequence[Token]) -> bool:
    """The words end partway through a multi-word cue: "up" of "up to", "not more" of
    "not more than"."""
    texts = [t.text for t in tokens[-3:]]
    for cue in _MULTIWORD_CUES:
        for n in range(1, len(cue)):
            if texts[-n:] == list(cue[:n]):
                return True
    return False


def _ends_multiword_price_cue(tokens: Sequence[Token], i: int) -> bool:
    """tokens[i] is the last word of a two-or-more word price cue ("price cap", "not more than")."""
    for cue, _ in _CUES_BY_LAST_WORD.get(tokens[i].text, ()):
        n = len(cue)
        if n > 1 and i + 1 >= n and tuple(t.text for t in tokens[i + 1 - n:i + 1]) == cue:
            return True
    return False


def _postfix_price_slot(tokens, end) -> Optional[str]:
    """"max_price" if a price cue follows the number ("1500 tak"), else None."""
    if end > 0 and tokens[end - 1].clause_end:
        return None
    following = tuple(t.text for t in tokens[end:end + 2])
    for cue in _POSTFIX_PRICE_CUES:
        if following[:len(cue)] == cue:
            return "max_price"
    return None
