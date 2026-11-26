"""Run the agent through the organisers' scorer and write the results and a report.

    cd backend
    python scripts/report.py                       # dev + dev_extra, writes outputs/
    python scripts/report.py --outdir /tmp/out     # somewhere else
    python scripts/report.py --no-variants         # skip the rules-only / model-only comparison

It writes into the output directory
    results.jsonl            one line per dev request, as `evaluate.py --log` writes it: the
                             "outputs on the public dev set" Round 1 asks for
    results_dev_extra.jsonl  the same for data/dev_extra.jsonl
    report.md                the numbers for the abstract and the architecture note

Scoring is done by the kit's own `evaluate.run`, `evaluate.score_one` and `evaluate.summarise`
(imported, never copied), so nothing here can drift from the official score. This script only runs
the agent, measures speed and memory, and lays the numbers out.

Everything is deterministic except the timing lines (latency, start-up, memory), which are
measured on the machine that runs this.
"""
import argparse
import json
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import evaluate  # noqa: E402  (the kit's scorer)

DEFAULT_DATASETS = (("dev", BACKEND / "dev.jsonl", "results.jsonl"),
                    ("dev_extra", BACKEND / "data" / "dev_extra.jsonl", "results_dev_extra.jsonl"))
VARIANTS = (("hybrid (default)", "agent.py"), ("rules only", "agent_heuristic.py"),
            ("learned model only", "agent_learned.py"))


# ----------------------------------------------------------------------------- measuring

def load_requests(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def percentile(values: Sequence[float], q: float) -> float:
    """The q-th percentile (0 to 100) by nearest rank; 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(q / 100 * (len(ordered) - 1))))]


def measure(agent_file: str, requests: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Score an agent on requests and time it. Returns results, summary and timings."""
    agent_class = evaluate.load_agent(str(BACKEND / agent_file))
    started = time.perf_counter()
    results, per_word = evaluate.run(agent_class, requests)
    total = time.perf_counter() - started
    return {"results": results, "summary": evaluate.summarise(results), "per_word": per_word,
            "startup": cold_start(agent_file), "total": total,
            "filters": evaluate.filter_accuracy(results)}


def cold_start(agent_file: str) -> float:
    """Seconds from a fresh interpreter to a ready agent: imports, vocabulary, word list, model.
    Measured in a subprocess, because inside this process the word list is already cached."""
    code = ("import sys, time; t = time.perf_counter(); sys.path.insert(0, %r); sys.path.insert(0, %r);"
            " import evaluate; import importlib.util as u;"
            " spec = u.spec_from_file_location('a', %r); m = u.module_from_spec(spec);"
            " spec.loader.exec_module(m); m.Agent(evaluate.Tools());"
            " print(time.perf_counter() - t)" % (str(BACKEND), str(BACKEND), str(BACKEND / agent_file)))
    runs = [float(subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                 check=True).stdout) for _ in range(3)]
    return statistics.median(runs)


