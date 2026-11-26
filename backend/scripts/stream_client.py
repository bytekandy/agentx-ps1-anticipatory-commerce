"""A small client for the stream server, built on httpx, httpx-sse and websockets.

    pip install -r requirements-server.txt            # Python 3.11 or newer
    cd backend && python -m server &                   # start the server
    python scripts/stream_client.py --live "black running shoes size 9 under 2000"
    python scripts/stream_client.py --rest "black running shoes size 9 under 2000"
    python scripts/stream_client.py --replay "black running shoes size 9 under 2000" --delay 300
    python scripts/stream_client.py --replay-example dev-0004 --delay 0

--live    one WebSocket: the words go out one by one and the server pushes each trace event
--rest    the stateless way: one POST per word carrying the words so far
--replay  the server paces the whole request as server-sent events
Set STREAM_API_KEY (or --api-key) if the server requires a key. See docs/stream-contract.md.
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, Iterator, Optional
from urllib.parse import urlencode

import httpx
from httpx_sse import connect_sse
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect


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
        print(f"start: agent {event['agent']}", file=out)
    elif kind == "error":
        print(f"error: {event['error']['code']}: {event['error']['message']}", file=out)


def check(response: httpx.Response) -> httpx.Response:
    """Turn an error response into a readable message instead of a traceback."""
    if response.is_error:
        response.read()                         # a streamed response has to be read before parsing
        try:
            error = response.json()["error"]
            detail = f"{error['code']}: {error['message']}"
        except (ValueError, KeyError):
            detail = response.text[:200]
        raise SystemExit(f"{response.request.method} {response.url.path}: {response.status_code} {detail}")
    return response


def live(server: str, text: str, agent: str, key: Optional[str]) -> None:
    url = server.replace("http", "ws", 1) + "/api/ws?" + urlencode({"agent": agent, **({"api_key": key} if key else {})})
    try:
        with connect(url) as ws:
            show(json.loads(ws.recv()))
            for word in text.split():
                ws.send(json.dumps({"word": word}))
                show(json.loads(ws.recv()))
            ws.send(json.dumps({"finish": True}))
            show(json.loads(ws.recv()))
    except InvalidStatus as err:
        raise SystemExit(f"websocket refused: HTTP {err.response.status_code} "
                         f"({'missing or wrong API key' if err.response.status_code == 403 else 'see the server log'})")
    except ConnectionClosed as err:
        raise SystemExit(f"websocket closed: {err.rcvd.code if err.rcvd else '?'}")


def rest(server: str, text: str, agent: str, key: Optional[str]) -> None:
    words = text.split()
    with httpx.Client(base_url=server, headers={"X-API-Key": key} if key else {}) as client:
        for n in range(1, len(words) + 1):
            show(check(client.post("/api/step", json={"words": words[:n], "agent": agent})).json())
        show(check(client.post("/api/answer", json={"words": words, "agent": agent})).json())


def replay(server: str, query: Dict[str, Any], key: Optional[str]) -> Iterator[Dict[str, Any]]:
    with httpx.Client(base_url=server, headers={"X-API-Key": key} if key else {}, timeout=None) as client:
        with connect_sse(client, "GET", "/api/replay", params=query) as source:
            check(source.response)
            for event in source.iter_sse():
                if event.event != "done":
                    yield json.loads(event.data)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server", default="http://127.0.0.1:8765")
    parser.add_argument("--api-key", default=os.environ.get("STREAM_API_KEY"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", metavar="TEXT", help="send these words one at a time over a WebSocket")
    mode.add_argument("--rest", metavar="TEXT", help="one stateless POST per word")
    mode.add_argument("--replay", metavar="TEXT", help="have the server stream this request")
    mode.add_argument("--replay-example", metavar="ID", help="stream a dev or dev_extra request")
    parser.add_argument("--agent", default="hybrid", choices=("hybrid", "heuristic", "learned"))
    parser.add_argument("--delay", type=int, default=300, help="ms between words in a replay")
    args = parser.parse_args(argv)

    if args.live is not None:
        live(args.server, args.live, args.agent, args.api_key)
    elif args.rest is not None:
        rest(args.server, args.rest, args.agent, args.api_key)
    else:
        query = {"agent": args.agent, "delay_ms": args.delay}
        query.update({"text": args.replay} if args.replay is not None else {"example": args.replay_example})
        for event in replay(args.server, query, args.api_key):
            show(event)
    return 0


if __name__ == "__main__":
    sys.exit(main())
