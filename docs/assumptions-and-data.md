# Assumptions, data sources and the evidence behind the numbers

Written for the Stage 9 review. It answers four questions: what data is used besides the
catalogue, what we assumed, which numbers are optimistic because dev influenced a choice, and what
was verified. Every figure below was measured; where something is a guess, it says so.

## 1. Data: what is real and what is synthetic

| Item | What it is | Where it comes from | Used for | In the repo? |
|---|---|---|---|---|
| `catalogue.csv`, `dev.jsonl`, `search.py`, `evaluate.py` | The organisers' starter kit | Given | The product catalogue, the scorer, the public dev set | Yes, unchanged (checked byte for byte against the base commit) |
| Training requests for the risk model | **Synthetic.** 30,000 shopper requests, plus 8,000 for validation, built from random catalogue products and hand-written phrasing pools | `scripts/make_training_data.py`, seeded | Training the 22-weight logistic regression and choosing its safety multiplier | Only the generator; the requests are regenerated on demand |
| `anticipatory/data/risk_model.json` | The trained weights | Output of `scripts/train_risk.py` | Runtime risk estimate | Yes (0.8 KB) |
| `data/dev_extra.jsonl` | **Hand-written** test requests (87), filled from real catalogue products | `scripts/build_dev_extra.py` | A test set with phrasing dev does not contain | Yes |
| Blind set (44 requests) | Hand-written, new phrasings, evaluated once | Written during this review | Estimating generalisation | No (scratch) |
| `anticipatory/data/english_words.tsv` | **External.** The 60,000 most frequent English words with counts | Peter Norvig's `count_1w.txt` (Google web corpus counts via the LDC; educational and research use; user accepted for a hackathon) | Telling real words from typos and names | Yes (912 KB) |
| Seed synonyms, cue words, number words, fillers | **Hand-written** language knowledge: about 90 synonyms, price and size cues, English and Hindi number words, Hindi and English fillers, correction markers | Me; part read off dev, part guessed (marked in the code) | The reader | Yes (`lexicon.py`, `numbers.py`) |

So besides the catalogue and dev, there is exactly one external dataset (the word list), one
synthetic training set (for 22 numbers), and two hand-written test sets. **No dev request is used
to fit anything.** The `dev.jsonl` file is read only by scripts and tests, never by the agent
(audited at run time: see section 5).

## 2. Assumptions

### About the task and the scoring
- The scorer is `evaluate.py`, and its formula is the truth: 0.4 for a right final answer, plus
  0.6 times the share of the request still to come at the first right commit, minus 1.0 per wrong
  commit, minus 0.02 per search after the first.
- The hidden set has about 300 requests of the same kinds as dev (plain, correction, late
  constraint, code-mixed), the same catalogue, and "some wording not in dev".
- Every hidden request has a target product that matches everything the shopper says. Requests
  for something the shop does not sell do not appear in the score (but are handled: see
  "unresolved constraints").
- A correction replaces an earlier value and comes 1 to 3 words after its marker (measured on dev:
  55 corrections, all within 3 words).
- Words arrive whitespace-split with punctuation still attached, as in dev ("size M," "UK.").
- One agent object is reused for every request, with `start()` called before each.

### About the language of requests
- English and Hinglish in Latin script. Devanagari words are tolerated (no crash) but not understood.
- Prices are rupees, as digits ("1500", "1,500", "Rs. 1500", "1500/-"), "k" amounts ("1.5k"), or
  English and Hindi number words. Sizes are catalogue sizes (UK shoe sizes, letter sizes, waists).
