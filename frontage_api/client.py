"""Talking to something else: the client half of the server (`API.md` §6.4).

    from frontage_api.client import Client

    models = Client("https://api.anthropic.com", headers=[("x-api-key", key)])

    @app.post("/ask")
    async def ask(body):
        answer = await models.post("/v1/messages", json=body)
        return answer.json()

and the same call with `stream=True` gives a response whose body arrives in pieces, which is
what a model's tokens are:

    async with await models.post("/v1/messages", json=body, stream=True) as answer:
        async for line in answer.lines():
            await send(line)

**This is `_http` over reqwest, not a socket library.** One connection pool per worker
thread, kept between requests — a handler that forwards to a model reuses the TLS session
rather than shaking hands per token. Nothing here is available in the browser: a page has
`fetch`, which is a different shape and a different trust boundary.

⚠ **A streamed response holds a connection until it is closed.** Read it to the end or use
`async with`; an abandoned one keeps the transfer alive until the peer gives up.
"""

import json as _json

try:
    import _http
except ImportError:  # pragma: no cover - the browser, or a runtime without the module
    _http = None

__all__ = ["Client", "HttpError", "Response", "delete", "get", "post", "put", "request"]

#: What a request without a timeout of its own gets. A handler that waits forever holds a
#: worker's turn forever, so the default is a number rather than `None`.
DEFAULT_TIMEOUT = 30.0


class HttpError(Exception):
    """A response `raise_for_status()` refused. It carries the response, because the body of
    a 4xx is where the reason is."""

    def __init__(self, response):
        self.response = response
        self.status = response.status
        Exception.__init__(self, str(response.status) + " for " + response.url)


class Response:
    """What a request answered. `body` is the bytes for a whole response; a streamed one has
    `body is None` and gives its pieces through `chunks()` or `lines()`."""

    def __init__(self, url, status, headers, body=None, token=None):
        self.url = url
        self.status = status
        self.headers = headers
        self.body = body
        self._token = token
        self._closed = False

    @property
    def ok(self):
        return 200 <= self.status < 300

    def header(self, name, default=None):
        lower = name.lower()
        for key, value in self.headers:
            if key.lower() == lower:
                return value
        return default

    def raise_for_status(self):
        if not self.ok:
            raise HttpError(self)
        return self

    def text(self):
        if self.body is None:
            raise ValueError("this response is streamed: read chunks() or lines()")
        return self.body.decode("utf-8")

    def json(self):
        return _json.loads(self.text())

    # -- the streamed form ----------------------------------------------------------------

    @property
    def streaming(self):
        return self._token is not None

    async def chunks(self):
        """The body as it arrives. Each piece is whatever the transfer gave us, so a piece is
        not a line and not a frame — `lines()` is the one that respects boundaries."""
        if self._token is None:
            raise ValueError("this response is not streamed: read body")
        while True:
            piece = await _http.chunk(self._token)
            if piece is None:
                self._closed = True
                return
            yield piece

    async def lines(self):
        """The body split on newlines, decoded. A chunk boundary lands anywhere, so a partial
        line is held until the rest of it arrives — which is the whole reason this exists and
        the bug every hand-rolled SSE reader has."""
        rest = b""
        async for piece in self.chunks():
            rest = rest + piece
            while True:
                cut = rest.find(b"\n")
                if cut < 0:
                    break
                line = rest[:cut]
                rest = rest[cut + 1 :]
                if line.endswith(b"\r"):
                    line = line[:-1]
                yield line.decode("utf-8")
        if rest:
            yield rest.decode("utf-8")

    async def close(self):
        if self._token is not None and not self._closed:
            _http.close(self._token)
            self._closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()
        return False


def _query(url, params):
    if not params:
        return url
    pairs = params.items() if hasattr(params, "items") else params
    parts = []
    for name, value in pairs:
        if value is None:
            continue
        parts.append(_quote(str(name)) + "=" + _quote(_plain(value)))
    if not parts:
        return url
    return url + ("&" if "?" in url else "?") + "&".join(parts)


def _plain(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"


def _quote(text):
    out = []
    for byte in text.encode("utf-8"):
        char = chr(byte)
        out.append(char if char in SAFE else "%%%02X" % byte)
    return "".join(out)


class Client:
    """A base URL, headers every request carries, and a timeout. Holding one is what keeps a
    connection open between calls; making one per request is not wrong, only slower."""

    def __init__(self, base="", headers=None, timeout=DEFAULT_TIMEOUT):
        self.base = base.rstrip("/")
        self.headers = list(headers or [])
        self.timeout = timeout

    def url(self, path):
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return self.base + ("" if path.startswith("/") else "/") + path

    async def request(self, method, path, params=None, headers=None, json=None, data=None, timeout=False, stream=False):
        if _http is None:
            raise RuntimeError("_http is not available on this runtime")
        url = _query(self.url(path), params)
        out = list(self.headers)
        body = None
        if json is not None:
            if data is not None:
                raise ValueError("request(): json= and data= are exclusive")
            body = _json.dumps(json).encode("utf-8")
            if not _named(out, headers, "content-type"):
                out.append(("content-type", "application/json"))
        elif data is not None:
            body = data.encode("utf-8") if isinstance(data, str) else data
        out.extend(headers or [])
        # `timeout=False` is "the client's", `timeout=None` is "no timeout at all". Two
        # different answers, and `None` cannot mean both.
        wait = self.timeout if timeout is False else timeout
        status, got, rest = await _http.request(method.upper(), url, out, body, wait, stream)
        if stream:
            return Response(url, status, got, None, rest)
        return Response(url, status, got, rest)

    async def get(self, path, **kw):
        return await self.request("GET", path, **kw)

    async def post(self, path, **kw):
        return await self.request("POST", path, **kw)

    async def put(self, path, **kw):
        return await self.request("PUT", path, **kw)

    async def patch(self, path, **kw):
        return await self.request("PATCH", path, **kw)

    async def delete(self, path, **kw):
        return await self.request("DELETE", path, **kw)


def _named(existing, extra, name):
    for key, _ in list(existing) + list(extra or []):
        if key.lower() == name:
            return True
    return False


#: One client for the module-level calls, so `get(url)` still reuses a connection.
_shared = Client()


async def request(method, url, **kw):
    return await _shared.request(method, url, **kw)


async def get(url, **kw):
    return await _shared.request("GET", url, **kw)


async def post(url, **kw):
    return await _shared.request("POST", url, **kw)


async def put(url, **kw):
    return await _shared.request("PUT", url, **kw)


async def delete(url, **kw):
    return await _shared.request("DELETE", url, **kw)
