"""The spike's routes (`PLAN.md` §6.1), shaped like Granian's benchmark app.

`hello` is the 1 KB GET that flatters every Rust server and proves little; `echo` reads the
request body and gives it back, which is where Granian loses half its throughput
(125,539 to 63,181 requests/s) and where the one-crossing rule of §4.4 has to pay.

The rest exercise §4.3, the host future hook. `sleeps` awaits a tokio deadline settling a
Python future, which is the shape every native module in §6.4 will use; `loops` awaits the
event loop's own timer; `both` mixes them. `stuck` awaits a future nobody will ever settle,
and must answer 500 rather than hang.

Every handler takes the body as `bytes` and returns `str` or `bytes`. `echo` is `async def`
on purpose: a coroutine that never suspends must cost one resume and no loop turn.
"""

import asyncio

import _host

PAYLOAD = "x" * 1024


def hello(body):
    return PAYLOAD


async def echo(body):
    return body


async def sleeps(body):
    await _host.sleep(0.01)
    return b"slept on a tokio deadline"


async def loops(body):
    await asyncio.sleep(0.01)
    return b"slept on the event loop"


async def both(body):
    await asyncio.sleep(0.005)
    await _host.sleep(0.005)
    return b"both"


async def stuck(body):
    await asyncio.get_event_loop().create_future()
    return b"unreachable"


ROUTES = {
    "/hello": hello,
    "/echo": echo,
    "/sleeps": sleeps,
    "/loops": loops,
    "/both": both,
    "/stuck": stuck,
}
