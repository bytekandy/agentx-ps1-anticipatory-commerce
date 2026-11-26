"""The HTTP shell around `StreamService`: routing, JSON, server-sent events, CORS, static files.

Standard library only (`http.server`). All behaviour lives in the service; this file only maps
requests to calls and results to responses. See `docs/stream-contract.md`.
"""
import json
import mimetypes
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlsplit

from .events import ServiceError, error_body
from .service import StreamService

MAX_BODY_BYTES = 16 * 1024
MAX_REPLAY_DELAY_MS = 2000

_SESSION_WORDS = re.compile(r"^/api/sessions/([\w-]+)/words$")
_SESSION_FINISH = re.compile(r"^/api/sessions/([\w-]+)/finish$")
_SESSION = re.compile(r"^/api/sessions/([\w-]+)$")
_EXAMPLE = re.compile(r"^/api/examples/([\w.-]+)$")
_RESULTS = re.compile(r"^/api/results/([\w-]+)$")


def make_server(service: StreamService, host: str = "127.0.0.1", port: int = 8765,
                static_dir: Optional[Path] = None, cors_origin: str = "*",
                verbose: bool = False, timeout: float = 30.0) -> ThreadingHTTPServer:
    """Build (but do not start) the server. Pass port 0 to let the system pick a free port.

    `timeout` (seconds) bounds every read and write on a connection: a client that connects and
    stays silent, or stops reading a stream, is dropped instead of holding a thread forever.
    """

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "anticipatory-stream/1"
        timeout = None            # set below: a class attribute the base class reads per connection
        disable_nagle_algorithm = True   # headers and body are separate small writes: without this
                                         # every keep-alive call waits about 40 ms for a delayed ACK

        # -- plumbing -------------------------------------------------------------------

        def log_message(self, fmt, *args):
            if verbose:
                sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")

        def _send_json(self, status: int, body: Any) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._cors()
            self.end_headers()
            self.wfile.write(data)

        def _send_empty(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self._cors()
            self.end_headers()

        def _consume_body(self) -> bytes:
            """Read the whole request body, whatever the route. A body left unread would be
            parsed as the next request on a keep-alive connection."""
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self.close_connection = True
                raise ServiceError(400, "bad_request", "invalid Content-Length")
            if length < 0 or length > MAX_BODY_BYTES:
                self.close_connection = True               # we will not read it, so do not reuse
                raise ServiceError(413, "body_too_large", f"body larger than {MAX_BODY_BYTES} bytes")
            return self.rfile.read(length) if length else b""

        def _read_json(self) -> Dict[str, Any]:
            raw = self._body
            if not raw.strip():
                return {}
            try:
                body = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ServiceError(400, "bad_json", "the body must be a JSON object")
            if not isinstance(body, dict):
                raise ServiceError(400, "bad_json", "the body must be a JSON object")
            return body

        def _dispatch(self, method: str) -> None:
            try:
                self._body = self._consume_body()
                url = urlsplit(self.path)
                query = {k: v[-1] for k, v in parse_qs(url.query).items()}
                if url.path.startswith("/api/"):
                    self._api(method, url.path.rstrip("/") or "/", query)
                elif method == "GET" and static_dir is not None:
                    self._static(url.path)
                else:
                    raise ServiceError(404, "not_found", "no such endpoint")
            except ServiceError as err:
                self._send_json(err.status, err.body())
            except OSError:                                # the client went away or stalled
                self.close_connection = True
            except Exception as err:                       # never leak internals to a client
                if verbose:
                    sys.stderr.write("internal error: %r\n" % (err,))
                self._send_json(500, error_body("internal", "internal error"))

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def do_OPTIONS(self):
            self._send_empty(204)

        # -- the API --------------------------------------------------------------------

        def _api(self, method: str, path: str, query: Dict[str, str]) -> None:
            if method == "GET":
                if path == "/api/health":
                    return self._send_json(200, {"status": "ok"})
                if path == "/api/info":
                    return self._send_json(200, service.info())
                if path == "/api/replay":
                    return self._replay(query)
                if path == "/api/examples":
                    return self._send_json(200, service.examples(
                        query.get("set", "dev"), query.get("tag"), _int(query, "limit", 50),
                        _int(query, "offset", 0)))
                m = _EXAMPLE.match(path)
                if m:
                    return self._send_json(200, service.example_detail(m.group(1)))
                m = _RESULTS.match(path)
                if m:
                    return self._send_json(200, service.results(m.group(1)))
            elif method == "POST":
                if path == "/api/sessions":
                    body = self._read_json()
                    return self._send_json(201, service.create_session(
                        body.get("agent", "hybrid"), body.get("request_id")))
                m = _SESSION_WORDS.match(path)
                if m:
                    return self._send_json(200, service.push_word(m.group(1),
                                                                  self._read_json().get("word")))
                m = _SESSION_FINISH.match(path)
                if m:
                    return self._send_json(200, service.finish(m.group(1)))
            elif method == "DELETE":
                m = _SESSION.match(path)
                if m:
                    service.close(m.group(1))
                    return self._send_empty(204)
            raise ServiceError(404, "not_found", "no such endpoint")

        def _replay(self, query: Dict[str, str]) -> None:
            events = service.replay(text=query.get("text"), example=query.get("example"),
                                    agent=query.get("agent", "hybrid"))   # validates before streaming
            delay = max(0, min(_int(query, "delay_ms", 400), MAX_REPLAY_DELAY_MS)) / 1000.0
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self._cors()
            self.end_headers()
            self.close_connection = True
            try:
                for event in events:
                    self._sse(event["type"], event, event.get("seq"))
                    if delay and event["type"] in ("start", "word"):
                        time.sleep(delay)
                self._sse("done", {"type": "done", "version": 1}, None)
            except OSError:
                pass                                        # the client closed or stalled the stream

        def _sse(self, name: str, data: Dict[str, Any], event_id: Optional[int]) -> None:
            lines = []
            if event_id is not None:
                lines.append("id: %d" % event_id)
            lines.append("event: " + name)
            lines.append("data: " + json.dumps(data, ensure_ascii=False))
            self.wfile.write(("\n".join(lines) + "\n\n").encode("utf-8"))
            self.wfile.flush()

        # -- static files (the UI, later) -----------------------------------------------

        def _static(self, url_path: str) -> None:
            root = Path(static_dir).resolve()
            relative = url_path.lstrip("/") or "index.html"
            target = (root / relative).resolve()
            if root != target and root not in target.parents:
                raise ServiceError(404, "not_found", "no such file")
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                raise ServiceError(404, "not_found", "no such file")
            data = target.read_bytes()
            kind = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", kind + ("; charset=utf-8" if kind.startswith("text/") else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

    Handler.timeout = timeout

    class QuietServer(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            """A client that vanished or stalled is routine, not a traceback on the console."""
            error = sys.exc_info()[1]
            if verbose or not isinstance(error, OSError):
                super().handle_error(request, client_address)

    server = QuietServer((host, port), Handler)
    server.daemon_threads = True
    server.service = service
    return server


def _int(query: Dict[str, str], key: str, default: int) -> int:
    try:
        return int(query.get(key, default))
    except (TypeError, ValueError):
        raise ServiceError(400, "bad_request", f"{key} must be an integer")
