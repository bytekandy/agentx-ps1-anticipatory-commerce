# Stream contract (version 1)

How a client (the UI, a script, a speech front end) drives the agent and watches it think. It is
written so the backend and the UI can be built independently: everything a client may rely on is
here; anything not here may change. The REST part is also published as a machine-readable
OpenAPI document by the running server (`/openapi.json`, interactive page at `/docs`), generated
from the same typed models the server validates every response against.

## 1. What it is, and what it is not
- It lets a client feed a shopping request to the agent **one word at a time** and receive, after
  each word, the agent's full **trace record**: what it read, how sure it is, what it did and why.
- It also **replays** a whole request on a timer (for demos) and serves the dev examples and the
  committed results.
- It adds no decisions of its own. For all 387 dev and `dev_extra` requests, what it reports (final
  answer, commit word and product, search count, score) is identical to the committed results of
  the kit's own harness, over the WebSocket, the stateless REST calls and the replay alike.
- It is a demo and UI interface, not part of what the competition harness runs. **The agent
  itself stays standard library only (Python 3.8+); only this server and its client use packages.**

## 2. Libraries, and why these
Round 1 allows third-party libraries; the agent avoids them so a missing install can never break
the scored run, but this optional interface has no such constraint, so it uses well-known ones
instead of hand-rolled code. Install: `pip install -r backend/requirements-server.txt`. **These
need Python 3.11 or newer** (the agent does not). Compared and tried on Python 3.14:

| Need | Chosen | Why | Considered |
|---|---|---|---|
| Web framework | **FastAPI** 0.165 | Typed models give validation, the OpenAPI document and `/docs` for free; WebSocket, server-sent events, API-key security, body limit, CORS and safe static files are built in or in Starlette | Starlette alone (no schema), aiohttp (manual validation and docs), Flask with extensions (sync, more parts), Litestar (smaller ecosystem) |
| Server | **uvicorn** 0.54 | The standard ASGI server; WebSocket and keep-alive handled | hypercorn, granian |
| Typed models | **Pydantic** 2 (comes with FastAPI) | One source for validation, docs and tests | dataclasses plus hand-written checks |
| Server-sent events | FastAPI's own `EventSourceResponse` | Built in since recent versions | `sse-starlette` (now redundant) |
| Python client: HTTP and SSE | **httpx** 0.29 + **httpx-sse** 0.4 | Sync and async, streaming, one API for both | requests + sseclient-py (sync only, the SSE parser is unmaintained) |
| Python client: WebSocket | **websockets** 17 | The reference implementation; has a simple sync client | aiohttp's client |

Earlier this stage used a hand-written `http.server` application and a hand-written client with
its own server-sent-event parser. Replacing them removed about 400 lines of code that were not
the project's business, and fixed all the "honest limits" the standard-library version had
(section 10).

## 3. Running it
```
pip install -r backend/requirements-server.txt        # once, Python 3.11 or newer
cd backend
python -m server                                       # http://127.0.0.1:8765, docs at /docs
python -m server --static ../frontend                  # also serve the UI folder at /
python -m server --api-key SECRET --cors-origin https://ui.example --host 0.0.0.0
python -m server --help
```
- `--host` defaults to `127.0.0.1` (this machine only). **The server refuses to listen on any
  other address without an API key.**
- `--api-key` (or the `STREAM_API_KEY` environment variable) requires a key on every endpoint
  except `/api/health`.
- CORS: pages served from `localhost`, `127.0.0.1` or `[::1]` (any port) may call the API;
  everything else is refused. Add origins with `--cors-origin` (repeatable); `'*'` allows any
  and is never the default; `--no-local-cors` turns the localhost allowance off.
- Also `--port` (0 picks a free port and prints it), `--static DIR`, `--timeout-keep-alive`,
  `--verbose`. The "listening" line is printed only once the server really accepts connections.

