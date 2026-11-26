"""All tunable numbers in one place.

Every setting lives in a frozen dataclass grouped by area, so each stage adds its own block and
logic modules contain no magic numbers. Later stages append blocks (slots, state, policy) to
`Config`; they do not edit existing ones.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class VocabConfig:
    """Vocabulary and number reading (Stage 2)."""

    # How much we trust a phrase match, by how it was found.
    confidence_exact: float = 0.95      # a word taken straight from the catalogue
    confidence_variant: float = 0.90    # plural, hyphen or spacing variant of such a word
    confidence_synonym: float = 0.85    # a synonym we listed ("slides" for sandals)
    confidence_fuzzy: float = 0.60      # a one-letter misspelling of a brand

    # Misspelling tolerance. Only brand names are matched fuzzily: they are long, distinctive
    # words, while fuzzy colours or categories would turn "than" into "tan".
    fuzzy_enabled: bool = True
    fuzzy_min_length: int = 5

    # A number below this is not a price; above the maximum it is not a price either.
    min_price: int = 100
    max_price: int = 200_000


@dataclass(frozen=True)
class SlotConfig:
    """Slot extraction (Stage 3): how much we trust a number, by the clue that classified it."""

    # A size: a letter or number right beside a size cue ("size M", "UK 9", "waist 32").
    confidence_size_cued: float = 0.97
    confidence_size_postfix: float = 0.90       # the cue comes after the number ("9 UK", "32 waist")
    confidence_size_bare_number: float = 0.45   # a lone 6 to 11 or 28 to 36 with no clue at all

    # A price: a number after a price cue ("under 1500", "budget of 800", "max 1k").
    confidence_price_cued: float = 0.95
    confidence_price_postfix: float = 0.90      # the cue comes after ("1500 tak", "1500 or less")
    confidence_price_bare_digits: float = 0.75  # "Rs.1500" or "1500" with no cue word
    confidence_price_bare_words: float = 0.65   # "fifteen hundred" with no cue word

    # `latest_filters` (the naive last-mention-wins reading) ignores anything below this.
    min_trusted_confidence: float = 0.5


@dataclass(frozen=True)
class Config:
    vocab: VocabConfig = field(default_factory=VocabConfig)
    slots: SlotConfig = field(default_factory=SlotConfig)


DEFAULT_CONFIG = Config()
