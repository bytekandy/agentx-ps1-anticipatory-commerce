"""Train the risk model (Stage 6): logistic regression in pure Python.

    cd backend
    python scripts/train_risk.py                       # train, report, write the model JSON
    python scripts/train_risk.py --train 40000 --seed 7 --no-write

What it does
  1. Generates synthetic requests (`make_training_data.py`) and replays each word by word,
     labelling every prefix where a single product matches: 1 if it is not the target.
  2. Fits a logistic regression on `risk_features` with Newton's method and a small ridge.
     Identical feature vectors are grouped first, so a fit over hundreds of thousands of
     prefixes takes seconds and needs no numpy.
  3. Refits on-policy. The agent commits at the FIRST prefix that looks safe, which is the
     riskiest one, so a model trained on every prefix is over-confident exactly where it is
     used. Each round keeps, per request, only the prefixes up to the one the current model
     would commit at, and fits again.
  4. Picks the safety multiplier by simulating the commit policy on fresh synthetic requests
     (score = 0.4 + 0.6 x earliness per right commit, -1.0 per wrong one): the smallest
     multiplier whose wrong-commit rate is no higher than the hand-coded heuristic's. The
     policy simulated is the shipped one, `HybridRisk`: the heuristic's rules for fresh or
     just-paused values, the learned model otherwise. The model therefore has to win on
     earliness at equal safety. `dev.jsonl` stays an untouched test.
  5. Reports log-loss, Brier score, expected calibration error and AUC on fresh synthetic
     requests and on `dev.jsonl`, plus the simulated policy score of the learned model and of
     the hand-coded heuristic side by side.
  6. Writes `anticipatory/data/risk_model.json` (feature names, weights, safety multiplier).

The agent itself never reads dev.jsonl or this script's output other than the JSON model.
"""
import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from anticipatory.lexicon import Lexicon, load_rows  # noqa: E402
from anticipatory.risk import (DEFAULT_MODEL_PATH, FEATURE_NAMES, RiskInput,  # noqa: E402
                               risk_features, sigmoid)
from make_training_data import Generator, build_examples  # noqa: E402

Group = Tuple[Tuple[float, ...], int, int]        # (feature vector, rows, wrong rows)
INPUT_FIELDS = tuple(RiskInput.__dataclass_fields__)


def to_input(row: Dict) -> RiskInput:
    return RiskInput(**{name: row[name] for name in INPUT_FIELDS})


def vector(row: Dict) -> Tuple[float, ...]:
    x = risk_features(to_input(row))
    return tuple(x[name] for name in FEATURE_NAMES)


