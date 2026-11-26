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
class Config:
    vocab: VocabConfig = field(default_factory=VocabConfig)


DEFAULT_CONFIG = Config()
