# Architecture note (one page)

**Goal:** after each word of a shopper's request, decide whether to commit to one product now, search, or wait. Scoring rewards earliness and punishes a wrong commit, so the design is built around the cost of being wrong.

## Pipeline (all in `backend/anticipatory/`, standard library only; `policy.py` also holds the catalogue port and `agent.py` the trace record)
```
word -> tokens -> slot reader -> filter state -> commit policy -> search tool
        (split     (mentions     (beliefs,        (risk vs        (kit
        glued      + confidence, revisions,       break-even,     search.py,
        sizes)     spelling,     corrections,     one match?)     counted)
                   price cues)   unresolved)
                                        |
                        risk model: rules when fresh or paused,
                        22-weight logistic regression once settled
```
1. **Tokens and slot reader.** Normalises words, corrects spelling with a noisy-channel model (keyboard-neighbour edit costs, a 60,000-word frequency list so real words are never "corrected"), reads English and Hindi number words, "k" amounts and price cues. Each mention gets a confidence by source (exact, synonym, fuzzy, bare number).
2. **Filter state.** Keeps the current belief per slot (category, colour, size, brand, max price), revises on correction markers ("no wait", "I mean"), flags numbers that may still grow and constraints it cannot place (a brand the shop does not sell).
3. **Commit policy.** Commits only when the catalogue search returns exactly one match, nothing is unresolved, and the estimated risk is below the break-even risk of 3.9 percent, derived from the scoring formula. Searches only when a commit would be worthwhile (each extra search costs 0.02).
4. **Risk.** `HeuristicRisk` (rules), `LearnedRisk` (logistic regression on 22 features, trained on 30,000 synthetic requests, multiplier 4.0 chosen on validation requests), and `HybridRisk`, which uses the rules while the request is fresh or paused and the learned model otherwise. `agent.py` is the hybrid.
5. **Learned words (optional).** A separate file taught by corrections ("clogs, I mean sandals") and accepted products; absent, an unplaceable word is dropped. The agent only reads it, so runs stay deterministic.
6. **Stream interface (optional).** FastAPI server: WebSocket for live typing, server-sent events for replay, stateless REST. The agent is causal and deterministic, so the server holds no session state. A static chat page draws what the server sends and contains no decision logic.

## Design decisions
- **No language model:** zero per-request cost, 0.09 ms per word, fully reproducible.
- **Never guess on the unknown:** unresolved constraints block an early commit; the final answer is still the best match without them.
- **Honest limits:** synonyms outside the seed list are not understood, punctuation inside a phrase breaks it, long-delayed corrections are unpredictable (about 0.25 percent wrong commits on synthetic data).

## Numbers (dev, official scorer)
Score 43.6 (baseline 20.0), accuracy 1.000, 0 wrong commits, 1.10 searches per request, 36 MB, 1.6 ms CPU per request. Details: `backend/outputs/report.md`, `docs/assumptions-and-data.md`, `docs/stream-contract.md`.
