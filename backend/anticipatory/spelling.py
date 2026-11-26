"""Noisy-channel spelling correction for the words that name a product.

A shopper typing fast writes "snekers", "blak" or "Pacvo". Spelling correction as search and
speech systems do it: of all the words we know, which one most probably produced what was
typed? By Bayes that is the word with the best

    prior(word)  x  channel(typed | word)

  * the **prior** is how common the word is in the shop (how many catalogue rows use it);
  * the **channel** says how likely it is to mistype that word that way: a slip to a
    neighbouring key, two letters swapped or a doubled letter are cheap; any other change costs
    more. Costs are summed edit distance, weighted.

Only words that name a product are corrected (categories, colours, brands, sizes), never cue
words or numbers. A typed word is left alone when

  * it is already a word we know, or an ordinary English word we must not "fix" ("than" is not
    a mistyped "tan", "while" is not a mistyped "white");
  * it is short (when both words have four letters only the cheapest edits are allowed;
    three letters or fewer are never corrected);
  * it starts with a different letter than every candidate, or
  * no candidate wins clearly: a runner-up almost as good means we do not know.

A corrected word carries lower confidence (see `SlotMention.kind == "fuzzy"`), so the policy
treats a request that rests on a correction with extra caution.
"""
import math
from dataclasses import replace
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .config import DEFAULT_CONFIG, SpellingConfig
from .tokens import Token

# Ordinary words a shopper uses around a request, and clothing words the catalogue does not
# sell. They are never corrected: a typo-correct that turns "while" into "white", or "shorts"
# into "shirts", is worse than missing a typo. The words that appear in the
# catalogue's own titles and descriptions are added automatically (`Lexicon.catalogue_words`).
COMMON_WORDS: FrozenSet[str] = frozenset("""
about above after again also always another anyone anything around away back because been before
being below best better between bring brought budget buying came care case cause change cheap
cheaper check choose clean close come comes coming could dont done down each easy else enough even
ever every everything fast feel find fine first flashy follow found from gift give given going good
great hand happy have having help here hope hurry idea into just keep kind know last later least
less let like likely line little long look looking made make makes many matter maybe mean means
meant might more most much must need needs never next nice nothing offer often once only open order
other over part party people perhaps pick place plan please plus price pretty quick quite rather
really right same save say see seem seen send several shall should show shown since small some
something soon sort sorry sound still such sure take tell than thank thanks that their them then
there these they thing things think this those though thought through time today together told too
took toward try under until upon used useful usual very want wanted wants wear week well went were
what when where whether which while whole will wish with within without wonder work would write
wrong year yeah years your yourself
shorts short skirt skirts socks sock belt belts tie ties scarf scarves gloves sweater sweaters
blazer blazers suit suits boots boot heels loafers slipper slippers sleeve sleeves collar pocket
pockets laces strap straps trouser trousers leggings saree sarees lehenga shawl muffler towel
earring earrings necklace ring bracelet sunglasses glasses bottle umbrella helmet
aapke bhai bhaiya chahiye chahie dikha dikhao dikhana hain karo kitna kuch matlab milega mujhe nahi
nahin paas wala wali yaar zara abhi bahut theek accha achha
""".split())

_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")


def _build_neighbours() -> Dict[str, FrozenSet[str]]:
    """Keys next to each other on a QWERTY keyboard. Rows are staggered: a key touches the
    ones left and right of it, two keys in the row above (same column and one to the right)
    and two in the row below (same column and one to the left)."""
    near: Dict[str, Set[str]] = {}
    for r, row in enumerate(_ROWS):
        for c, ch in enumerate(row):
            around = {(r, c - 1), (r, c + 1), (r - 1, c), (r - 1, c + 1),
                      (r + 1, c - 1), (r + 1, c)}
            near[ch] = {_ROWS[r2][c2] for r2, c2 in around
                        if 0 <= r2 < len(_ROWS) and 0 <= c2 < len(_ROWS[r2])}
    return {ch: frozenset(s) for ch, s in near.items()}


NEIGHBOURS = _build_neighbours()


