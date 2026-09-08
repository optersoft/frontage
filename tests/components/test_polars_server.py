"""frontage-polars, the server half: named queries over HTTP, and what never leaves.

Driven through FastAPI's test client, so every assertion is about the bytes a page would get.
"""

import json
import sys
import time
from datetime import date

import httpx
import polars as pl
import pytest
from fastapi.testclient import TestClient

from frontage.remote.server import Sources

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))

PEOPLE = pl.DataFrame(
    {
        "name": ["Ada", "Grace", "Barbara", "Margaret"],
        "qty": [1200, 70, 340, None],
        "ratio": [0.5, float("nan"), 2.0, 1.0],
        "born": [date(1815, 12, 10), date(1906, 12, 9), date(1932, 8, 2), date(1936, 8, 17)],
        "team": ["north", "south", "north", "south"],
    }
)


@pytest.fixture
def sources():
    src = Sources(cache=4, max_rows=3)
    calls = []

    @src.query
    def people(team: str = "all"):
        calls.append(team)
        frame = PEOPLE.lazy()
        return frame if team == "all" else frame.filter(pl.col("team") == team)

    @src.query
    def count(team: str = "all", min_qty: int = 0):
        return (
            PEOPLE.filter((pl.col("team") == team) | (pl.lit(team) == "all"))
            .filter(pl.col("qty") >= min_qty)
            .select(pl.len())
        )

    @src.query(name="born-after")
    def born_after(when: date):
        return PEOPLE.filter(pl.col("born") > when).select("name")

    src.calls = calls  # ty: ignore[unresolved-attribute]
    return src


@pytest.fixture
def client(sources):
    return TestClient(sources.app(prefix="/api"))


# --- frames ---------------------------------------------------------------------------------


def test_a_frame_is_column_oriented_json_with_names_and_dtypes(client):
    body = client.get("/api/frame/count?team=north").json()
    assert body["columns"] == ["len"] and body["height"] == 1 and body["data"] == {"len": [2]}
    assert body["dtypes"] == ["UInt32"]


def test_nan_becomes_null_and_a_date_becomes_iso_text(client):
    body = client.get("/api/frame/people?team=south").json()
    assert body["data"]["ratio"] == [None, 1.0]
    assert body["data"]["born"] == ["1906-12-09", "1936-08-17"]
    assert body["data"]["qty"] == [70, None]
    # And the text itself is strict JSON: a MicroPython parser would choke on `NaN`.
    assert "NaN" not in client.get("/api/frame/people?team=south").text


def test_a_frame_over_the_cap_is_refused_rather_than_shipped(client):
    response = client.get("/api/frame/people")
    assert response.status_code == 413
    assert "4 rows" in response.json()["detail"] and "window" in response.json()["detail"]


def test_every_answer_allows_any_origin(client):
    # `frontage serve` on one port and the server on another, and the site's opaque-origin
    # runner: both need this or the page works in production and not in development.
    for path in ("/api/frame/count", "/api/rows/people", "/api/"):
        assert client.get(path).headers["access-control-allow-origin"] == "*"


# --- parameters -----------------------------------------------------------------------------


def test_parameters_are_converted_by_annotation(client):
    assert client.get("/api/frame/count?min_qty=100").json()["data"] == {"len": [2]}
    assert client.get("/api/frame/born-after?when=1930-01-01").json()["data"] == {"name": ["Barbara", "Margaret"]}


def test_an_unknown_parameter_is_a_400_that_names_it(client):
    response = client.get("/api/frame/count?nope=1")
    assert response.status_code == 400 and "'nope'" in response.json()["detail"]


def test_a_missing_required_parameter_is_a_400(client):
    response = client.get("/api/frame/born-after")
    assert response.status_code == 400 and "'when'" in response.json()["detail"]


def test_a_malformed_value_is_a_400_not_a_500(client):
    assert client.get("/api/frame/count?min_qty=lots").status_code == 400
    assert client.get("/api/frame/born-after?when=yesterday").status_code == 400


def test_an_unknown_query_is_a_404(client):
    assert client.get("/api/frame/secrets").status_code == 404
    assert client.get("/api/rows/secrets").status_code == 404


def test_the_index_lists_the_queries(client):
    assert client.get("/api/").json() == {"queries": ["born-after", "count", "people"]}


def test_a_query_cannot_take_star_args():
    src = Sources()
    with pytest.raises(TypeError):

        @src.query
        def bad(**anything):
            return PEOPLE


# --- windows --------------------------------------------------------------------------------


def test_a_window_is_a_slice_with_the_total(client):
    body = client.get("/api/rows/people?offset=1&limit=2").json()
    assert body["total"] == 4 and body["offset"] == 1
    assert [r["name"] for r in body["rows"]] == ["Grace", "Barbara"]


