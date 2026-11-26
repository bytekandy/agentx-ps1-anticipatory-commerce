# Round 1 Plan - AgentX PS1 (Anticipatory Commerce)

Hard deadline for Round 1: **30 Nov 2026, 11:59 PM IST**. The stages below have no per-stage dates; work through them in order. A stage is finished when its **exit criteria** are met, and it lands on `main` through its own pull request.

---

## 1. What Round 1 is judged on

| Criterion | Pts | Round 1 evidence | Where we produce it |
|---|---|---|---|
| Benchmark performance | 25 | Automated run on the hidden set | `backend/` agent, scored by `evaluate.py` |
| Technical depth | 20 | Repo + 1-page architecture note | clean code, tests, `docs/architecture-note.md` |
| Robustness | 15 | Results on corrections and late constraints | per-tag table from `--log` output |
| Innovation | 15 | Abstract | `docs/abstract.md` |
| Feasibility, cost and scale | 15 | Abstract: impact, cost estimate | `docs/abstract.md`, latency and search numbers |
| Presentation and Q&A | 10 | not scored in Round 1 (total rescaled 90 to 100) | finals only |

**Targets (our own; revised after Stage 1, see `docs/dev-analysis.md`):**
- Hard gates: wrong commits = 0 on dev (each exception documented); accuracy at or above the baseline (0.527).
- Score on dev: floor 40.0 (perfect reading with no early commit), goal 43 to 46, ceiling about 50. Below 40 means the early-commit logic is losing points.
- Efficiency: about 1.5 searches per request or fewer (one extra search costs 2 points); well under 5 ms per word.

**Status against the targets (Stage 9 review, see `docs/assumptions-and-data.md`):** wrong commits 0 on dev (300) and on `dev_extra` (87), but **0.25% of 20,000 synthetic requests**, so zero on the hidden set is likely, not guaranteed; accuracy 1.000 on dev against the 0.527 baseline; score 43.5 on dev (goal 43 to 46); 1.19 searches per request; 0.09 ms per word on average.

---

## 2. Design principles (how we build)

1. **Safety first.** A wrong commit costs about 1.0 plus lost earliness; one word earlier gains about 0.045. The default action is always "wait".
2. **Layered, pure core.** Reading words (pure functions) -> filter state -> decision policy -> orchestration -> I/O adapter. Only the outermost layer touches `tools.search`.
3. **Dependency inversion.** The agent depends on a tiny `CatalogPort` interface. Tests use a fake catalogue; runtime uses the counted `tools.search`. The risk model sits behind an interface too (`RiskModel`: rules, learned and hybrid implementations). The slot reader does not, so an LLM reader would first need an interface added (only when the user says so).
4. **One source of tunables.** Thresholds and limits live in `config.py`, as frozen dataclasses grouped per area. A few structural constants stay in code (feature scaling in `risk.py`, the extra-size pattern in `unknown.py`, the rule that a size under 20 is settled early in `slots.py`).
5. **Deterministic and reproducible.** No randomness, no network. Same input gives the same output.
6. **Observable.** Every word produces a trace record (filters, confidences, candidates, action, reason). Used for debugging, analysis, the UI and the demo video.
7. **Test pyramid.** Unit tests for pure modules, scenario tests for corrections and late constraints, benchmark runs through `evaluate.py`.
8. **Time-boxed simplicity (YAGNI).** Python standard library only for the agent, a small flat package, no frameworks. Add structure only when it earns its place.
9. **Kit immutability.** The five kit files in `backend/` are never edited.
10. **Bounded cost.** The state re-reads the words so far after every word, so the work per word grows with the request (about 0.09 ms for real requests of 6 to 25 words) and is capped by `max_live_words` (200: past it the agent only waits, and `finish()` reads the request once); the catalogue is read only to build vocabularies; products are looked up through counted searches. Candidate searches use a large `k` because cost is per call, not per result.
11. **Clear boundary between backend and UI.** The UI only consumes the agent's trace records through one thin interface; it contains no decision logic.

---

## 3. Monorepo layout and naming conventions

