"""A response written in pieces: Server-Sent Events, a long export, a model's tokens.

    @app.get("/events")
    async def events():
        def frames():
            for i in range(3):
                yield sse({"n": i})
        return Stream(frames(), media_type="text/event-stream")

`Stream` takes whatever can produce chunks:

- an **iterable or generator** — the common case, and the one that works on this runtime today;
- a **callable taking `send`** — `async def produce(send): await send(chunk)` — for a producer
  that has to await between pieces, which a plain generator cannot do here;
- an **async iterable** (`__aiter__`/`__anext__`), once the runtime grows async generators.

The server pulls one chunk at a time and writes it, so nothing buffers the whole answer, and
a producer that awaits parks the same way a handler does.

⚠ **`x-accel-buffering: no` and `cache-control: no-cache` go on by default for
`text/event-stream`.** Without them a reverse proxy holds the whole stream and delivers it in
one lump, which looks exactly like a model that does not stream — a bug that only appears once
there is a proxy in front, which is to say in production and not in a test.
"""

import json as _json

__all__ = ["Stream", "sse", "SSE_DONE"]

SSE_TYPE = "text/event-stream"
SSE_DONE = "data: [DONE]\n\n"


def sse(payload):
    """One Server-Sent Events frame. The payload is JSON, so a newline inside it survives:
    raw text would be split across two `data:` lines and the break would be lost."""
    return "data: " + _json.dumps(payload) + "\n\n"


class Stream:
    """A response whose body arrives in pieces."""

    def __init__(self, source, media_type="text/plain; charset=utf-8", status=200, headers=None):
        self.source = source
        self.media_type = media_type
        self.status = status
        self.headers = list(headers or [])
        if media_type == SSE_TYPE:
            names = [name.lower() for name, _ in self.headers]
            if "cache-control" not in names:
                self.headers.append(("cache-control", "no-cache"))
            if "x-accel-buffering" not in names:
                self.headers.append(("x-accel-buffering", "no"))

    def parts(self):
        return self.status, [("content-type", self.media_type)] + self.headers

    def chunks(self):
        """A `Chunks` over whatever this was given."""
        return Chunks(self.source)


class Chunks:
    """What the server pulls from: `next()`, awaited, giving a chunk or `None` at the end.

    One shape for the server whatever the producer was, so the Rust side knows exactly one
    protocol and every new kind of producer is handled here instead.
    """

    def __init__(self, source):
        self._iter = None
        self._aiter = None
        self._producer = None
        self._task = None
        self._item = None
        self._finished = False
        self._failure = None
        if hasattr(source, "__anext__") or hasattr(source, "__aiter__"):
            self._aiter = source.__aiter__() if hasattr(source, "__aiter__") else source
        elif callable(source):
            self._producer = source
        else:
            self._iter = iter(source)

    async def next(self):
        if self._finished:
            return None
        if self._iter is not None:
            for value in self._iter:
                return _encode(value)
            self._finished = True
            return None
        if self._aiter is not None:
            try:
                value = await self._aiter.__anext__()
            except StopAsyncIteration:
                self._finished = True
                return None
            return _encode(value)
        if self._producer is not None:
            return await self._pull()
        self._finished = True
        return None

    # -- the callable form ---------------------------------------------------------------
    #
    # ⚠ **A rendezvous, not a queue, and the difference is the whole feature.** The first
    # version ran the producer to completion on the first `next()` and handed the pieces out
    # afterwards, which passes every test that checks *what* arrives and none that checks
    # *when*: three 20 ms sleeps delivered four frames at 71 ms, together. So `send` parks
    # until the consumer has taken the chunk, and the producer runs as a task the loop steps.

    async def _pull(self):
        import asyncio

        if self._task is None:
            self._ready = asyncio.Event()
            self._taken = asyncio.Event()
            self._task = asyncio.get_event_loop().create_task(self._run())
        await self._ready.wait()
        self._ready.clear()
        if self._failure is not None:
            failure, self._failure = self._failure, None
            self._finished = True
            raise failure
        if self._finished:
            return None
        item, self._item = self._item, None
        self._taken.set()
        return item

    async def _run(self):
        async def send(chunk):
            self._item = _encode(chunk)
            self._ready.set()
            await self._taken.wait()
            self._taken.clear()

        try:
            result = self._producer(send)
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            # A producer that raises halfway through has already sent bytes, so there is no
            # status left to change. Carry it to the puller, which ends the stream.
            self._failure = exc
        self._finished = True
        self._ready.set()


def _encode(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return _json.dumps(value).encode("utf-8")
