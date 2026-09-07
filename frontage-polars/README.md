# frontage-polars

Big datasets for [frontage](https://github.com/optersoft/frontage) apps: **polars on the
server, small answers in the page.** The frame never travels.

```sh
pip install frontage-polars            # the browser half, packed into the page by `frontage build`
pip install "frontage-polars[server]"  # the server half: polars, FastAPI, uvicorn
```

## The idea

A frontage app is a directory of static files; this package does not change that. What it adds
is an opt-in server half that an app *points at*: named functions returning polars frames,
behind a FastAPI router. The browser asks for a function by name, with parameters, and gets
back a few kilobytes — an aggregate as columns, or one window of rows for a grid. Nothing from
the browser is evaluated: no expression, no SQL, no column list. The surface is exactly the
functions you wrote.

**Server**, CPython:

```python
import polars as pl
from frontage_polars.server import Sources

trips = pl.scan_parquet("trips.parquet")
src = Sources()


@src.query
def by_hour(borough: str = "all"):
    frame = trips if borough == "all" else trips.filter(pl.col("borough") == borough)
    return frame.group_by("hour").len().sort("hour")


@src.query
def rows(borough: str = "all"):
    return trips.filter(pl.col("borough") == borough)  # the server pages, sorts and searches it


app = src.app(static="www")  # the router at /api, the built page at /
```

**Browser**, MicroPython, in the page:

```python
from frontage_polars import remote
from frontage_chart import bar_chart
from frontage_table import table

api = remote("/api")
borough = Signal("all")

hourly = api.query("by_hour", borough=borough)  # a Resource; refetches when borough changes
bar_chart(lambda: hourly().series("hour", "len"))
table(api.rows("rows", borough=borough), columns=[...])  # asks for the window it shows
```

Change the signal and two requests go out; the chart and the grid update in place. Scroll the
grid and it fetches the next block; click a header or type in the search box and the server
sorts or searches, and the page gets a few dozen rows back.

## What the server does

| route | answer |
|---|---|
| `GET /frame/{name}?params` | the whole result, column-oriented JSON, capped at `max_rows` (100,000) — past that it answers 413, because a frame that size is the dataset, not an answer |
| `GET /series/{name}?columns=a,b&params` | the named columns as float64, binary, behind an 8-byte header: what a chart draws. The page's JavaScript hands the typed arrays to the canvas and **no value ever passes through Python** |
| `GET /rows/{name}?offset&limit&sort&desc&search&params` | one window of rows, sorted and searched on the server; `limit` is capped at 1,000 |
| `GET /events` | Server-Sent Events: `changed(name)` on the server tells every open page to refetch that query |

Parameters come from the query string and are converted by the function's annotations
(`str`, `int`, `float`, `bool`, `date`, `datetime`); an unknown or missing one is a 400.
Results are cached per `(name, arguments)`, and a window is cut from the cached frame, so
scrolling never re-runs the query. `src.changed(name)` drops the cache for that query and
notifies the pages; `src.changed()` drops everything. Every response answers CORS, so
`frontage serve` on another port during development works, and so does the site's
opaque-origin runner.

## A big series for a chart

```python
cumulative = api.series("cumulative", "h", "revenue", borough=borough)   # a Resource of a Series
line_chart(lambda: cumulative().data)                                     # Float64Arrays, drawn as they are
```

`query` answers JSON, which MicroPython parses into lists that then cross into JavaScript for
the canvas. For a few hundred points that is nothing; for 8,784 points it measures 11 ms per
redraw (6 ms of parsing, 5 ms of lists and crossing) and 152 KB. `series` asks for exactly the
columns a chart needs as float64: 140 KB, decoded in 0.007 ms by the JavaScript half into
typed arrays the chart uses without a copy, and Python holds a handle, not a value. Nulls are
NaN, a Date is days since the epoch, and a text column is a 400 — cast it in the query.

## Developing with two servers

```sh
uvicorn server:app --app-dir examples/trips --port 8000           # the server half
frontage serve examples/trips --proxy /api=http://127.0.0.1:8000    # the page, with module swap
```

`frontage serve --proxy` (frontage ≥ 0.9.1) forwards `/api` to uvicorn from the page's own
origin and streams the event stream through, so a save swaps the app's modules in place while
the data keeps coming from polars. Without it, the router's CORS headers make two origins work
too; in production one FastAPI app serves both.

## When the data changes

```python
src.changed("rows")  # after an ingest, a file rewrite, a timer — whatever moved the data
```

The pages holding `api.query("rows", …)` or `api.rows("rows", …)` refetch, and only those.
No polling, no re-run: the event bumps one version signal per query name, and the reactive
graph does the rest.

## Why HTTP and SSE, not a WebSocket

Each interaction is one query and one answer, which is what HTTP is. A WebSocket buys a
session on the server — a frame per client, a process that remembers each page — which is
Streamlit's model and the thing a static-files app avoids. Polars' lazy API makes stateless
re-execution cheap, and a small cache makes it free. Push, the one thing HTTP lacks, is a
Server-Sent Events stream, which is plain HTTP and goes through every proxy.

## Not phoning home

This package makes requests only to the base URL the app named. It is the author's own
server; nothing here contacts anything else.

## Measured

The `examples/trips` dashboard — 500,000 synthetic rows in polars, one borough signal, four
queries (a summary, a daily series, an hourly histogram, a grid over every row) — built with
`frontage build`, served by its own uvicorn, loaded cold in Chromium on localhost:

| | |
|---|---|
| cold to drawn (metrics, chart, first grid rows) | **94 ms** median of 3 |
| page, cold | 17 requests, 780 KB (interpreter + framework + layout, chart, table and this) |
| the four answers | summary 204 B · by_hour 274 B · daily 5.9 KB · one grid window 4.1 KB |
| borough change to updated metric | **15 ms**, four requests, four answers, nothing remounted |

About ten kilobytes of answers for a frame that is thirty megabytes in memory. The numbers
come from `tests/browser/test_trips.py`'s setup run by hand; the suite asserts the shape
(four questions, none of them the dataset), not the milliseconds.

## Running the example

```sh
frontage build examples/trips -o examples/trips/www
uvicorn server:app --app-dir examples/trips        # http://127.0.0.1:8000
curl -X POST 'http://127.0.0.1:8000/demo/append?n=5000'   # watch every open page update
```

Half a million synthetic trips, one borough signal, four queries, and a grid over all of them.
