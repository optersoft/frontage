"""`async def` with a `yield`: an async generator, and `async for` over it.

Both `await` and `yield` suspend the same frame, so the interesting cases are the ones that
mix them — a generator that awaits between items, one that never awaits at all, and one that
is stopped early.
"""

import asyncio


async def ticker(n):
    for i in range(n):
        await asyncio.sleep(0)
        yield i


async def plain():
    yield "a"
    yield "b"


async def pairs():
    yield ("x", 1)
    await asyncio.sleep(0)
    yield ("y", 2)


async def main():
    out = []
    async for v in ticker(3):
        out.append(v)
    print("awaits between items:", out)

    out = []
    async for v in plain():
        out.append(v)
    print("never awaits:", out)

    # (an async comprehension is a separate gap the compiler still rejects outright)
    print("mixed:", await collect(pairs()))

    # Stopped early: the rest of the generator is simply never asked for.
    seen = []
    async for v in ticker(10):
        seen.append(v)
        if len(seen) == 2:
            break
    print("stopped early:", seen)

    # The protocol by hand.
    agen = plain()
    print("aiter is self:", agen.__aiter__() is agen)
    print("first:", await agen.__anext__())
    print("second:", await agen.__anext__())
    try:
        await agen.__anext__()
    except StopAsyncIteration:
        print("exhausted: StopAsyncIteration")


async def collect(agen):
    out = []
    async for v in agen:
        out.append(v)
    return out


asyncio.run(main())
