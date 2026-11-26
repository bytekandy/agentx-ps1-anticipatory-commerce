"""A small client for the stream server, and a worked example of the contract.

    cd backend
    python -m server &                                   # start the server in another terminal
    python scripts/stream_client.py --live "black running shoes size 9 under 2000"
    python scripts/stream_client.py --replay "black running shoes size 9 under 2000" --delay 300
    python scripts/stream_client.py --replay-example dev-0004 --delay 0

`--live` sends the words one at a time (POST per word) and prints each trace event as it comes
back, which is how a typed or spoken request would be fed. `--replay` lets the server pace the
whole request as server-sent events. Standard library only; see docs/stream-contract.md.
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterator, Optional, Tuple


def call(base: str, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as err:
        raise SystemExit(describe(method, path, err))


def describe(method: str, path: str, err: urllib.error.HTTPError) -> str:
    """A readable message for an error response, e.g. "GET /api/replay: 404 unknown_example: ..."."""
    try:
        payload = json.loads(err.read() or b"{}").get("error", {})
    except ValueError:
        payload = {}
    finally:
        err.close()
    return f"{method} {path}: {err.code} {payload.get('code', '')}: {payload.get('message', err.reason)}"


def events(base: str, path: str) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Read a server-sent event stream: yields (event name, data) until the stream ends."""
    try:
        response = urllib.request.urlopen(base + path)
    except urllib.error.HTTPError as err:
        raise SystemExit(describe("GET", path.split("?")[0], err))
    with response:
        name, data = None, []
        for raw in response:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data.append(line[6:])
            elif not line and name:
                yield name, json.loads("\n".join(data))
                name, data = None, []


def show(event: Dict[str, Any], out=None) -> None:
    out = out or sys.stdout                       # looked up now, so redirecting stdout works
    kind = event["type"]
    if kind == "word":
        t = event["trace"]
        shown = {k: v for k, v in t["filters"].items() if v is not None}
        flag = "COMMIT " + event["commit"]["product_id"] if event["commit"] else t["action"]
        print(f"{event['seq']:3} {event['word']:<14} {flag:<14} {t['reason'][:58]:<58} {shown}", file=out)
    elif kind == "final":
        product = event["product"]
        print(f"final: {event['final_product_id']}  {product['title'] if product else '(none)'}"
              f"  searches={event['searches']}  unresolved={event['unresolved']}", file=out)
        if event["evaluation"]:
            e = event["evaluation"]
            print(f"scored: correct={e['correct']} early_words={e['early_words']} "
                  f"wrong_commits={e['wrong_commits']} score={e['score']:.3f}", file=out)
    elif kind == "start":
        print(f"start: session {event['session']}, agent {event['agent']}", file=out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", metavar="TEXT", help="send these words one at a time")
    mode.add_argument("--replay", metavar="TEXT", help="have the server stream this request")
    mode.add_argument("--replay-example", metavar="ID", help="stream a dev or dev_extra request")
    parser.add_argument("--agent", default="hybrid", choices=("hybrid", "heuristic", "learned"))
    parser.add_argument("--delay", type=int, default=300, help="ms between words in a replay")
    args = parser.parse_args(argv)

    if args.live is not None:
        start = call(args.server, "POST", "/api/sessions", {"agent": args.agent})
        show(start)
        for word in args.live.split():
            show(call(args.server, "POST", f"/api/sessions/{start['session']}/words", {"word": word}))
        show(call(args.server, "POST", f"/api/sessions/{start['session']}/finish"))
        return 0
    query = {"agent": args.agent, "delay_ms": args.delay}
    query.update({"text": args.replay} if args.replay is not None else {"example": args.replay_example})
    for name, data in events(args.server, "/api/replay?" + urllib.parse.urlencode(query)):
        if name != "done":
            show(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
