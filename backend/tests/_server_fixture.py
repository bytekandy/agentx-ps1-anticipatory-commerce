"""Shared helpers for the server tests: skip when the optional packages are missing, and run a
real uvicorn server in a thread so tests talk to it over real sockets."""
import socket
import threading
import time
import unittest


def require_extras():
    """Skip the calling test module unless the optional server packages are installed."""
    try:
        import fastapi, httpx, httpx_sse, uvicorn, websockets  # noqa: F401
    except ImportError as err:                         # pragma: no cover
        raise unittest.SkipTest(f"optional server packages not installed ({err.name}); "
                                f"see backend/requirements-server.txt")


class LiveServer:
    """The app served by uvicorn on a free local port, for the length of a test class."""

    def __init__(self, app, ws_max_size=16 * 1024, **config):
        import uvicorn
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.ws_url = f"ws://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(uvicorn.Config(app, log_level="error", ws_max_size=ws_max_size,
                                                    **config))
        self.thread = threading.Thread(target=lambda: self.server.run(sockets=[self.sock]),
                                       daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.server.started:                    # pragma: no cover
            raise RuntimeError("test server did not start")
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)
        self.sock.close()