An example client built on the libraries above is `backend/scripts/stream_client.py`:
```
python scripts/stream_client.py --live "beige Loomsy sneakers size 10 under 3000"   # WebSocket
python scripts/stream_client.py --rest "beige Loomsy sneakers size 10 under 3000"   # stateless POSTs
python scripts/stream_client.py --replay-example dev-0004 --delay 300               # server-sent events
```

## 4. Conventions
- JSON in UTF-8. Every event has `type` and `version` (currently `1`).
- `null` means "not available / not mentioned". Keys are never omitted from an event.
- **Compatibility within version 1:** fields are only ever added, never renamed, removed or
  changed in meaning. Clients must ignore fields they do not know.
- Words are exactly as typed, punctuation included ("size,", "Rs.", "XS"). Send one word per
  entry; do not clean or lower-case them.
- **The authentication key** goes in the `X-API-Key` header, or `Authorization: Bearer KEY`, or the
  query parameter `api_key` (the only choice for a browser's `EventSource` and `WebSocket`, which
  cannot set headers).

## 5. Three ways to talk to it
| Use | Mechanism | Choose it when |
|---|---|---|
| **Live, pushed** | One **WebSocket** per request: the client sends a word, the server pushes the event | A UI or a speech recogniser feeding words as they come. One connection, no per-word HTTP overhead |
| **Live, stateless** | **REST**: every call carries the words so far and returns the event for the last word | A script, a test, or any client that cannot hold a connection. There is no session to open, expire or lose |
| **Replay** | **Server-sent events**, paced by the server | A demo: watch the agent read a request. A browser's `EventSource` consumes it with no code |

Why stateless REST is safe: the agent is deterministic and causal (the answer at word *t* depends
only on words 1 to *t*; tested on 4,440 prefixes), so a call that replays the words it is given
returns exactly what a live session would have. Any process can answer any call, and restarts lose
nothing.

## 6. Endpoints
| Method and path | Purpose | Success |
|---|---|---|
| `GET /api/health` | Is it up (no key needed) | `200 {"status": "ok"}` |
| `GET /api/info` | Version, agents, limits, dataset sizes, break-even risk, `auth_required` | `200` |
| `POST /api/step` | The event for the last of the words so far. Body: `{"words": ["beige", "Loomsy"], "agent": "hybrid", "request_id": null}` | `200` **word** event |
| `POST /api/answer` | The final answer for a finished request. Same body | `200` **final** event |
| `POST /api/feedback` | The shopper accepted this product for this request; the agent remembers what words it could not place probably meant (`learned_lexicon.json`, read at the next start). Body: `{"words": ["black", "clogs"], "product_id": "P0001"}` | `200 {"learned": [...]}` |
| `POST /api/run` | Every event of a whole request at once. Same body | `200 {"events": [...]}` |
| `GET /api/replay?text=...` or `?example=dev-0004` | Stream a whole request as server-sent events. Also `agent=` and `delay_ms=` (default 400, capped at 2000) | `200` event stream |
| `GET /api/examples?set=dev&tag=correction&limit=50&offset=0` | List dev or dev_extra requests (`set`: `dev`, `dev_extra`; `tag` optional, `plain` allowed) | `200` list |
| `GET /api/examples/{id}` | One example with its gold answer | `200` detail |
| `GET /api/results/{set}` | The committed results of the final agent on a set, summarised with the kit's scorer, with the kit baseline | `200` results |
| `WS /api/ws?agent=hybrid&request_id=abc` | Live, pushed (section 7) | upgrade |

`agent` is `hybrid` (default, the submitted agent), `heuristic` (rules only) or `learned` (model only).
Request bodies are limited to 16 KB. Interactive documentation of the REST endpoints: `/docs`.

## 7. The WebSocket protocol
Connect to `/api/ws` (optionally `?agent=`, `?request_id=`, `?api_key=`). Messages are JSON text.