- A comma or period ends a clause, and **a multi-word phrase is not split by punctuation** ("navy
  blue", "extra large", "t shirt"). Inserting commas inside phrases breaks them (measured below).
- Typing slips follow a QWERTY keyboard: a neighbouring key, two letters swapped, a doubled letter.
- Colour, brand and category words either name something in the catalogue, are in the seed synonym
  list, or are not understood. There is no semantic fallback yet.

### About the environment
- The harness imports `agent.py` from its folder with the `anticipatory/` package next to it, and
  `catalogue.csv` where the kit puts it. The package reads its own data files relative to itself.
- Python 3.8 or later (static analysis says 3.8 is the minimum; only 3.14 was executed here).
- No network, no writes, no randomness: same input, same output (5,000 of 5,000 requests identical
  on a replay). The optional stream server (`python -m server`) is a demo interface for one
  machine: it listens on localhost, has no authentication, and is not part of what the harness runs.

### Design constants, and how each was set
| Constant | Value | How it was set | Depends on dev? |
|---|---|---|---|
| Break-even risk (words saved, average length, forfeited share) | 1 word, 13.3, 0.2, giving 3.9% | Derived from the score formula and dev's average length | Weakly (13.3 is dev's mean) |
| `hold_words`, `clause_end_penalty` | 1 word, 0.5 | Chosen so no dev correction is committed wrongly (Stage 5) | **Yes, tuned on dev** |
| `base_risk`, `confidence_weight`, `fresh_penalty` | 0.01, 0.2, 0.5 | Reasoned, not fitted | No (guesses) |
| `correction_window` | 6 words | Dev showed 1 to 3; 6 is a margin | Weakly |
| `restate_confidence`, `unmarked_revision_confidence` | 0.85, 0.6 | Reasoned | No (guesses) |
| Learned safety multiplier | 4.0 | Smallest value whose wrong-commit rate on synthetic validation requests is no higher than the rules-only policy's | No (synthetic), but the synthetic world mimics dev |
| Synthetic correction rate, delayed share, slot mix, pause rates | 18.3%, 42%, size 23 / colour 18 / brand 13 / category 1, 64% vs 16% | **Measured on dev** | **Yes** |
| Confidence by source (exact 0.95, synonym 0.85, fuzzy 0.60, bare number 0.45...) | as listed | Reasoned | No (guesses) |
| Spelling costs and limits, real-word ratio 100 | see `config.py` | Reasoned, then checked on synthetic typos and a protected-word list | No |
| `name_min_rank` 2000, `stopword_rank` 300 | 2000, 300 | Chosen from a handful of ranks (friday 914, nike 5380) | No |
| `max_live_words` | 200 | Reasoned: 8 times the longest dev request | No |

## 3. What dev influenced (so dev scores are optimistic)
- About half of the seed synonyms were met while reading dev ("slides", "floaters", "joggers"...).
- The marker words, the Hindi cue words and the filler pools came from reading dev.
- `hold_words` and `clause_end_penalty` were tuned until dev had no wrong commit.
- The synthetic generator copies dev's rates and phrasing patterns.
- `dev_extra` was written after reading dev, and bugs found on it were fixed, so it is no longer unseen.

Nothing is fitted to dev's answers, but dev is **not** an unbiased estimate. The unbiased
evidence is the blind set and the synthetic runs below.

## 4. The evidence and its limits
| Test set | Size | Accuracy | Wrong early commits | Score | Kit baseline | Tuned on it? |
|---|---|---|---|---|---|---|
| dev | 300 | 1.000 | 0 | 43.5 | 20.0 (0.527) | Partly (section 3) |
| dev_extra | 87 | 0.989 | 0 | 40.5 | 31.3 (0.793) | Bugs fixed on it |
| Blind set, before any fix | 44 | 0.977 | 0 | 42.6 | 29.3 (0.750) | **No** |
| Blind set after fixing the one bug it found ("price cap") | 44 | 1.000 | 0 | 43.8 | | Now yes |
| Synthetic, 4 seeds, typo rates 0 / 0 / 5% / 15% | 20,000 | 0.9993 | 50 requests (**0.25%**) | n/a | | Model trained on the same world |
| Random word-soup fuzz | 20,000 | n/a | n/a | n/a | | n/a |

What to expect on the hidden set (an estimate, not a promise): accuracy 0.98 to 1.00, between 0
and 2 wrong early commits in 300 requests (0.25% per request gives 0.75 on average; each costs
about 0.4 points of the final score), and a score between about 40.5 (phrasing as foreign as
`dev_extra`) and 44 (phrasing like dev). The score floor for a perfect reader that never commits
early is 40.0, and the cut-off is 60% of the baseline, 12.0.

