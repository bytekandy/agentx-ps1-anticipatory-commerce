"""Filter state: what the shopper wants so far, how sure we are, and how stable that is.

`build_snapshot(tokens, ...)` turns the words heard so far into a `Snapshot`: one belief per
slot (value, confidence, revision history) plus the warning signs the decision policy needs.
It is a pure function of the words, so the same words always give the same snapshot.
`FilterState` is a thin wrapper that keeps the words and takes them one at a time.

What the state adds on top of slot extraction (Stage 3)
  * **Revisions.** A second value for a slot replaces the first. If a correction marker
    ("oops", "sorry", "I meant", "make that", ...) sits just before it, the revision is
    `marked` and trusted; without a marker the new value still wins (the last word is usually
    right) but at lower confidence.
  * **Restatements.** A bare number right after a marker, for a slot that already has a value
    ("size eight, actually six"), is read as the new value of that slot.
  * **Pending correction.** Once a marker is heard and no mention has followed yet, a
    replacement is on its way: `correction_pending` is True for a few words. The policy must
    not commit then.
  * **Pending numbers.** A price that may still grow ("under two thousand") is listed in
    `pending_slots` and is not part of the reading until it settles.
  * **Late constraints.** A mention introduced by "and", "also", "oh" or "aur" is flagged
    `late`. It is an ordinary slot value; the flag is for the trace and the demo.
  * **Fit with the category.** A size that cannot belong to the category (size 9 for jeans,
    any size for a backpack) is dropped once the category is known, even if the category
    comes later in the request.

The state never searches and never decides to commit; that is the policy's job (Stage 5).
"""
from dataclasses import dataclass, replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .config import DEFAULT_CONFIG, Config
from .lexicon import CORRECTION_WORDS, LATE_WORDS, PRICE_CUES, SIZE_CUES, Lexicon
from .slots import SlotMention, cue_awaiting_number, read_words, size_fits_category
from .unknown import Unresolved, find_unresolved
from .tokens import Token, make_tokens

# Two-word markers that the single-word list cannot express ("make that XXL", "make it Kudova").
# "make sure" is not a marker, which is why "make" alone is not in `CORRECTION_WORDS`.
MARKER_PHRASES = frozenset({("make", "that"), ("make", "it")})
# A word that, said last, almost always opens a two-word marker: wait one word to see.
MARKER_STARTERS = frozenset({"make"})

# Slots in the order the evaluator expects; `min_price` is added only when it is present.
REPORTED_SLOTS = ("category", "colour", "size", "brand", "max_price")


# ----------------------------------------------------------------------------- data types

@dataclass(frozen=True)
class SlotBelief:
    """The current reading of one slot."""
    slot: str
    value: object
    confidence: float
    start: int                              # token span of the mention that set the value
    end: int
    via: str                                # the clue that classified it (see SlotMention)
    history: Tuple[Tuple[object, int, int], ...] = ()    # replaced values: (value, start, end)
    marked: bool = False                    # the latest revision followed a correction marker
    late: bool = False                      # introduced by "and", "also", "oh", "aur"

    @property
    def revisions(self) -> int:
        return len(self.history)


@dataclass(frozen=True)
class Marker:
    """A correction marker: tokens[start:end]."""
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Snapshot:
    """Everything the policy may look at after one more word."""
    words_seen: int
    slots: Mapping[str, SlotBelief]
    markers: Tuple[Marker, ...]
    pending_slots: Tuple[str, ...]          # a number that may still grow
    correction_pending: bool                # a marker was heard and its replacement has not come
    at_clause_end: bool                     # the last word ended with , . ; ! ?
    quiet_words: int                        # words since the last mention ended
    cue_pending: bool = False               # the words end on a cue awaiting its number, or on "make"
    unresolved: Tuple[Unresolved, ...] = () # constraints stated that nothing in the shop answers to
    unsettled_factor: float = 0.5

    @property
    def settled(self) -> bool:
        """No correction on its way, no number still growing, no cue awaiting its number, and
        no constraint stated that we cannot represent (an unknown brand, size or colour)."""
        return (not self.correction_pending and not self.pending_slots and not self.cue_pending
                and not self.unresolved)

    @property
    def filters(self) -> Dict[str, object]:
        """The reading in the shape `dev.jsonl` and the evaluator use."""
        out: Dict[str, object] = {k: (self.slots[k].value if k in self.slots else None)
                                  for k in REPORTED_SLOTS}
        if "min_price" in self.slots:
            out["min_price"] = self.slots["min_price"].value
        return out

    @property
    def confidence(self) -> float:
        """The weakest slot's confidence, halved while unsettled; 0 with nothing read."""
        if not self.slots:
            return 0.0
        weakest = min(b.confidence for b in self.slots.values())
        return weakest if self.settled else weakest * self.unsettled_factor


