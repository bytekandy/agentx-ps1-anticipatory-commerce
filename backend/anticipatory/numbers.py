"""Reading numbers from tokens: digits, "3.5k", and English or Hindi number words.

`read_number(tokens, start)` answers one question: does a number begin at `start`, what is its
value, how many tokens does it use, and is it *complete*?

Completeness matters because words arrive one at a time. "eight" may be a shoe size or the
start of "eight hundred"; "9" may be a size or the start of "9 hundred". A reading is
`complete` only when the next word (or a clause-ending punctuation mark) shows it cannot grow.
Whether a number is a price or a size is decided later, from context words; this module only
reads the value.

Grammar notes (kept deliberately small):
  * "twenty five hundred" = 2500, "four thousand five hundred" = 4500, "one thousand seven
    hundred" = 1700, "five hundred fifty" = 550.
  * A bare unit directly after "hundred" is not merged ("five hundred seven" stops after
    "hundred"), so "seven hundred size seven" and "five hundred. one more thing" stay apart.
  * Hindi: "satrah sau" = 1700, "paanch hazaar" = 5000, "dhai hazaar" = 2500,
    "saadhe teen hazaar" = 3500. "tees" is left out: it is also the plural of "tee".
  * "and" inside a number ("five hundred and fifty") is not supported.
"""
import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .tokens import Token

_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9}
_TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
         "eighty": 80, "ninety": 90}
_HINDI_UNITS = {"ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
                "chhe": 6, "chhah": 6, "saat": 7, "aath": 8, "nau": 9}
_HINDI_TWO_DIGIT = {"das": 10, "gyarah": 11, "barah": 12, "terah": 13, "chaudah": 14,
                    "pandrah": 15, "solah": 16, "satrah": 17, "atharah": 18, "unnis": 19,
                    "bees": 20, "pachees": 25, "paintees": 35, "chalis": 40, "pachaas": 50,
                    "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90}
_HALVES = {"dedh": 1.5, "dhai": 2.5}
_MULTIPLIERS = {"hundred": 100, "sau": 100, "thousand": 1000, "hazaar": 1000}

MULTIPLIER_WORDS = frozenset(_MULTIPLIERS)

_K_FORM = re.compile(r"(\d+(?:\.\d+)?)k")
_DECIMAL = re.compile(r"\d+(?:\.\d+)?")
_PLAIN_DIGITS = re.compile(r"\d+")

# Which kind of atom may directly precede each kind. `None` means "start of the number".
_MAY_FOLLOW = {
    "unit": (None, "tens", "thousand"),
    "teen": (None, "thousand"),
    "tens": (None, "hundred", "thousand"),
    "half": (None, "thousand"),
    "hundred": (None, "unit", "teen", "tens", "half"),
    "thousand": (None, "unit", "teen", "tens", "half"),
}


@dataclass(frozen=True)
class NumberReading:
    value: int          # the number, rounded to a whole number
    length: int         # how many tokens it used
    form: str           # "digits", "k" or "words"
    complete: bool      # False while the next word could still extend it


def read_number(tokens: Sequence[Token], start: int) -> Optional[NumberReading]:
    """Read a number that begins at `tokens[start]`, or return None."""
    text = tokens[start].text
    following = tokens[start + 1].text if start + 1 < len(tokens) else None

    match = _K_FORM.fullmatch(text)
    if match:
        return NumberReading(_whole(float(match.group(1)) * 1000), 1, "k", True)

    if _DECIMAL.fullmatch(text):
        if following == "k":
            return NumberReading(_whole(float(text) * 1000), 2, "k", True)
        if following not in MULTIPLIER_WORDS:
            if not _PLAIN_DIGITS.fullmatch(text):
                return None                      # "3.5" with no unit is not a number we trust
            value = int(text)
            at_end = following is None
            # A small number at the end of the text could still become "9 hundred" or "2 k".
            complete = not (at_end and value < 100 and not tokens[start].clause_end)
            return NumberReading(value, 1, "digits", complete)

    return _read_words(tokens, start)


def _read_words(tokens: Sequence[Token], start: int) -> Optional[NumberReading]:
    total = 0.0         # thousands banked so far
    current = 0.0       # the group below one thousand being built
    last = None         # kind of the previous atom
    half_pending = False
    end = start         # index after the last fully consumed atom
    i = start
    closed = False      # a clause end or a word that cannot continue the number

    while i < len(tokens):
        following = tokens[i + 1].text if i + 1 < len(tokens) else None
        atom = _atom(tokens[i].text, following)
        if atom is None:
            closed = True
            break
        kind, value = atom

        if kind == "saadhe":                     # "saadhe teen hazaar": the next atom plus a half
            if half_pending or last not in (None, "thousand"):
                closed = True
                break
            half_pending = True
            i += 1
            continue
        if half_pending:
            if kind not in ("unit", "teen"):
                closed = True
                break
            value, kind, half_pending = value + 0.5, "half", False
        if last not in _MAY_FOLLOW[kind]:
            closed = True
            break

        if kind == "hundred":
            current = max(current, 1) * 100
        elif kind == "thousand":
            total += max(current, 1) * 1000
            current = 0.0
        else:
            current += value
        last = kind
        end = i + 1
        i += 1
        if tokens[end - 1].clause_end:
            closed = True
            break

    if end == start:
        return None
    complete = closed or i < len(tokens)
    return NumberReading(_whole(total + current), end - start, "words", complete)


def _atom(text: str, following: Optional[str]) -> Optional[Tuple[str, float]]:
    """Classify one word as a number atom: (kind, value), or None."""
    if text in _UNITS:
        return "unit", _UNITS[text]
    if text in _TEENS:
        return "teen", _TEENS[text]
    if text in _TENS:
        return "tens", _TENS[text]
    if text in _HINDI_UNITS:
        return "unit", _HINDI_UNITS[text]
    if text in _HINDI_TWO_DIGIT:
        return "teen", _HINDI_TWO_DIGIT[text]
    if text in _HALVES:
        return "half", _HALVES[text]
    if text in _MULTIPLIERS:
        return ("hundred" if _MULTIPLIERS[text] == 100 else "thousand"), _MULTIPLIERS[text]
    if text == "saadhe":
        return "saadhe", 0
    if "-" in text:                              # "twenty-five"
        head, _, tail = text.partition("-")
        if head in _TENS and tail in _UNITS:
            return "teen", _TENS[head] + _UNITS[tail]
    if _DECIMAL.fullmatch(text) and following in MULTIPLIER_WORDS:   # "15 hundred", "2 thousand"
        return "unit", float(text)
    return None


def _whole(x: float) -> int:
    return int(round(x))
