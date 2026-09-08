"""The server half: the process that holds the API key and streams an answer back.

    # server.py
    from frontage.chat.server import Conversation

    chat = Conversation()

    @chat.reply
    async def answer(messages):
        async for chunk in my_model(messages):
            yield chunk

    app = chat.app(static="dist/chat")   # POST /api/chat, and the built page at /

`reply` decorates an **async generator** of text chunks. Whatever it yields reaches the page
as it is yielded, so a model that streams streams, and one that does not simply yields once.

Two things this deliberately does. It **never trusts the conversation it is sent** — the page
is a public directory of static files and anyone can post to this route, so the payload is
checked (roles from a fixed set, a length cap, a turn cap) before your function sees it. And
it keeps **no session**: the whole conversation arrives with every request, which is what lets
this be one stateless process behind any number of pages, and is the reason there is nothing
here to leave running with a growing dictionary of strangers' chats in it.

CPython only; nothing in the page imports this file. `pip install "frontage[chat]"`.
"""

import json

__all__ = ["Conversation", "sse"]

ROLES = ("system", "user", "assistant")
MAX_TURNS = 200
MAX_CHARS = 100_000


def sse(payload):
    """One Server-Sent Events frame. The token is JSON, so a newline in it survives the wire:
    SSE would otherwise split it over two `data:` lines and the break would be lost."""
    return "data: " + json.dumps(payload) + "\n\n"


DONE = "data: [DONE]\n\n"


class ChatRequestError(ValueError):
    """The posted conversation is not one. Answered as 400, with this message."""


def parse(payload, max_turns=MAX_TURNS, max_chars=MAX_CHARS):
    """The turns out of a posted body, or `ChatRequestError`. Public, so a test can call it
    and so an app that mounts its own route can reuse the checking."""
    if not isinstance(payload, dict):
        raise ChatRequestError("the body must be an object")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ChatRequestError("messages must be a non-empty list")
    if len(messages) > max_turns:
        raise ChatRequestError(f"too many turns: {len(messages)} > {max_turns}")
    total = 0
    turns = []
    for i, turn in enumerate(messages):
        if not isinstance(turn, dict):
            raise ChatRequestError(f"turn {i} is not an object")
        role = turn.get("role")
        content = turn.get("content")
        if role not in ROLES:
            raise ChatRequestError(f"turn {i}: role must be one of {', '.join(ROLES)}")
        if not isinstance(content, str):
            raise ChatRequestError(f"turn {i}: content must be a string")
        total += len(content)
        if total > max_chars:
            raise ChatRequestError(f"the conversation is longer than {max_chars} characters")
        turns.append({"role": role, "content": content})
    return turns


class Conversation:
    """One chat endpoint: the reply function, and the app that serves it."""

    def __init__(self, max_turns=MAX_TURNS, max_chars=MAX_CHARS):
        self._reply = None
        self.max_turns = max_turns
        self.max_chars = max_chars

    def reply(self, fn):
        """Register the async generator that answers. Returns it, so it is a decorator."""
        self._reply = fn
        return fn

    async def stream(self, payload):
        """The frames for one posted body, as an async generator of strings. The transport is
        separate from the route so a test can read the stream without a server, and so an app
        with its own FastAPI can mount this anywhere."""
        if self._reply is None:
            raise RuntimeError("no reply function: decorate one with @chat.reply")
        turns = parse(payload, self.max_turns, self.max_chars)
        async for chunk in self._reply(turns):
            if chunk:
                yield sse(chunk)
        yield DONE

    def router(self, path="/api/chat"):
        """A FastAPI router with the one POST route on it."""
        from fastapi import APIRouter, Request
        from fastapi.responses import JSONResponse, StreamingResponse

        router = APIRouter()

        @router.post(path)
        async def post(request: Request):
            try:
                payload = await request.json()
            except ValueError:
                return JSONResponse({"detail": "the body is not JSON"}, status_code=400)
            try:
                parse(payload, self.max_turns, self.max_chars)
            except ChatRequestError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)
            return StreamingResponse(
                self.stream(payload),
                media_type="text/event-stream",
                # Without this a reverse proxy buffers the whole answer and the reader gets it
                # in one lump, which looks exactly like a model that does not stream.
                headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
            )

        return router

    def app(self, path="/api/chat", static=None, cors=None):
        """A FastAPI app: the route, and optionally the built page served beside it.

        `static` is what `frontage build` wrote. Serving both from one process is the simple
        deployment and the one with no CORS in it; `cors` (a list of origins) is for when the
        page is on a static host and this is not.
        """
        from fastapi import FastAPI
        from fastapi.staticfiles import StaticFiles

        app = FastAPI()
        app.include_router(self.router(path))
        if cors:
            from fastapi.middleware.cors import CORSMiddleware

            app.add_middleware(CORSMiddleware, allow_origins=list(cors), allow_methods=["POST"], allow_headers=["*"])
        if static:
            app.mount("/", StaticFiles(directory=static, html=True), name="page")
        return app
