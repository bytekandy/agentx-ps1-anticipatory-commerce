# AgentX PS1 - Anticipatory Commerce

Entry for **AgentX: The Agentic Commerce Challenge** (Techfest 2026-27, IIT Bombay, by Rezolve.ai), Problem Statement 1.

A shopping request arrives one word at a time, for example "black running shoes, size nine, under two thousand...". The agent predicts the shopper's filters (category, colour, size, budget, brand) from the words so far, searches early, and commits to a product as soon as it is safe to, without ever committing to a wrong one. Text only. No language model is used.

## Status

Work in progress. The starter kit is in place; the agent is being built stage by stage (see `docs/round1-plan.md`). Only the kit's baseline agent exists so far.

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

Scoring our own agent is added once the agent exists (`python evaluate.py --agent agent.py`).

## Working on this repo

- One branch per stage, named `stage-<n>/<short-kebab>`, merged into `main` through a pull request.
- Commits follow Conventional Commits (`feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `chore`).
- The full plan, design principles, naming conventions and git workflow are in [`docs/round1-plan.md`](docs/round1-plan.md).
