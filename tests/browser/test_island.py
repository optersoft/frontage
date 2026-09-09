"""Islands in Chromium: what a static page downloads, and when.

The whole of 0.11 is one number — a prerendered page is 455 bytes and today waits for 265 KB
of WebAssembly whether or not anything on it is interactive. These tests are that claim,
made checkable: a page with nothing interactive asks for nothing under `_frontage/`, an
island below the fold asks for nothing until it is scrolled to, and two islands on one page
boot one runtime between them.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"

STATIC_APP = """from frontage import h, mount


def page():
    return h.main(h.h1("Nothing to run", id="title"), h.p("This page is HTML and stops there."))


mount(page, "#app", when="never")
"""

DEFERRED_APP = """from frontage import Signal, h, island, mount


def counter():
    n = Signal(0)
    return h.div(
        h.button("+", on_click=lambda ev: n.update(lambda v: v + 1), id="inc"),
        h.span(n, id="value"),
        id="counter",
    )


def page():
    return h.main(
        h.h1("Far above", id="title"),
        *[h.p("filler " * 40) for _ in range(40)],
        island(counter, when="visible"),
    )


mount(page, "#app", when="never")
"""


def _prerender(name, source="", example=ROOT):
    src = BUILD / f"src-{name}"
    out = BUILD / f"island-{name}"
    for directory in (src, out):
        if directory.exists():
            shutil.rmtree(directory)
    if source:
        src.mkdir(parents=True)
        (src / "app.py").write_text(source)
    else:
        shutil.copytree(example, src, ignore=shutil.ignore_patterns("__pycache__", "_frontage"))
    command = [sys.executable, "-m", "frontage", "prerender", str(src), "--out", str(out)]
    subprocess.run(command, check=True, cwd=ROOT, capture_output=True)
    return out


@pytest.fixture(scope="module")
def pages():
    """Three prerendered directories under `build/`, which the suite's server already serves."""
    return {
        "static": _prerender("static", STATIC_APP),
        "deferred": _prerender("deferred", DEFERRED_APP),
        "example": _prerender("example", example=ROOT / "examples" / "islands"),
    }


def runtime_requests(urls):
    return [u for u in urls if "/_frontage/" in u and not u.endswith("island.js")]


def test_a_page_with_no_island_ships_no_runtime(server, page: Page, pages):
    html = (pages["static"] / "index.html").read_text()
    assert "data-fr-boot" not in html, "a static page kept the boot tag"
    assert "island.js" not in html, "a page with no island got the loader"

    asked = []
    page.on("request", lambda r: asked.append(r.url))
    page.goto(f"{server}/build/island-static/index.html")
    expect(page.locator("#title")).to_have_text("Nothing to run")
    page.wait_for_timeout(500)
    assert runtime_requests(asked) == [], "a page with nothing to run fetched the runtime"


def test_a_visible_island_waits_until_it_is_seen(server, page: Page, pages):
    html = (pages["deferred"] / "index.html").read_text()
    assert 'data-fr-when="visible"' in html
    assert "island.js" in html and "data-fr-boot" not in html

    asked = []
    page.on("request", lambda r: asked.append(r.url))
    page.goto(f"{server}/build/island-deferred/index.html")
    expect(page.locator("#title")).to_have_text("Far above")
    # The island's HTML is on screen from the first byte; only its behaviour is deferred.
    expect(page.locator("#value")).to_have_text("0")
    page.wait_for_timeout(700)
    assert runtime_requests(asked) == [], "the runtime arrived before anything asked for it"

    asked.clear()
    page.locator("#counter").scroll_into_view_if_needed()
    expect(page.locator("#value")).to_have_text("0")
    page.wait_for_function("() => window.frontage !== undefined", timeout=30_000)
    page.click("#inc")
    expect(page.locator("#value")).to_have_text("1")
    assert len([u for u in asked if u.endswith(".wasm")]) == 1


def test_two_islands_share_one_runtime_and_the_chart_is_a_chunk(server, page: Page, pages):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    asked = []
    page.on("request", lambda r: asked.append(r.url))
    page.goto(f"{server}/build/island-example/index.html")

    # The toggle is `idle`, so the runtime does boot — once — and the chart's chunk does not.
    page.wait_for_function("() => window.frontage !== undefined", timeout=30_000)
    page.click("#theme")
    expect(page.locator("#theme-state")).to_have_text(" on")
    assert [u for u in asked if "charts" in u or "samples" in u] == [], "the chunk came with the page"

    asked.clear()
    page.locator("#spark").scroll_into_view_if_needed()
    expect(page.locator("#peak")).to_have_text(" peak 78")
    page.wait_for_function(
        "() => document.querySelector('fr-island[data-fr-index=\"1\"]').hasAttribute('data-fr-mounted')"
    )
    page.click("#taller")
    expect(page.locator("#peak")).to_have_text(" peak 58")

    chunk = {u.rsplit("/", 1)[-1].split(".")[0] for u in asked if "/_frontage/" in u}
    assert {"charts", "samples"} <= chunk, f"the chunk did not arrive: {chunk}"
    assert [u for u in asked if u.endswith(".wasm")] == [], "the second island booted a second runtime"
    assert errors == []
