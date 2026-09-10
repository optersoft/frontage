"""The same two routes on FastAPI: the comparison `PLAN.md` §6.1 sets its gate against."""

from fastapi import Request
from fastapi.responses import Response

from fastapi import FastAPI

app = FastAPI()
PAYLOAD = b"x" * 1024


@app.get("/hello")
async def hello():
    return Response(PAYLOAD, media_type="application/octet-stream")


@app.post("/echo")
async def echo(request: Request):
    return Response(await request.body(), media_type="application/octet-stream")
