"""The browser half: named server-side queries as reactive values.

    api = remote("/api")
    day = Signal("2014-09-01")
    hourly = api.query("by_hour", day=day)     # a Resource; refetches when `day` changes
    line_chart(lambda: hourly().series("hour", "len"))
    table(api.rows("trips", day=day), columns=[...])   # a grid that asks for windows

A parameter may be a value or an accessor; the accessors are tracked, so a change re-asks the
server and nothing else moves. The answer to `query` is a `Frame` — columns, not a dataframe —
sized by the server's cap, never the dataset. `rows` returns a windowed source for
`frontage.table.table`: the grid asks for the window it shows, sorted and searched on the
server, and the rest of the frame stays there. `series` is the chart's path: the named
columns arrive as float64 typed arrays that the chart's JavaScript draws directly, so a
10,000-point line costs Python nothing — no JSON parse, no list, no copy across the bridge.

When the server's data changes (`Sources.changed(name)`), the event stream this opens bumps a
version signal for that name and every query and grid reading it refetches. Nothing polls.

This module runs on both interpreters. In the browser the transport is `_browser/index.js`,
registered as `remote` by `frontage build`; on CPython pass `fetch=` (an `async (url) ->
(status, text)`) and there is no event stream, which is how the tests drive it.
"""

import json

from frontage import Resource, Signal
from frontage.runtime import CPYTHON, create_proxy, platform

__all__ = ["Frame", "Remote", "RemoteError", "RowSource", "Series", "remote"]

_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"


def _quote(text):
    """Percent-encode a query-string value. No `urllib` on MicroPython, and it is ten lines."""
    out = []
    for byte in str(text).encode("utf-8"):
        char = chr(byte)
        out.append(char if char in _SAFE else "%%%02X" % byte)
    return "".join(out)


def _encode(params):
    parts = []
    for key in sorted(params):  # sorted, so the same arguments make the same URL
        value = params[key]
        if value is None:
            continue
        if value is True or value is False:
            value = "true" if value else "false"
        parts.append(_quote(key) + "=" + _quote(value))
    return "&".join(parts)


def _read(params):
    """Parameter values, reading the accessors among them. Tracked by whoever calls this."""
    return {key: (value() if callable(value) else value) for key, value in params.items()}


def _detail(text):
    """The server's message out of a FastAPI error body, or the body itself."""
    try:
        return json.loads(text).get("detail", text)
    except (ValueError, AttributeError):
        return text


class RemoteError(Exception):
    """A non-200 answer: `.status` and the server's message."""

    def __init__(self, status, message):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class Frame:
    """The answer to `query`: column names, dtypes as strings, and a list per column."""

    def __init__(self, payload):
        self.columns = list(payload["columns"])
        self.dtypes = list(payload.get("dtypes", []))
        self.height = payload["height"]
        self._data = payload["data"]
        self._rows = None

    def __len__(self):
        return self.height

    def __getitem__(self, name):
        return self._data[name]

    def column(self, name):
        return self._data[name]

    def series(self, *names):
        """`[x, y1, …]`, what `frontage.chart` draws: the named columns, in that order."""
        return [self._data[name] for name in names]

    def rows(self):
        """The frame as a list of dicts, built once."""
        if self._rows is None:
            columns = self.columns
            self._rows = [dict(zip(columns, values)) for values in zip(*[self._data[c] for c in columns])]  # noqa: B905  (MicroPython zip has no strict)
        return self._rows

    def __iter__(self):
        return iter(self.rows())

    def __repr__(self):
        return f"Frame({self.height} rows, columns={self.columns})"


class Series:
    """The answer to `series`: `columns` (names), `height`, and `data` — one float64 column per
    name, in that order. In the browser `data` is a JavaScript array of `Float64Array`s the
    chart takes as it is; on CPython it is a list of lists, decoded with `struct`."""

    def __init__(self, columns, height, data):
        self.columns = list(columns)
        self.height = height
        self.data = data

    def __len__(self):
        return self.height

    def __repr__(self):
        return f"Series({self.height} rows, columns={self.columns})"


def decode_series(payload):
    """`(data, height)` from the bytes `/series/` answers, on CPython (the browser decodes in
    JavaScript and never brings the bytes into Python)."""
    import struct

    columns, height = struct.unpack_from("<II", payload, 0)
    data = []
    for c in range(columns):
        data.append(list(struct.unpack_from(f"<{height}d", payload, 8 + c * height * 8)))
    return data, height


async def _get_series_browser(url):
    import remote as _js  # ty: ignore[unresolved-import]

    request = _js.getSeries(url)
    try:
        response = await request.promise
    except BaseException:
        request.abort()
        raise
    return int(response.status), str(response.text), response.series, int(response.height)


