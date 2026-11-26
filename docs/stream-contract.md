# Stream contract (version 1)

How a client (the UI, a script, a speech front end) drives the agent and watches it think. It is
written so the backend and the UI can be built independently: everything a client may rely on is
here; anything not here may change. Every payload below is real output of the running service.

## 1. What it is, and what it is not
- It lets a client feed a shopping request to the agent **one word at a time** and receive, after
  each word, the agent's full **trace record**: what it read, how sure it is, what it did and why.
- It also **replays** a whole request on a timer (for demos) and serves the dev examples and the
  committed results.
- It adds no decisions of its own. The interface was tested to be transparent: for all 387 dev and
  `dev_extra` requests, what it reports (final answer, commit word and product, search count,
  score) is identical to the committed results of the kit's own harness.
- It is not authenticated and not meant for the open internet (see section 8).

## 2. Transport, and why
Plain HTTP and JSON, standard library only (`http.server`), plus Server-Sent Events for replays.

| Use | Mechanism | Why |
|---|---|---|
| Live (typing, voice) | One `POST` per word; the reply is the next event | Works from any client, browser or script; no connection to keep alive; one word, one answer |
| Replay (demo) | `GET` that streams server-sent events, paced by the server | A browser's built-in `EventSource` consumes it with no code; the server controls the speed |
| Everything else | `GET` JSON | Plain |

WebSockets are not in the standard library, and neither use needs a two-way channel.

## 3. Running it
```
cd backend
python -m server                                  # http://127.0.0.1:8765
python -m server --port 9000 --static ../frontend # also serve the UI folder at /
python -m server --help
```
Options: `--host` (default `127.0.0.1`, this machine only), `--port` (0 picks a free port and
prints it), `--static DIR`, `--cors-origin` (default `*`), `--timeout` (seconds a silent
connection may stay open, default 30), `--verbose`.

An example client that follows this contract is `backend/scripts/stream_client.py`:
```
python scripts/stream_client.py --live "beige Loomsy sneakers size 10 under 3000"
python scripts/stream_client.py --replay-example dev-0004 --delay 300
```

## 4. Conventions
- JSON in UTF-8. Every event has `type` and `version` (currently `1`).
- `null` means "not available / not mentioned". Keys are never omitted from an event.
- **Compatibility within version 1:** fields are only ever added, never renamed, removed or
  changed in meaning. Clients must ignore fields they do not know.
- Words are exactly as typed, punctuation included ("size,", "Rs.", "XS"). Send one word per call;
  do not clean or lower-case them.
- Per session, words are processed strictly in order and one at a time.

## 5. Endpoints
| Method and path | Purpose | Success |
|---|---|---|
| `GET /api/health` | Is it up | `200 {"status": "ok"}` |
| `GET /api/info` | Version, agents, limits, dataset sizes, break-even risk | `200` info |
| `POST /api/sessions` | Open a live request. Body (optional): `{"agent": "hybrid", "request_id": "any JSON value"}` | `201` **start** event |
| `POST /api/sessions/{id}/words` | Send the next word. Body: `{"word": "beige"}` | `200` **word** event |
| `POST /api/sessions/{id}/finish` | The request is over; get the answer | `200` **final** event |
| `DELETE /api/sessions/{id}` | Forget a session | `204` |
| `GET /api/replay?text=...` or `?example=dev-0004` | Stream a whole request as server-sent events. Also `agent=` and `delay_ms=` (default 400, capped at 2000) | `200` event stream |
| `GET /api/examples?set=dev&tag=correction&limit=50&offset=0` | List dev or dev_extra requests (`set`: `dev`, `dev_extra`; `tag` optional, `plain` allowed) | `200` list |
| `GET /api/examples/{id}` | One example with its gold answer | `200` detail |
| `GET /api/results/{set}` | The committed results of the final agent on a set, summarised with the kit's scorer, with the kit baseline | `200` results |

`agent` is `hybrid` (default, the submitted agent), `heuristic` (rules only) or `learned` (model only).
Request bodies are limited to 16 KB. Any `OPTIONS` request gets a CORS preflight answer (`204`).

## 6. Events
### start
```json
{"type": "start", "version": 1, "session": "ykU7QPn6Wxne", "agent": "hybrid",
 "request_id": "demo-1", "text": null, "words": null}
```
In a replay, `text` and `words` hold the request that is about to be streamed.

