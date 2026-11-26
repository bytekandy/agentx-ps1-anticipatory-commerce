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

---

## 2. Design principles (how we build)

1. **Safety first.** A wrong commit costs about 1.0 plus lost earliness; one word earlier gains about 0.045. The default action is always "wait".
2. **Layered, pure core.** Reading words (pure functions) -> filter state -> decision policy -> orchestration -> I/O adapter. Only the outermost layer touches `tools.search`.
3. **Dependency inversion.** The agent depends on a tiny `CatalogPort` interface. Tests use a fake catalogue; runtime uses the counted `tools.search`. The filter reader sits behind an interface too, so an LLM reader could replace the rules later (only when the user says so).
4. **One source of tunables.** All thresholds and limits live in `config.py`, as frozen dataclasses grouped per area. No magic numbers in logic.
5. **Deterministic and reproducible.** No randomness, no network. Same input gives the same output.
6. **Observable.** Every word produces a trace record (filters, confidences, candidates, action, reason). Used for debugging, analysis, the UI and the demo video.
7. **Test pyramid.** Unit tests for pure modules, scenario tests for corrections and late constraints, benchmark runs through `evaluate.py`.
8. **Time-boxed simplicity (YAGNI).** Python standard library only for the agent, a small flat package, no frameworks. Add structure only when it earns its place.
9. **Kit immutability.** The five kit files in `backend/` are never edited.
10. **Bounded cost.** O(1) work per word; the catalogue is read only to build vocabularies; products are looked up through counted searches. Candidate searches use a large `k` because cost is per call, not per result.
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
5. **The user reviews and merges** (squash and merge, so `main` stays linear, with the PR title as the commit message). Claude never merges.
6. **Next stage starts only after the previous PR is merged**, branching from the updated `main`. No stacked or parallel stage branches unless the user asks; if the previous PR is still open, ask first.

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
word -> slots.read_word -> state.FilterState.update -> policy.plan_search
                                                          |
                                           catalog_port.search (counted, large k)
                                                          |
                                           policy.decide_commit(candidates, state)
                                                          |
                              {wait | commit(product_id)} + trace record

finish(): re-read the full request -> final search -> return product_id
```

- **Slots:** category, colour, brand, size, max_price (plus min_price if seen). Each slot holds a value, a confidence, and a revision history.
- **Revisions:** markers like "oops", "no wait", "sorry I meant", "actually" replace the earlier slot value and start a cooldown before that slot is trusted again.
- **Commit rule (user confirmed):** commit once the remaining candidates cannot be separated by anything the shopper might still add. Candidate rows differ by size, so sized categories normally wait for the size; unsized categories (backpacks, caps, headphones, watches, wallets) can commit earlier.
- **Hybrid layer (team leader's request, decided 2026-11-26):** the rules read the request and stay the backbone. Learned or statistical parts answer how risky a commit is (`risk.py`, Stage 6) and recover misspellings (`spelling.py`, Stage 7). Everything is trained offline in pure Python and shipped as small JSON, so the runtime stays standard-library only. Possible later additions (after Round 1): a probability over candidate products instead of a single guess, and a soft lexicon from pretrained word vectors. No language model.
- **Commit rule as expected value (technique A):** committing now is worth it when `P(wrong) x (1.0 + earliness forfeited)` is smaller than the earliness gained by not waiting, which in practice means a risk below about 4 percent when it saves one word and about 12 percent when it saves four (derived from the score formula; the exact budget is tuned in `config.py`).
- **Key risk (Stages 5 to 8):** corrections, not late constraints. Stage 1 showed a unique match built from correctly read values can only be overturned by a correction (or a misread); late constraints never invalidate it. Measure per-slot correction risk and clause-boundary signals, then set the thresholds in `config.py`.
- **Confidence:** exact catalogue match high; synonym medium; number-word parse and ambiguous tokens (for example a bare "M") lower, raised by context.
- **Final check:** `finish()` ignores earlier guesses, reads the whole request, searches once more, and returns that result.

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
- Safety rule: an unsettled state is never safe whatever the model says. `agent.py` keeps the heuristic as the default; `agent_learned.py` selects the learned model. (An ensemble that takes the more cautious of the two was measured and rejected: 0 wrong on dev but only 41.2.)
- **Owns:** `backend/scripts/make_training_data.py`, `backend/scripts/train_risk.py`, `backend/anticipatory/data/risk_model.json`, `backend/agent_learned.py`, `backend/tests/test_risk.py`, `backend/tests/test_training.py`; extends `risk.py` (new `RiskInput` fields and `LearnedRisk`); adds a learned-risk block to `config.py`; two small reader fixes in `slots.py` found by the generator round trip.
- **Exit:** calibration error reported on dev (held out); wrong commits at or below the heuristic; score at or above the heuristic, per-tag table in the PR. If it does not beat the heuristic, the PR says so and the heuristic stays the default.

### Stage 7 - Noisy-channel spelling (hybrid) - `stage-7/spelling` - todo
- `spelling.py`: candidates within one edit (two for long words) of a known word, scored by an edit model (keyboard-adjacent substitutions and transpositions cheaper) times a word prior from the catalogue, with guard words so common English words are never "corrected" (technique D). Extends the brand-only fuzzy match to every slot at lower confidence.
- **Owns:** `backend/anticipatory/spelling.py`, `backend/tests/test_spelling.py`; small additive hook in `lexicon.py`; a spelling block in `config.py`.
- **Exit:** at least 90 percent of single-typo variants of catalogue values recovered in a synthetic test; zero new stray matches on dev; wrong commits not higher than Stage 6.

### Stage 8 - Robustness and tuning - `stage-8/robustness` - todo
- Late constraints, Hindi-English handling, correction edge cases; tune `config.py` values.
- Build `data/dev_extra.jsonl` (60 or more invented requests with unseen phrasings and tricky corrections).
- Tune on about two thirds of dev; validate on the rest plus `dev_extra.jsonl` to avoid overfitting.
- **Owns:** `backend/data/dev_extra.jsonl`, scenario tests, small additive changes to earlier modules and `config.py` values.
- **Exit:** zero wrong commits on dev (or each exception documented); per-tag table recorded in the PR.

### Stage 9 - Evaluation and hardening - `stage-9/evaluation` - todo
- `scripts/report.py` (per-tag, latency and searches summary); edge-case tests (empty words, very long requests, odd punctuation); code cleanup; finish the root `README.md` run steps.
- Generate `backend/outputs/results.jsonl` with `--log` from the final agent.
- **Owns:** `backend/scripts/report.py`, `backend/outputs/results.jsonl`, `backend/tests/test_edge_cases.py`, `README.md` updates.
- **Exit:** full test suite green; results file produced; numbers frozen for the abstract and note.

### Stage 10 - Stream interface - `stage-10/stream-interface` - todo
- A thin backend interface that replays or live-feeds a request and streams the trace records; the contract is written down so backend and UI can be built independently. Transport (for example standard-library HTTP with server-sent events) is decided here.
- **Owns:** `backend/server/`, `docs/stream-contract.md`, tests for the interface.
- **Exit:** a client can submit words one by one and receive trace records; contract documented; tests green.

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
Impact (earlier, safer shopping assistance) / Build summary (layered rules engine, commit policy, verification, UI) / Innovation (separability-based commit rule, confidence and revision handling, trace) / Cost estimate and scale (no model calls, O(1) per word, in-memory vocabulary, searches counted) / Results.

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

- Merge style for PRs: squash and merge is proposed (linear `main`); confirm at the first PR.
- UI specs, framework and how it talks to the backend - discussed at Stage 10 and Stage 11.