async def _get_browser(url):
    import remote as _js  # ty: ignore[unresolved-import]  # the JavaScript half, registered by the build; absent on CPython

    request = _js.get(url)
    try:
        response = await request.promise
    except BaseException:  # cancelled by the owner: stop the request too
        request.abort()
        raise
    return int(response.status), str(response.text)


class Remote:
    def __init__(self, base, events=True, fetch=None, fetch_bytes=None):
        self._base = base.rstrip("/")
        self._fetch = fetch or _get_browser
        self._fetch_bytes = fetch_bytes  # CPython only: `async (url) -> (status, bytes)`
        self._events = events
        self._close = None
        self._versions = {}  # query name -> Signal, bumped by an event for that name

    # -- the reactive surface -----------------------------------------------------------------

    def query(self, name, **params):
        """A `Resource` of the `Frame` the named query answers; refetches when a parameter's
        accessor changes or the server says the query's data did."""
        version = self._version(name)

        def source():
            return (self.url("/frame/" + name, _read(params)), version())

        async def load(argument):
            return Frame(await self._json(argument[0]))

        self._listen()
        return Resource(load, source=source)

    def series(self, name, *columns, **params):
        """A `Resource` of a `Series`: the named columns of the query as float64, for a chart.
        `line_chart(lambda: s().data)` draws them with no value passing through Python."""
        if not columns:
            raise TypeError("series wants the columns to fetch: series('daily', 'day', 'trips')")
        version = self._version(name)
        names = list(columns)

        def source():
            args = _read(params)
            args["columns"] = ",".join(names)
            return (self.url("/series/" + name, args), version())

        async def load(argument):
            return await self._series(argument[0], names)

        self._listen()
        return Resource(load, source=source)

    def rows(self, name, **params):
        """A windowed source over the named query, for `frontage.table.table`."""
        self._listen()
        return RowSource(self, name, params)

    def close(self):
        if self._close is not None:
            self._close()
            self._close = None

    # -- plumbing -----------------------------------------------------------------------------

    def url(self, path, params=None):
        query = _encode(params) if params else ""
        return self._base + path + ("?" + query if query else "")

    async def _json(self, url):
        status, text = await self._fetch(url)
        if status != 200:
            raise RemoteError(status, _detail(text))
        return json.loads(text)

    async def _series(self, url, names):
        if platform == CPYTHON:
            if self._fetch_bytes is None:
                raise RemoteError(0, "no binary transport on CPython: pass fetch_bytes= to remote()")
            status, payload = await self._fetch_bytes(url)
            if status != 200:
                raise RemoteError(status, _detail(payload.decode("utf-8", "replace")))
            data, height = decode_series(payload)
            return Series(names, height, data)
        status, text, data, height = await _get_series_browser(url)
        if status != 200:
            raise RemoteError(status, _detail(text))
        return Series(names, height, data)

    def _version(self, name):
        signal = self._versions.get(name)
        if signal is None:
            signal = self._versions[name] = Signal(0)
        return signal

    def _listen(self):
        if self._close is not None or not self._events or platform == CPYTHON:
            return
        import remote as _js  # ty: ignore[unresolved-import]

        self._close = _js.subscribe(self._base + "/events", create_proxy(self._on_event))

    def _on_event(self, text):
        try:
            payload = json.loads(str(text))
        except ValueError:
            return
        name = payload.get("source") if hasattr(payload, "get") else None
        names = [name] if name is not None else list(self._versions)
        for key in names:
            signal = self._versions.get(key)
            if signal is not None:
                signal.set(signal.peek() + 1)


class RowSource:
    """What `table` needs: `key()` is tracked and changes when the rows should be re-asked;
    `window(key, offset, limit, sort, descending, search)` fetches one window."""

    def __init__(self, remote, name, params):
        self._remote = remote
        self.name = name
        self._params = params

    def key(self):
        return (self._remote.url("/rows/" + self.name, _read(self._params)), self._remote._version(self.name)())

    async def window(self, key, offset, limit, sort=None, descending=False, search=None):
        base = key[0]
        extra = _encode({"offset": offset, "limit": limit, "sort": sort, "desc": descending or None, "search": search})
        url = base + ("&" if "?" in base else "?") + extra
        payload = await self._remote._json(url)
        return payload["total"], payload["offset"], payload["rows"]


def remote(base, events=True, fetch=None, fetch_bytes=None):
    """`Remote(base)`: the client for a `Sources` router mounted at `base`."""
    return Remote(base, events=events, fetch=fetch, fetch_bytes=fetch_bytes)
