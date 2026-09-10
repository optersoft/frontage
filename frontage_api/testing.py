"""A client with no server under it.

    from frontage_api.testing import Client

    client = Client(app)
    answer = client.get("/trips/42")
    assert answer.status == 200
    assert answer.json()["id"] == 42

`App.handle` is the whole of what a server calls, so a test calls the same thing and there is
no socket, no port and no process anywhere in a test run. This is the piece of FastAPI the
fleet's own server code actually leans on — `frontage.chat` and `frontage.remote` have 22
tests through `TestClient` between them — and it costs a page of code here because the seam
was designed to be callable.

Runs on CPython and on frontage's own runtime: `asyncio.run` is in both.
"""

import asyncio
import json as _json

__all__ = ["Client", "Answer"]


class Answer:
    """One response: the status, the headers, the body, and `json()` when it is JSON."""

    def __init__(self, status, headers, body):
        self.status = status
        self.headers = list(headers)
        self.body = body

    def header(self, name):
        name = name.lower()
        for key, value in self.headers:
            if key.lower() == name:
                return value
        return None

    def json(self):
        return _json.loads(self.body.decode("utf-8"))

    def text(self):
        return self.body.decode("utf-8")

    def __repr__(self):
        return "<Answer %s %r>" % (self.status, self.body[:60])


class Client:
    def __init__(self, app):
        self.app = app

    def request(self, method, path, body=None, json=None, headers=None):
        if json is not None:
            body = _json.dumps(json).encode("utf-8")
        if isinstance(body, str):
            body = body.encode("utf-8")
        query = ""
        if "?" in path:
            path, _, query = path.partition("?")
        scope = {
            "method": method.upper(),
            "path": path,
            "query_string": query,
            "headers": list(headers or []),
            "body": body or b"",
        }
        status, out, payload = asyncio.run(self.app.handle(scope))
        return Answer(status, out, payload)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def put(self, path, **kw):
        return self.request("PUT", path, **kw)

    def patch(self, path, **kw):
        return self.request("PATCH", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)