# ----------------------------------------------------------------------------- the pure core

def find_markers(tokens: Sequence[Token]) -> List[Marker]:
    """Correction markers in the words so far, in order.

    "no" inside a price cue ("no more than 1500") is not a correction.
    """
    markers: List[Marker] = []
    for i, token in enumerate(tokens):
        pair = tuple(t.text for t in tokens[i:i + 2])
        if pair in MARKER_PHRASES:
            markers.append(Marker(i, i + 2, " ".join(pair)))
        elif token.text in CORRECTION_WORDS and not _starts_price_cue(tokens, i):
            markers.append(Marker(i, i + 1, token.text))
    return markers


def _starts_price_cue(tokens: Sequence[Token], i: int) -> bool:
    for cue in PRICE_CUES:
        n = len(cue)
        if n > 1 and cue[0] == tokens[i].text \
                and tuple(t.text for t in tokens[i:i + n]) == cue:
            return True
    return False


def build_snapshot(tokens: Sequence[Token], lexicon: Lexicon, config: Config = DEFAULT_CONFIG,
                   final: bool = False) -> Snapshot:
    """Read the words so far into a snapshot. `final=True` marks the end of the request."""
    cfg = config.state
    reading = read_words(tokens, lexicon, config, final=final)
    tokens = reading.tokens            # spell-corrected: "sorey" is the marker "sorry", "saiz" a cue
    mentions = sorted(reading.mentions, key=lambda m: m.start)
    markers = find_markers(tokens)

    events: Dict[str, List[_Event]] = {}
    pending: List[str] = []
    heard: List[SlotMention] = []                       # mentions that count (not weak guesses)
    for m in mentions:
        marked = _marker_before(markers, m.start, cfg.correction_window)
        confidence = m.confidence
        if m.via == "bare" and marked and m.slot in events:
            confidence = max(confidence, cfg.restate_confidence)       # a restatement
        if confidence < cfg.min_belief_confidence:
            continue                                                   # a weak guess
        heard.append(m)
        if not m.complete:
            if m.slot not in pending:
                pending.append(m.slot)
            continue
        late = _late_before(tokens, m.start, cfg.late_window)
        events.setdefault(m.slot, []).append(_Event(m, confidence, marked is not None, late))

    category = _fold("category", events.get("category", []), cfg)
    unresolved: List[Unresolved] = find_unresolved(reading, lexicon, config)
    beliefs: Dict[str, SlotBelief] = {}
    if category:
        beliefs["category"] = category
    for slot, slot_events in events.items():
        if slot == "category":
            continue
        if slot == "size":
            fitting = [e for e in slot_events
                       if size_fits_category(str(e.mention.value),
                                             category.value if category else None, lexicon)]
            if not fitting:                    # a size was asked for that this category lacks
                unresolved += [Unresolved("size", str(e.mention.value), e.mention.start,
                                          e.mention.end,
                                          f"the shop has no size {e.mention.value} for "
                                          f"{category.value}")
                               for e in slot_events if e.mention.via in ("size-cue", "size-after")]
            slot_events = fitting
        belief = _fold(slot, slot_events, cfg)
        if belief:
            beliefs[slot] = belief

    words = len(tokens)
    last_end = max((m.end for m in heard), default=0)
    return Snapshot(
        words_seen=words,
        slots=beliefs,
        markers=tuple(markers),
        pending_slots=tuple(pending),
        correction_pending=_correction_pending(markers, heard, words, cfg),
        cue_pending=_something_follows(tokens, mentions),
        unresolved=tuple(sorted(unresolved, key=lambda u: u.start)),
        at_clause_end=bool(tokens) and tokens[-1].clause_end,
        quiet_words=words - last_end,
        unsettled_factor=cfg.unsettled_factor,
    )


