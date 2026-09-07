"""frontage-polars, the browser half, on CPython with the transport faked.

`remote(base, fetch=...)` takes an `async (url) -> (status, text)`, so what these assert is the
URL Python builds and what it does with the answer: the only part this package owns in a page.
"""

import asyncio
import json

from frontage import Loading, RecordingRenderer, Signal, h, mount
from frontage_polars import Frame, RemoteError, remote

FRAME = {
    "columns": ["hour", "trips"],
    "dtypes": ["Int8", "UInt32"],
    "height": 3,
    "data": {"hour": [0, 1, 2], "trips": [5, 7, 9]},
}


class FakeServer:
    def __init__(self, answers=None):
        self.urls = []
        self.answers = answers or {}

    async def fetch(self, url):
        self.urls.append(url)
        await asyncio.sleep(0)
        for prefix, answer in self.answers.items():
            if url.startswith(prefix):
                status, payload = answer if isinstance(answer, tuple) else (200, answer)
                return status, json.dumps(payload)
        return 200, json.dumps(FRAME)


async def settle(n=4):
    for _ in range(n):
        await asyncio.sleep(0)


def mounted(view):
    renderer = RecordingRenderer()
    root = renderer.inner.create_element("div")
    mount(view, root, renderer)
    return root


def html(root):
    return "".join(c.to_html() for c in root.children)


# --- Frame ----------------------------------------------------------------------------------


def test_a_frame_answers_columns_series_and_rows():
    frame = Frame(FRAME)
    assert len(frame) == 3 and frame.columns == ["hour", "trips"]
    assert frame["trips"] == [5, 7, 9] and frame.column("hour") == [0, 1, 2]
    assert frame.series("hour", "trips") == [[0, 1, 2], [5, 7, 9]]
    assert frame.rows() == [{"hour": 0, "trips": 5}, {"hour": 1, "trips": 7}, {"hour": 2, "trips": 9}]
    assert list(frame) == frame.rows()


# --- URLs -----------------------------------------------------------------------------------


def test_the_url_names_the_query_and_encodes_the_parameters():
    api = remote("/api/", events=False, fetch=None)
    assert (
        api.url("/frame/x", {"b": "two words", "a": 1, "flag": True, "none": None})
        == "/api/frame/x?a=1&b=two%20words&flag=true"
    )
    assert api.url("/frame/x") == "/api/frame/x"


def test_unicode_and_reserved_characters_are_percent_encoded():
    api = remote("/api", events=False)
    assert api.url("/frame/q", {"s": "Ciutat Vella & co/ü"}) == "/api/frame/q?s=Ciutat%20Vella%20%26%20co%2F%C3%BC"


# --- query ----------------------------------------------------------------------------------


def test_a_query_is_a_resource_that_refetches_when_a_parameter_changes():
    async def scenario():
        server = FakeServer()
        api = remote("/api", fetch=server.fetch)
        borough = Signal("all")
        hourly = api.query("by_hour", borough=borough)
        root = mounted(h.div(Loading(h.i("…"), lambda: h.b(lambda: str(hourly()["trips"])))))
        assert html(root) == "<div><i>…</i></div>"
        await settle()
        assert html(root) == "<div><b>[5, 7, 9]</b></div>"
        assert server.urls == ["/api/frame/by_hour?borough=all"]
        borough.set("Queens")
        await settle()
        assert server.urls[-1] == "/api/frame/by_hour?borough=Queens"

    asyncio.run(scenario())


def test_a_plain_value_parameter_is_sent_once_and_never_tracked():
    async def scenario():
        server = FakeServer()
        api = remote("/api", fetch=server.fetch)
        api.query("by_hour", borough="Bronx", limit=5)
        await settle()
        assert server.urls == ["/api/frame/by_hour?borough=Bronx&limit=5"]

    asyncio.run(scenario())


def test_a_non_200_answer_raises_a_remote_error_with_the_servers_message():
    async def scenario():
        server = FakeServer({"/api/frame/nope": (404, {"detail": "no query named 'nope'"})})
        api = remote("/api", fetch=server.fetch)
        res = api.query("nope")
        await settle()
        assert res.state() == "errored"
        assert isinstance(res.error(), RemoteError)
        assert res.error().status == 404 and "no query named" in res.error().message

    asyncio.run(scenario())


def test_an_event_for_a_query_refetches_it_and_leaves_the_others_alone():
    async def scenario():
        server = FakeServer()
        api = remote("/api", fetch=server.fetch)
        api.query("by_hour")
        api.query("daily")
        await settle()
        assert sorted(server.urls) == ["/api/frame/by_hour", "/api/frame/daily"]
        api._on_event('{"source": "daily"}')
        await settle()
        assert server.urls[2:] == ["/api/frame/daily"]
        api._on_event('{"source": null}')  # `changed()` with no name: everything
        await settle()
        assert sorted(server.urls[3:]) == ["/api/frame/by_hour", "/api/frame/daily"]
        api._on_event("not json")  # a stray line is ignored
        await settle()
        assert len(server.urls) == 5

    asyncio.run(scenario())


# --- rows -----------------------------------------------------------------------------------


def test_a_row_source_asks_for_one_window_with_the_query_parameters():
    async def scenario():
        server = FakeServer({"/api/rows/trips": {"total": 500, "offset": 40, "rows": [{"id": 40}]}})
        api = remote("/api", fetch=server.fetch)
        borough = Signal("Queens")
        rows = api.rows("trips", borough=borough)
        key = rows.key()
        assert key[0] == "/api/rows/trips?borough=Queens"
        total, offset, page = await rows.window(key, 40, 20, "fare", True, "abc")
        assert (total, offset, page) == (500, 40, [{"id": 40}])
        assert server.urls == ["/api/rows/trips?borough=Queens&desc=true&limit=20&offset=40&search=abc&sort=fare"]
        total, offset, page = await rows.window(key, 0, 20)
        assert server.urls[-1] == "/api/rows/trips?borough=Queens&limit=20&offset=0"

    asyncio.run(scenario())


def test_a_row_source_key_changes_with_its_version():
    api = remote("/api", events=False)
    rows = api.rows("trips")
    before = rows.key()
    api._on_event('{"source": "trips"}')
    assert rows.key() != before and rows.key()[0] == before[0]


def test_the_browser_half_never_imports_the_server_half():
    import sys

    for name in [n for n in sys.modules if n.startswith("frontage_polars")]:
        del sys.modules[name]
    import frontage_polars

    assert set(frontage_polars.__all__) == {"Frame", "Remote", "RemoteError", "RowSource", "remote"}
    assert "frontage_polars.server" not in sys.modules, "the page would try to import polars"
