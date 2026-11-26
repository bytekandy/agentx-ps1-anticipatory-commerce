# AgentX PS1 - Anticipatory Commerce

Entry for **AgentX: The Agentic Commerce Challenge** (Techfest 2026-27, IIT Bombay, by Rezolve.ai), Problem Statement 1.

A shopping request arrives one word at a time, for example "black running shoes, size nine, under two thousand...". The agent predicts the shopper's filters (category, colour, size, budget, brand) from the words so far, searches early, and commits to a product as soon as it is safe to, without ever committing to a wrong one. Text only. No language model is used.

## Status

Work in progress; the agent is being built stage by stage (see `docs/round1-plan.md`). The first end-to-end agent exists: on the dev set it scores 42.1 against the kit baseline's 20.0, with every answer right and no wrong commit.

## Repository layout

This is a monorepo.

```
backend/     Python (standard library only): the agent and the Rezolve starter kit
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

Score our agent on the dev set:

```
python evaluate.py --agent agent.py
python evaluate.py --agent agent_learned.py   # same agent with the learned risk model
```

Retrain the risk model (synthetic requests, pure Python, about two minutes): `python scripts/train_risk.py` from `backend/`.

Run the unit tests (also from `backend/`; works from the repo root too with `python -m unittest discover -s backend/tests -t backend`):

```
python -m unittest discover -s tests -t .
```

The agent code lives in the package `backend/anticipatory/` (standard library only). So far it has the vocabulary layer: `config.py` (all tunables), `tokens.py` (word normalisation), `numbers.py` (prices and sizes written as digits, "3.5k" or English and Hindi number words) and `lexicon.py` (categories, colours, brands and sizes with synonyms), and slot extraction: `slots.py` turns the words so far into slot mentions with confidences (size or price decided by cue words such as "size", "UK", "under", "tak"). Check it against dev with `python scripts/slot_accuracy.py` (run from `backend/`). `state.py` keeps the running reading of the request: one belief per slot, revisions when the shopper corrects themself ("black, oops, navy"), and warning flags for the decision policy. Replay dev word by word with `python scripts/state_replay.py`. On top of that sit the decision layer (`risk.py`, `policy.py`, `catalog_port.py`, `trace.py`) and the orchestrator `agent.py`: the agent searches only when a search could lead to a commit, and commits only to a single matching product when the estimated risk of being wrong is below the break-even set by the score formula.

## Working on this repo

- One branch per stage, named `stage-<n>/<short-kebab>`, merged into `main` through a pull request.
- Commits follow Conventional Commits (`feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `chore`).
- The full plan, design principles, naming conventions and git workflow are in [`docs/round1-plan.md`](docs/round1-plan.md).