## 5. Verification done for this review
Everything ran on a fresh clone of the PR branch, except where noted.
- **Clean room:** 338 tests passed from `backend/` and from the repo root (344 after the fixes
  below); the kit baseline, `agent.py`, `agent_heuristic.py` and `agent_learned.py` score as
  documented; the agent runs from another working directory; `results.jsonl` and
  `results_dev_extra.jsonl` regenerate **byte for byte**.
- **Independent scorer:** a re-implementation of the formula, written from the README and not from
  `evaluate.py`, reproduces every per-request score in both committed logs exactly (difference 0).
- **Runtime rules (audit hook and spy):** the shipped package never reads dev files and never
  imports the kit's `search`. During 387 requests the only file opened after construction was
  `catalogue.csv`, opened by the kit's own `search.py` the first time it was called (its lazy
  index). All 460 searches went through the counted tool, asked for at most 50 results, and
  used only valid filters.
- **Causality (no lookahead):** for all 387 requests, every proper prefix was replayed in a fresh
  run: 4,440 prefixes, 0 outputs that differed from the full run.
- **Pin point:** `finish()` on only the words up to the oracle pin returns the target in 386 of
  387 requests.
- **Metamorphic tests (the final answer must not change), 387 requests each:** uppercasing,
  lowercasing, appending "please thanks", prepending "hey, do you have" or "yo bro", doubling
  "size": 0 changes and 0 wrong commits. A filler "hmm," after the first word: 1 change. A comma
  after every third word: 34 changes and 1 wrong commit, all caused by a comma splitting a phrase
  ("t, shirt", "extra, large", "navy, blue").
- **Scale and determinism:** 20,000 synthetic requests, 0 exceptions, accuracy 0.9993, replay
  identical. 20,000 fuzz requests: 0 exceptions; never more than one commit; every commit
  consistent with the agent's own reading; the final answer always a real product or none.
- **Hostile input and long requests:** Devanagari, emoji, control characters, a 20,000-letter word,
  a 400-digit number, SQL-looking text, blank words; 20,000 words in 235 ms (the cost per word was
  quadratic until Stage 9, now capped).
- **Python versions:** static analysis (vermin) puts the shipped package at Python 3.8 or later.

### Bugs this review found, now fixed
1. "price cap 2000" read "cap" as the category caps. Fix: the cues "price cap", "budget cap" and
   "spending cap" claim the word. Found by the blind set.
2. A size glued to its cue ("size9", "UK10", "sz10", "w32") was not read. Fix: the tokenizer splits
   it into two tokens.
Both have tests; dev and `dev_extra` scores are unchanged by them.

## 6. Known limitations
- **Synonyms outside the seed list are not understood** ("sliders", "lowers"). The agent notices a
  word it cannot place and does not commit early on it; the final answer is the best match
  without it. Planned: a soft lexicon from word vectors after Round 1.
- **Punctuation inside a phrase** breaks it (section 5).
- **A typo in a cue word** ("saiz 10") is not corrected: only product words are.
- **Half sizes** ("10.5") do not exist in the catalogue; the final answer is a near product.
- **A shopper who contradicts themselves without a marker** gets the last value at lower
  confidence, and no early commit on it.
- **Long-delayed corrections** (an old slot corrected long after, with nothing in front of it) are
  the one case no signal predicts. They are why the agent pays about 3 earliness points for
  safety, and why 0.25% of synthetic requests still end in a wrong early commit.
- **Earliness is modest:** 6.4% of a request on dev, against 16.3% possible. That is a decision:
  every faster setting tried added wrong commits (Stage 8).
- **Unresolved-constraint false flags** cost earliness (the agent waits) but never cause a wrong
  commit. None occurred on dev or on 3,000 clean synthetic requests.
- Only Python 3.14 was executed in this review; 3.8 to 3.13 are covered by static analysis only.
