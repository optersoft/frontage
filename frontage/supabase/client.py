"""The client: a base URL, a key, a token, and the four verbs.

There is no JavaScript here and no Supabase library. Supabase's data API *is* PostgREST, which
is HTTP and JSON, and the browser already has `fetch` — so the same object talks to a Supabase
project or to a PostgREST you host yourself by changing one URL.

`Result` rather than a bare list, because `Content-Range` carries the total row count and a grid
that cannot see it has to guess how far it scrolls.
"""

import json

from frontage import Resource, Signal
from frontage.runtime import to_js, window

from .query import PostgrestError, Query

__all__ = ["Auth", "Client", "PostgrestError", "Result", "Table"]


class Result:
    """Rows, and how many there are in the table behind them.

    `count` is `None` unless the query asked — PostgREST only counts when told, because on a
    large table it is a second scan.
    """

    def __init__(self, rows, count=None, status=200):
        self.rows = rows
        self.count = count
        self.status = status

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        return self.rows[index]

    def __repr__(self):
        return f"<Result {len(self.rows)} rows of {self.count if self.count is not None else '?'}>"


def _total(content_range):
    """`0-24/573` -> 573. `*/*` and a missing header mean "not counted"."""
    if not content_range or "/" not in content_range:
        return None
    total = content_range.rsplit("/", 1)[1]
    return None if total in ("", "*") else int(total)


class Table:
    """`client.table("cities")`. Reads build a `Query`; writes are awaited directly."""

    def __init__(self, client, name):
        self._client = client
        self._name = name

    def __getattr__(self, attr):
        # Every read-side builder lives on Query, so `table.eq(...)` starts one rather than
        # making the caller write `table.select().eq(...)` when they wanted every column.
        return getattr(Query(self._name), attr)

    def select(self, columns="*"):
        return Query(self._name).select(columns)

    # -- writes -------------------------------------------------------------------------------

    async def insert(self, rows, returning=True):
        """One dict or a list of them. Returns the inserted rows, which is how you learn the
        ids and anything a default or a trigger filled in."""
        return await self._client.run(self._write("POST", rows, returning))

    async def upsert(self, rows, on_conflict=None, returning=True):
        query = self._write("POST", rows, returning)._prefer("resolution=merge-duplicates")
        if on_conflict:
            query = query._param("on_conflict", on_conflict)
        return await self._client.run(query)

    def update(self, values, returning=True):
        """Returns a `Query` rather than a coroutine, because an UPDATE without a filter is a
        mistake you make once: `table.update({...}).eq("id", 3)` reads in the order it happens,
        and the request is not sent until it is awaited."""
        return self._write("PATCH", values, returning)

    def delete(self, returning=True):
        return self._write("DELETE", None, returning)

    def _write(self, method, body, returning):
        query = Query(self._name, method=method, body=body)
        return query._prefer("return=representation" if returning else "return=minimal")


class Auth:
    """GoTrue, the part a browser-only app needs: get a JWT, keep it, drop it.

    The session is a signal, so a page reads `auth.user()` in a hole and the header updates
    itself when someone signs in. What this deliberately does not do is refresh the token on a
    timer — see the README; a component that silently re-authenticates in the background is a
    thing an app should opt into, not inherit.
    """

    def __init__(self, client):
        self._client = client
        self.session = Signal(None)

    def user(self):
        session = self.session()
        return session.get("user") if session else None

    def token(self):
        session = self.session()
        return session.get("access_token") if session else None

    async def sign_in(self, email, password):
        session = await self._grant("password", {"email": email, "password": password})
        self.session.set(session)
        return session

    async def sign_up(self, email, password):
        body = json.dumps({"email": email, "password": password})
        session = await self._client.request("POST", "/auth/v1/signup", body=body, base="")
        # A project with email confirmation on answers with a user and no token, which is not
        # a failure and must not look like one.
        if session and session.get("access_token"):
            self.session.set(session)
        return session

    async def sign_out(self):
        token = self.token()
        if token:
            await self._client.request("POST", "/auth/v1/logout", base="", token=token, parse=False)
        self.session.set(None)

    async def _grant(self, grant_type, payload):
        return await self._client.request(
            "POST", "/auth/v1/token?grant_type=" + grant_type, body=json.dumps(payload), base=""
        )


