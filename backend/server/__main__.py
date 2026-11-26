"""Run the stream server:  cd backend && python -m server  [--port 8765] [--static DIR] [--api-key KEY]

Needs the optional packages in `backend/requirements-server.txt` (Python 3.11 or newer). The agent
itself does not: it is standard library only.
"""
import argparse
import os
import socket
import sys
import threading
import time
from pathlib import Path

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server", description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to bind (default: this machine only)")
    parser.add_argument("--port", type=int, default=8765, help="0 picks a free port and prints it")
    parser.add_argument("--static", type=Path, default=None, help="also serve this folder (the UI) at /")
    parser.add_argument("--api-key", default=os.environ.get("STREAM_API_KEY"),
                        help="require this key (header X-API-Key, Bearer token, or ?api_key=); "
                             "default: the STREAM_API_KEY environment variable")
    parser.add_argument("--cors-origin", action="append", default=[], metavar="ORIGIN",
                        help="allow this web origin to call the API (repeatable; '*' allows any). "
                             "Pages served from localhost are always allowed unless --no-local-cors")
    parser.add_argument("--no-local-cors", action="store_true",
                        help="do not allow pages from localhost; only the --cors-origin ones")
    parser.add_argument("--timeout-keep-alive", type=int, default=30,
                        help="seconds an idle connection may stay open")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args(argv)

    if args.static is not None and not args.static.is_dir():
        parser.error(f"--static: {args.static} is not a folder")
    if args.host not in LOOPBACK and not args.api_key:
        parser.error("refusing to listen beyond this machine without an API key "
                     "(set --api-key or STREAM_API_KEY)")

    try:
        import uvicorn
        from .app import Settings, create_app
    except ImportError as err:
        parser.error(f"missing package ({err.name}); install them with: "
                     f"pip install -r backend/requirements-server.txt   (Python 3.11 or newer)")
    from .service import StreamService

    settings = Settings(api_key=args.api_key, cors_origins=tuple(args.cors_origin),
                        cors_origin_regex=None if args.no_local_cors else Settings.cors_origin_regex,
                        static_dir=args.static)
    app = create_app(StreamService(), settings)

    family = socket.AF_INET6 if ":" in args.host else socket.AF_INET
    # IPPROTO_TCP matters: asyncio only turns off Nagle's algorithm on connections whose socket
    # says it is TCP, and without it every keep-alive reply waits about 40 ms for a delayed ACK.
    sock = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))
    host, port = sock.getsockname()[:2]
    server = uvicorn.Server(uvicorn.Config(
        app, log_level="info" if args.verbose else "warning", access_log=args.verbose,
        timeout_keep_alive=args.timeout_keep_alive, ws_max_size=16 * 1024))
    def announce():
        """Say where we are listening only once the server really accepts connections."""
        for _ in range(3000):
            if server.started:
                print(f"stream server on http://{host}:{port}  (docs at /docs; "
                      f"{'API key required' if args.api_key else 'no API key, local only'}; "
                      f"Ctrl-C to stop)", flush=True)
                return
            time.sleep(0.01)

    threading.Thread(target=announce, daemon=True).start()
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
