"""The stream service: runs of the agent, replay, examples and results. No web framework here.

A *run* is one request being read by one agent. It is owned by exactly one caller (one REST call,
or one WebSocket connection), so there are no sessions to store, expire or share: the agent is
deterministic and causal (the answer at word t depends only on words 1 to t, which is tested), so
a stateless call can simply replay the words it is given and return the event for the last one.

    step(words)      the event for the last word of the words so far (stateless REST)
    answer(words)    the final answer for a finished request (stateless REST)
    run(words)       every event of a whole request
    replay(...)      the same, from free text or a dev example id, for paced streaming
    new_run(...)     a Run to feed word by word (one WebSocket connection)

The agent is not thread-safe but a Run is never shared, and everything runs share (the lexicon,
the risk model, the product directory) is read-only apart from a spelling cache that is safe
under concurrent use.
"""
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

from anticipatory.agent import AnticipatoryAgent
from anticipatory.catalog_port import ToolsCatalog
from anticipatory.config import DEFAULT_CONFIG, Config
from anticipatory.learned import LearnedStore, learn_from_request
from anticipatory.lexicon import Lexicon
from anticipatory.policy import break_even_risk
from anticipatory.risk import HeuristicRisk, HybridRisk, LearnedRisk

import search as kit_search  # the kit's search, behind the counted tool below

from .events import (BACKEND, ProductDirectory, ServiceError, VERSION, final_event, start_event,
                     word_event)

AGENT_NAMES = ("hybrid", "heuristic", "learned")
DATASETS = {"dev": (BACKEND / "dev.jsonl", BACKEND / "outputs" / "results.jsonl"),
            "dev_extra": (BACKEND / "data" / "dev_extra.jsonl",
                          BACKEND / "outputs" / "results_dev_extra.jsonl")}


@dataclass(frozen=True)
class Limits:
    max_words: int = 500             # per request
    max_word_chars: int = 100
    max_text_chars: int = 4000       # a replayed free-text request
    max_examples: int = 500          # per page
    max_body_bytes: int = 16 * 1024  # enforced by the web layer


class RunTools:
    """What `tools` is for the agent: the kit's search, counted per run."""

    def __init__(self):
        self.searches = 0

    def search(self, query: str = "", filters: Optional[Dict[str, Any]] = None, k: int = 10):
        self.searches += 1
        return kit_search.search(query, filters, k)

    def record_search(self, n: int = 1) -> None:
        self.searches += n


