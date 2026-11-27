# AgentX PS1 - Anticipatory Commerce

Entry for **AgentX: The Agentic Commerce Challenge** (Techfest 2026-27, IIT Bombay, by Rezolve.ai), Problem Statement 1.

## What it does

A shopping request arrives one word at a time: "black running shoes, size nine, under two thousand...". After every word the agent keeps a running reading of what the shopper wants (category, colour, size, brand, budget), and decides whether to **wait**, **search** the catalogue, or **commit** to one product right now. Committing early is rewarded, committing to the wrong product is punished harder, so the agent commits only when exactly one product matches and the estimated chance of being wrong is below the break-even point derived from the scoring formula (about 3.9%). Text only, English and Hindi-English. No language model: rules, a spelling corrector, and a small statistical model for the commit risk.

How it is scored (the organisers' `evaluate.py`): 0.4 for the right final answer, plus 0.6 times the share of the request still to come at the first right commit, minus 1.0 per wrong commit, minus 0.02 per search after the first.

On the public dev set: **43.3** against the kit baseline's 20.0, every final answer right, no wrong early commit. On 87 extra hand-written requests with unseen phrasing: 40.1 against 31.3. On two further sets written from an outside-author prompt, blind (200 requests) and brutal (97, deliberately hard wording): 46.9 and 40.2 against 28.5 and 24.3, accuracy 0.995 and 1.000, no wrong early commit. Their failures were studied to improve the reader, so they are development sets, not blind tests; `python backend/scripts/provenance.py --ablate` shows which hand-written word lists matter only on them. About 1.5 ms of CPU per request, no model API. Full numbers: [`backend/outputs/report.md`](backend/outputs/report.md); per-request dev output (as the organisers ask): `backend/outputs/results.jsonl`.

## How the agent thinks

```
word -> tokens -> slot reader -> filter state -> commit policy -> search
                      |              |               |
                spelling, numbers,  one belief    risk model (rules + learned),
                synonyms, cues      per slot,     break-even rule, exactly one match
                                    corrections
```

The agent code is the package `backend/anticipatory/` (Python standard library only):

| File | Role |
|---|---|
| `tokens.py` | normalises each word ("Rs.1,500," becomes 1500, "UK10" becomes "UK", "10"); also English word frequencies |
| `numbers.py` | prices and sizes from digits, "3.5k", English and Hindi number words |
| `lexicon.py` | categories, colours, brands, sizes from the catalogue, a seed synonym list, cue words |
| `spelling.py` | noisy-channel typo correction of product and cue words; real English words are never "corrected" |
| `slots.py` | turns the words so far into slot mentions with confidences ("size 9" versus "under 900") |
| `unknown.py` | notices constraints the shop cannot answer (a brand, size or colour it does not sell) so the agent does not commit early on them |
| `state.py` | the running reading: one belief per slot, corrections ("black, oops, navy"), numbers still growing |
| `risk.py` | chance a commit is wrong: hand-coded rules, a 22-weight logistic regression, and a hybrid of both |
| `policy.py` | the only door to the catalogue (counted searches) and the rule for when to search and commit |
| `agent.py` | the orchestrator that implements the kit's `start / observe / finish` and records a trace per word |
| `learned.py` | optional words taught by earlier requests (`data/learned_lexicon.json`; absent means unknown words are dropped) |
| `config.py` | every tunable number, in one place |

`backend/agent.py` is the entry point the evaluator loads (the hybrid); `agent_heuristic.py` (rules only) and `agent_learned.py` (learned risk only) are comparison variants.

## Repository layout

```
backend/
  agent.py agent_heuristic.py agent_learned.py   entry points for evaluate.py
  anticipatory/    the agent package (table above), with data/ (english_words.tsv, risk_model.json)
  server/          optional FastAPI stream interface: REST, WebSocket, server-sent events
  scripts/         ask.py, report.py, check_reader.py, train_risk.py, make_training_data.py,
                   build_dev_extra.py, analyze_dev.py, learn_lexicon.py, stream_client.py
  tests/           unit, scenario, edge-case and server tests
  data/            dev_extra.jsonl: 87 hand-written test requests
  outputs/         committed results on dev and dev_extra, and the generated report
  catalogue.csv dev.jsonl search.py evaluate.py README.md   Rezolve's starter kit, never edited
frontend/          the web page (chat layout, plain JavaScript, no build step), served by the server
docs/              abstract, architecture note, assumptions and data, stream contract
```

## Run it

Quickest start (macOS, Linux, or Git Bash / WSL on Windows; Python 3.11 or newer and curl): one command sets up the backend on the first run (`backend/.venv`), starts the API and the page, connects them and opens your browser. Ctrl-C stops both. On macOS you can double-click `start.command` instead.

```
./run.sh                            # page on http://127.0.0.1:5173/, API on http://127.0.0.1:8765
BACKEND_PORT=9000 FRONTEND_PORT=3000 ./run.sh     # other ports; NO_BROWSER=1 to skip the browser
```

Or run each part on its own:

```
./backend/setup.sh                  # API and page together on :8765 (--api-only, --setup-only, --port N)
./frontend/run.sh                   # page only on :5173, using the API on :8765 (--port N, --api URL)
```

Requires Python 3.14. The agent needs nothing installed. Run everything from `backend/`.

```
python evaluate.py --agent agent.py                                  # score on dev (the official scorer)
python evaluate.py --agent agent.py --data data/dev_extra.jsonl      # the 87 extra requests
python evaluate.py --agent agent_heuristic.py                        # comparison variants
python scripts/ask.py "beige Loomsy sneakers size 10 under 3000"     # ask in the terminal, word by word
python scripts/report.py                                             # regenerate outputs/ (about 15 s)
python -m unittest discover -s tests -t .                            # tests
```

The optional web interface and stream server use well-known packages and Python 3.11 or newer; the agent does not:

```
pip install -r requirements-server.txt
python -m server --static ../frontend        # page and API at http://127.0.0.1:8765/ (docs at /docs)
python scripts/stream_client.py --live "beige Loomsy sneakers size 10 under 3000"      # WebSocket
python scripts/stream_client.py --replay-example dev-0004 --delay 300                  # server-sent events
```

It listens on this machine only and refuses another address without an API key (`--api-key` or `STREAM_API_KEY`). The protocol is in [`docs/stream-contract.md`](docs/stream-contract.md).

Other scripts: `scripts/train_risk.py` retrains the risk model on synthetic requests (pure Python, about two minutes), `scripts/build_dev_extra.py` rebuilds the extra requests, `scripts/check_reader.py slots|state` measures the reader against dev, `scripts/analyze_dev.py` reproduces the dev findings, `scripts/learn_lexicon.py log.jsonl` teaches the agent words from logged requests.

## Documents

- [`docs/abstract.md`](docs/abstract.md): impact, what was built, results, cost estimate, innovation.
- [`docs/architecture-note.md`](docs/architecture-note.md): one-page architecture.
- [`docs/assumptions-and-data.md`](docs/assumptions-and-data.md): data sources (including every synthetic set), assumptions, what dev influenced, evidence and its limits, verification, known limitations, the learned lexicon, what the dev set shows.
- [`docs/stream-contract.md`](docs/stream-contract.md): the stream interface.

## Data sources

- `backend/catalogue.csv`, `dev.jsonl`, `evaluate.py`, `search.py`: the organisers' starter kit, unchanged.
- `backend/anticipatory/data/english_words.tsv`: the 60,000 most frequent English words with counts, from Peter Norvig's `count_1w.txt` (https://norvig.com/ngrams/count_1w.txt), a subset of Google Web Trillion Word Corpus counts distributed by the Linguistic Data Consortium for educational and research use. It only tells real words from typos and ranks how common a word is.
- `backend/anticipatory/data/risk_model.json`: the risk model, trained by `scripts/train_risk.py` on synthetic requests generated from the catalogue.
- Fonts in `frontend/fonts/`: Geist and Geist Mono (SIL Open Font License, licence file included).

## Known limits

The seed synonym list is hand-written, so a synonym nobody listed ("trainers") is not understood: the agent notices a word it cannot place and does not commit early on it (an optional learning lexicon can be taught such words). A brand, size or colour the shop does not sell is flagged, not guessed. A correction long after the value it replaces cannot be predicted, which costs a wrong early commit in about 0.25% of synthetic requests. The full list, with the evidence behind every number, is in [`docs/assumptions-and-data.md`](docs/assumptions-and-data.md).
