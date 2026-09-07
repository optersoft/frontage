"""frontage-supabase driven through a real browser against a real server.

The unit tests stub `fetch` and hold a fake socket, which proves the request this package builds
and the meaning it takes from a reply. They cannot prove that any of it survives MicroPython:
`Exception.__init__(self, …)` type-checks on CPython and raises `AttributeError` in a page, and
a signal read inside a `Resource`'s fetcher is a dependency on CPython and a silent no-op after
the first await in the browser. Both were found here and only here.

`supabase_stub.Stub` is not a mock inside this process — it is a socket serving PostgREST's wire
format and Phoenix's frames, so the component is exercised through the browser's own `fetch` and
`WebSocket`. What it does not prove is that Supabase itself behaves as its documentation says;
nothing in this repository has talked to a Supabase project.
"""

import functools
import http.server
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from playwright.sync_api import sync_playwright  # noqa: E402
from supabase_stub import Stub  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

APP = """
import asyncio

from frontage import Signal, h, mount
from frontage.runtime import window
from frontage_supabase import Channel, Client, PostgrestError

BASE = window.location.search.split("base=")[1]
db = Client(BASE, "anon-key")

floor = Signal(500000)
log = Signal([])
live = Signal([])

cities = db.resource(lambda: db.table("cities").select("*").gt("people", floor()).order("people", desc=True))


def say(line):
    log.update(lambda current: list(current) + [line])


async def script():
    try:
        await db.run(db.table("secret").select("*"))
        say("denied:NO")
    except PostgrestError as exc:
        say("denied:%s:%s:%s" % (exc.denied, exc.code, "hint" if exc.hint else "nohint"))
    result = await db.table("cities").insert({"name": "Girona", "people": 103000})
    say("insert:%s:%s" % (result[0]["id"], result[0]["name"]))
    await db.auth.sign_in("ada@example.com", "hunter2")
    say("signin:%s" % db.auth.user()["email"])
    channel = Channel(db, "cities").subscribe()
    channel.follow(live)
    for _ in range(80):
        if channel.state() == "joined":
            break
        await asyncio.sleep(0.05)
    say("channel:%s" % channel.state())


asyncio.create_task(script())
mount(
    lambda: h.div(
        h.p(lambda: " ".join(log()), id="log"),
        h.p(lambda: ",".join(str(r["id"]) for r in (cities().rows if cities() else [])), id="ids"),
        h.p(lambda: str(cities().count) if cities() else "-", id="count"),
        h.p(lambda: ",".join(r["name"] for r in live()), id="live"),
        h.button("raise", id="raise", on_click=lambda ev: floor.set(1000000)),
    ),
    "#app",
)
"""

PAGE = (
    '<div id="app">Loading…</div>\n'
    '<script type="module" src="./_frontage/boot.js" data-fr-boot data-fr-entry="app"></script>\n'
)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    """The app built with the real command, served by a plain static server."""
    source = tmp_path_factory.mktemp("supabase-app")
    (source / "app.py").write_text(APP)
    (source / "index.html").write_text(PAGE)
    out = tmp_path_factory.mktemp("supabase-out")
    subprocess.run(
        [sys.executable, "-m", "frontage", "build", str(source), "--out", str(out), "--quiet"],
        check=True,
        cwd=ROOT,
    )
    assert (out / "_frontage" / "components" / "supabase" / "index.js").is_file()

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(out))
    handler.extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".wasm": "application/wasm",
        ".css": "text/css",
        ".tar": "application/x-tar",
    }
    handler.log_message = lambda *a, **k: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", free_port()), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    server.shutdown()


def test_the_whole_component_against_a_server_that_speaks_postgrest_and_phoenix(app):
    stub = Stub()
    stub.start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        # A warning is a failure here: "a signal was read after the first await" means a
        # dependency the framework did not take, which is a resource that silently stops
        # refetching. It is the second bug this test found.
        page.on(
            "console",
            lambda m: errors.append("console: " + m.text) if m.type == "warning" else None,
        )
        page.goto(f"{app}?base={stub.url()}")
        page.wait_for_function(
            "document.querySelector('#log') && document.querySelector('#log').textContent.includes('channel:')",
            timeout=60_000,
        )

        script = page.locator("#log").inner_text()
        assert "denied:True:42501:hint" in script, "row-level security must be told apart, with its hint"
        assert "insert:99:Girona" in script, "a write returns the row, with the id the server assigned"
        assert "signin:ada@example.com" in script
        assert "channel:joined" in script

        assert page.locator("#ids").inner_text() == "1,2,3"
        assert page.locator("#count").inner_text() == "4", "the total comes from Content-Range"

        # The query is reactive: a signal write rebuilds it and refetches.
        page.locator("#raise").click()
        page.wait_for_timeout(900)
        assert page.locator("#ids").inner_text() == "1,2"

        # Realtime: the database pushes and the list follows.
        stub.push("realtime:public:cities", "INSERT", {"id": 50, "name": "Girona"})
        stub.push("realtime:public:cities", "INSERT", {"id": 51, "name": "Lleida"})
        page.wait_for_timeout(900)
        assert page.locator("#live").inner_text() == "Girona,Lleida"
        stub.push("realtime:public:cities", "DELETE", {"id": 50, "name": "Girona"})
        page.wait_for_timeout(700)
        assert page.locator("#live").inner_text() == "Lleida"

        assert stub.joins[0]["config"]["postgres_changes"] == [{"event": "*", "schema": "public", "table": "cities"}]
        # Signing in refetches, because row-level security will answer differently.
        bearing = [
            r
            for r in stub.requests
            if r[1].startswith("/rest/v1/cities") and r[2].get("authorization", "").startswith("Bearer jwt-")
        ]
        assert bearing, "no request carried the session token, so signing in changed nothing"
        assert errors == []
        browser.close()