| Direction | Message | Meaning |
|---|---|---|
| server to client | a **start** event | Sent on connect |
| client to server | `{"word": "beige"}` | The next word |
| server to client | a **word** event | The agent's reading after that word |
| client to server | `{"finish": true}` | The request is over |
| server to client | a **final** event, then the connection closes with code `1000` | The answer |
| server to client | `{"type": "error", "version": 1, "error": {"code", "message"}}` | The last message was not acceptable. The run **continues** after `bad_word`, `bad_json` and `bad_request` |

The server closes the connection when the run cannot continue (`too_many_words`), after 5 minutes
without a message (code `1001`), or if a message is larger than 16 KB. A missing or wrong API key
is refused during the handshake with `HTTP 403`.

## 8. Events
### start
```json
{"type": "start", "version": 1, "agent": "hybrid", "request_id": "demo-1",
 "text": "beige Loomsy sneakers size 10 under 3000 please",
 "words": ["beige", "Loomsy", "sneakers", "size", "10", "under", "3000", "please"]}
```
`text` and `words` are filled only in a replay or a `/api/run`; for a live run they are `null`.

### word (one per word)
`seq` is the 1-based position of the word. `trace` is the agent's own record. `commit` is `null`
except on the single word where the agent commits; `committed` is `null` until then and holds the
commit on that word **and every later one**, so the latest event alone tells a client whether and
where the agent committed.
```json
{"type": "word", "version": 1, "seq": 3, "word": "sneakers",
 "trace": {"index": 3, "word": "sneakers",
           "filters": {"category": "sneakers", "colour": "beige", "size": null, "brand": "Loomsy", "max_price": null},
           "confidence": 0.95, "settled": true, "correction_pending": false, "pending_slots": [],
           "searched": false, "n_candidates": null, "action": "wait", "product_id": null,
           "risk": null, "reason": "size not known", "unresolved": []},
 "commit": null, "committed": null, "searches": 0}
```
The commit word of the same request:
```json
{"type": "word", "version": 1, "seq": 8, "word": "please",
 "trace": {"index": 8, "word": "please",
           "filters": {"category": "sneakers", "colour": "beige", "size": "10", "brand": "Loomsy", "max_price": 3000},
           "confidence": 0.95, "settled": true, "correction_pending": false, "pending_slots": [],
           "searched": true, "n_candidates": 1, "action": "commit", "product_id": "P0081",
           "risk": 0.0203, "reason": "one product matches and the risk is low", "unresolved": []},
 "commit": {"seq": 8, "product_id": "P0081",
            "product": {"product_id": "P0081", "title": "Loomsy Street Sneakers, Beige", "brand": "Loomsy",
                        "category": "sneakers", "colour": "beige", "size": "10", "price": 2899,
                        "description": "Street sneakers by Loomsy in beige. Everyday low-top for college and weekends."}},
 "committed": {"seq": 8, "product_id": "P0081", "product": {"...": "same as commit"}},
 "searches": 1}
```

| `trace` field | Meaning |
|---|---|
| `filters` | The reading so far. Keys `category`, `colour`, `size`, `brand`, `max_price` (and `min_price` only if the shopper gave one). `null` = not mentioned. `size` is a string ("10", "XL"); `max_price` an integer in rupees |
| `confidence` | The weakest slot's confidence, 0 to 1; halved while unsettled; 0 when nothing is read yet |
| `settled` | `false` while the reading may still change: a correction is on its way, a number may still grow, a size or price cue awaits its number, or something is unresolved |
| `correction_pending` | A correction marker ("oops", "make that"...) was heard and its replacement has not come |
| `pending_slots` | Slots whose number may still grow, e.g. `["max_price"]` after "under two thousand" |
| `unresolved` | What the shopper asked for that nothing in the shop answers to, e.g. `["brand: nike", "size: 14"]`. The agent does not commit early while this is non-empty |
| `searched` / `n_candidates` | Whether a (counted) search was made after this word and how many products matched |
| `action` | `wait` or `commit` |
| `risk` | The estimated chance the commit is wrong, when the agent got as far as weighing it; compare with `info.break_even_risk` |
| `reason` | A short human-readable why, suitable to show |

