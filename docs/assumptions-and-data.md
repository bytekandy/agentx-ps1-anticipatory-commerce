# Assumptions, data sources and the evidence behind the numbers

Kept up to date through the final test (Stage 19). It answers four questions: what data is used besides the
catalogue, what we assumed, which numbers are optimistic because dev influenced a choice, and what
was verified. Every figure below was measured; where something is a guess, it says so.

## 1. Data: what is real and what is synthetic

| Item | What it is | Where it comes from | Used for | In the repo? |
|---|---|---|---|---|
| `catalogue.csv`, `dev.jsonl`, `search.py`, `evaluate.py` | The organisers' starter kit | Given | The product catalogue, the scorer, the public dev set | Yes, unchanged (checked byte for byte against the base commit) |
| Training requests for the risk model | **Synthetic.** 30,000 shopper requests, plus 8,000 for validation, built from random catalogue products and hand-written phrasing pools | `scripts/make_training_data.py`, seeded | Training the 22-weight logistic regression and choosing its safety multiplier | Only the generator; the requests are regenerated on demand |
| `anticipatory/data/risk_model.json` | The trained weights | Output of `scripts/train_risk.py` | Runtime risk estimate | Yes (0.8 KB) |
| `data/dev_extra.jsonl` | **Hand-written** test requests (87), filled from real catalogue products | `scripts/build_dev_extra.py` | A test set with phrasing dev does not contain | Yes |
| Blind set (44 requests) | Hand-written, new phrasings, evaluated once | Written during the Stage 9 review | Estimating generalisation | No (scratch) |
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
- Python 3.14, the only version run, tested and supported (decision: the team uses the version installed on its machine).
- No network, no writes, no randomness: same input, same output (5,000 of 5,000 requests identical
  on a replay). The optional stream server (`python -m server`) is a demo interface that
  is not part of what the harness runs. It uses third-party packages (`backend/requirements-server.txt`,
  Python 3.11 or newer); the agent does not. It listens on localhost by default and refuses another
  address without an API key; there is no TLS.

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

