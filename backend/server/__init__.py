"""A thin streaming interface over the agent, for the UI and for any other client.

    cd backend
    python -m server                 # http://127.0.0.1:8765
    python -m server --help

The contract (endpoints, event shapes, errors) is `docs/stream-contract.md`. Layers:

    events.py    the event shapes and the product directory (pure data)
    service.py   sessions, replay, examples, results: no HTTP in it, so it is tested without sockets
    http_app.py  the HTTP shell: routing, JSON, server-sent events, CORS, static files

Standard library only. The agent itself is untouched: this package only drives it.
"""