def test_the_server_sorts_by_the_raw_value(client):
    names = [r["name"] for r in client.get("/api/rows/people?sort=qty").json()["rows"]]
    assert names == ["Grace", "Barbara", "Ada", "Margaret"]  # nulls last
    names = [r["name"] for r in client.get("/api/rows/people?sort=qty&desc=true").json()["rows"]]
    assert names == ["Ada", "Barbara", "Grace", "Margaret"]


def test_search_is_a_case_insensitive_substring_over_every_column(client):
    body = client.get("/api/rows/people?search=NORTH").json()
    assert body["total"] == 2 and {r["name"] for r in body["rows"]} == {"Ada", "Barbara"}
    body = client.get("/api/rows/people?search=1815").json()  # a date, matched as text
    assert [r["name"] for r in body["rows"]] == ["Ada"]


def test_a_window_takes_the_query_parameters_too(client):
    body = client.get("/api/rows/people?team=south&sort=name").json()
    assert [r["name"] for r in body["rows"]] == ["Grace", "Margaret"]


def test_the_limit_is_capped_and_the_offset_clamped(client):
    body = client.get("/api/rows/people?offset=99&limit=5000").json()
    assert body["offset"] == 4 and body["rows"] == []


def test_sorting_by_an_unknown_column_is_a_400(client):
    assert client.get("/api/rows/people?sort=salary").status_code == 400


def test_a_window_does_not_re_run_the_query(client, sources):
    client.get("/api/rows/people?offset=0&limit=2")
    client.get("/api/rows/people?offset=2&limit=2&sort=name")
    client.get("/api/frame/people?team=north")
    assert sources.calls == ["all", "north"]


# --- the cache and `changed` ----------------------------------------------------------------


def test_changed_drops_one_query_and_the_next_request_recomputes(client, sources):
    client.get("/api/frame/people?team=north")
    client.get("/api/frame/people?team=north")
    assert sources.calls == ["north"]
    sources.changed("people")
    client.get("/api/frame/people?team=north")
    assert sources.calls == ["north", "north"]


def test_the_cache_is_bounded(sources):
    for team in ("a", "b", "c", "d", "e"):
        sources.frame("people", team=team)
    assert len(sources._cache) == 4


def test_a_query_that_returns_something_else_is_a_type_error():
    src = Sources()

    @src.query
    def oops():
        return [1, 2, 3]

    with pytest.raises(TypeError, match="not a polars frame"):
        src.frame("oops")


def test_changed_reaches_an_open_event_stream(sources):
    """The push half: a page holding `/events` hears `changed(name)` and nothing else until
    then. Over a real socket, because an in-process ASGI transport buffers a stream to its
    end, and this one has none."""
    from live import serving

    with serving(sources.app(prefix="/api")) as base:
        with httpx.stream("GET", f"{base}/api/events", timeout=10) as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["access-control-allow-origin"] == "*"
            lines = response.iter_lines()
            assert next(lines) == ": connected"
            sources.changed("people")
            data = None
            started = time.time()
            while data is None and time.time() - started < 5:
                line = next(lines)
                if line.startswith("data:"):
                    data = json.loads(line[5:])
            assert data == {"source": "people"}


# --- series ---------------------------------------------------------------------------------


def _decode(body):
    import struct

    columns, height = struct.unpack_from("<II", body, 0)
    return [list(struct.unpack_from(f"<{height}d", body, 8 + c * height * 8)) for c in range(columns)], height


def test_series_is_float64_columns_behind_an_8_byte_header(client):
    response = client.get("/api/series/people?columns=qty,ratio&team=north")
    assert response.status_code == 200 and response.headers["content-type"] == "application/octet-stream"
    assert response.headers["access-control-allow-origin"] == "*"
    data, height = _decode(response.content)
    assert height == 2 and len(response.content) == 8 + 2 * 2 * 8
    assert data[0] == [1200.0, 340.0] and data[1] == [0.5, 2.0]


def test_series_sends_null_and_nan_as_nan_and_a_date_as_a_number(client):
    import math

    data, _ = _decode(client.get("/api/series/people?columns=qty,ratio,born&team=south").content)
    assert data[0][0] == 70.0 and math.isnan(data[0][1])  # a null
    assert math.isnan(data[1][0]) and data[1][1] == 1.0  # a NaN
    assert data[2][0] == (date(1906, 12, 9) - date(1970, 1, 1)).days  # a Date is days since the epoch


def test_series_refuses_a_text_column_an_unknown_one_and_no_columns(client):
    assert client.get("/api/series/people?columns=name&team=north").status_code == 400
    assert "not a number" in client.get("/api/series/people?columns=name&team=north").json()["detail"]
    assert client.get("/api/series/people?columns=salary&team=north").status_code == 400
    assert client.get("/api/series/people?team=north").status_code == 400
    assert client.get("/api/series/nope?columns=qty").status_code == 404


def test_series_is_capped_like_a_frame(sources):
    src = Sources(max_rows=3)

    @src.query
    def people():
        return PEOPLE

    assert TestClient(src.app()).get("/api/series/people?columns=qty").status_code == 413