class Run:
    """One request being read by one agent. Not shared between threads or callers."""

    def __init__(self, service: "StreamService", agent_name: str, request_id: Any = None,
                 example: Optional[Dict[str, Any]] = None):
        self.service = service
        self.agent_name = agent_name
        self.request_id = request_id
        self.example = example
        self.tools = RunTools()
        self.agent = service._make_agent(agent_name, self.tools)
        self.agent.start(request_id)
        self.words: List[str] = []
        self.commit: Optional[Dict[str, Any]] = None       # {"seq", "product_id"}
        self.last_filters: Optional[Dict[str, Any]] = None
        self.finished = False

    def start_event(self, text: Optional[str] = None, words: Optional[List[str]] = None):
        return start_event(self.agent_name, self.request_id, text, words)

    def _commit_view(self) -> Optional[Dict[str, Any]]:
        if not self.commit:
            return None
        return dict(self.commit, product=self.service.directory.get(self.commit["product_id"]))

    def push(self, word: str) -> Dict[str, Any]:
        word = self.service._check_word(word)
        if self.finished:
            raise ServiceError(409, "run_finished", "this request is finished")
        if len(self.words) >= self.service.limits.max_words:
            raise ServiceError(413, "too_many_words",
                               f"a request is limited to {self.service.limits.max_words} words")
        self.words.append(word)
        out = self.agent.observe(word)
        record = self.agent.trace[-1]
        commit = None
        if out and out.get("commit"):
            self.commit = {"seq": record.index, "product_id": out["commit"]}
            commit = self._commit_view()
        if out:
            self.last_filters = out.get("filters")
        return word_event(record, commit, self._commit_view(), self.tools.searches)

    def finish(self) -> Dict[str, Any]:
        if self.finished:
            raise ServiceError(409, "run_finished", "this request is already finished")
        final_id = self.agent.finish()
        self.finished = True
        snapshot = self.agent.state.snapshot
        return final_event(len(self.words), final_id, self.service.directory.get(final_id),
                           snapshot.filters, [u.label() for u in snapshot.unresolved],
                           self._commit_view(), self.tools.searches, self._evaluation(final_id))

    def _evaluation(self, final_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Score a replayed dev request with the kit's own scorer; None for free text."""
        if self.example is None:
            return None
        import evaluate
        commits = [(self.commit["seq"], self.commit["product_id"])] if self.commit else []
        scored = evaluate.score_one(self.example, commits, final_id, self.tools.searches,
                                    self.last_filters)
        directory = self.service.directory
        return {"target": self.example["target"],
                "target_product": directory.get(self.example["target"]),
                "correct": scored["correct"], "wrong_commits": scored["wrong_commits"],
                "early_words": scored["early_words"], "early_share": scored["early_share"],
                "oracle_share": scored["oracle_share"], "searches": scored["searches"],
                "score": scored["score"], "gold_filters": self.example.get("filters")}


class StreamService:
    def __init__(self, config: Config = DEFAULT_CONFIG, limits: Limits = Limits(),
                 lexicon: Optional[Lexicon] = None, directory: Optional[ProductDirectory] = None,
                 learned_path: Optional[Path] = None):
        self.learned_path = learned_path       # None: the default learned_lexicon.json
        self.config = config
        self.limits = limits
        self.lexicon = lexicon or Lexicon.from_catalogue(config=config.vocab,
                                                         spelling=config.spelling)
        self.directory = directory or ProductDirectory.from_catalogue()
        self._learned = LearnedRisk.from_file(config=config)
        self._examples: Dict[str, Dict[str, Any]] = {}
        self._example_sets: Dict[str, List[str]] = {}
        self._baseline: Dict[str, Dict[str, Any]] = {}

    # -- teaching ---------------------------------------------------------------------------

    def feedback(self, words: Sequence[str], product_id: str) -> Dict[str, Any]:
        """The shopper accepted `product_id` for this request: remember what the words we could
        not place probably meant. The agent reads the result the next time it starts."""
        words = self._check_words(words)
        product = self.directory.get(product_id)
        if not product:
            raise ServiceError(404, "not_found", "no such product")
        store = LearnedStore(self.learned_path)
        seen = learn_from_request(words, self.lexicon, store, product)
        if seen:
            store.save()
        return {"learned": [{"word": w, "slot": s, "value": v} for w, s, v in seen]}

    # -- information ------------------------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        return {"version": VERSION, "agents": list(AGENT_NAMES), "default_agent": "hybrid",
                "products": len(self.directory),
                "datasets": {name: len(self._load_set(name)) for name in DATASETS},
                "break_even_risk": round(break_even_risk(self.config.policy.words_saved_assumed,
                                                         self.config), 4),
                "limits": {"max_words": self.limits.max_words,
                           "max_word_chars": self.limits.max_word_chars,
                           "max_text_chars": self.limits.max_text_chars,
                           "max_body_bytes": self.limits.max_body_bytes},
                "python": platform.python_version()}

    # -- runs -------------------------------------------------------------------------------

    def _make_agent(self, name: str, tools: RunTools) -> AnticipatoryAgent:
        if name not in AGENT_NAMES:
            raise ServiceError(400, "unknown_agent", f"agent must be one of {list(AGENT_NAMES)}")
        risk = {"hybrid": lambda: HybridRisk(self._learned, self.config),
                "heuristic": lambda: HeuristicRisk(self.config),
                "learned": lambda: self._learned}[name]()
        return AnticipatoryAgent(ToolsCatalog(tools), self.config, risk_model=risk,
                                 lexicon=self.lexicon)

    def new_run(self, agent: str = "hybrid", request_id: Any = None,
                example: Optional[Dict[str, Any]] = None) -> Run:
        return Run(self, agent, request_id, example)

    def _check_word(self, word: Any) -> str:
        if not isinstance(word, str):
            raise ServiceError(400, "bad_word", "word must be a string")
        if not word.strip():
            raise ServiceError(400, "bad_word", "word must not be empty")
        if len(word.split()) != 1:
            raise ServiceError(400, "bad_word", "send one word at a time (no spaces)")
        if len(word) > self.limits.max_word_chars:
            raise ServiceError(400, "bad_word",
                               f"word longer than {self.limits.max_word_chars} characters")
        return word

    def _check_words(self, words: Any) -> List[str]:
        if not isinstance(words, (list, tuple)) or not words:
            raise ServiceError(400, "bad_request", "words must be a non-empty list")
        if len(words) > self.limits.max_words:
            raise ServiceError(413, "too_many_words",
                               f"a request is limited to {self.limits.max_words} words")
        return [self._check_word(w) for w in words]

    def step(self, words: Sequence[str], agent: str = "hybrid",
             request_id: Any = None) -> Dict[str, Any]:
        """The event for the last of `words`, as if they had been sent one at a time."""
        words = self._check_words(words)
        run = self.new_run(agent, request_id)
        event = None
        for word in words:
            event = run.push(word)
        return event

    def answer(self, words: Sequence[str], agent: str = "hybrid",
               request_id: Any = None) -> Dict[str, Any]:
        """The final event for a finished request made of `words`."""
        run = self.new_run(agent, request_id)
        for word in self._check_words(words):
            run.push(word)
        return run.finish()

    def run(self, words: Sequence[str], agent: str = "hybrid",
            request_id: Any = None) -> List[Dict[str, Any]]:
        """Every event of a whole request: start, one per word, final."""
        words = self._check_words(words)
        run = self.new_run(agent, request_id)
        return [run.start_event(" ".join(words), list(words))] + [run.push(w) for w in words] \
            + [run.finish()]

    # -- replay -----------------------------------------------------------------------------

    def replay(self, text: Optional[str] = None, example: Optional[str] = None,
               agent: str = "hybrid") -> Iterator[Dict[str, Any]]:
        """Yield the events of a whole request: start, one per word, final.

        Give either free `text` or the `example` id of a dev or dev_extra request (which is
        then also scored). Everything is validated before the first event, so a caller can
        reject a bad request before it starts streaming.
        """
        if (text is None) == (example is None):
            raise ServiceError(400, "bad_request", "give exactly one of text or example")
        request = None
        if example is not None:
            request = self.example(example)
            words, text = list(request["words"]), request["text"]
        else:
            if len(text) > self.limits.max_text_chars:
                raise ServiceError(400, "text_too_long",
                                   f"text longer than {self.limits.max_text_chars} characters")
            words = text.split()
            if not words:
                raise ServiceError(400, "bad_request", "text has no words")
            if len(words) > self.limits.max_words:
                raise ServiceError(413, "too_many_words",
                                   f"a request is limited to {self.limits.max_words} words")
        run = self.new_run(agent, request["id"] if request else None, request)
        return self._replay_events(run, text, words)

    @staticmethod
    def _replay_events(run: Run, text: str, words: List[str]) -> Iterator[Dict[str, Any]]:
        yield run.start_event(text, words)
        for word in words:
            yield run.push(word)
        yield run.finish()

    # -- examples and results ---------------------------------------------------------------

    def _load_set(self, name: str) -> List[str]:
        if name not in DATASETS:
            raise ServiceError(404, "unknown_set", f"set must be one of {list(DATASETS)}")
        if name not in self._example_sets:
            ids = []
            with open(DATASETS[name][0], encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        row = json.loads(line)
                        self._examples[row["id"]] = dict(row, set=name)
                        ids.append(row["id"])
            self._example_sets[name] = ids
        return self._example_sets[name]

    def examples(self, set_name: str = "dev", tag: Optional[str] = None,
                 limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        ids = self._load_set(set_name)
        rows = [self._examples[i] for i in ids]
        if tag:
            rows = [r for r in rows if tag in r["tags"] or (tag == "plain" and not r["tags"])]
        limit = max(1, min(limit, self.limits.max_examples))
        offset = max(0, offset)
        page = rows[offset:offset + limit]
        return {"set": set_name, "total": len(rows), "offset": offset,
                "items": [{"id": r["id"], "text": r["text"], "tags": r["tags"],
                           "words": len(r["words"])} for r in page]}

    def example(self, example_id: str) -> Dict[str, Any]:
        for name in DATASETS:
            self._load_set(name)
        row = self._examples.get(example_id)
        if row is None:
            raise ServiceError(404, "unknown_example", "no such example id")
        return row

    def example_detail(self, example_id: str) -> Dict[str, Any]:
        row = self.example(example_id)
        return {"id": row["id"], "set": row["set"], "text": row["text"], "words": row["words"],
                "tags": row["tags"], "gold_filters": row.get("filters"), "target": row["target"],
                "target_product": self.directory.get(row["target"]),
                "earliest": row.get("earliest")}

    def results(self, set_name: str) -> Dict[str, Any]:
        """The committed results of the final agent on a dataset, summarised with the kit's scorer."""
        import evaluate
        self._load_set(set_name)
        path = DATASETS[set_name][1]
        if not Path(path).exists():
            raise ServiceError(404, "no_results",
                               "run `python scripts/report.py` to create the results")
        with open(path, encoding="utf-8") as fh:
            results = [json.loads(line) for line in fh if line.strip()]
        tags = sorted({t for r in results for t in r["tags"]}) + ["plain"]
        by_tag = {}
        for tag in tags:
            rows = [r for r in results if tag in r["tags"] or (tag == "plain" and not r["tags"])]
            if rows:
                by_tag[tag] = evaluate.summarise(rows)
        if set_name not in self._baseline:
            requests = [self._examples[i] for i in self._example_sets[set_name]]
            self._baseline[set_name] = evaluate.summarise(
                evaluate.run(evaluate.BaselineAgent, requests)[0])
        return {"set": set_name, "summary": evaluate.summarise(results), "by_tag": by_tag,
                "baseline": self._baseline[set_name],
                "requests": [{"id": r["id"], "tags": r["tags"], "words": r["words"],
                              "correct": r["correct"], "final": r["final"], "target": r["target"],
                              "commits": r["commits"], "wrong_commits": r["wrong_commits"],
                              "early_words": r["early_words"], "score": r["score"]}
                             for r in results]}
