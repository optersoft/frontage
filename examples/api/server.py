"""The server for `app.py`: one record, and both sides of the wire using it.

    frontage build examples/api --out examples/api/www
    frontage-api examples/api/server.py --addr 127.0.0.1:8000

`Signup` is declared once, in `contract.py`, and both halves import it. The page builds its
form from it and refuses to post a bad one; this route validates the body against the same
object and answers 422 with the field that failed. There is no second copy of the rules, so
there is nothing to keep in step — which is the whole reason this server exists rather than
any other.

The handlers run on frontage's own runtime, compiled into the binary: no CPython, one
interpreter per worker thread, no GIL.
"""

import asyncio

from contract import CAPACITY, Signup

from frontage_api import SSE_DONE, App, HTTPError, Stream, sse

# `static="www"` is the built page, served by Rust from this same process: one origin, no
# CORS, one thing to deploy. In development `frontage serve --proxy` stands in for it.
app = App(title="Signups", version="1.0.0", description="One record, both sides of the wire.", static="www")

# The routes live under `/api` so that development and production address them identically:
# in production this one process answers both the page and `/api`, and in development
# `frontage serve --proxy /api=…` forwards exactly that prefix. A page that has to know which
# it is running under is a page with a bug waiting for a deploy.

SIGNUPS = {}
_next = [1]


@app.get("/api/signups")
async def listing(limit: int = 20):
    """Every signup taken so far, newest first."""
    rows = sorted(SIGNUPS.values(), key=lambda row: row["id"], reverse=True)
    return {"signups": rows[:limit], "total": len(SIGNUPS)}


@app.get("/api/signups/{signup_id}")
async def one(signup_id: int) -> Signup:
    """One signup, by id."""
    row = SIGNUPS.get(signup_id)
    if row is None:
        raise HTTPError(404, "no such signup")
    return row


@app.post("/api/signups")
async def create(body: Signup):
    """Take a signup. The body is validated against `Signup` before this runs, so `body` is
    a dict whose fields are already the right types — and a bad one never reaches here."""
    row = dict(body, id=_next[0])
    SIGNUPS[_next[0]] = row
    _next[0] += 1
    return row


@app.get("/api/seats")
async def seats():
    """Seats left, as Server-Sent Events — a number that changes while nobody reloads."""

    async def produce(send):
        for _ in range(20):
            taken = sum(row["seats"] for row in SIGNUPS.values())
            await send(sse({"left": max(0, CAPACITY - taken)}))
            await asyncio.sleep(1)
        await send(SSE_DONE)

    return Stream(produce, media_type="text/event-stream")