```
agentx1_hack/                      monorepo root (git repo, branch main)
  README.md                        project overview and run steps (the kit's backend/README.md is immutable)
  .gitignore                       project artifacts only (pycache, local scratch)
  .editorconfig                    shared whitespace rules
  .github/pull_request_template.md
  docs/
    round1-plan.md                 this file
    dev-analysis.md                findings from Stage 1
    stream-contract.md             trace stream contract (Stage 10)
    architecture-note.md           1-page architecture note (Stage 12)
    abstract.md                    max 500 words (Stage 12)
  backend/                         Python, standard library only - the main project
    catalogue.csv dev.jsonl evaluate.py search.py README.md    <- Rezolve kit, DO NOT EDIT
    agent.py                       thin entry point: exposes Agent for evaluate.py
    anticipatory/                  our package
      config.py                    frozen dataclasses per area (all tunables)
      lexicon.py                   vocabularies from catalogue.csv, synonyms, Hindi-English words
      tokens.py                    word normalisation shared by lexicon, numbers and slots
      numbers.py                   number words, "k" amounts, Indian price phrasing
      slots.py                     pure per-word slot extraction
      state.py                     incremental FilterState: values, confidences, revisions
      catalog_port.py              CatalogPort interface + adapter over tools.search
      risk.py                      RiskModel interface, HeuristicRisk, LearnedRisk (Stage 6)
      spelling.py                  noisy-channel spelling correction (Stage 7)
      policy.py                    search scheduling + commit policy
      agent.py                     orchestrator implementing the kit's Agent interface
      trace.py                     per-word decision trace records
    server/                          thin streaming interface for the UI (Stage 10)
    tests/                         test_<module>.py, unittest
    scripts/                       analyze_dev.py, report.py
    data/dev_extra.jsonl           our own extra requests, dev format
    outputs/                       committed run outputs (results.jsonl) for the submission
  frontend/                        base UI (Stage 11; specs discussed then)
```

**Conventions**
- **Python (PEP 8):** modules `snake_case` nouns; classes `PascalCase`; functions and variables `snake_case` verbs; constants `UPPER_SNAKE`; private names with a leading `_`; type hints and short docstrings on public items. Do not name a module `parser.py` or `search.py`.
- **Tests:** `tests/test_<module>.py`, test names `test_<behaviour>`.
- **Docs:** `kebab-case.md` in `docs/`. Data files `snake_case.jsonl`.
- **Commits (Conventional Commits):** `type(scope): imperative subject`, 72 characters or fewer. Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `chore`. Scopes: `backend`, `frontend`, `docs`, `slots`, `policy`, `eval`. Example: `feat(slots): extract budget from number words`. Never add Claude as co-author.
- **Branches:** `stage-<n>/<short-kebab>` (see section 4). Fixes after a stage merged: `fix/<short-kebab>`.
- **Tag:** `r1-submission` on the exact commit that is submitted.
- **Frontend:** conventions (language, framework, file naming) decided in Stage 11 together with the UI specs.

---

## 4. Git workflow (branch per stage, PR per stage)

1. **One branch per stage**, named `stage-<n>/<short-kebab>`, always created from an up-to-date `main`.
2. **Commit on the stage branch** in small Conventional Commits.
3. **When the stage's exit criteria are met:** fetch, rebase on `origin/main` (normally a no-op), run the merge gate, push, and open a pull request into `main` with `gh pr create`. The PR body has: summary, files added or changed, exit-criteria checklist, how it was verified. No Claude attribution lines.
4. **Merge gate (every PR):** unit tests green; `python evaluate.py --agent agent.py` runs (from Stage 5 on); no kit file touched; no generated or local files committed; `main` stays working.
5. **Claude opens the PR and stops.** It never merges on its own initiative and does no further work while any PR is open. The user reviews the PR and may ask for changes (made on the same branch), then replies "start the next stage" (they merged it) or "merge and start the next stage" (Claude squash-merges with the PR title as the commit message, syncs `main`, deletes the branch, then starts). If told "start the next stage" while the PR is still open, Claude asks whether to merge it first.
6. **Next stage starts only after the previous PR is merged**, branching from the updated `main`. No stacked or parallel stage branches unless the user asks.

**How we avoid merge conflicts**
- **Sequential stages, short-lived branches.** Conflicts need two lines of work touching the same lines; with one stage at a time and `main` always current, there is nothing to conflict with.
- **Disjoint ownership.** Each stage lists the files it owns. Stages mostly add new files. Changes to a file an earlier stage created must be small and additive.
- **Hot files stay additive.** `config.py` is split into per-area frozen dataclasses (vocabulary, slots, state, policy), so each stage appends its own block instead of editing shared lines.
- **Separate trees for separate concerns:** `backend/`, `frontend/`, `docs/` never share files; each doc is owned by one stage.
- **No running logs in git.** The Claude context file is excluded locally and never committed.
- **No noise diffs.** PEP 8 and `.editorconfig` from the start; no mass reformatting commits.
- **Kit files untouched**, so nothing can conflict with them.
- **No generated files in git** (pycache, scratch). The only committed output is `backend/outputs/results.jsonl`, written once for the submission.

---

## 5. Backend architecture

```
word -> tokens.make_tokens -> slots.read_words (+ spelling, possessives)
     -> state.build_snapshot (+ unknown.find_unresolved)   [FilterState.push / finish]
     -> policy.CommitPolicy.step:  gates -> risk.p_wrong (pre-check) -> catalog_port.find (counted, k=50)
     -> {wait | commit(product_id)} + trace record

finish(): re-read the whole request with final=True -> reuse the last search if its filters are
          unchanged and it matched exactly one product, else search once more (relaxing filters
          in the baseline's order if nothing matches) -> return product_id
```