`searches` on the event is the number of counted searches so far in this run.

### final
```json
{"type": "final", "version": 1, "words": 8, "final_product_id": "P0081",
 "product": {"...": "as above"},
 "filters": {"category": "sneakers", "colour": "beige", "size": "10", "brand": "Loomsy", "max_price": 3000},
 "unresolved": [], "commit": {"seq": 8, "product_id": "P0081", "product": {"...": "as above"}},
 "searches": 1, "evaluation": null}
```
`final_product_id` / `product` are the answer after the whole request was re-read (they can be
`null` if nothing matched). `commit` is the early commit, or `null` if the agent never committed.
`evaluation` is `null` for free text. For a replayed dev example it holds the kit's own scoring:
```json
{"target": "P0206", "target_product": {"...": "..."}, "correct": true, "wrong_commits": 0,
 "early_words": 2, "early_share": 0.1333, "oracle_share": 0.4, "searches": 1, "score": 0.48,
 "gold_filters": {"category": "sandals", "colour": "black", "size": "9", "brand": "Strydo", "max_price": 800}}
```
`score` is the per-request score of `evaluate.py` (0.4 for a right answer plus 0.6 times the share
of the request still to come at the commit, minus 1.0 per wrong commit, minus 0.02 per extra
search). `oracle_share` is the best possible share.

### The replay stream
`GET /api/replay` answers `200` with `Content-Type: text/event-stream`. Each message is
```
id: 3
event: word
data: {"type": "word", ...}

```
in this order: one `start`, one `word` per word (`id` = `seq`), one `final`, then
`event: done` with `data: {"type": "done", "version": 1}`. The server waits `delay_ms` after the
start and after each word. Errors in the request are returned as an ordinary JSON error **before**
any streaming begins. If the client disconnects, the server just stops.

### Results and examples
`/api/results/{set}` returns `{"set", "summary", "by_tag", "baseline", "requests"}`:
`summary`, each `by_tag` entry and `baseline` have the kit's summary keys (`requests`, `accuracy`,
`wrong_commits`, `requests_with_wrong_commit`, `early_words`, `early_share`, `oracle_share`,
`searches`, `wasted`, `score`); `requests` lists, per request, `id`, `tags`, `words`, `correct`,
`final`, `target`, `commits` (`[[word_number, product_id]]`), `wrong_commits`, `early_words`,
`score`. `/api/examples` items are `{id, text, tags, words}`; the detail adds `set`, `words` (the
list), `gold_filters`, `target`, `target_product`, `earliest`.

## 9. Errors
Every error is JSON `{"error": {"code": "...", "message": "..."}}` with the right HTTP status.

| Status | `code` | When |
|---|---|---|
| 400 | `bad_word` | Not a string, empty, contains spaces, or longer than 100 characters |
| 400 | `bad_json`, `bad_request` | The body or message is not what the endpoint takes (missing or mistyped fields, an empty word list, replay needs exactly one of `text`, `example`, a non-numeric number) |
| 400 | `unknown_agent` | `agent` is not one of the listed names |
| 400 | `text_too_long` | A replayed text over 4000 characters |
| 401 | `unauthorized` | A key is required and was missing or wrong |
| 404 | `unknown_example`, `unknown_set`, `no_results`, `not_found` | No such thing |
| 405 | `method_not_allowed` | The path exists but not for that method |
| 409 | `run_finished` | A word or a second finish sent to a finished run (WebSocket) |
| 413 | `too_many_words`, `body_too_large` | More than 500 words in a request, or a body over 16 KB |
| 500 | `internal` | A bug; the message is generic on purpose |

## 10. Limits, and what is still not covered
Fixed by using the libraries (these were the honest limits of the first, standard-library version):
- **Sessions:** none. REST is stateless and a WebSocket run lives only as long as its connection,
  so nothing is lost on a restart, nothing expires, there is no session limit, and several
  processes behind one address can all answer any call.