## 5. Verification
### Final test (Stage 19), on a fresh clone of `main`
- **Tests:** 467 pass with the server extras installed; 395 pass and 6 skip without them (the agent's own tests need only Python).
- **Scores (official `evaluate.py`):** `agent.py` 43.5 on dev, 0 wrong commits; `agent_heuristic.py` 41.6; `agent_learned.py` 43.6 but 2 wrong commits (why the hybrid is the default); `agent.py` on `dev_extra` 40.5, 0 wrong commits; kit baseline 20.0 and 31.3.
- **Reproducible:** `scripts/report.py` regenerates `results.jsonl` and `results_dev_extra.jsonl` byte for byte.
- **Kit files untouched:** `catalogue.csv`, `dev.jsonl`, `evaluate.py`, `search.py` and `README.md` in `backend/` are identical to the first commit.
- **Determinism and causality:** 80 random requests run twice give identical outputs, and every proper prefix (939) replayed in a fresh run matches the full run exactly: no lookahead.
- **Hostile input:** Devanagari, emoji, control characters, a 20,000-letter word, a 400-digit number, SQL-looking text and empty words cause no error; 3,000 random word-soup requests cause no exception.
- **Server and page:** the live server answers health checks; the page passes its 15-step jsdom end-to-end check against the real agent; the WebSocket client gets the right final answer; `scripts/ask.py` works in a terminal.

### Earlier review (Stage 9). Not repeated after the later reader fixes, so treat as historical
- **Independent scorer:** a re-implementation of the formula, written from the README and not from `evaluate.py`, reproduced every per-request score in both committed logs exactly.
- **Runtime rules (audit hook and spy):** the shipped package never reads dev files and never imports the kit's `search`. During 387 requests the only file opened after construction was `catalogue.csv`, opened by the kit's own `search.py`. All 460 searches went through the counted tool, asked for at most 50 results and used only valid filters.
- **Pin point:** `finish()` on only the words up to the oracle pin returned the target in 386 of 387 requests.
- **Metamorphic tests (the final answer must not change):** uppercasing, lowercasing, appending "please thanks", prepending "hey, do you have" or "yo bro", doubling "size": 0 changes, 0 wrong commits. A comma after every third word changed 34 of 383 answers (1 wrong commit) then; after Stages 13 and 16 it changes 7 (0 wrong commits), and typos in size, price and correction words changed 17 answers (5 wrong commits) then and 0 now.
- **Scale:** 20,000 synthetic requests with 0 exceptions and accuracy 0.9993; 20,000 word-soup requests with 0 exceptions, never more than one commit.

### Bugs found by reviews, now fixed
1. "price cap 2000" read "cap" as the category caps (blind set). The cues "price cap", "budget cap" and "spending cap" now claim the word.
2. A size glued to its cue ("size9", "UK10", "sz10", "w32") was not read. The tokenizer now splits it.
3. A comma inside a phrase ("navy, blue", "t, shirt") split it, and a comma after a cue detached its number (Stages 13 and 16).
4. Typos in size, price and correction words were ignored, and the filter state read uncorrected words (Stage 13).
5. A half size ("size 10.5") was silently dropped; it is now an unresolved size (Stage 14).

## 6. Known limitations
Resolved or decided; the open ones come first.

- **Synonyms outside the seed list are not understood** ("sliders", "lowers"). The agent notices a
  word it cannot place and does not commit early on it; the final answer is the best match
  without it. Stage 15 added a learning lexicon instead of pretrained vectors (below): words are
  taught by earlier requests, in a separate optional file.
- **Commas near numbers** (Stage 16): a cue keeps its number across a comma ("size, nine",
  "under, 1500"). Still open on purpose: a comma inside a spoken number ("one thousand, five
  hundred") ends the number, because merging would also turn "two thousand, nine UK" into 2009.
  Commas after every third word now change 7 of 383 final answers (34 before Stage 13), 0 wrong commits.
- **Half sizes** ("10.5"): fixed in Stage 14. The shop has none, so the size is reported as
  unresolved: no early commit, and the final answer is the best match without it.
- **A shopper who contradicts themselves without a marker** ("size 9 size 10", "red black"):
  decision, not a bug. The last value wins at lower confidence (0.6) and the agent does not commit
  early on it. There is no better reading without a marker.
- **Long-delayed corrections** (an old slot corrected long after, with nothing in front of it) are
  the one case no signal predicts. They are why the agent pays about 3 earliness points for
  safety, and why 0.25% of synthetic requests still end in a wrong early commit. Inherent, accepted.
- **Earliness is modest:** 6.4% of a request on dev, against 16.3% possible. A decision: every
  faster setting tried added wrong commits (Stage 8). Accepted.
- **Unresolved-constraint false flags** cost earliness (the agent waits) but never cause a wrong
  commit. None occurred on dev or on 3,000 clean synthetic requests. Accepted.
- **Python:** only 3.14 is supported (decision above).
- **Web page and server** (Devanagari words, Python 3.11+ for the server, no TLS): out of scope.
  The page is an optional extra and is not evaluated.

## 7. The learned lexicon (Stage 15)
No pretrained word-vector file was used (too large to ship; user decision). Instead the agent can
be taught words by use. This needs no external data.

- **Separate, optional file:** `backend/anticipatory/data/learned_lexicon.json` (git-ignored). The
  agent only reads it, at start. **When the file is absent, a word the lexicon cannot place is
  dropped, exactly as before** (Round 1 and the harness run without it; dev 43.5 is measured
  without it).
- **Evidence:** (1) a correction in a request ("sliders, I mean sandals" teaches sliders = sandals);
  (2) an accepted product (the "This is what I wanted" button, `POST /api/feedback`): if exactly one
  unknown word was said and exactly one of category, colour and brand was not, they are linked;
  (3) repeat evidence: a word is used only after 2 agreeing observations and is switched off when
  evidence against it (an accepted product that disagrees) reaches half of the support.
- **Safety:** learned words never override a catalogue or seed word, can only name values that exist
  in the shop, and read at confidence 0.60 (like a spell-corrected word), so the agent does not
  commit early on them lightly.
- **Teaching:** `python scripts/learn_lexicon.py log.jsonl` (offline) or the server endpoint; a
  change is used the next time the agent starts. The agent itself never writes, so a harness run
  stays read-only and deterministic.
- **Limits:** one word maps to one meaning; slots are category, colour and brand (not size or
  price); it only learns a word that appears in a correction or an accepted request; the server
  has to be restarted to use new words. A shared learned file could be poisoned by bad feedback;
  there is no per-user separation.

## 8. What the dev set shows (`scripts/analyze_dev.py` reproduces these)
- **The score is mostly reading correctly.** The baseline's 20.0 comes from accuracy 0.527. Reading every request correctly and never committing early scores 40.0 (the floor); early commits add at most about 10 points, and every wrong commit takes back 1.0.
- **The ceiling is low and uneven.** A perfect early committer would save 16.3% of each request (plain 19.0%, correction 12.2%, late constraint 9.3%, code-mixed 20.0%); for 34% of requests the target is only pinned by the last word. Size completes the pin in 37% of requests (price 19%, colour 14%, brand 11%, category 2%).
- **Only corrections endanger an early commit.** Every stated value is consistent with the target, so a unique match from correctly read values can only be overturned by a correction or a misread. 55 requests (18%) correct a slot (size 23, colour 18, brand 13, category 1), and the replacement comes 1 to 3 words after the marker.
- **Searching before the size is known is wasted.** Mean candidates as slots are added (category, colour, brand, size, price): 80, 17, 7.9, 1.5, 1.0. The agent therefore searches only when the size is known or the category has none.
- **Number words are ambiguous word by word.** "eight" may be size 8 or the start of "eight hundred"; price phrases run up to four words, so a number word is never acted on until it is settled.
- **The vocabulary is small but the hidden set has unseen wording:** 300 requests use only 283 distinct tokens, which is why plurals, spelling variants, number words and Hindi forms are generalised in the lexicon rather than copied from dev.
- **Reference agents (kit scorer):** no early commit with perfect reading 40.0; commit at the first unique product 32.7 (22 wrong commits); marker-aware with a one-word hold 39.6 (8 wrong commits). Our hybrid reaches 43.5 with none.
