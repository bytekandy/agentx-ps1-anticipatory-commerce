"""The stream service: sessions, replay, examples and results. No HTTP in this file.

A client drives the agent in one of two ways:

  live    `create_session`, then `push_word` once per word, then `finish`. Every call returns
          the next event, so any client (a browser, a script, a speech recogniser) works.
  replay  `replay` yields the events of a whole request in order; the HTTP layer paces them as
          server-sent events, so a browser can simply watch the agent read a request.

Safety: a session is one agent with its own state and its own search counter, guarded by a lock
(the agent is not thread-safe). Sessions expire when idle, and the number of sessions, words per
session and the size of a word are limited, so a client cannot exhaust the process.
"""
import json
import platform
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from anticipatory.agent import AnticipatoryAgent
from anticipatory.catalog_port import ToolsCatalog
from anticipatory.config import DEFAULT_CONFIG, Config
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
    max_sessions: int = 200
    idle_seconds: float = 600.0      # an open session nobody touches is forgotten after this
    finished_seconds: float = 30.0   # a finished one is kept this long (for "already finished" replies)
    max_words: int = 500             # per session
    max_word_chars: int = 100
    max_text_chars: int = 4000       # a replayed free-text request
    max_examples: int = 500


class SessionTools:
    """What `tools` is for the agent: the kit's search, counted per session."""

    def __init__(self):
        self.searches = 0

    def search(self, query: str = "", filters: Optional[Dict[str, Any]] = None, k: int = 10):
        self.searches += 1
        return kit_search.search(query, filters, k)

    def record_search(self, n: int = 1) -> None:
        self.searches += n


@dataclass
class Session:
    id: str
    agent_name: str
    agent: AnticipatoryAgent
    tools: SessionTools
    request_id: Any
    created: float
    touched: float
    lock: threading.Lock = field(default_factory=threading.Lock)
    words: List[str] = field(default_factory=list)
    commit: Optional[Dict[str, Any]] = None      # {"seq", "product_id"}
    finished: bool = False
    last_filters: Optional[Dict[str, Any]] = None
    example: Optional[Dict[str, Any]] = None     # the dev request being replayed, if any