class Client:
    """A Supabase project, or any PostgREST.

    `url` is the project URL (`https://<ref>.supabase.co`) or the PostgREST root. `key` is the
    **anonymous** key. Never the service key: it bypasses row-level security by design, and a
    browser is a place anyone can read.
    """

    def __init__(self, url, key=None, token=None, schema=None, rest="/rest/v1"):
        self.url = url.rstrip("/")
        self.key = key
        self.rest = rest
        self.schema = schema
        self._token = Signal(token)
        self.auth = Auth(self)

    def table(self, name):
        return Table(self, name)

    def set_token(self, token):
        """Use this JWT from now on. Reactive, so a `Resource` built on this client refetches
        when someone signs in — which is the behaviour you want, since row-level security will
        return different rows."""
        self._token.set(token)

    def token(self):
        return self.auth.token() or self._token()

    # -- requests -----------------------------------------------------------------------------

    def headers(self, extra=None, token=None):
        headers = {"Accept": "application/json"}
        if self.key:
            headers["apikey"] = self.key
        bearer = token or self.token() or self.key
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        if self.schema:
            headers["Accept-Profile"] = self.schema
            headers["Content-Profile"] = self.schema
        headers.update(extra or {})
        return headers

    async def _send(self, method, url, headers, body):
        """The one place this package touches the network.

        A non-2xx does not raise in `fetch` — it answers with `ok` false — so the check is
        explicit. A request that never reached the server raises out of `fetch` itself and is
        deliberately left to propagate as it is: "the network is down" and "the database
        refused you" must not arrive as the same exception, because only one of them is worth
        retrying.
        """
        options = {"method": method, "headers": headers}
        if body is not None:
            headers["Content-Type"] = "application/json"
            options["body"] = body
        response = await window.fetch(url, to_js(options))
        text = await response.text()
        if not response.ok:
            try:
                payload = json.loads(text) if text else {}
            except (ValueError, TypeError):
                payload = text
            raise PostgrestError(response.status, payload, url)
        return response, (json.loads(text) if text else None)

    async def request(self, method, path, body=None, headers=None, token=None, parse=True, base=None):
        """One call against the project, for the routes that are not PostgREST — `/auth/v1/*`.

        `base` replaces the REST prefix; pass `""` to address the project root.
        """
        url = self.url + (self.rest + "/" if base is None else base) + path
        _, data = await self._send(method, url, self.headers(headers, token), body)
        return data if parse else None

    async def run(self, query, token=None):
        """Execute a `Query`: a `Result`, or the row itself for `one()`."""
        return await self._run(query, self.headers(query.headers, token))

    async def _run(self, query, headers):
        url = self.url + self.rest + "/" + query.path
        body = json.dumps(query.body) if query.body is not None else None
        response, data = await self._send(query.method, url, headers, body)
        if query.single:
            return data
        rows = data if isinstance(data, list) else ([] if data is None else [data])
        return Result(rows, _total(response.headers.get("content-range")), response.status)

    def resource(self, build, initial=None):
        """A `Resource` over a query that may change.

        `build` is called inside the tracking phase and returns a `Query`, so any signal it
        reads becomes a dependency: write to the search box and the query is rebuilt, compared
        by URL, and refetched only if it actually differs. The token is read here too, so
        signing in refetches everything — which it must, because row-level security will answer
        differently.
        """

        def source():
            # The headers are built *here*, in the tracked phase, and handed to the fetcher —
            # which therefore reads no signal at all. Two reasons, and the second is not
            # obvious: signing in must refetch, because row-level security will answer
            # differently; and a signal read inside the fetcher, after its first await, is not
            # a dependency — the framework warns about exactly this, and the read would have
            # been a lie rather than a subscription.
            query = build()
            return (query, self.headers(query.headers))

        async def load(pair):
            return await self._run(pair[0], pair[1])

        return Resource(load, source=source, initial=initial)
