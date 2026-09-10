# frontage-api

FastAPI's shape on [axum](https://github.com/tokio-rs/axum), with the handlers running on
[frontage](https://pypi.org/project/frontage/)'s own Python runtime — a bytecode VM written
in Rust and compiled into the server binary. No CPython, and so no GIL: one interpreter per
worker thread, one OS thread per worker, sharing nothing.

```python
from frontage_api import App, HTTPError
from frontage.schema import record, integer, text

app = App(title="trips")
Trip = record(("id", integer(ge=0)), ("note", text()))


@app.get("/trips/{trip_id}")
async def trip(trip_id: int) -> Trip:
    """One trip, by id."""
    row = TRIPS.get(trip_id)
    if row is None:
        raise HTTPError(404, "no such trip")
    return row


@app.post("/trips")
async def create(body: Trip):  # validated, coerced, 422 with the field errors
    return {"id": store(body)}
```

```
frontage-api app.py --addr 0.0.0.0:8000 --workers 4
```

The routes describe themselves at `/openapi.json`, with a page over it at `/docs`.

## Why it exists

**The same record validates the form in the page and the body that form posts.**
`frontage.schema` runs in the browser and on the server, so a contract is written once and
neither side can drift from the other. That is the whole pitch; everything else follows from
it.

It is also fast, because there is one crossing per request rather than one per read: axum
parses the request, the body arrives whole, Python is entered once, and the response leaves
in one piece. On a body-echo route that measures **5.97× Granian + FastAPI**, and reading the
body costs 5% here where it costs Granian 48%.

## What is in it

`App` and the seven method decorators, path/query binding from annotations, request bodies
through `frontage.schema`, `Depends`, `HTTPError`, lifespan hooks, CORS, streaming responses
(Server-Sent Events included), static files served by Rust, an HTTP client for handlers that
have to call something else, an OpenAPI document and a docs page, and a Google sign-in gate
(`--auth google`) that can sit in front of everything the server answers.

## What it is not

**Not for existing FastAPI applications.** The handlers run on frontage's runtime, which is a
subset of Python: no `typing` at runtime, no dataclasses, and a standard library that is
short and grows by need. Someone who arrives from frontage wanting a server is the reader
this is for.

Full design, measurements and the reasoning: [`API.md`](https://github.com/optersoft/frontage/blob/main/API.md).

Apache-2.0 · © Optersoft, S.L.