def by_tag(results: Sequence[Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
    tags = sorted({t for r in results for t in r["tags"]}) + ["plain"]
    out = []
    for tag in tags:
        rows = [r for r in results if tag in r["tags"] or (tag == "plain" and not r["tags"])]
        if rows:
            out.append((tag, evaluate.summarise(rows)))
    return out


def oracle_score(results: Sequence[Dict[str, Any]]) -> Optional[float]:
    """The score of an agent that commits the moment the target is pinned, with no waste."""
    if any(r["oracle_share"] is None for r in results):
        return None
    return 100 * statistics.mean(evaluate.W_CORRECT + evaluate.W_EARLY * r["oracle_share"]
                                 for r in results)


def exceptions(results: Sequence[Dict[str, Any]], requests: Sequence[Dict[str, Any]]):
    """Requests with a wrong final answer or a wrong early commit."""
    text = {r["id"]: r["text"] for r in requests}
    return [(r["id"], r["tags"], text[r["id"]], r["final"], r["target"], r["wrong_commits"])
            for r in results if not r["correct"] or r["wrong_commits"]]


def disk_kb(path: Path) -> float:
    return path.stat().st_size / 1024 if path.exists() else 0.0


# ----------------------------------------------------------------------------- rendering

def table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def headline_rows(s: Dict[str, Any], base: Optional[Dict[str, Any]], oracle: Optional[float]):
    def pair(key, fmt):
        return (format(s[key], fmt), format(base[key], fmt) if base else "")

    rows = [("requests", s["requests"], ""),
            ("accuracy (right final answer)", *pair("accuracy", ".3f")),
            ("wrong early commits", f"{s['wrong_commits']} in {s['requests_with_wrong_commit']} requests",
             f"{base['wrong_commits']}" if base else ""),
            ("**score**", f"**{s['score']:.1f}**", f"{base['score']:.1f}" if base else ""),
            ("earliness (share of the request still to come at the first right commit)",
             f"{s['early_share']:.1%}", f"{base['early_share']:.1%}" if base else ""),
            ("searches per request (the first is free)", *pair("searches", ".2f"))]
    if oracle is not None:
        rows.insert(4, ("score of a perfect early committer (ceiling)", f"{oracle:.1f}", ""))
    return rows


def render_dataset(name: str, data: Dict[str, Any], base: Optional[Dict[str, Any]],
                   requests: Sequence[Dict[str, Any]]) -> str:
    s = data["summary"]
    oracle = oracle_score(data["results"])
    out = [f"## {name}", "", table(("", "our agent", "kit baseline"),
                                   headline_rows(s, base["summary"] if base else None, oracle)), "",
           f"Baseline = the organisers' agent that waits for the whole request. Our floor, a perfect "
           f"reader that never commits early, scores {100 * evaluate.W_CORRECT:.1f}.", "",
           "### By tag", "",
           table(("tag", "requests", "accuracy", "wrong commits", "earliness", "score"),
                 [(tag, t["requests"], f"{t['accuracy']:.3f}", t["wrong_commits"],
                   f"{t['early_share']:.1%}", f"{t['score']:.1f}") for tag, t in by_tag(data["results"])])]
    if data["filters"]:
        n, acc = data["filters"]
        out += ["", f"Filters reported at the last word ({n} requests): "
                    + ", ".join(f"{k} {v:.2f}" for k, v in acc.items())
                    + ". (A price that ends the request is still growing at that word; "
                      "`finish()` settles it, so these understate the final reading.)"]
    bad = exceptions(data["results"], requests)
    out += ["", "### Requests with a wrong final answer or a wrong early commit", ""]
    if bad:
        out.append(table(("id", "tags", "request", "final", "target", "wrong commits"),
                         [(i, ", ".join(t) or "plain", f"`{x}`", f, tg, w) for i, t, x, f, tg, w in bad]))
    else:
        out.append("None.")
    return "\n".join(out)


def render_cost(data: Dict[str, Any], dev_requests: int) -> str:
    ms = [1000 * x for x in data["per_word"]]
    per_request_ms = 1000 * data["total"] / dev_requests
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    package = BACKEND / "anticipatory"
    code_kb = sum(p.stat().st_size for p in package.glob("*.py")) / 1024
    rows = [
        ("language model calls per request", "0 (rules, a 22-weight logistic regression, a word list)"),
        ("per-word latency, mean / median / p95 / p99 / max",
         f"{statistics.mean(ms):.3f} / {percentile(ms, 50):.3f} / {percentile(ms, 95):.3f} / "
         f"{percentile(ms, 99):.3f} / {max(ms):.3f} ms"),
        ("CPU per request (the whole request, including searches)", f"{per_request_ms:.2f} ms"),
        ("cold start (fresh interpreter to a ready agent: imports, vocabulary, word list, model; median of 3)", f"{1000 * data['startup']:.0f} ms"),
        ("memory (process peak, with all agents and data loaded)", f"{peak_mb:.0f} MB"),
        ("searches per request", f"{data['summary']['searches']:.2f}"),
        ("extrapolated: one million requests on one core",
         f"{per_request_ms * 1e6 / 3.6e6:.1f} CPU-hours, no per-request API cost"),
        ("size on disk: code / word list / risk model",
         f"{code_kb:.0f} KB / {disk_kb(package / 'data' / 'english_words.tsv'):.0f} KB / "
         f"{disk_kb(package / 'data' / 'risk_model.json'):.1f} KB"),
        ("dependencies", "Python 3.9+ standard library only"),
    ]
    return "\n".join(["## Cost, speed and size", "", "Measured on the dev set, on the machine that generated "
                      "this file (timings vary a little from run to run).", "",
                      table(("", ""), rows)])


def render_variants(rows: Sequence[Tuple[str, Dict[str, Any], Dict[str, Any]]]) -> str:
    header = ("agent", "dev score", "dev wrong commits", "dev earliness", "dev_extra score",
              "dev_extra wrong commits", "dev_extra accuracy")
    body = [(name, f"{d['summary']['score']:.1f}", d["summary"]["wrong_commits"],
             f"{d['summary']['early_share']:.1%}", f"{e['summary']['score']:.1f}",
             e["summary"]["wrong_commits"], f"{e['summary']['accuracy']:.3f}")
            for name, d, e in rows]
    return "\n".join(["## Agent variants", "", "The default asks the hand-coded rules while a value is fresh "
                      "or just followed by a pause, and the learned risk model once the state is calm. "
                      "The other two are kept for comparison.", "", table(header, body)])


def render_report(sections: Sequence[str]) -> str:
    head = ["# Results", "", "Generated by `backend/scripts/report.py`. Scoring is the organisers' own "
            "`evaluate.py`, imported unchanged. Re-create with `cd backend && python scripts/report.py`.", ""]
    return "\n\n".join(["\n".join(head)] + list(sections)) + "\n"


# ----------------------------------------------------------------------------- main

def write_results(results: Sequence[Dict[str, Any]], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent", default="agent.py", help="agent file inside backend/")
    parser.add_argument("--outdir", default=str(BACKEND / "outputs"))
    parser.add_argument("--no-variants", action="store_true", help="skip the variant comparison")
    args = parser.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    sections: List[str] = []
    measured: Dict[str, Dict[str, Any]] = {}
    for name, path, filename in DEFAULT_DATASETS:
        requests = load_requests(path)
        data = measure(args.agent, requests)
        base = {"summary": evaluate.summarise(evaluate.run(evaluate.BaselineAgent, requests)[0])}
        measured[name] = data
        write_results(data["results"], outdir / filename)
        sections.append(render_dataset(name, data, base, requests))
        print(f"{name}: {len(requests)} requests, score {data['summary']['score']:.1f}, "
              f"wrong commits {data['summary']['wrong_commits']} -> {outdir / filename}")
    sections.insert(1, render_cost(measured["dev"], len(measured["dev"]["results"])))
    if not args.no_variants:
        rows = []
        for label, file in VARIANTS:
            pair = [measure(file, load_requests(p)) for _, p, _ in DEFAULT_DATASETS]
            rows.append((label, pair[0], pair[1]))
        sections.append(render_variants(rows))
    (outdir / "report.md").write_text(render_report(sections), encoding="utf-8")
    print(f"report: {outdir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