def edit_cost(typed: str, word: str, cfg: SpellingConfig, limit: float) -> Optional[float]:
    """Weighted edit distance from `word` to `typed` (optimal string alignment), or None when
    it is above `limit`. Substituting a neighbouring key, swapping two letters and a doubled
    letter are the cheap edits."""
    n, m = len(typed), len(word)
    if abs(n - m) > 2:
        return None
    INF = float("inf")
    d = [[INF] * (m + 1) for _ in range(n + 1)]
    d[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            here = d[i][j]
            if here == INF:
                continue
            if i < n and j < m:
                if typed[i] == word[j]:
                    sub = 0.0
                elif typed[i] in NEIGHBOURS.get(word[j], ()):
                    sub = cfg.cost_neighbour_key
                else:
                    sub = cfg.cost_substitution
                d[i + 1][j + 1] = min(d[i + 1][j + 1], here + sub)
                if i + 1 < n and j + 1 < m and typed[i] == word[j + 1] and typed[i + 1] == word[j]:
                    d[i + 2][j + 2] = min(d[i + 2][j + 2], here + cfg.cost_transposition)
            if i < n:                               # an extra letter in what was typed
                double = i > 0 and typed[i] == typed[i - 1]
                d[i + 1][j] = min(d[i + 1][j], here + (cfg.cost_doubled if double else cfg.cost_indel))
            if j < m:                               # a letter missing from what was typed
                double = j > 0 and word[j] == word[j - 1]
                d[i][j + 1] = min(d[i][j + 1], here + (cfg.cost_doubled if double else cfg.cost_indel))
    cost = d[n][m]
    return cost if cost <= limit else None


class SpellingCorrector:
    """Corrects single typed words against a weighted vocabulary. Results are cached."""

    def __init__(self, weights: Mapping[str, float], guard: Iterable[str] = (),
                 config: SpellingConfig = DEFAULT_CONFIG.spelling):
        self.cfg = config
        self.weights = {w: v for w, v in weights.items() if len(w) >= config.min_length}
        self.known: FrozenSet[str] = frozenset(weights)
        self.guard: FrozenSet[str] = frozenset(guard) | COMMON_WORDS
        self._cache: Dict[str, Optional[str]] = {}

    def limit(self, length: int) -> float:
        cfg = self.cfg
        if length < cfg.min_length:
            return 0.0
        if length <= 4:
            return cfg.max_cost_short
        return cfg.max_cost_medium if length <= 6 else cfg.max_cost_long

    def correct(self, text: str) -> Optional[str]:
        """The known word `text` was most probably meant to be, or None."""
        if text in self._cache:
            return self._cache[text]
        result = self._correct(text)
        self._cache[text] = result
        return result

    def _correct(self, text: str) -> Optional[str]:
        cfg = self.cfg
        if (not cfg.enabled or len(text) < cfg.min_length or not text.isascii()
                or not text.isalpha() or text in self.known or text in self.guard):
            return None
        scored: List[Tuple[float, str]] = []
        for word, weight in self.weights.items():
            if abs(len(word) - len(text)) > 1 + (len(text) >= 7):
                continue
            if cfg.same_first_letter and word[0] != text[0]:
                continue
            cost = edit_cost(text, word, cfg, self.limit(max(len(text), len(word))))
            if cost is not None:
                scored.append((math.log(weight) - cfg.channel_weight * cost, word))
        if not scored:
            return None
        scored.sort(reverse=True)
        if len(scored) > 1 and scored[0][0] - scored[1][0] < cfg.min_margin:
            return None                              # two candidates almost as good: unsure
        return scored[0][1]

    def correct_tokens(self, tokens: Sequence[Token]) -> Tuple[List[Token], FrozenSet[int]]:
        """Replace corrected words in a token list. Returns the new tokens and which indexes
        were corrected (so mentions that rest on them can be trusted less)."""
        out: List[Token] = []
        changed: Set[int] = set()
        for i, token in enumerate(tokens):
            fixed = self.correct(token.text)
            if fixed:
                out.append(replace(token, text=fixed))
                changed.add(i)
            else:
                out.append(token)
        return out, frozenset(changed)
