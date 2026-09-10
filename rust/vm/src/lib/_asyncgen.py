"""The awaitable behind an async generator's `__anext__`.

`async def` with a `yield` in it makes an *async generator*: both `await` and `yield` suspend
the same frame, so something has to tell them apart. The VM records which opcode suspended it
(`_async_yielded`), and this walks the frame until it yields a value, passing anything it
awaited up to whoever is driving us.

It is Python, not Rust, for one reason: propagating an inner `await` means `yield`ing it, and
only a generator function can do that. `__await__` is exactly that.
"""


class ANext:
    """`await agen.__anext__()`: the next item, or `StopAsyncIteration`."""

    def __init__(self, agen):
        self.agen = agen

    def __await__(self):
        agen = self.agen
        sent = None
        while True:
            try:
                value = agen.send(sent)
            except StopIteration:
                raise StopAsyncIteration from None
            if agen._async_yielded():
                return value
            # It awaited something: hand it up, and hand the answer back down.
            sent = yield value
