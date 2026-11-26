"""The web application: FastAPI routes over `StreamService`.

What the libraries do, so this file does not have to:
    FastAPI      routing, validation, the OpenAPI document and `/docs`, WebSocket, server-sent
                 events (`EventSourceResponse`), the request body limit (`max_body_size`)
    Starlette    CORS (`CORSMiddleware`), static files without path traversal (`StaticFiles`)
    Pydantic     the typed models in `models.py`
    uvicorn      the server (`__main__.py`)

What is here is the project's own: the endpoints, the API key check, the error shape, and the
WebSocket protocol. See `docs/stream-contract.md`.
"""
import asyncio
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterable, Optional, Tuple

from fastapi import APIRouter, Depends, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import models
from .events import ServiceError, VERSION, error_body
from .service import StreamService

LOCAL_ORIGINS = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
MAX_REPLAY_DELAY_MS = 2000
WS_IDLE_SECONDS = 300.0
ERRORS = {code: {"model": models.ErrorBody} for code in (400, 401, 404, 409, 413)}


@dataclass(frozen=True)
class Settings:
    api_key: Optional[str] = None
    cors_origins: Tuple[str, ...] = ()                 # exact origins, or ("*",) for any
    cors_origin_regex: Optional[str] = LOCAL_ORIGINS   # default: a page served from this machine
    static_dir: Optional[Path] = None
    ws_idle_seconds: float = WS_IDLE_SECONDS


def _key_matches(supplied: Optional[str], expected: str) -> bool:
    return supplied is not None and secrets.compare_digest(supplied.encode(), expected.encode())


def _supplied_key(headers, query) -> Optional[str]:
    """`X-API-Key`, `Authorization: Bearer ...`, or `?api_key=` (browsers cannot set headers on
    EventSource or WebSocket, so the query form exists for them)."""
    bearer = headers.get("authorization", "")
    return (headers.get("x-api-key") or (bearer[7:] if bearer.lower().startswith("bearer ") else None)
            or query.get("api_key"))