def group(rows: Sequence[Dict]) -> List[Group]:
    counts: Dict[Tuple[float, ...], List[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        entry = counts[vector(row)]
        entry[0] += 1
        entry[1] += row["label"]
    return [(vec, n, wrong) for vec, (n, wrong) in counts.items()]


def synthetic_requests(count: int, seed: int, lexicon: Lexicon, rows) -> List[List[Dict]]:
    """Per request, its commit-candidate prefixes (see `build_examples`)."""
    generator = Generator(rows, seed)
    out: List[List[Dict]] = []
    for _ in range(count):
        req = generator.request()
        out.append(build_examples(req["words"], req["target"], lexicon, rows, generator.catalog))
    return out


def dev_requests(path: Path, lexicon: Lexicon, rows) -> List[List[Dict]]:
    out: List[List[Dict]] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                req = json.loads(line)
                out.append(build_examples(req["words"], req["target"], lexicon, rows))
    return out


def flatten(requests: Sequence[Sequence[Dict]]) -> List[Dict]:
    return [row for request in requests for row in request]


def visited(requests: Sequence[Sequence[Dict]], w: Sequence[float], budget: float,
            multiplier: float = 1.0) -> List[List[Dict]]:
    """Per request, the prefixes up to and including the one the model commits at."""
    out = []
    for request in requests:
        kept = []
        for row in request:
            kept.append(row)
            if predict(w, vector(row)) * multiplier <= budget:
                break
        out.append(kept)
    return out


def simulate(requests: Sequence[Sequence[Dict]], risk, budget: float) -> Dict[str, float]:
    """The commit policy on labelled prefixes: commit at the first one with risk <= budget.

    Per request: 0.4 if it never commits (the final search still answers right), 0.4 plus
    0.6 x the share of words still to come for a right commit, and -0.6 for a wrong one
    (right final answer, minus the 1.0 penalty, no earliness).
    """
    total, wrong, early = 0.0, 0, 0.0
    for request in requests:
        score = 0.4
        for row in request:
            if risk(row) <= budget:
                if row["label"]:
                    wrong += 1
                    score = 0.4 - 1.0
                else:
                    share = (row["n_words"] - row["index"]) / row["n_words"]
                    early += share
                    score = 0.4 + 0.6 * share
                break
        total += score
    n = len(requests)
    return {"score": 100 * total / n, "wrong": wrong, "wrong_rate": wrong / n,
            "early_share": early / n}


# ----------------------------------------------------------------------------- fitting

def solve(matrix: List[List[float]], rhs: List[float]) -> List[float]:
    """Gaussian elimination with partial pivoting."""
    n = len(rhs)
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        for r in range(col + 1, n):
            factor = a[r][col] / a[col][col]
            for c in range(col, n + 1):
                a[r][c] -= factor * a[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (a[i][n] - sum(a[i][j] * x[j] for j in range(i + 1, n))) / a[i][i]
    return x


def fit(groups: Sequence[Group], ridge: float = 1.0, iterations: int = 25) -> List[float]:
    """Newton's method (IRLS) for ridge-regularised logistic regression."""
    d = len(FEATURE_NAMES)
    w = [0.0] * d
    total = sum(n for _, n, _ in groups)
    for _ in range(iterations):
        grad = [0.0] * d
        hess = [[0.0] * d for _ in range(d)]
        for vec, n, wrong in groups:
            p = sigmoid(sum(w[j] * vec[j] for j in range(d)))
            err = wrong - n * p
            weight = n * p * (1.0 - p)
            for j in range(d):
                if vec[j]:
                    grad[j] += err * vec[j]
                    for k in range(d):
                        if vec[k]:
                            hess[j][k] += weight * vec[j] * vec[k]
        for j in range(1, d):                       # do not penalise the bias
            grad[j] -= ridge * w[j]
            hess[j][j] += ridge
        hess[0][0] += 1e-9
        step = solve(hess, grad)
        w = [w[j] + step[j] for j in range(d)]
        if max(abs(s) for s in step) < 1e-6:
            break
    return w


# ----------------------------------------------------------------------------- reporting

def predict(w: Sequence[float], vec: Sequence[float]) -> float:
    return sigmoid(sum(w[j] * vec[j] for j in range(len(w))))


def report(name: str, groups: Sequence[Group], w: Sequence[float], budget: float) -> None:
    total = sum(n for _, n, _ in groups)
    wrong_total = sum(k for _, _, k in groups)
    scored = [(predict(w, vec), n, k) for vec, n, k in groups]
    eps = 1e-12
    logloss = -sum(k * math.log(p + eps) + (n - k) * math.log(1 - p + eps)
                   for p, n, k in scored) / total
    brier = sum(k * (1 - p) ** 2 + (n - k) * p ** 2 for p, n, k in scored) / total
    bins = [[0, 0, 0.0] for _ in range(10)]
    for p, n, k in scored:
        b = min(9, int(p * 10))
        bins[b][0] += n
        bins[b][1] += k
        bins[b][2] += p * n
    ece = sum(abs(k - ps) for n, k, ps in bins) / total
    order = sorted(scored, key=lambda t: t[0])           # AUC by pairwise counting on groups
    negatives = total - wrong_total
    auc_sum, seen_neg = 0.0, 0.0
    for p, n, k in order:
        auc_sum += k * (seen_neg + (n - k) / 2.0)
        seen_neg += n - k
    auc = auc_sum / (wrong_total * negatives) if wrong_total and negatives else float("nan")
    allowed = [(n, k) for p, n, k in scored if p <= budget]
    allowed_n = sum(n for n, _ in allowed)
    allowed_wrong = sum(k for _, k in allowed)
    print(f"\n{name}: {total} prefixes, {wrong_total} wrong ({wrong_total / total:.1%})")
    print(f"  log-loss {logloss:.4f}   Brier {brier:.4f}   ECE {ece:.4f}   AUC {auc:.3f}")
    print(f"  states the model allows to commit (risk <= {budget:.3f}): {allowed_n} "
          f"({allowed_n / total:.1%}), of which wrong: {allowed_wrong} "
          f"({allowed_wrong / max(1, allowed_n):.2%})")
    print("  reliability (predicted bin: rows, predicted mean, observed rate)")
    for i, (n, k, ps) in enumerate(bins):
        if n:
            print(f"    {i / 10:.1f}-{(i + 1) / 10:.1f}: {n:7d}   {ps / n:.3f}   {k / n:.3f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--train", type=int, default=30000, help="synthetic training requests")
    parser.add_argument("--val", type=int, default=5000, help="synthetic validation requests")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--ridge", type=float, default=1.0)
    parser.add_argument("--rounds", type=int, default=3, help="on-policy refits")
    parser.add_argument("--dev", default=str(BACKEND / "dev.jsonl"))
    parser.add_argument("--out", default=str(DEFAULT_MODEL_PATH))
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    rows = load_rows()
    lexicon = Lexicon(rows)
    from anticipatory.config import DEFAULT_CONFIG
    from anticipatory.policy import break_even_risk
    from anticipatory.risk import HeuristicRisk
    budget = break_even_risk(1)
    heuristic = HeuristicRisk(DEFAULT_CONFIG)

    print(f"generating {args.train} training and {args.val} validation requests ...")
    train_req = synthetic_requests(args.train, args.seed, lexicon, rows)
    val_req = synthetic_requests(args.val, args.seed + 1, lexicon, rows)
    dev_req = dev_requests(Path(args.dev), lexicon, rows)

    w = fit(group(flatten(train_req)), ridge=args.ridge)
    print(f"round 0 (all prefixes): val simulated score "
          f"{simulate(val_req, lambda r: predict(w, vector(r)), budget)['score']:.1f}")
    for round_no in range(1, args.rounds + 1):
        w = fit(group(flatten(visited(train_req, w, budget))), ridge=args.ridge)
        sim = simulate(val_req, lambda r: predict(w, vector(r)), budget)
        print(f"round {round_no} (on-policy): val simulated score {sim['score']:.1f}, "
              f"wrong commits {sim['wrong']}, earliness {sim['early_share']:.1%}")

    # choose the safety multiplier on validation, never on dev: the smallest one whose
    # wrong-commit rate is no higher than the heuristic's on the same requests
    hand_val = simulate(val_req, lambda r: heuristic.p_wrong(to_input(r)), budget)
    print(f"\nheuristic on validation: wrong rate {hand_val['wrong_rate']:.2%}, "
          f"score {hand_val['score']:.2f}, earliness {hand_val['early_share']:.1%}")
    print("safety multiplier (validation, simulated policy):")
    multiplier = None
    hold = DEFAULT_CONFIG.risk.hold_words

    def hybrid(m):
        def risk(r):
            learned = predict(w, vector(r)) * m
            if r["quiet_words"] < hold or r["at_clause_end"]:
                return max(heuristic.p_wrong(to_input(r)), learned)
            return learned
        return risk

    for m in (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0):
        sim = simulate(val_req, hybrid(m), budget)
        ok = sim["wrong_rate"] <= hand_val["wrong_rate"]
        print(f"  x{m:<5} score {sim['score']:.2f}  wrong {sim['wrong']:4d} "
              f"({sim['wrong_rate']:.2%})  earliness {sim['early_share']:.1%}"
              f"{'   <- chosen' if ok and multiplier is None else ''}")
        if ok and multiplier is None:
            multiplier = m
    multiplier = multiplier or 4.0
    print(f"chosen multiplier: x{multiplier}")

    print("\nsimulated policy: heuristic vs learned alone vs hybrid (the shipped design):")
    for label, reqs in (("validation", val_req), ("dev (held out)", dev_req)):
        for name, fn in (("heuristic", lambda r: heuristic.p_wrong(to_input(r))),
                         ("learned", lambda r: predict(w, vector(r)) * multiplier),
                         ("hybrid", hybrid(multiplier))):
            sim = simulate(reqs, fn, budget)
            print(f"  {label:<15}{name:<10} score {sim['score']:.2f}  wrong {sim['wrong']:3d}  "
                  f"earliness {sim['early_share']:.1%}")

    report("validation (fresh synthetic, all prefixes)", group(flatten(val_req)), w, budget)
    report("dev.jsonl (real, held out, all prefixes)", group(flatten(dev_req)), w, budget)

    print("\nweights:")
    for name, value in sorted(zip(FEATURE_NAMES, w), key=lambda t: -abs(t[1])):
        print(f"  {name:<22}{value:+.3f}")

    if not args.no_write:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        meta = {"training_requests": args.train, "seed": args.seed, "ridge": args.ridge,
                "on_policy_rounds": args.rounds, "break_even_budget": round(budget, 4),
                "safety_multiplier": multiplier}
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "features": list(FEATURE_NAMES),
                       "weights": [round(v, 6) for v in w], "meta": meta}, fh, indent=1)
            fh.write("\n")
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