- **One call per word:** the WebSocket pushes events over one connection.
- **No authentication:** an API key, required on every endpoint but `/api/health` when set, and
  **mandatory to listen beyond localhost**. Compared in constant time.
- **CORS `*`:** the default now allows only pages served from this machine; anything else is an
  explicit `--cors-origin`.
- **Body size, validation, SSE and static files** (including path traversal) are the libraries'
  own, tested here.

Defaults that bound abuse: 500 words per request, 100 characters per word, a 16 KB body and
WebSocket message, 4000 characters of replay text, a 2 second cap on the replay delay, a 5 minute
idle limit on a WebSocket, a 30 second idle limit on a keep-alive connection.

Still not covered, so be aware:
- **There is no TLS.** For anything beyond a demo on one machine, run it behind a reverse proxy
  that terminates TLS.
- **The API key is one shared secret.** A browser must pass it in the query string (for
  `EventSource` and `WebSocket`), where it can end up in logs; use the header from any client
  that can.
- **There is no per-client rate limiting.** Requests are bounded in size and cost (about 0.1 ms
  per word), but a proxy should rate-limit if the server is exposed.
- The extras need **Python 3.11 or newer**, unlike the agent.

## 11. Using it from a browser
Watch a replay (no code beyond this):
```js
const es = new EventSource("http://127.0.0.1:8765/api/replay?example=dev-0004&delay_ms=300");
es.addEventListener("word",  e => render(JSON.parse(e.data)));   // update chips, confidence, commit
es.addEventListener("final", e => showAnswer(JSON.parse(e.data)));
es.addEventListener("done",  () => es.close());                   // otherwise EventSource reconnects
```
Live typing or speech, pushed:
```js
const ws = new WebSocket("ws://127.0.0.1:8765/api/ws?agent=hybrid");
ws.onmessage = m => { const e = JSON.parse(m.data); e.type === "final" ? showAnswer(e) : render(e); };
const sendWord = w => ws.send(JSON.stringify({word: w}));        // once per word
const finish   = () => ws.send(JSON.stringify({finish: true}));
```
Stateless, with `fetch`:
```js
const words = [];
async function addWord(w) {
  words.push(w);
  const r = await fetch("http://127.0.0.1:8765/api/step", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({words})});
  return r.json();                                                // the event for the last word
}
```
**Speech:** send a word only once the recogniser has finalised it. The agent cannot take a word
back, but the shopper's own corrections ("black, no wait, white") are handled: send them as spoken.

What to show, by field: slot chips from `trace.filters`; a confidence bar from `trace.confidence`;
a "waiting for..." state from `settled`, `correction_pending`, `pending_slots`; a warning from
`unresolved` ("not understood: brand: nike"); the reason line from `trace.reason`; the risk against
`info.break_even_risk`; the product card from `commit.product` and `final.product`; "committed at
word k" from `committed.seq`.

## 12. Measured behaviour
On loopback, Python 3.14, one uvicorn process:

| | median | p95 |
|---|---|---|
| a live word over the WebSocket, agent included | 0.60 ms | 1.3 ms |
| a stateless REST step (it replays the words it is given: 1 to 11 words in this measurement) | 2.3 ms | 5.0 ms |

16 concurrent clients sustained about 900 WebSocket words per second, or 270 REST calls per second,
with no errors. The agent itself takes 0.09 ms per word; a REST step costs about 0.2 ms for each word
it replays. One process is limited by Python's interpreter lock; because nothing is stored, more
processes behind one address scale it.

A note on the launcher: it binds its own socket so it can print the port, and that socket must be
created with `IPPROTO_TCP`. Without it asyncio does not turn off Nagle's algorithm, and every
keep-alive reply waits about 40 ms for a delayed ACK (measured: 43 ms against 0.4 ms). Tests guard
this.