def create_app(service: Optional[StreamService] = None, settings: Settings = Settings()) -> FastAPI:
    service = service or StreamService()
    app = FastAPI(title="Anticipatory commerce stream interface", version=str(VERSION),
                  max_body_size=service.limits.max_body_bytes,
                  description="Feed a shopping request to the agent one word at a time and watch "
                              "its trace. Contract: docs/stream-contract.md.")

    # -- errors in the project's one shape: {"error": {"code", "message"}} ---------------------

    def fail(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(error_body(code, message), status_code=status)

    @app.exception_handler(ServiceError)
    async def on_service_error(_: Request, err: ServiceError):
        return fail(err.status, err.code, err.message)

    @app.exception_handler(RequestValidationError)
    async def on_invalid(_: Request, err: RequestValidationError):
        first = err.errors()[0] if err.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        return fail(400, "bad_request", f"{where}: {first.get('msg', 'invalid request')}".strip(": "))

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(_: Request, err: StarletteHTTPException):
        codes = {404: "not_found", 405: "method_not_allowed", 413: "body_too_large"}
        return fail(err.status_code, codes.get(err.status_code, "http_error"), str(err.detail))

    @app.exception_handler(Exception)
    async def on_crash(_: Request, __: Exception):
        return fail(500, "internal", "internal error")              # never leak internals

    # -- middleware: CORS and headers ---------------------------------------------------------

    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_origin_regex=None if "*" in settings.cors_origins else settings.cors_origin_regex,
                       allow_methods=["GET", "POST", "OPTIONS"],
                       allow_headers=["Content-Type", "X-API-Key", "Authorization"], max_age=600)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # -- the API key --------------------------------------------------------------------------

    async def require_key(request: Request) -> None:
        if settings.api_key and not _key_matches(_supplied_key(request.headers, request.query_params),
                                                 settings.api_key):
            raise ServiceError(401, "unauthorized", "missing or wrong API key")

    public = APIRouter(prefix="/api")
    api = APIRouter(prefix="/api", dependencies=[Depends(require_key)], responses=ERRORS)

    @public.get("/health", response_model=models.Health, tags=["meta"])
    def health():
        return {"status": "ok"}

    @api.get("/info", response_model=models.Info, tags=["meta"])
    def info():
        return dict(service.info(), auth_required=bool(settings.api_key))

    # -- live, stateless: the words so far in, the event for the last word out -----------------

    @api.post("/step", response_model=models.WordEvent, tags=["live"],
              summary="The event for the last of the words so far")
    def step(body: models.RunRequest):
        return service.step(body.words, body.agent, body.request_id)

    @api.post("/answer", response_model=models.FinalEvent, tags=["live"],
              summary="The final answer for a finished request")
    def answer(body: models.RunRequest):
        return service.answer(body.words, body.agent, body.request_id)

    @api.post("/run", response_model=models.RunResult, tags=["live"],
              summary="Every event of a whole request at once")
    def run(body: models.RunRequest):
        return {"events": service.run(body.words, body.agent, body.request_id)}

    # -- replay as server-sent events ---------------------------------------------------------

    def replay_events(text: Optional[str] = Query(None), example: Optional[str] = Query(None),
                      agent: str = Query("hybrid")):
        """Validate and compute before streaming starts, so a bad request is a plain JSON error."""
        return list(service.replay(text=text, example=example, agent=agent))

    @api.get("/replay", response_class=EventSourceResponse, tags=["replay"],
             summary="Stream a whole request, paced, as server-sent events")
    async def replay(events=Depends(replay_events),
                     delay_ms: int = Query(400, description="pause after the start and each word; capped at 2000")
                     ) -> AsyncIterable[ServerSentEvent]:
        delay = max(0, min(delay_ms, MAX_REPLAY_DELAY_MS)) / 1000.0
        for event in events:
            yield ServerSentEvent(data=event, event=event["type"],
                                  id=str(event["seq"]) if "seq" in event else None)
            if delay and event["type"] in ("start", "word"):
                await asyncio.sleep(delay)
        yield ServerSentEvent(data={"type": "done", "version": VERSION}, event="done")

    # -- examples and results -----------------------------------------------------------------

    @api.get("/examples", response_model=models.ExamplesPage, tags=["examples"])
    def examples(set: str = "dev", tag: Optional[str] = None, limit: int = 50, offset: int = 0):
        return service.examples(set, tag, limit, offset)

    @api.get("/examples/{example_id}", response_model=models.ExampleDetail, tags=["examples"])
    def example(example_id: str):
        return service.example_detail(example_id)

    @api.get("/results/{set_name}", response_model=models.Results, tags=["examples"])
    def results(set_name: str):
        return service.results(set_name)

    app.include_router(public)
    app.include_router(api)

    # -- live, pushed: one WebSocket per request ----------------------------------------------

    async def send_error(ws: WebSocket, err: ServiceError) -> None:
        await ws.send_json(err.body() | {"type": "error", "version": VERSION})

    @app.websocket("/api/ws")
    async def live(ws: WebSocket):
        """Send `{"word": "beige"}` per word and `{"finish": true}` at the end; the server pushes a
        `start` event on connect, a `word` event per word and a `final` event, then closes."""
        if settings.api_key and not _key_matches(_supplied_key(ws.headers, ws.query_params),
                                                 settings.api_key):
            await ws.close(code=1008)        # closed before accept: the handshake gets HTTP 403
            return
        await ws.accept()
        try:
            run = service.new_run(ws.query_params.get("agent", "hybrid"), ws.query_params.get("request_id"))
        except ServiceError as err:
            await send_error(ws, err)
            await ws.close(code=1008)
            return
        try:
            await ws.send_json(run.start_event())
            while True:
                try:
                    message = await asyncio.wait_for(ws.receive_json(), settings.ws_idle_seconds)
                except asyncio.TimeoutError:
                    await ws.close(code=1001)                       # going away: idle too long
                    return
                except ValueError:
                    await send_error(ws, ServiceError(400, "bad_json", "send JSON text messages"))
                    continue
                try:
                    if not isinstance(message, dict):
                        raise ServiceError(400, "bad_request", "each message must be a JSON object")
                    if message.get("finish"):
                        await ws.send_json(await run_in_threadpool(run.finish))
                        await ws.close(code=1000)
                        return
                    await ws.send_json(await run_in_threadpool(run.push, message.get("word")))
                except ServiceError as err:
                    await send_error(ws, err)
                    if err.status in (409, 413):                    # the run cannot continue
                        await ws.close(code=1008)
                        return
        except WebSocketDisconnect:
            return

    # -- the UI, if a folder is given: after the API so it cannot shadow it -------------------

    if settings.static_dir is not None:
        app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="ui")
    return app
