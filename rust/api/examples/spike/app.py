"""The example app: `API.md` §6.2's surface, and §6.1's two benchmark routes.

`hello` is the 1 KB GET that flatters every Rust server and proves little; `echo` reads the
request body and gives it back, which is where Granian loses half its throughput and where
the one-crossing rule of §4.4 has to pay. Both now go through `frontage_api.App` — matching,
binding and the response rules included — so the benchmark measures the surface people would
actually write, not a hand-rolled dispatch.

`stamp` is the smaller point and the one that took longest to be true: a handler that reaches
*outside* its own source, to the environment and to the clock. Until `os` and `datetime`
existed it could not read an API key or date a row, which is the difference between a demo
and a server.

The rest exercise §4.3, the host future hook. `sleeps` awaits a tokio deadline settling a
Python future, which is the shape every native module in §6.4 will use; `loops` awaits the
event loop's own timer; `both` mixes them. `stuck` awaits a future nobody will ever settle,
and must answer 500 rather than hang.

    frontage-api rust/api/examples/spike/app.py --path .     # from the repository root
"""

import asyncio
import os
from datetime import datetime, timezone

import _host
from frontage.schema import integer, optional, record, text
from frontage_api import SSE_DONE, App, HTTPError, Response, Stream, sse

app = App(title="the spike")

PAYLOAD = "x" * 1024
Trip = record(("id", integer(ge=0)), ("note", optional(text()), None))
TRIPS = {1: {"id": 1, "note": "north"}, 2: {"id": 2, "note": None}}


@app.get("/hello")
async def hello():
    return Response(PAYLOAD, media_type="text/plain; charset=utf-8")


@app.post("/echo", body=bytes)
async def echo(body):
    return body


@app.get("/trips/{trip_id}")
async def trip(trip_id: int):
    row = TRIPS.get(trip_id)
    if row is None:
        raise HTTPError(404, "no such trip")
    return row


@app.post("/trips")
async def create(body: Trip):
    TRIPS[body["id"]] = body
    return {"stored": body["id"]}


@app.get("/search")
async def search(q: str = "", n: int = 10):
    return {"q": q, "n": n}


@app.get("/sleeps")
async def sleeps():
    await _host.sleep(0.01)
    return "slept on a tokio deadline"


@app.get("/loops")
async def loops():
    await asyncio.sleep(0.01)
    return "slept on the event loop"


@app.get("/both")
async def both():
    await asyncio.sleep(0.005)
    await _host.sleep(0.005)
    return "both"


@app.get("/stuck")
async def stuck():
    await asyncio.get_event_loop().create_future()
    return "unreachable"


@app.get("/feed")
async def feed():
    """A sync generator: the shape that works on this runtime today."""

    def frames():
        for i in range(5):
            yield sse({"n": i})
        yield SSE_DONE

    return Stream(frames(), media_type="text/event-stream")


@app.get("/slowfeed")
async def slowfeed():
    """A producer that awaits between pieces, which a plain generator cannot do here."""

    async def produce(send):
        for i in range(3):
            await _host.sleep(0.02)
            await send(sse({"n": i}))
        await send(SSE_DONE)

    return Stream(produce, media_type="text/event-stream")


@app.get("/stamp")
async def stamp():
    """The environment and the clock, from inside a handler."""
    now = datetime.now(timezone.utc)
    return {
        "key": os.getenv("FRONTAGE_API_KEY", "unset"),
        "at": now.isoformat(),
        "day": now.strftime("%A"),
        "year": now.year,
    }
