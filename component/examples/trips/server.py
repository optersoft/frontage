"""The server for `app.py`: a synthetic half-million-row frame and five named queries.

    uvicorn server:app --app-dir examples/trips           # after `frontage build examples/trips`

`TRIPS_STATIC` names the built directory to serve at `/` (default `www` beside this file);
`TRIPS_ROWS` sizes the dataset. `POST /demo/append?n=1000` adds rows and tells every open page.
"""

import os
import random
from datetime import date
from pathlib import Path

import polars as pl
from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles
from frontage_polars.server import Sources

HERE = Path(__file__).parent
BOROUGHS = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]
BOROUGH_WEIGHTS = [45, 25, 18, 8, 4]
HOUR_WEIGHTS = [3, 2, 1, 1, 1, 2, 4, 7, 9, 7, 6, 6, 7, 7, 7, 8, 9, 10, 10, 9, 8, 7, 6, 4]


def make_trips(n, seed=7, start_id=0):
    """`n` plausible trips: skewed boroughs, a rush-hour curve, fares that follow distance."""
    r = random.Random(seed + start_id)
    boroughs = r.choices(BOROUGHS, weights=BOROUGH_WEIGHTS, k=n)
    hours = r.choices(range(24), weights=HOUR_WEIGHTS, k=n)
    days = [r.randrange(366) for _ in range(n)]
    distance = [round(r.lognormvariate(0.9, 0.7), 2) for _ in range(n)]
    passengers = r.choices([1, 2, 3, 4, 5, 6], weights=[70, 15, 6, 5, 2, 2], k=n)
    fare = [round(3.0 + d * 2.5 + r.random() * 3, 2) for d in distance]
    return pl.DataFrame(
        {
            "id": pl.int_range(start_id, start_id + n, eager=True),
            "day": pl.Series(days, dtype=pl.Int32),
            "hour": pl.Series(hours, dtype=pl.Int8),
            "borough": pl.Series(boroughs, dtype=pl.Categorical),
            "distance_km": distance,
            "fare": fare,
            "passengers": pl.Series(passengers, dtype=pl.Int8),
        }
    ).with_columns((pl.lit(date(2024, 1, 1)) + pl.duration(days=pl.col("day"))).alias("date"))


TRIPS = make_trips(int(os.environ.get("TRIPS_ROWS", "500000")))
src = Sources()


def _where(borough):
    frame = TRIPS.lazy()
    return frame if borough == "all" else frame.filter(pl.col("borough") == borough)


@src.query
def summary(borough: str = "all"):
    return _where(borough).select(
        pl.len().alias("trips"),
        pl.col("fare").sum().round(0).alias("revenue"),
        pl.col("distance_km").mean().round(2).alias("avg_km"),
        pl.col("passengers").mean().round(2).alias("avg_passengers"),
    )


@src.query
def daily(borough: str = "all"):
    return (
        _where(borough).group_by("day").agg(pl.len().alias("trips"), pl.col("fare").sum().alias("revenue")).sort("day")
    )


@src.query
def by_hour(borough: str = "all"):
    return _where(borough).group_by("hour").agg(pl.len().alias("trips")).sort("hour")


@src.query
def cumulative(borough: str = "all"):
    """Revenue, cumulative, per hour of the year: ~8,800 points, which is why the page asks for
    it as `series` — binary float64 the chart draws directly — rather than as a frame."""
    return (
        _where(borough)
        .group_by((pl.col("day") * 24 + pl.col("hour")).alias("h"))
        .agg(pl.col("fare").sum().alias("revenue"))
        .sort("h")
        .with_columns(pl.col("revenue").cum_sum())
    )


@src.query
def trips(borough: str = "all"):
    return _where(borough).select("id", "date", "hour", "borough", "distance_km", "fare", "passengers")


def make_app(static=None):
    # A route of our own beside the router, so the app is assembled by hand: Starlette matches
    # in order, and a static mount at `/` registered first would swallow `/demo/append`.
    app = FastAPI()
    app.include_router(src.router, prefix="/api")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "rows": TRIPS.height}

    @app.post("/demo/append")
    def append(n: int = Query(1000, ge=1, le=100_000)):
        """More trips arrived: extend the frame and tell the pages. What a real server does
        after its ingest, in one call."""
        global TRIPS
        TRIPS = pl.concat([TRIPS, make_trips(n, start_id=TRIPS.height)])
        src.changed()
        return {"rows": TRIPS.height}

    if static is not None:
        app.mount("/", StaticFiles(directory=str(static), html=True), name="static")
    return app


static = os.environ.get("TRIPS_STATIC", str(HERE / "www"))
app = make_app(static if Path(static).is_dir() else None)


def main():
    """The `trips` script: uvicorn on `TRIPS_ADDR` (default 127.0.0.1:8000). What the fleet's
    unit runs, from the venv `uv sync --frozen` built on the box."""
    import uvicorn

    host, _, port = os.environ.get("TRIPS_ADDR", "127.0.0.1:8000").rpartition(":")
    uvicorn.run(app, host=host or "127.0.0.1", port=int(port or 8000), log_level="info")
