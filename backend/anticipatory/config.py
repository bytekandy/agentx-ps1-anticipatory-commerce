"""All tunable numbers in one place.

Every setting lives in a frozen dataclass grouped by area, so each stage adds its own block and
logic modules contain no magic numbers. Later stages append blocks (slots, state, policy) to
`Config`; they do not edit existing ones.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class VocabConfig:
    """Vocabulary and number reading (Stage 2)."""

    # How much we trust a phrase match, by how it was found.
    confidence_exact: float = 0.95      # a word taken straight from the catalogue
    confidence_variant: float = 0.90    # plural, hyphen or spacing variant of such a word
    confidence_synonym: float = 0.85    # a synonym we listed ("slides" for sandals)
    confidence_fuzzy: float = 0.60      # a word that had to be spell-corrected (Stage 7)

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
class StateConfig:
    """Filter state and corrections (Stage 4)."""

    # A mention below this confidence is a weak guess and never becomes part of the reading.
    min_belief_confidence: float = 0.5

    # After a correction marker ("oops", "make that") the replacement normally follows within
    # 1 to 3 words in dev. For this many words the state reports `correction_pending`. The same
    # window decides whether a revision counts as announced by a marker.
    correction_window: int = 6

    # A bare number straight after a marker, for a slot that already has a value ("size eight,
    # actually six"), is read as a restatement and trusted this much.
    restate_confidence: float = 0.85

    # A new value for a slot that already had one, with no marker to explain it, still wins
    # (the last word is usually right) but is trusted less.
    unmarked_revision_confidence: float = 0.60

    # An afterthought word ("and", "also", "oh", "aur") this close before a mention marks the
    # mention as a late constraint.
    late_window: int = 3

    # The overall confidence reported to the evaluator is scaled by this while the reading is
    # unsettled (a correction is pending or a number may still grow).
    unsettled_factor: float = 0.5


@dataclass(frozen=True)
class PolicyConfig:
    """Search scheduling and the commit rule (Stage 5)."""

    # Candidate searches ask for this many results. Cost is per call, not per result, and a
    # long list lets the risk model see how many products are still in play.
    candidate_k: int = 50
    final_k: int = 10                 # the verification search in `finish()`

    # A belief weaker than this is not used as a search filter.
    min_search_confidence: float = 0.5

    # The commit rule is an expected-value comparison built from the score formula: a commit is
    # worth it when P(wrong) is below `break_even_risk(words_saved)`. These are the formula's
    # numbers: 0.6 points for a whole request of earliness, 13.3 words on average, and the
    # share of earliness a wrong commit typically forfeits on top of its -1.0.
    earliness_weight: float = 0.6
    avg_request_words: float = 13.3
    forfeit_share: float = 0.2
    words_saved_assumed: int = 1


@dataclass(frozen=True)
class RiskConfig:
    """The hand-coded risk estimate used until a learned model replaces it (Stage 5)."""

    base_risk: float = 0.01           # even a perfect-looking unique match can be overturned
    confidence_weight: float = 0.2    # added risk per unit of missing confidence
    hold_words: int = 1               # a correction usually follows its value within 1 to 3 words
    fresh_penalty: float = 0.5        # added risk while the last mention is younger than that
    # A pause (comma or period) right after the last word is where corrections start: in dev
    # every correction after a pause follows a value that ended with one.
    clause_end_penalty: float = 0.5
    unsettled_risk: float = 1.0       # a correction is pending or a number is still growing
    # In the hybrid, a state resting on a value read below this confidence (a spell-corrected
    # word, an unmarked revision) stays under the rules' caution instead of going to the model.
    rules_confidence_floor: float = 0.7


@dataclass(frozen=True)
class LearnedRiskConfig:
    """The learned risk model (Stage 6)."""

    # Multiplies the model's probability. Above 1 makes the agent more cautious than the model
    # says; it is the safety margin for the gap between synthetic training data and real requests.
    # None means "use the multiplier the trainer chose and stored in the model file".
    safety_multiplier: Optional[float] = None


@dataclass(frozen=True)
class SpellingConfig:
    """Noisy-channel spelling correction (Stage 7)."""

    enabled: bool = True
    min_length: int = 4               # three letters or fewer are never corrected ("tan", "red")
    same_first_letter: bool = True    # people rarely mistype the first letter

    # Edit costs: the channel model. Cheap edits are the common slips.
    cost_neighbour_key: float = 0.5   # pressed the key next to the right one
    cost_transposition: float = 0.6   # two letters swapped
    cost_doubled: float = 0.6         # a doubled letter typed once or three times
    cost_indel: float = 1.0           # any other letter added or left out
    cost_substitution: float = 1.0    # any other letter changed

    # The most an edit may cost, by word length: short words are the easiest to confuse.
    max_cost_short: float = 0.7       # four letters: only the cheapest single slip
    max_cost_medium: float = 1.0      # five or six letters: one ordinary slip
    max_cost_long: float = 1.7        # seven or more: one ordinary slip plus a cheap one

    channel_weight: float = 2.0       # how strongly the channel outweighs the word prior
    min_margin: float = 0.5           # the best candidate must beat the runner-up by this


@dataclass(frozen=True)
class Config:
    vocab: VocabConfig = field(default_factory=VocabConfig)
    slots: SlotConfig = field(default_factory=SlotConfig)
    state: StateConfig = field(default_factory=StateConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    learned: LearnedRiskConfig = field(default_factory=LearnedRiskConfig)
    spelling: SpellingConfig = field(default_factory=SpellingConfig)


DEFAULT_CONFIG = Config()