- **Slots:** category, colour, brand, size, max_price (plus min_price if seen). Each slot holds a value, a confidence, and a revision history.
- **Revisions:** markers like "oops", "no wait", "sorry I meant", "actually" replace the earlier slot value. While a marker's replacement has not arrived (up to 6 words) the state is unsettled and nothing is committed; a value that was just heard (1 word) or just followed by a pause is held back by the risk rules. There is no per-slot cooldown.
- **Commit rule (user confirmed):** commit once the remaining candidates cannot be separated by anything the shopper might still add. Candidate rows differ by size, so sized categories normally wait for the size; unsized categories (backpacks, caps, headphones, watches, wallets) can commit earlier.
- **Hybrid layer (team leader's request, decided 2026-11-26):** the rules read the request and stay the backbone. Learned or statistical parts answer how risky a commit is (`risk.py`, Stage 6) and recover misspellings (`spelling.py`, Stage 7). Everything is trained offline in pure Python and shipped as small JSON, so the runtime stays standard-library only. Possible later additions (after Round 1): a probability over candidate products instead of a single guess, and a soft lexicon from pretrained word vectors. No language model.
- **Commit rule as expected value (technique A):** committing now is worth it when `P(wrong) x (1.0 + earliness forfeited)` is smaller than the earliness gained by not waiting, which in practice means a risk below about 4 percent when it saves one word and about 12 percent when it saves four (derived from the score formula; the exact budget is tuned in `config.py`).
- **Key risk (Stages 5 to 8):** corrections, not late constraints. Stage 1 showed a unique match built from correctly read values can only be overturned by a correction (or a misread); late constraints never invalidate it. Measure per-slot correction risk and clause-boundary signals, then set the thresholds in `config.py`.
- **Confidence:** exact catalogue match high; synonym medium; number-word parse and ambiguous tokens (for example a bare "M") lower, raised by context.
- **Final check:** `finish()` ignores earlier guesses and reads the whole request. If the filters are the ones of the last search and it matched exactly one product, that search is the check (no extra search); otherwise it searches once more and returns the best match.

---

## 6. Stages

Status: `todo`, `doing`, `done`. Each stage = one branch = one PR. "Owns" lists the files the stage creates or changes.

### Stage 0 - Foundation - `stage-0/foundation` - done (on merge)
- Base commit already on `main` (kit files in `backend/`).
- Commit this plan plus project scaffolding: root `README.md` (overview, run steps), `.gitignore` (project artifacts only), `.editorconfig`, `.github/pull_request_template.md`.
- Public GitHub repository `bytekandy/agentx-ps1-anticipatory-commerce` created, set as `origin`, `main` pushed.
- **Owns:** `docs/round1-plan.md`, `README.md`, `.gitignore`, `.editorconfig`, `.github/`.
- **Exit:** PR merged; `main` is on GitHub.

### Stage 1 - Baseline and data analysis - `stage-1/dev-analysis` - done (on merge)
- Run the baseline once and confirm 20.0 / 0.527.
- `scripts/analyze_dev.py`: per-tag stats, how often each slot arrives late, where the oracle `earliest` falls, inventory of synonyms, number phrasings, correction markers and Hindi-English words.
- Mine dev for rules that generalise, not just exact strings; the hidden set has unseen wording.
- **Owns:** `backend/scripts/analyze_dev.py`, `docs/dev-analysis.md`.
- **Exit:** findings written up; lexicon wish-list included; targets in section 1 revised.

### Stage 2 - Vocabulary - `stage-2/vocabulary` - done (on merge)
- `config.py` (vocabulary block), `tokens.py`, `lexicon.py`, `numbers.py` with unit tests.
- Vocabularies built from `catalogue.csv`; synonyms ("slides", "floaters"); plural, singular, hyphen and spacing variants by rule; number words; "0.8k"; size spellings ("UK" after size); Hindi-English word list; brand-only fuzzy matching; cue-word sets for later stages.
- **Owns:** `backend/anticipatory/{__init__,config,tokens,numbers,lexicon}.py`, `backend/tests/{__init__,test_tokens,test_numbers,test_lexicon}.py`.
- **Exit:** unit tests green; every catalogue value and all dev synonyms resolve.

### Stage 3 - Slot extraction - `stage-3/slot-extraction` - done (on merge)
- `slots.py`: pure per-word extraction of category, colour, brand, size, budget, with confidences.
- **Owns:** `backend/anticipatory/slots.py`, `backend/tests/test_slots.py`, `backend/scripts/slot_accuracy.py`; adds a slots block to `config.py`.
- **Exit:** unit tests green; slot accuracy on plain dev requests at or above 95% (measured with a small script over `dev.jsonl` gold filters, without an agent).

### Stage 4 - Filter state and corrections - `stage-4/filter-state` - done (on merge)
- `state.py`: incremental `FilterState` (values, confidences, revision history); correction markers; cooldown after a revision; late constraints added without losing earlier slots.
- **Owns:** `backend/anticipatory/state.py`, `backend/tests/test_state.py`, `backend/scripts/state_replay.py`; adds a state block to `config.py`; makes `size_fits_category` public in `slots.py` (a rename).
- **Exit:** unit tests green; replaying dev requests word by word gives the gold filters at the last word for at least 95% of plain and correction requests.

### Stage 5 - Decision engine, first end-to-end - `stage-5/decision-engine` - done (on merge)
- `catalog_port.py` (interface over the counted `tools.search`, with a fake for tests), `risk.py` (the `RiskModel` interface plus a hand-coded `HeuristicRisk`), `policy.py` (search scheduling and the decision-theoretic commit rule, see section 5), `trace.py` (one record per word), `anticipatory/agent.py` (orchestrator over `FilterState`), `backend/agent.py` (entry point for `evaluate.py`). Conservative thresholds first; verification in `finish()`.
- **Owns:** those files, `backend/tests/test_policy.py`, `backend/tests/test_agent.py`; adds a policy block to `config.py`.
- **Exit:** `python evaluate.py --agent agent.py` runs; accuracy at or above baseline; zero wrong commits on the plain subset; score above 20. The score and per-tag table are recorded as the baseline for the hybrid comparison in Stage 6.

### Stage 6 - Learned risk model (hybrid) - `stage-6/risk-model` - done (on merge)
- A calibrated model that answers "how likely is the current best product to be wrong?" and replaces `HeuristicRisk` behind the same `RiskModel` interface (technique B; the commit rule is technique A from Stage 5).
- `scripts/make_training_data.py`: synthetic requests generated from `catalogue.csv` with templates and noise rates mined from dev (corrections about 18 percent, markers, number phrasing, fillers, late constraints), replayed word by word through `FilterState`; every prefix is labelled "is the current unique candidate the final target?". `dev.jsonl` is never training data: it is the held-out check.
- `scripts/train_risk.py`: pure-Python logistic regression (Newton's method, ridge), refitted on-policy (only the prefixes the agent would actually visit, because the first safe-looking prefix is the riskiest); writes `backend/anticipatory/data/risk_model.json`. `risk.py` gains a standard-library-only `LearnedRisk` that loads it. The safety multiplier is chosen on synthetic validation requests as the smallest one whose wrong-commit rate is no higher than the heuristic's, so the model must win on earliness at equal safety and dev stays untouched.
- **Shipped design: `HybridRisk`** (the team leader's hybrid idea, refined by measurement). The hand-coded rules decide while a value is fresh (`quiet_words < hold_words`) or just followed by a pause; the learned model decides in calm states. Routing on a *detected* correction was measured and cannot work, because every wrong commit happens before the correction word is heard; routing on freshness and pauses (the moments a correction can begin) does. The safety multiplier (x4.0) is chosen on synthetic validation so the hybrid's wrong-commit rate is no higher than the rules-only policy's. An unsettled state is never safe whatever the model says.
- Two state fixes found while analysing the remaining wrong commits: the state is also unsettled while the words end on a size or price cue still waiting for its number (`within Rs.`, `up to`, including the first word of a two-word cue) or on `make` (which may become `make that`). They also halved the wrong-commit rate of the rules-only policy on fresh synthetic requests.
- Entry points: `agent.py` is the hybrid (default), `agent_heuristic.py` rules only, `agent_learned.py` model only.
- **Results (dev, `evaluate.py`):** hybrid 43.4, 0 wrong commits, earliness 6.4% (plain 43.7, correction 43.7, late constraint 42.2, code-mixed 43.8); rules only 41.5, 0 wrong, 3.0%; model only 43.5 but 2 wrong commits on corrections. Fresh synthetic requests: hybrid 44.9 at a 0.29% wrong rate, rules only 43.2 at 0.29%, model only 46.0 at 0.50%.
- **Owns:** `backend/scripts/make_training_data.py`, `backend/scripts/train_risk.py`, `backend/anticipatory/data/risk_model.json`, `backend/agent_learned.py`, `backend/agent_heuristic.py`, `backend/tests/test_risk.py`, `backend/tests/test_training.py`; extends `risk.py` (new `RiskInput` fields, `LearnedRisk`, `HybridRisk`); adds a learned-risk block to `config.py`; changes `agent.py` to use the hybrid; small additive changes to `slots.py` (two reader fixes and `cue_awaiting_number`) and `state.py` (`cue_pending`).
- **Exit (met):** calibration error reported on dev (held out); wrong commits at or below the rules-only policy (0 vs 0 on dev, equal rate on fresh synthetic requests); score above the rules-only policy (43.4 vs 41.5); per-tag table in the PR.

### Stage 7 - Noisy-channel spelling (hybrid) - `stage-7/spelling` - done (on merge)
- `spelling.py`: of all known words, which one most probably produced the typed word (technique D). Score = log prior (catalogue row count of the word) minus a weighted edit cost (neighbouring key 0.5, swap 0.6, doubled letter 0.6, other edit 1.0). Guards: known words and every word in the catalogue's own titles and descriptions are never touched (Stage 7b replaced the first hand-written word list by a real-word frequency rule); three letters or fewer are never corrected; the first letter must match; short words allow only the cheapest slip; a runner-up within 0.5 of the best means "unsure" and nothing changes. Corrects every product word (category, colour, brand, size words), not only brands; a mention resting on a corrected word has `kind="fuzzy"` and confidence 0.60.
- (A rules floor for low-confidence reads was added here and removed again in Stage 7b: it cost more than it saved.)
- The generator can inject typos (`typo_rate`) for robustness checks; training leaves it at 0 because dev has none.
- Replaced the earlier brand-only fuzzy match (`Lexicon.lookup_fuzzy`) and its config fields.
- **Owns:** `backend/anticipatory/spelling.py`, `backend/tests/test_spelling.py`; adds `SpellingConfig`; `Lexicon` gains `word_weights`, `catalogue_words` and the corrector; `slots.py` corrects tokens before lookup.
- **Results:** single-slip recovery 96% (swap, neighbouring key, doubled letter), 77% for a dropped letter (the misses are four-letter words that become three letters, which are never corrected by design); no false correction on any dev word or generator phrase; dev score unchanged at 43.4 with 0 wrong commits. Whole pipeline on typed requests, 15% of product phrases with a typo: accuracy 0.998 with spelling versus 0.845 without; score 43.0 versus 36.7.
- **Exit (met):** at least 90 percent of single-slip variants recovered; zero new stray matches on dev; wrong commits not higher than Stage 6.

### Stage 7b - Real words and unresolved constraints (hybrid) - `stage-7b/unknown-words` - done (on merge)
- Added after the Stage 7 review (user request): no hand-written lists of words to protect or of brands we do not sell.
- `words.py` plus `data/english_words.tsv` (60,000 most frequent English words with counts). `spelling.py` now treats a real English word as a typo only when the shop word it resembles is at least 100 times more common ("short" and "skirt" stay, "runing" becomes "running"); the hand-written guard list is gone. Rule measured on 63 protected words (unsold clothing, brands, colours, ordinary English): none changed, all typos still fixed.
- `unknown.py`: finds constraints the shop cannot answer, for every slot, from structure plus data (words the catalogue text and lexicon explain are never flagged; function words come from the frequency list). Unknown brand (after "from", "by", "brand", before "brand", capitalised mid-sentence, or a name-like word before the category), unknown size ("size 14", "4XL", "size 32 sandals", "size M cap", handled in the state), unknown colour or style ("purple shirt", "in purple", "violet colour"). A very common English word (friday, nice) is never flagged. `Snapshot.unresolved` makes the state unsettled: no early commit, the trace and `agent.unresolved` say what was not understood.
- Removed the low-confidence rules floor in `HybridRisk`: it cost 1.3 score points on typo-heavy requests and saved at most 0.3.
- **Owns:** `backend/anticipatory/{words,unknown}.py`, `backend/anticipatory/data/english_words.tsv`, `backend/tests/{test_words,test_unknown}.py`; changes `spelling.py`, `slots.py` (`Reading`), `state.py`, `policy.py`, `trace.py`, `agent.py`, `lexicon.py` (`FILLER_WORDS`), `config.py` (`UnknownConfig`, spelling ratio).
- **Results:** dev unchanged at 43.4 with 0 wrong commits and 0 flagged dev requests (every dev request is satisfiable, so any flag would be a false positive); 0 of 3,000 clean synthetic requests flagged. On requests that ask for something the shop cannot answer, early commits fall from 20.9% to 5.6% (unknown brand) and 2.8% to 0.5% (colour); for an unknown size from 1.9% to 0.8% (corrected in Stage 8: the first measurement, 16.5% to 0.2%, inserted the unknown size after a valid one and was wrong; sized categories already cannot commit without a recognised size). The brand figure that remains is commits made before the unknown word was spoken, which no reading can prevent.
- **Exit (met):** zero flags on dev; zero wrong commits on dev; hand-written guard list removed.

### Stage 8 - Robustness and tuning - `stage-8/robustness` - done (on merge)
- `backend/data/dev_extra.jsonl` (87 requests in the dev format), built by `backend/scripts/build_dev_extra.py` from about 90 hand-written phrasing templates filled from real catalogue products (deterministic; every target is the unique match of the slots mentioned; `earliest` computed). Phrasing the generator never produces: other openers, unseen cue words ("not exceeding", "at most"), possessives, price corrections (dev has none), two corrections in one request, markers such as "correction:" and "scratch that", Hindi-English, typos, odd punctuation, seed-list synonyms and three synonyms outside the seed list (tag `unseen_synonym`, expected to fail). Run with `python evaluate.py --agent agent.py --data data/dev_extra.jsonl`.
- Bugs found on it and fixed: a trailing "size" that closes a size ("M size", "XXL size", "size 8 UK") was treated as a cue still awaiting a number and cost a word or more on a very common phrasing; "Pacevo's" was not read as the brand (now: drop the possessive when what is left is a known word); colloquial openers ("gimme", "wanna", "plz", "yo") were flagged as unknown styles; "correction", "ignore", "disregard" were not marker words.
- `backend/tests/test_scenarios.py`: 23 hand-written end-to-end scenarios (price corrections, double corrections, unseen markers, possessives, rupee formats, odd punctuation, typos, unknown brand and size holding back, empty and very long requests) on real anchor products.
- **Tuning (protocol):** tune on two thirds of dev (every request whose index is not divisible by 3), hold out the other third, `dev_extra` and 3,000 fresh synthetic requests. Grid: learned safety multiplier (4, 3, 2), words a commit is assumed to save (1, 2), price-cue hold (all cues, size cue only, "make" only). **Outcome: keep the defaults.** The current setting is the only one with zero wrong commits on the tune split, the held-out third and `dev_extra` together; every setting that adds earliness (+0.4 to +2.8 score) adds 1 to 2 wrong commits per set and 13 to 28 wrong commits on 3,000 synthetic requests against 7 for the default. The dangling price-cue hold, which costs earliness, is what prevents the long-exposure corrections.
- **Results (dev_extra, agent.py):** accuracy 0.989 (the one miss class is `unseen_synonym`), 0 wrong commits, score 40.5; the kit baseline scores 0.793 and 31.3 on the same file. Dev unchanged: 43.5, 0 wrong.
- **Owns:** `backend/data/dev_extra.jsonl`, `backend/scripts/build_dev_extra.py`, `backend/tests/test_scenarios.py`; small changes to `state.py`, `slots.py`, `lexicon.py`, tests.
- **Exit (met):** zero wrong commits on dev and on dev_extra; per-tag table in the PR.

### Stage 9 - Evaluation and hardening - `stage-9/evaluation` - done (on merge)
- `backend/scripts/report.py`: runs the agent through the organisers' own scorer (`evaluate.run`, `score_one`, `summarise`, imported unchanged) on dev and `dev_extra`, writes `backend/outputs/results.jsonl` (the "outputs on the public dev set" Round 1 asks for), `results_dev_extra.jsonl` and `report.md`: headline numbers against the kit baseline and the perfect-early-committer ceiling, per-tag tables, every request with a wrong answer or wrong commit, cost and speed (per-word latency percentiles, CPU per request, cold start in a fresh interpreter, memory, searches, disk size, extrapolation to a million requests), and the hybrid, rules-only and learned-only variants side by side.
- Hardening (`tests/test_edge_cases.py`): devanagari, emoji, control characters, zero-width marks, a 20,000-letter word, a 400-digit number, negative and scientific numbers, SQL-looking text, blank words; protocol misuse (finish twice, words after finish, start twice, back-to-back requests, observe before start). Nothing raised. One real weakness found and fixed: the cost of a request grew with the square of its length (2,000 words took 12.9 s). `StateConfig.max_live_words` (200): past it the state stops refreshing per word (the agent can only wait) and `finish()` still reads the whole request once; 2,000 words now take 155 ms and 20,000 words 235 ms, with the final answer unchanged. Real requests are 6 to 25 words and are unaffected.
- Cleanup: unused imports removed (five files), a scan for unreferenced definitions found none, all scripts re-run.
- `README.md`: status with the final numbers, layout, run steps and a layered description of the package. Section 4 step 5 above replaced with the user's current PR rule.
- **Owns:** `backend/scripts/report.py`, `backend/outputs/`, `backend/tests/{test_edge_cases,test_report}.py`, `docs/assumptions-and-data.md`, `README.md`; one setting in `config.py` and `state.py`; the two review fixes in `lexicon.py`, `slots.py`, `tokens.py`, `state.py`.
- **Frozen numbers (for the abstract and the note):** dev 43.5 (kit baseline 20.0, accuracy 1.000 vs 0.527, 0 wrong commits, earliness 6.4% of a possible 16.3%, 1.19 searches per request); dev_extra 40.5 (baseline 31.3; accuracy 0.989 vs 0.793; 0 wrong commits); 0.088 ms per word on average (p95 0.40 ms), 1.55 ms CPU per request, cold start 73 ms, 36 MB, about 0.4 CPU-hours per million requests, no model calls, standard library only.
- **Review before merge (user request: is the backend really solid?):** full details and numbers in `docs/assumptions-and-data.md`. Clean-room clone of the branch (tests from both directories, all agents, another working directory, outputs reproduce byte for byte); an independent re-implementation of the scorer matches every logged score; run-time audit (no dev file read, every search through the counted tool); causality test (4,440 prefixes, 0 lookahead); metamorphic tests (case, politeness words, openers: 0 changes); 20,000 synthetic requests (accuracy 0.9993, 0.25% wrong early commits, deterministic); 20,000 random-word fuzz requests (no violations); a 44-request blind set (accuracy 0.977, 0 wrong commits, baseline 0.750, taken before fixing what it found); probes of plausible phrasing outside the design.
- **Found and fixed in review:** "price cap 2000" read "cap" as a category (multi-word price cues now claim it); sizes glued to their cue ("size9", "UK10", "sz10", "w32") are split into two tokens. Documentation corrected where it overstated: no interface for the slot reader, an outdated architecture diagram, a per-slot cooldown that does not exist, "O(1) per word" (it is a bounded re-read), the `finish()` search description, and the "never a wrong commit" wording (0 on dev, 0.25% on synthetic).
- **Exit (met):** full test suite green (344 tests); results file produced; numbers frozen; assumptions and data sources documented.

### Stage 10 - Stream interface - `stage-10/stream-interface` - done (on merge)
- `backend/server/` and `docs/stream-contract.md` (version 1). **Libraries, not hand-rolled code** (user review: third-party libraries are allowed; the stdlib-only rule is for the agent, which the harness runs, not for this optional demo interface): **FastAPI + uvicorn** (typed Pydantic models give validation, an OpenAPI document and `/docs`; WebSocket, server-sent events, API-key security, body limit, CORS and safe static files), **httpx + httpx-sse + websockets** for the client. Compared hands-on on Python 3.14 (Starlette alone, aiohttp, Flask, Litestar, requests + sseclient-py); recorded in the contract. They need Python 3.11 or newer and live in `backend/requirements-server.txt`; the agent still needs only Python 3.8+.
- Design, fixing every "honest limit" of the first (standard-library) version: **stateless REST** (`POST /api/step`, `/answer`, `/run` carry the words so far; the agent is deterministic and causal, so replaying them gives the live answer; no sessions to store, expire or lose, any process can answer); a **WebSocket** (`/api/ws`) that pushes events over one connection; **server-sent events** for paced replays; an **API key** (header, bearer or query), **mandatory to listen beyond localhost**; CORS limited to pages served from this machine unless `--cors-origin` says otherwise. Word events also carry `committed`, so the latest event alone tells a client where the agent committed.
- Layers: `models.py` (Pydantic), `events.py`, `service.py` (stdlib only, no web framework, tested without the extras), `app.py` (routes, auth, errors, WebSocket), `__main__.py` (`python -m server`), `scripts/stream_client.py`.
- **Verification:** the interface is transparent: for all 387 dev and dev_extra requests, what it reports equals the committed results of the kit's harness, over replay, WebSocket and stateless REST, and a stateless `step` equals the live feed at every prefix. `tests/test_server_contract.py` checks the contract document against the generated OpenAPI paths, the Pydantic models, real events, the error table and the limits; `tests/test_server_models.py` fails if a model lags behind an event (a missing field would otherwise be dropped silently). Also tested over real sockets: auth in every form, CORS, SSE, the WebSocket protocol including errors, idle timeout and oversized messages, a vanishing client, static files and path traversal, body limits, parallel clients, the launcher as a subprocess including the fail-closed rule.
- **Bugs found by testing and measuring (fixed, with regression tests):** unread request bodies corrupting keep-alive connections (first version); the launcher's self-created socket lacked `IPPROTO_TCP`, so asyncio left Nagle on and every keep-alive call took 43 ms (now 0.4 ms; the test fails when the bug is put back); the "listening" line was printed before the server accepted connections; a wrong key on a WebSocket is refused at the handshake with HTTP 403, not a close code.
- **Measured** (loopback, one process): 0.60 ms median per live word over the WebSocket (p95 1.3 ms); 2.3 ms for a stateless step that replays up to 11 words; about 900 WebSocket words per second or 270 REST calls per second with 16 concurrent clients, no errors.
- **Still not covered (documented):** no TLS (use a reverse proxy), one shared API key that a browser must pass in the query string, no per-client rate limiting.
- **Owns:** `backend/server/`, `backend/requirements-server.txt`, `backend/scripts/stream_client.py`, `docs/stream-contract.md`, `backend/tests/{_server_fixture,test_server_service,test_server_models,test_server_http,test_server_cli,test_server_client,test_server_contract}.py`, `README.md`.
- **Exit (met):** a client can submit words one by one and receive trace records (WebSocket, REST and replay, tested); contract documented and checked by a test; 446 tests green with the extras, 376 plus 5 skipped modules without them.

### Stage 11 - Base UI - `stage-11/base-ui` - todo
- Specs are discussed with the user at the start of this stage; this is only the starting point.
- Starting point: a UI that replays or live-types a request word by word and shows slots, confidences, candidate count and the commit moment, driven by the stream interface.
- Create `frontend/`, agree its conventions, add a short run guide.
- **Owns:** `frontend/` only (plus a `README.md` run-steps section).
- **Exit:** the UI runs end to end against the real agent on dev requests, including a correction case; it is good enough to record the demo video from.

### Stage 12 - Submission package - `stage-12/submission-package` - todo
- `docs/architecture-note.md` (1 page), `docs/abstract.md` (500 words or fewer: impact, cost estimate, innovation, build summary).
- 3-minute demo video recorded from the UI (the video itself lives outside git).
- Drive folder with documents + repo link + video, sharing set to "anyone with the link can view"; paste the folder link into the "Submission Link" field; test the link in a private window first.
- **Owns:** `docs/architecture-note.md`, `docs/abstract.md`.
- **Exit:** PR merged; submitted and confirmation saved; tag `r1-submission` on the submitted commit.

### Stage 13 - Finals prep (after Round 1) - `stage-13/finals-prep` - todo
- Voice demo through browser speech-to-text feeding words to the backend.
- Wasted-search limit exposed as a setting in the UI.
- Fresh hidden-set robustness; latency and cost numbers; live jury test practice; 10-minute pitch.
- **Soft lexicon (user decision 2026-11-26, after the Stage 6 audit of hand-written words):** the synonym tables in `lexicon.py` (about 90 phrases, part read off dev, part guessed) are an honest seed list, not a solution. After Round 1 replace or back them with pretrained word vectors: an unknown word ("trainers") maps to its nearest category by meaning, as a lower-trust fallback behind the exact and seed matches (option C: keep the seed list as the high-trust layer). Needs an external vector file (a trimmed GloVe or fastText subset shipped as small JSON), so check size and licence first.
- Hybrid extras if not done earlier: a probability over candidate products (technique C) and a soft lexicon from pretrained word vectors (technique E).
- LLM reader only if the user decides to add one.
- This stage may split into several branches once the finals details are known.

---

## 7. Round 1 deliverables

### Demo video outline (3 minutes)
1. The problem and the score rule (never commit wrong).
2. A plain request word by word in the UI: slots filling, confidence rising, the commit moment.
3. A correction ("size M, oops, XS") and a late constraint: the agent waits, then commits safely.
4. Results table: accuracy, wrong commits, earliness vs best possible, searches, latency.
5. What is next: voice demo and finals plans.

### Abstract outline (500 words or fewer)
Impact (earlier, safer shopping assistance) / Build summary (layered rules engine, commit policy, verification, UI) / Innovation (separability-based commit rule, confidence and revision handling, trace) / Cost estimate and scale (no language model calls, about 0.09 ms per word and 1.5 ms of CPU per request on one core, a bounded re-read of the words so far, in-memory vocabulary, searches counted) / Results.

### Final checklist
- [ ] Abstract (500 words or fewer)
- [ ] 1-page architecture note
- [ ] 3-minute demo video
- [ ] Repo with README, tests, and outputs on dev (`backend/outputs/results.jsonl`)
- [ ] Drive folder with everything, shared by link
- [ ] Folder link submitted before the deadline
- [ ] Tag `r1-submission` on the submitted commit

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Limited time before the deadline | Small stages; Stages 2 to 8 are the core; keep the UI small; skip nothing in the merge gate |
| PR review waits block the next stage | Keep PRs small so review is quick; ask before stacking if one is still open |
| Merge conflicts | Section 4 rules: sequential stages, disjoint files, additive config blocks |
| Overfitting to dev | Rules over memorised strings; held-out split; `dev_extra.jsonl` |
| Hidden set has unseen wording | Generalising synonym and number handling; conservative confidence |
| Late constraint invalidates a commit | Policy waits when a constraint is statistically likely; measured in Stages 6 and 8 |
| Wrong commit penalty | Hard gate of zero on dev; default action is wait |
| UI scope creep | Specs agreed at the start of Stage 11; UI shows trace only, no logic |
| Submission mishap | Submit early; test the Drive link privately |

---

## 9. Open decisions

- Merge style for PRs: squash and merge (decided; linear `main`).
- UI specs, framework and how it talks to the backend - discussed at Stage 10 and Stage 11.
