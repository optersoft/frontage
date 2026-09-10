"""The same routes as `../examples/spike/app.py`, on FastAPI: the comparison `API.md` §6.1
sets its gate against, and §6.2 measures its surface against.

`/trips` is the interesting one. Pydantic's validator is compiled Rust; `frontage.schema` is
pure Python on our own VM. That axis should favour pydantic, and the number is worth having
either way — what is being compared is the whole request, not the validator.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

app = FastAPI()
PAYLOAD = b"x" * 1024
TRIPS = {1: {"id": 1, "note": "north"}, 2: {"id": 2, "note": None}}


class Trip(BaseModel):
    id: int = Field(ge=0)
    note: str | None = None


@app.get("/hello")
async def hello():
    return Response(PAYLOAD, media_type="text/plain; charset=utf-8")


@app.post("/echo")
async def echo(request: Request):
    return Response(await request.body(), media_type="application/octet-stream")


@app.get("/trips/{trip_id}")
async def trip(trip_id: int):
    row = TRIPS.get(trip_id)
    if row is None:
        raise HTTPException(404, "no such trip")
    return row


@app.post("/trips")
async def create(body: Trip):
    TRIPS[body.id] = body.model_dump()
    return {"stored": body.id}


@app.get("/search")
async def search(q: str = "", n: int = 10):
    return {"q": q, "n": n}