@dataclass(frozen=True)
class _Event:
    mention: SlotMention
    confidence: float
    marked: bool
    late: bool


def _marker_before(markers: Sequence[Marker], start: int, window: int) -> Optional[Marker]:
    """The nearest marker that ended at most `window` words before `start`."""
    best = None
    for marker in markers:
        if marker.end <= start and start - marker.end <= window:
            best = marker
    return best


def _late_before(tokens: Sequence[Token], start: int, window: int) -> bool:
    return any(t.text in LATE_WORDS for t in tokens[max(0, start - window):start])


def _fold(slot: str, events: Sequence[_Event], cfg) -> Optional[SlotBelief]:
    """Turn the mentions of one slot, in order, into a belief with its revision history."""
    belief: Optional[SlotBelief] = None
    for ev in events:
        m = ev.mention
        if belief is None:
            belief = SlotBelief(slot, m.value, ev.confidence, m.start, m.end, m.via,
                                late=ev.late)
        elif m.value == belief.value:                   # said again: trust the better reading
            belief = replace(belief, confidence=max(belief.confidence, ev.confidence))
        else:                                           # a revision
            confidence = (ev.confidence if ev.marked
                          else min(ev.confidence, cfg.unmarked_revision_confidence))
            belief = SlotBelief(slot, m.value, confidence, m.start, m.end, m.via,
                                belief.history + ((belief.value, belief.start, belief.end),),
                                marked=ev.marked, late=ev.late)
    return belief


def _something_follows(tokens: Sequence[Token], mentions: Sequence[SlotMention] = ()) -> bool:
    """The words end on a word that announces more: a size or price cue awaiting its number,
    or "make" (which may be about to become "make that"). "make sure" costs one word of wait.

    A cue that closes a size already heard ("M size", "XXL size", "size 8 UK") announces
    nothing: no number is coming.
    """
    if tokens and tokens[-1].text in SIZE_CUES and any(
            m.slot == "size" and m.end == len(tokens) - 1 for m in mentions):
        return bool(tokens[-1].text in MARKER_STARTERS)
    return cue_awaiting_number(tokens) or (bool(tokens) and tokens[-1].text in MARKER_STARTERS)


def _correction_pending(markers: Sequence[Marker], heard: Sequence[SlotMention],
                        words: int, cfg) -> bool:
    """A marker was heard, its replacement has not started, and the wait is not over yet.

    Any complete mention after the marker answers it; a number that is still growing does not.
    """
    for marker in markers:
        if words - marker.end > cfg.correction_window:
            continue                                    # nothing came: a false alarm
        answered = any(m.start >= marker.end and m.complete for m in heard)
        if not answered:
            return True
    return False


# ----------------------------------------------------------------------------- incremental

class FilterState:
    """Holds the words of one request and the snapshot after each of them."""

    def __init__(self, lexicon: Optional[Lexicon] = None, config: Config = DEFAULT_CONFIG):
        self.lexicon = lexicon or Lexicon.from_catalogue()
        self.config = config
        self.reset()

    def reset(self) -> None:
        """Start a new request."""
        self.tokens: List[Token] = []
        self.snapshot = build_snapshot(self.tokens, self.lexicon, self.config)

    def push(self, word: str) -> Snapshot:
        """Take the next word of the request and return the new snapshot.

        Past `max_live_words` the snapshot is no longer refreshed (see `StateConfig`): a request
        that long gets no early commit, but `finish()` still reads all of it.
        """
        self.tokens.extend(make_tokens(word))
        if len(self.tokens) <= self.config.state.max_live_words:
            self.snapshot = build_snapshot(self.tokens, self.lexicon, self.config)
        return self.snapshot

    def finish(self) -> Snapshot:
        """The request is over: nothing more can follow, so settle numbers that were waiting."""
        self.snapshot = build_snapshot(self.tokens, self.lexicon, self.config, final=True)
        return self.snapshot
