"""The server half: named polars queries behind a FastAPI router. CPython only.

An app author writes ordinary functions that return a polars frame and registers each under a
name; the browser asks for them by name, with parameters in the query string, and gets back a
small answer — an aggregate as columns, or a window of rows. **The frame never travels.**

    src = Sources()

    @src.query
    def by_hour(day: str):
        return trips.filter(pl.col("date") == day).group_by("hour").len().sort("hour")

    app = src.app(static="www")          # or app.include_router(src.router, prefix="/api")

Three routes, all `GET`, all answering CORS so `frontage serve` on another port and the
opaque-origin runner both work:

    /frame/{name}?params          the whole result, column-oriented, capped at `max_rows`
    /rows/{name}?offset&limit&sort&desc&search&params
                                  a window of rows for a grid: the server pages, sorts, searches
    /events                       Server-Sent Events; `changed(name)` tells every page to refetch

Nothing from the browser is ever evaluated: a name selects a function, and the query string
becomes its arguments, converted by the annotations on its signature. There is no expression,
no SQL, no column list from the client — the surface is exactly the functions the author wrote.

Results are cached per `(name, arguments)` up to `cache` entries, and a window is cut from the
cached frame, so scrolling a grid never re-runs the query. `changed(name)` drops the cache for
that name and notifies the pages; `changed()` with no name drops everything.
"""

import asyncio
import inspect
import json
import threading
from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import polars as pl
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

__all__ = ["Sources"]

MAX_LIMIT = 1_000  # rows per window; a grid shows ~20 and asks for a few times that
DEFAULT_MAX_ROWS = 100_000  # a frame past this is not an answer, it is the dataset
CORS = {"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"}
HEARTBEAT = 15.0  # seconds between SSE comments, so a proxy does not close an idle stream


class _Source:
    def __init__(self, name, fn):
        self.name = name
        self.fn = fn
        self.params = {}
        for p in inspect.signature(fn).parameters.values():
            if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                raise TypeError(f"{name}: *args/**kwargs cannot come from a query string")
            self.params[p.name] = p

    def arguments(self, query):
        """The function's keyword arguments from a query string: converted by annotation,
        defaulted, and refused when unknown or missing."""
        kwargs = {}
        for key in query:
            if key not in self.params:
                raise HTTPException(400, f"{self.name} takes no parameter {key!r}")
        for name, p in self.params.items():
            if name in query:
                kwargs[name] = _convert(query[name], p.annotation, name)
            elif p.default is not p.empty:
                kwargs[name] = p.default
            else:
                raise HTTPException(400, f"{self.name} needs {name!r}")
        return kwargs


def _convert(text, annotation, name):
    try:
        if annotation is int:
            return int(text)
        if annotation is float:
            return float(text)
        if annotation is bool:
            return text.lower() in ("1", "true", "yes", "on")
        if annotation is date:
            return date.fromisoformat(text)
        if annotation is datetime:
            return datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(400, f"{name}: {exc}") from None
    return text  # str, or unannotated


def _json_default(value):
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _dumps(payload):
    # NaN and Infinity are not JSON, and MicroPython's parser will not take them.
    return json.dumps(payload, default=_json_default, allow_nan=False, separators=(",", ":"))


def _plain(df):
    """A frame the JSON encoder can take: NaN becomes null, nested types become strings."""
    float_cols = [c for c, t in df.schema.items() if t in (pl.Float32, pl.Float64)]
    if float_cols:
        df = df.with_columns(pl.col(float_cols).fill_nan(None))
    nested = [c for c, t in df.schema.items() if t.is_nested()]
    if nested:
        df = df.with_columns(pl.col(nested).cast(pl.String))
    return df


