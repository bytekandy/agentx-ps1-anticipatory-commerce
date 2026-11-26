# AgentX PS1 - Anticipatory Commerce

Entry for **AgentX: The Agentic Commerce Challenge** (Techfest 2026-27, IIT Bombay, by Rezolve.ai), Problem Statement 1.

A shopping request arrives one word at a time, for example "black running shoes, size nine, under two thousand...". The agent predicts the shopper's filters (category, colour, size, budget, brand) from the words so far, searches early, and commits to a product as soon as it is safe to, without ever committing to a wrong one. Text only. No language model is used.

## Status

The backend is complete for Round 1; the stream interface and the base UI come next (see `docs/round1-plan.md`). On the public dev set the agent scores **43.5** against the kit baseline's 20.0, with every final answer right and no wrong early commit. On 87 extra hand-written requests with phrasing the dev set does not contain (`backend/data/dev_extra.jsonl`) it scores 40.5 (accuracy 0.989) against the baseline's 31.3 (0.793). It uses about 1.5 ms of CPU per request, no model API, and only the Python standard library. The full numbers, per-tag tables and the cost figures are in [`backend/outputs/report.md`](backend/outputs/report.md), and the per-request output on the dev set, as the organisers ask for, is `backend/outputs/results.jsonl`.

## Repository layout

This is a monorepo.

```
backend/     Python (standard library only): the agent and the Rezolve starter kit
  anticipatory/   the agent package (see below)
  data/           our own extra test requests (dev_extra.jsonl)
  outputs/        results on dev and dev_extra, and the generated report
  scripts/        analysis, training, report and test-data builders
  tests/          unit and scenario tests
frontend/    base UI (added in a later stage)
docs/        plan, analysis, architecture note, abstract
```

`backend/` also holds the unmodified starter kit from Rezolve: `catalogue.csv`, `dev.jsonl`, `search.py`, `evaluate.py` and the kit's own `README.md`. These five files are never edited; our code sits beside them.

## Run

Requires Python 3.9 or later. Nothing to install.

```
cd backend
python evaluate.py                    # score the kit's baseline on dev.jsonl
python search.py white Pacevo sneakers  # try the local catalogue search
```

Score our agent on the dev set (`agent.py` is the hybrid: hand-coded rules for fresh values, a learned risk model for calm states):

```
python evaluate.py --agent agent.py
python evaluate.py --agent agent.py --data data/dev_extra.jsonl   # 87 extra hand-written requests (unseen phrasing)
python evaluate.py --agent agent_heuristic.py   # rules only (the safe reference)
python evaluate.py --agent agent_learned.py     # learned risk model only
```

Regenerate the committed outputs (results on dev and dev_extra, and the report with per-tag tables and the cost and speed numbers; about 15 seconds; scoring is the organisers' own `evaluate.py`, imported unchanged):

```
python scripts/report.py
```

Retrain the risk model (synthetic requests, pure Python, about two minutes): `python scripts/train_risk.py` from `backend/`. Rebuild the extra test requests: `python scripts/build_dev_extra.py`.

Run the unit tests (also from `backend/`; works from the repo root too with `python -m unittest discover -s backend/tests -t backend`):

```
python -m unittest discover -s tests -t .
```

The agent code lives in the package `backend/anticipatory/` (standard library only). Layers, from the words up:

- **Reading the words:** `tokens.py` (normalise words), `numbers.py` (prices and sizes as digits, "3.5k" or English and Hindi number words), `lexicon.py` (categories, colours, brands and sizes from the catalogue, plus a seed synonym list), `words.py` (general English word frequencies), `spelling.py` (noisy-channel correction of typed product words), `slots.py` (slot mentions with confidences: size or price decided by cue words such as "size", "UK", "under", "tak").
- **Knowing what the shopper wants:** `state.py` (the running reading: one belief per slot, corrections such as "black, oops, navy", warning flags), `unknown.py` (constraints the shop cannot answer: an unknown brand, size, colour or style).
- **Deciding:** `risk.py` (how likely a commit is to be wrong: hand-coded rules and a learned logistic regression, combined), `policy.py` (when to search and when to commit, from the break-even of the score formula), `catalog_port.py` (the only door to the catalogue), `trace.py` (one record per word), `agent.py` (the orchestrator).

Check the reader against dev with `python scripts/slot_accuracy.py` and `python scripts/state_replay.py` (from `backend/`).

## Known limits

- **The synonym list is hand-written.** `backend/anticipatory/lexicon.py` holds a seed list of about 90 synonyms (some read off the dev set, some guessed, the guesses marked in the code). A synonym nobody listed ("trainers") is not understood. The agent then notices a word it cannot place (see below) and does not commit early. A soft lexicon from pretrained word vectors is planned for after Round 1 (see the plan, finals prep).
- **Things we do not sell are noticed, not guessed.** A brand we do not stock ("from Nike"), a size that does not exist ("size 14", "4XL", "size 32 sandals"), or a colour or style we do not have ("purple shirt") is flagged as unresolved: the agent does not commit early, and the trace says what it could not match. No list of brands, sizes or colours is used. The structure of the request plus a general English word-frequency list decide.
- Everything else the agent knows about products (categories, colours, brands, sizes, prices) is read from `catalogue.csv`; no dev request or answer is stored in the code.

## Data sources

- `backend/catalogue.csv`, `backend/dev.jsonl`, `backend/evaluate.py`, `backend/search.py`: the organisers' starter kit, unchanged.
- `backend/anticipatory/data/english_words.tsv`: the 60,000 most frequent English words with their counts, from Peter Norvig's `count_1w.txt` (https://norvig.com/ngrams/count_1w.txt), a subset of the Google Web Trillion Word Corpus counts distributed by the Linguistic Data Consortium. The data is distributed for educational and research use; it is used here only to tell real words from typos and to rank how common a word is. Check the licence before any commercial use.
- `backend/anticipatory/data/risk_model.json`: the learned risk model, trained by `backend/scripts/train_risk.py` on synthetic requests we generate ourselves.

## Working on this repo

- One branch per stage, named `stage-<n>/<short-kebab>`, merged into `main` through a pull request.
- Commits follow Conventional Commits (`feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `chore`).
- The full plan, design principles, naming conventions and git workflow are in [`docs/round1-plan.md`](docs/round1-plan.md).
