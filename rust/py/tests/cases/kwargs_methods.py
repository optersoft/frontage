# Keyword arguments through bound methods, plain and async, positional mixed with keywords.
import asyncio


class C:
    def request(self, method, path, body=None, headers=None, token=None, parse=True, base=None):
        return (method, path, body, headers, token, parse, base)

    async def arequest(self, method, path, body=None, headers=None, token=None, parse=True, base=None):
        await asyncio.sleep(0)
        return (method, path, body, headers, token, parse, base)

    async def grant(self, kind, payload):
        return await self.arequest("POST", "/token?grant=" + kind, body=payload, base="")

    def via_attr(self):
        f = self.request
        return f("GET", "/x", base="", body="b")


c = C()
print(c.request("POST", "/p", body="B", base=""))
print(c.request("GET", "/q", headers={"a": 1}, token="t", parse=False))
print(c.via_attr())
print(asyncio.run(c.arequest("POST", "/p", body="B", base="")))
print(asyncio.run(c.grant("password", {"email": "x"})))


async def gen(a, b=2, *, c=3):
    await asyncio.sleep(0)
    return (a, b, c)


print(asyncio.run(gen(1, c=5)))
print(asyncio.run(gen(1, 7, c=5)))