class Sources:
    def __init__(self, cache=64, max_rows=DEFAULT_MAX_ROWS):
        self._sources = {}
        self._cache = OrderedDict()
        self._cache_size = cache
        self._max_rows = max_rows
        self._lock = threading.Lock()
        self._subscribers = []  # (loop, queue) per open event stream
        self._router = None

    # -- registration -------------------------------------------------------------------------

    def query(self, fn=None, *, name=None):
        """Register `fn` as a named query. Its parameters come from the query string, converted
        by annotation (`str`, `int`, `float`, `bool`, `date`, `datetime`); it returns a
        `DataFrame` or a `LazyFrame`, which is collected once and cached."""

        def register(function):
            key = name or function.__name__
            if key in ("events",) or "/" in key:
                raise ValueError(f"{key!r} cannot name a query")
            self._sources[key] = _Source(key, function)
            return function

        return register(fn) if fn is not None else register

    def names(self):
        return sorted(self._sources)

    # -- results ------------------------------------------------------------------------------

    def frame(self, name, **kwargs):
        """The collected result of a query, from the cache when it is there. Callable from the
        author's own code too, for a route of theirs or a test."""
        source = self._sources.get(name)
        if source is None:
            raise HTTPException(404, f"no query named {name!r}")
        key = (name, tuple(sorted(kwargs.items())))
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
        result = source.fn(**kwargs)
        if isinstance(result, pl.LazyFrame):
            result = result.collect()
        if not isinstance(result, pl.DataFrame):
            raise TypeError(f"{name} returned {type(result).__name__}, not a polars frame")
        result = _plain(result)
        with self._lock:
            self._cache[key] = result
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return result

    def window(self, name, offset=0, limit=100, sort=None, descending=False, search=None, **kwargs):
        """`(total, offset, rows)`: the rows of a query between `offset` and `offset + limit`,
        after an optional sort and a case-insensitive substring search over every column."""
        df = self.frame(name, **kwargs)
        if search:
            needle = search.lower()
            df = df.filter(
                pl.any_horizontal(pl.all().cast(pl.String).str.to_lowercase().str.contains(needle, literal=True))
            )
        if sort:
            if sort not in df.columns:
                raise HTTPException(400, f"{name} has no column {sort!r}")
            df = df.sort(sort, descending=descending, nulls_last=True)
        total = df.height
        offset = max(0, min(offset, total))
        limit = max(0, min(limit, MAX_LIMIT))
        return total, offset, df.slice(offset, limit).to_dicts()

    def changed(self, name=None):
        """The data behind `name` (or everything) moved: drop the cache and tell every page,
        which refetches what it shows from that query. Safe to call from any thread."""
        with self._lock:
            if name is None:
                self._cache.clear()
            else:
                for key in [k for k in self._cache if k[0] == name]:
                    del self._cache[key]
            subscribers = list(self._subscribers)
        message = _dumps({"source": name})
        for loop, queue in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, message)

    # -- the HTTP surface ---------------------------------------------------------------------

    @property
    def router(self):
        """A `fastapi.APIRouter` to include in an app of your own, under any prefix."""
        if self._router is None:
            self._router = self._build_router()
        return self._router

    def app(self, static=None, prefix="/api"):
        """A whole FastAPI app: the router under `prefix`, and if `static` is a directory (what
        `frontage build` wrote), the page itself at `/`. One process, one port. An app with
        routes of its own includes `router` in its own `FastAPI()` instead, and mounts the
        static directory last: Starlette matches in order."""
        app = FastAPI()
        app.include_router(self.router, prefix=prefix)
        if static is not None:
            from fastapi.staticfiles import StaticFiles

            app.mount("/", StaticFiles(directory=str(static), html=True), name="static")
        return app

    def _build_router(self):
        router = APIRouter()
        sources = self

        @router.get("/frame/{name}")
        def frame(name: str, request: Request):
            source = sources._sources.get(name)
            if source is None:
                raise HTTPException(404, f"no query named {name!r}")
            df = sources.frame(name, **source.arguments(dict(request.query_params)))
            if df.height > sources._max_rows:
                raise HTTPException(
                    413,
                    f"{name} has {df.height:,} rows, more than {sources._max_rows:,}: "
                    "aggregate it, or ask for rows with a window",
                )
            payload = {
                "columns": df.columns,
                "dtypes": [str(t) for t in df.dtypes],
                "height": df.height,
                "data": df.to_dict(as_series=False),
            }
            return Response(_dumps(payload), media_type="application/json", headers=CORS)

        @router.get("/rows/{name}")
        def rows(
            name: str,
            request: Request,
            offset: int = 0,
            limit: int = 100,
            sort: str | None = None,
            desc: bool = False,
            search: str | None = None,
        ):
            source = sources._sources.get(name)
            if source is None:
                raise HTTPException(404, f"no query named {name!r}")
            reserved = ("offset", "limit", "sort", "desc", "search")
            query = {k: v for k, v in request.query_params.items() if k not in reserved}
            total, offset, page = sources.window(name, offset, limit, sort, desc, search, **source.arguments(query))
            payload = {"total": total, "offset": offset, "rows": page}
            return Response(_dumps(payload), media_type="application/json", headers=CORS)

        @router.get("/events")
        async def events(request: Request):
            loop = asyncio.get_running_loop()
            queue = asyncio.Queue()
            entry = (loop, queue)
            with sources._lock:
                sources._subscribers.append(entry)

            async def stream():
                try:
                    yield ": connected\n\n"
                    while True:
                        try:
                            message = await asyncio.wait_for(queue.get(), HEARTBEAT)
                        except asyncio.TimeoutError:
                            yield ": ping\n\n"
                            continue
                        yield f"data: {message}\n\n"
                finally:
                    with sources._lock:
                        if entry in sources._subscribers:
                            sources._subscribers.remove(entry)

            headers = dict(CORS, **{"X-Accel-Buffering": "no"})
            return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)

        @router.get("/")
        def index():
            return Response(_dumps({"queries": sources.names()}), media_type="application/json", headers=CORS)

        return router