### word (one per word)
`seq` is the 1-based position of the word. `trace` is the agent's own record. `commit` is `null`
except on the single word where the agent commits, when it holds the product to show.
```json
{"type": "word", "version": 1, "session": "ykU7QPn6Wxne", "seq": 3, "word": "sneakers",
 "trace": {"index": 3, "word": "sneakers",
           "filters": {"category": "sneakers", "colour": "beige", "size": null, "brand": "Loomsy", "max_price": null},
           "confidence": 0.95, "settled": true, "correction_pending": false, "pending_slots": [],
           "searched": false, "n_candidates": null, "action": "wait", "product_id": null,
           "risk": null, "reason": "size not known", "unresolved": []},
 "commit": null, "searches": 0}
```
The commit word of the same request:
```json
{"type": "word", "version": 1, "session": "ykU7QPn6Wxne", "seq": 8, "word": "please",
 "trace": {"index": 8, "word": "please",
           "filters": {"category": "sneakers", "colour": "beige", "size": "10", "brand": "Loomsy", "max_price": 3000},
           "confidence": 0.95, "settled": true, "correction_pending": false, "pending_slots": [],
           "searched": true, "n_candidates": 1, "action": "commit", "product_id": "P0081",
           "risk": 0.0252, "reason": "one product matches and the risk is low", "unresolved": []},
 "commit": {"seq": 8, "product_id": "P0081",
            "product": {"product_id": "P0081", "title": "Loomsy Street Sneakers, Beige", "brand": "Loomsy",
                        "category": "sneakers", "colour": "beige", "size": "10", "price": 2899,
                        "description": "Street sneakers by Loomsy in beige. Everyday low-top for college and weekends."}},
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

`searches` on the event is the number of counted searches so far in this session.

### final
```json
{"type": "final", "version": 1, "session": "ykU7QPn6Wxne", "words": 8,
 "final_product_id": "P0081", "product": {"...": "as above"},
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

### Replay stream
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

## 7. Errors
Every error is JSON `{"error": {"code": "...", "message": "..."}}` with the right HTTP status.

| Status | `code` | When |
|---|---|---|
| 400 | `bad_word` | Not a string, empty, contains spaces, or longer than 100 characters |
| 400 | `bad_json` | The body is not a JSON object |
| 400 | `bad_request` | Missing or conflicting parameters (replay needs exactly one of `text`, `example`), a non-numeric number |
| 400 | `unknown_agent` | `agent` is not one of the listed names |
| 400 | `text_too_long` | A replayed text over 4000 characters |
| 404 | `unknown_session`, `unknown_example`, `unknown_set`, `no_results`, `not_found` | No such thing (a session also disappears when idle, see below) |
| 409 | `session_finished` | A word or a second finish sent to a finished session |
| 413 | `too_many_words`, `body_too_large` | More than 500 words in a request, or a body over 16 KB |
| 429 | `too_many_sessions` | 200 open sessions already |
| 500 | `internal` | A bug; the message is generic on purpose |

## 8. Limits, sessions and security
- A session is one agent with its own state and its own search counter. Sessions are independent
  and safe to use from many clients at once (tested with 24 threads and 16 HTTP clients).
- An open session nobody touches for **10 minutes** is forgotten (then `404`). A finished session
  is kept **30 seconds** (so a second call gets `409`, not `404`) and then dropped; only open
  sessions count against the limit of 200.
- Defaults are safe for a demo on one machine: it listens on `127.0.0.1` only, every read and
  write has a 30 second timeout, request bodies are capped, sessions and words are capped, errors
  never expose internals, static files cannot leave the `--static` folder (tested against `..`,
  encoded `..` and double slashes), and nothing is written to disk.
- **There is no authentication.** `Access-Control-Allow-Origin: *` is the default so a UI served
  from another port works. Do not expose the server beyond localhost without putting something in
  front of it, and set `--cors-origin` to the UI's origin if you do.

## 9. Using it from a browser
Watch a replay (no code beyond this):
```js
const es = new EventSource("http://127.0.0.1:8765/api/replay?example=dev-0004&delay_ms=300");
es.addEventListener("word",  e => render(JSON.parse(e.data)));   // update chips, confidence, commit
es.addEventListener("final", e => showAnswer(JSON.parse(e.data)));
es.addEventListener("done",  () => es.close());                   // otherwise EventSource reconnects
```
Live typing or speech:
```js
const api = "http://127.0.0.1:8765/api";
const post = (path, body) => fetch(api + path, {method: "POST", headers: {"Content-Type": "application/json"},
                                                body: JSON.stringify(body ?? {})}).then(r => r.json());
const {session} = await post("/sessions", {agent: "hybrid"});
for (const word of text.split(/\s+/)) render(await post(`/sessions/${session}/words`, {word}));
showAnswer(await post(`/sessions/${session}/finish`));
```
**Speech:** send a word only once the recogniser has finalised it. The agent cannot take a word
back, but the shopper's own corrections ("black, no wait, white") are handled: send them as spoken.

What to show, by field: slot chips from `trace.filters`; a confidence bar from `trace.confidence`;
a "waiting for..." state from `settled`, `correction_pending`, `pending_slots`; a warning from
`unresolved` ("not understood: brand: nike"); the reason line from `trace.reason`; the risk against
`info.break_even_risk`; the product card from `commit.product` and `final.product`.

## 10. Measured behaviour
On loopback (Python 3.14), one persistent connection: a live word costs **0.85 ms** median
(p95 1.4 ms) including the agent; 16 concurrent clients sustain about 900 calls per second with no
errors. The agent itself takes 0.09 ms per word, so almost all of it is HTTP.
