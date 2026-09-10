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
from frontage_api.client import Client, HttpError

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


# -- `_http`: a handler that talks to something else (`API.md` §6.4) ---------------------
#
# The peer is this same server, so the test needs no network and no second process — and the
# three routes below are exactly `frontage.chat`'s shape: hold a key, forward a body, relay
# an answer token by token.

SELF = Client(os.getenv("FRONTAGE_API_SELF", "http://127.0.0.1:8791"), timeout=5.0)


@app.get("/fetch")
async def fetch():
    """A whole response, read at once."""
    answer = await SELF.get("/hello")
    return {"status": answer.status, "len": len(answer.body), "type": answer.header("content-type")}


@app.post("/forward", body=bytes)
async def forward(body):
    """A body out and the same body back, which is what a proxy is."""
    answer = await SELF.post("/echo", data=body)
    return Response(answer.body, media_type="application/octet-stream")


@app.get("/relay")
async def relay():
    """The whole point: a streamed answer re-emitted as it arrives, not collected first."""

    async def produce(send):
        answer = await SELF.get("/slowfeed", stream=True)
        async with answer:
            async for line in answer.lines():
                if line:
                    await send(line + "\n\n")

    return Stream(produce, media_type="text/event-stream")


@app.get("/unreachable")
async def unreachable():
    """A connection that cannot be made is an OSError, not a hang and not a 500."""
    try:
        await SELF.get("http://127.0.0.1:9/nothing", timeout=1.0)
    except OSError as exc:
        return {"failed": True, "why": str(exc)[:40]}
    return {"failed": False}


@app.get("/refused")
async def refused():
    """`raise_for_status` carries the response, because the body of a 404 is the reason."""
    try:
        (await SELF.get("/nope")).raise_for_status()
    except HttpError as exc:
        return {"status": exc.status, "body": exc.response.text()[:20]}
    return {"status": 0}
