"""The spike's two routes (`PLAN.md` §6.1), shaped like Granian's benchmark app.

`hello` is the 1 KB GET that flatters every Rust server and proves little; `echo` reads the
request body and gives it back, which is where Granian loses half its throughput
(125,539 to 63,181 requests/s) and where the one-crossing rule of §4.4 has to pay.

Every handler takes the body as `bytes` and returns `str` or `bytes`. `echo` is `async def`
on purpose: a coroutine that never suspends must cost one resume and no loop turn.
"""

PAYLOAD = "x" * 1024


def hello(body):
    return PAYLOAD


async def echo(body):
    return body


ROUTES = {"/hello": hello, "/echo": echo}
