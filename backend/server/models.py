"""Typed shapes of everything the interface sends and receives (Pydantic).

FastAPI turns these into the OpenAPI document (`/openapi.json`) and the interactive docs (`/docs`),
and checks every response against them, so the documented contract and the real payloads are one
thing. `tests/test_server_models.py` checks that no model lags behind the service's events.
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class Product(BaseModel):
    product_id: str
    title: str
    brand: str
    category: str
    colour: str
    size: Optional[str] = None
    price: int
    description: str = ""


class Trace(BaseModel):
    """The agent's own record for one word."""
    index: int = Field(description="1-based position of the word")
    word: str
    filters: Dict[str, Any] = Field(description="The reading so far; null = not mentioned")
    confidence: float
    settled: bool = Field(description="False while the reading may still change")
    correction_pending: bool
    pending_slots: List[str]
    searched: bool = Field(description="A counted search was made after this word")
    n_candidates: Optional[int] = None
    action: Literal["wait", "commit"]
    product_id: Optional[str] = None
    risk: Optional[float] = Field(None, description="Estimated chance a commit is wrong")
    reason: str
    unresolved: List[str] = Field(description='Constraints nothing in the shop answers, e.g. ["brand: nike"]')


class Commit(BaseModel):
    seq: int
    product_id: str
    product: Optional[Product] = None


class StartEvent(BaseModel):
    type: Literal["start"]
    version: int
    agent: str
    request_id: Any = None
    text: Optional[str] = None
    words: Optional[List[str]] = None


class WordEvent(BaseModel):
    type: Literal["word"]
    version: int
    seq: int
    word: str
    trace: Trace
    commit: Optional[Commit] = Field(None, description="Set only on the word where the agent commits")
    committed: Optional[Commit] = Field(None, description="Set on the commit word and every later word")
    searches: int


class Evaluation(BaseModel):
    """The kit's own scoring of a replayed dev request."""
    target: str
    target_product: Optional[Product] = None
    correct: bool
    wrong_commits: int
    early_words: int
    early_share: float
    oracle_share: Optional[float] = None
    searches: int
    score: float
    gold_filters: Optional[Dict[str, Any]] = None


class FinalEvent(BaseModel):
    type: Literal["final"]
    version: int
    words: int
    final_product_id: Optional[str] = None
    product: Optional[Product] = None
    filters: Dict[str, Any]
    unresolved: List[str]
    commit: Optional[Commit] = None
    searches: int
    evaluation: Optional[Evaluation] = None


class DoneEvent(BaseModel):
    type: Literal["done"]
    version: int


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorBody(BaseModel):
    error: ErrorDetail


class RunRequest(BaseModel):
    """The words so far (stateless): the whole request goes in every call."""
    words: List[str] = Field(description="The request so far, one entry per word, exactly as typed")
    agent: Literal["hybrid", "heuristic", "learned"] = "hybrid"
    request_id: Any = None


class FeedbackRequest(BaseModel):
    """The shopper accepted this product for this request."""
    words: List[str]
    product_id: str


class FeedbackResult(BaseModel):
    learned: List[Any] = Field(description="What was remembered: {word, slot, value}; empty if nothing")


class RunResult(BaseModel):
    events: List[Any] = Field(description="start, one word event per word, then final")


class Health(BaseModel):
    status: Literal["ok"]


class Limits(BaseModel):
    max_words: int
    max_word_chars: int
    max_text_chars: int
    max_body_bytes: int


class Info(BaseModel):
    version: int
    agents: List[str]
    default_agent: str
    products: int
    datasets: Dict[str, int]
    break_even_risk: float
    limits: Limits
    python: str
    auth_required: bool = False


class ExampleItem(BaseModel):
    id: str
    text: str
    tags: List[str]
    words: int


class ExamplesPage(BaseModel):
    set: str
    total: int
    offset: int
    items: List[ExampleItem]


class ExampleDetail(BaseModel):
    id: str
    set: str
    text: str
    words: List[str]
    tags: List[str]
    gold_filters: Optional[Dict[str, Any]] = None
    target: str
    target_product: Optional[Product] = None
    earliest: Optional[int] = None


class Summary(BaseModel):
    requests: int
    accuracy: float
    wrong_commits: int
    requests_with_wrong_commit: int
    early_words: float
    early_share: float
    oracle_share: Optional[float] = None
    searches: float
    wasted: float
    score: float


class ResultRow(BaseModel):
    id: str
    tags: List[str]
    words: int
    correct: bool
    final: Optional[str] = None
    target: str
    commits: List[List[Any]]
    wrong_commits: int
    early_words: int
    score: float


class Results(BaseModel):
    set: str
    summary: Summary
    by_tag: Dict[str, Summary]
    baseline: Summary
    requests: List[ResultRow]
