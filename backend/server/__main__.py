"""Run the stream server:  cd backend && python -m server  [--port 8765] [--static DIR]"""
import argparse
import sys
from pathlib import Path

from .http_app import make_server
from .service import StreamService


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server", description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to bind (default: this machine only)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--static", type=Path, default=None,
                        help="also serve this folder (the UI) at /")
    parser.add_argument("--cors-origin", default="*", help="value of Access-Control-Allow-Origin")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="seconds a connection may stay silent before it is dropped")
    parser.add_argument("--verbose", action="store_true", help="log requests to stderr")
    args = parser.parse_args(argv)
    if args.static is not None and not args.static.is_dir():
        parser.error(f"--static: {args.static} is not a folder")

    server = make_server(StreamService(), args.host, args.port, args.static, args.cors_origin,
                         args.verbose, args.timeout)
    host, port = server.server_address[:2]
    print(f"stream server on http://{host}:{port}  (GET /api/info; Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