class StreamService:
    def __init__(self, config: Config = DEFAULT_CONFIG, limits: Limits = Limits(),
                 clock: Callable[[], float] = time.monotonic,
                 lexicon: Optional[Lexicon] = None, directory: Optional[ProductDirectory] = None):
        self.config = config
        self.limits = limits
        self.clock = clock
        self.lexicon = lexicon or Lexicon.from_catalogue(config=config.vocab,
                                                         spelling=config.spelling)
        self.directory = directory or ProductDirectory.from_catalogue()
        self._learned = LearnedRisk.from_file(config=config)
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()
        self._examples: Dict[str, Dict[str, Any]] = {}
        self._example_sets: Dict[str, List[str]] = {}
        self._baseline: Dict[str, Dict[str, Any]] = {}

    # -- information ------------------------------------------------------------------------

    def info(self) -> Dict[str, Any]:
        return {"version": VERSION, "agents": list(AGENT_NAMES), "default_agent": "hybrid",
                "products": len(self.directory), "datasets": {n: len(self._load_set(n))
                                                              for n in DATASETS},
                "break_even_risk": round(break_even_risk(self.config.policy.words_saved_assumed,
                                                         self.config), 4),
                "limits": {"max_sessions": self.limits.max_sessions,
                           "idle_seconds": self.limits.idle_seconds,
                           "finished_seconds": self.limits.finished_seconds,
                           "max_words": self.limits.max_words,
                           "max_word_chars": self.limits.max_word_chars,
                           "max_text_chars": self.limits.max_text_chars},
                "python": platform.python_version()}

    # -- sessions (live use) ----------------------------------------------------------------

    def _make_agent(self, name: str, tools: SessionTools) -> AnticipatoryAgent:
        if name not in AGENT_NAMES:
            raise ServiceError(400, "unknown_agent", f"agent must be one of {list(AGENT_NAMES)}")
        risk = {"hybrid": lambda: HybridRisk(self._learned, self.config),
                "heuristic": lambda: HeuristicRisk(self.config),
                "learned": lambda: self._learned}[name]()
        return AnticipatoryAgent(ToolsCatalog(tools), self.config, risk_model=risk,
                                 lexicon=self.lexicon)

    def _new_session(self, agent: str, request_id: Any) -> Session:
        tools = SessionTools()
        now = self.clock()
        session = Session(id=secrets.token_urlsafe(9), agent_name=agent,
                          agent=self._make_agent(agent, tools), tools=tools,
                          request_id=request_id, created=now, touched=now)
        session.agent.start(request_id)
        return session

    def _sweep(self) -> None:
        """Forget sessions that are idle (open ones) or long finished. Call with the lock held."""
        now = self.clock()
        for sid, sess in list(self._sessions.items()):
            limit = self.limits.finished_seconds if sess.finished else self.limits.idle_seconds
            if now - sess.touched > limit:
                del self._sessions[sid]

    def create_session(self, agent: str = "hybrid", request_id: Any = None) -> Dict[str, Any]:
        with self._lock:
            self._sweep()
            open_now = sum(1 for s in self._sessions.values() if not s.finished)
            if open_now >= self.limits.max_sessions:
                raise ServiceError(429, "too_many_sessions",
                                   "too many open sessions; finish or close one and retry")
            room = 4 * self.limits.max_sessions       # bound the memory finished sessions use
            for sid in [s for s, sess in sorted(self._sessions.items(), key=lambda kv: kv[1].touched)
                        if sess.finished][:max(0, len(self._sessions) - room + 1)]:
                del self._sessions[sid]
            session = self._new_session(agent, request_id)
            self._sessions[session.id] = session
        return start_event(session.id, agent, request_id)

    def _get(self, sid: str) -> Session:
        with self._lock:
            self._sweep()
            session = self._sessions.get(sid)
        if session is None:
            raise ServiceError(404, "unknown_session", "no such session (it may have expired)")
        return session

    def _check_word(self, word: Any) -> str:
        if not isinstance(word, str):
            raise ServiceError(400, "bad_word", "word must be a string")
        if not word.strip():
            raise ServiceError(400, "bad_word", "word must not be empty")
        if len(word.split()) != 1:
            raise ServiceError(400, "bad_word", "send one word at a time (no spaces)")
        if len(word) > self.limits.max_word_chars:
            raise ServiceError(400, "bad_word", f"word longer than {self.limits.max_word_chars} characters")
        return word

    def _observe(self, session: Session, word: str) -> Dict[str, Any]:
        """Feed one word to the agent. The session lock must be held."""
        if len(session.words) >= self.limits.max_words:
            raise ServiceError(413, "too_many_words",
                               f"a request is limited to {self.limits.max_words} words")
        session.words.append(word)
        out = session.agent.observe(word)
        record = session.agent.trace[-1]
        commit = None
        if out and out.get("commit"):
            session.commit = {"seq": record.index, "product_id": out["commit"]}
            commit = dict(session.commit, product=self.directory.get(out["commit"]))
        if out:
            session.last_filters = out.get("filters")
        session.touched = self.clock()
        return word_event(session.id, record, commit, session.tools.searches)

    def push_word(self, sid: str, word: Any) -> Dict[str, Any]:
        word = self._check_word(word)
        session = self._get(sid)
        with session.lock:
            if session.finished:
                raise ServiceError(409, "session_finished", "this request is finished; start a new session")
            return self._observe(session, word)

    def _finish(self, session: Session) -> Dict[str, Any]:
        """Finish the request. The session lock must be held."""
        final_id = session.agent.finish()
        session.finished = True
        session.touched = self.clock()
        snapshot = session.agent.state.snapshot
        commit = None
        if session.commit:
            commit = dict(session.commit, product=self.directory.get(session.commit["product_id"]))
        return final_event(session.id, len(session.words), final_id, self.directory.get(final_id),
                           snapshot.filters, [u.label() for u in snapshot.unresolved], commit,
                           session.tools.searches, self._evaluate(session, final_id))

    def finish(self, sid: str) -> Dict[str, Any]:
        session = self._get(sid)
        with session.lock:
            if session.finished:
                raise ServiceError(409, "session_finished", "this request is already finished")
            return self._finish(session)

    def close(self, sid: str) -> None:
        with self._lock:
            if self._sessions.pop(sid, None) is None:
                raise ServiceError(404, "unknown_session", "no such session (it may have expired)")

    def open_sessions(self) -> int:
        """Sessions that are not finished yet (the ones the limit counts)."""
        with self._lock:
            self._sweep()
            return sum(1 for s in self._sessions.values() if not s.finished)

    # -- evaluation of a replayed dev request -----------------------------------------------

    def _evaluate(self, session: Session, final_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Score a replayed dev request with the kit's own scorer; None for free text."""
        example = session.example
        if example is None:
            return None
        import evaluate
        commits = [(session.commit["seq"], session.commit["product_id"])] if session.commit else []
        scored = evaluate.score_one(example, commits, final_id, session.tools.searches,
                                    session.last_filters)
        return {"target": example["target"], "target_product": self.directory.get(example["target"]),
                "correct": scored["correct"], "wrong_commits": scored["wrong_commits"],
                "early_words": scored["early_words"], "early_share": scored["early_share"],
                "oracle_share": scored["oracle_share"], "searches": scored["searches"],
                "score": scored["score"], "gold_filters": example.get("filters")}

    # -- replay -----------------------------------------------------------------------------

    def replay(self, text: Optional[str] = None, example: Optional[str] = None,
               agent: str = "hybrid") -> Iterator[Dict[str, Any]]:
        """Yield the events of a whole request: start, one per word, final.

        Give either free `text` or the `example` id of a dev or dev_extra request (which is
        then also scored). The caller decides how fast to consume the events.
        """
        if (text is None) == (example is None):
            raise ServiceError(400, "bad_request", "give exactly one of text or example")
        request = None
        if example is not None:
            request = self.example(example)
            words, text = list(request["words"]), request["text"]
        else:
            if len(text) > self.limits.max_text_chars:
                raise ServiceError(400, "text_too_long", f"text longer than {self.limits.max_text_chars} characters")
            words = text.split()
            if not words:
                raise ServiceError(400, "bad_request", "text has no words")
            if len(words) > self.limits.max_words:
                raise ServiceError(413, "too_many_words", f"a request is limited to {self.limits.max_words} words")
        session = self._new_session(agent, request["id"] if request else None)
        session.example = request
        return self._replay_events(session, text, words)

    def _replay_events(self, session: Session, text: str, words: List[str]) -> Iterator[Dict[str, Any]]:
        yield start_event(session.id, session.agent_name, session.request_id, text, words)
        for word in words:
            with session.lock:
                yield self._observe(session, word)
        with session.lock:
            yield self._finish(session)

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
            raise ServiceError(404, "no_results", "run `python scripts/report.py` to create the results")
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
