# Abstract: an agent that acts before the shopper finishes speaking

## Problem and impact
A shopper who speaks or types a request word by word still waits for the last word before a shop reacts. An agent that can safely start earlier shortens every voice and chat purchase. The risk is a premature wrong answer, which costs more than the time saved. Our agent decides after every word whether it knows enough to commit to one product, and holds back when a correction ("black, no wait, white"), a late constraint or an unfamiliar word could still change the answer.

## What we built
A deterministic agent with no language model calls. It reads each word, keeps a belief for category, colour, size, brand and price, tracks corrections and numbers still being spoken, and searches only when a commit is worth its cost. A 22-weight statistical model, trained on synthetic requests, estimates the chance that a commit is wrong; a rules layer takes over while the request is still changing. It commits only when exactly one product matches and that chance is below the break-even point derived from the scoring formula (3.9 percent).

## Results (public dev set, scored by the organisers' evaluate.py)
- Score 43.6 against 20.0 for the kit baseline; right final answer on all 300 requests (baseline 0.527); zero wrong early commits.
- 87 requests we wrote with new phrasing: 40.0 against 31.3, no wrong early commit. Two outside-author sets, since used for development: 48.1 and 40.4.
- 20,000 synthetic requests: about 0.25 percent end in a wrong early commit.
Dev scores are optimistic: some vocabulary and tuning came from reading dev. The earliness gain is modest by design (6.4 percent of the request out of 16.3 possible): every faster setting we tried added wrong commits.

## Cost estimate
No model calls and no per-request fees. Mean 0.09 ms per word, 1.6 ms of CPU per whole request, 36 MB of memory, 73 ms cold start, about 1 MB on disk. One core handles a million requests in roughly 0.4 CPU-hours. The agent uses only the Python standard library.

## Innovation
1. Commit decisions are priced from the score itself: the break-even risk comes from the formula, not a hand-picked threshold.
2. A hybrid: rules while the request is fresh, the learned risk model once it settles.
3. Honest handling of the unknown: a brand, size or colour the shop does not sell is detected and blocks an early commit, and a real-word guard stops "short" becoming "shirt".
4. Noisy-channel spelling correction, English and Hindi number words, and an optional lexicon that learns words from corrections and accepted answers, with no lookup of dev answers.

## Interface and reproducibility
An optional FastAPI server streams the agent's reading word by word over WebSocket and server-sent events, and a chat page shows slots, confidence, the commit moment and the score live. Output is deterministic and the committed result logs regenerate byte for byte.
