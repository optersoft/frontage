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


# `load`, `only` and a `media:` query that does not match at 1000px: the three triggers the
# example does not use, and the page the replay test needs — one island alive from the first
# frame, one that stays HTML until the viewport says otherwise.
TRIGGERS_APP = """from frontage import Signal, h, island, mount


def counter(name="a"):
    n = Signal(0)
    return h.div(
        h.button("+", on_click=lambda ev: n.update(lambda v: v + 1), id="inc-" + name),
        h.span(n, id="v-" + name),
        id="c-" + name,
    )


def page():
    return h.main(
        h.h1("Triggers", id="title"),
        island(counter, when="load", name="a"),
        island(counter, when="media:(max-width: 600px)", name="b"),
        island(counter, when="only", name="c"),
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


#: A static page typed into a live-code frame. The runner has no boot tag and no island
#: loader — it is handed a program and runs it — so `when="never"` must mount there like any
#: other page, islands rendered where they stand. The first version of this told the two
#: apart by the boot tag, and every `::: frontage` block in the docs showing a static page
#: would have been a blank frame.
RUNNER_PROGRAM = """from frontage import html, island, mount


def badge(label="hi"):
    return html(t"<b id='badge'>{label}</b>")


def page():
    return html(t"<main id='page'>a static page: {island(badge, when='visible', label='island')}</main>")


mount(page, "#app", when="never")
"""


@pytest.fixture(scope="module")
def runner():
    """`web/public/runner.html` with the runtime beside it: the page a live-code frame is."""
    from frontage.cli import frontage_rt

    out = BUILD / "island-runner"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    frontage_rt.site_files(out / "_frontage")
    shutil.copy2(ROOT / "web" / "public" / "runner.html", out / "runner.html")
    return out


@pytest.fixture(scope="module")
def pages():
    """Three prerendered directories under `build/`, which the suite's server already serves."""
    return {
        "static": _prerender("static", STATIC_APP),
        "deferred": _prerender("deferred", DEFERRED_APP),
        "example": _prerender("example", example=ROOT / "examples" / "islands"),
        "triggers": _prerender("triggers", TRIGGERS_APP),
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


def test_only_is_not_in_the_page_and_media_waits_for_its_query(server, page: Page, pages):
    html = (pages["triggers"] / "index.html").read_text()
    # `only` says "do not render this at build", and the page has to be honest about it.
    assert 'data-fr-when="only"' in html and 'id="v-c"' not in html
    # The other two are rendered, whether or not they will ever be hydrated.
    assert 'id="v-a"' in html and 'id="v-b"' in html
    assert 'data-fr-when="media:(max-width: 600px)"' in html

    page.set_viewport_size({"width": 1000, "height": 700})
    page.goto(f"{server}/build/island-triggers/index.html")
    # `load` and `only` boot at once; `only` had nothing on the page until it did.
    expect(page.locator("#v-c")).to_have_text("0", timeout=30_000)
    page.click("#inc-a")
    expect(page.locator("#v-a")).to_have_text("1")
    assert not page.locator('fr-island[data-fr-when^="media"]').get_attribute("data-fr-mounted")

    page.set_viewport_size({"width": 500, "height": 700})
    page.click("#inc-b")
    expect(page.locator("#v-b")).to_have_text("1", timeout=30_000)


def test_a_click_on_an_island_that_has_not_hydrated_yet_is_replayed(server, page: Page, pages):
    """The bug this fixes: the replay used to be the page's, so the first island to hydrate
    dispatched the whole queue and took the listeners with it — and a click on a second
    island, made while its trigger had not fired, was lost with no trace."""
    page.set_viewport_size({"width": 1000, "height": 700})
    page.goto(f"{server}/build/island-triggers/index.html")
    # Island `a` is up: under the old replay this is the moment the queue was emptied.
    expect(page.locator("#v-c")).to_have_text("0", timeout=30_000)
    page.click("#inc-a")
    expect(page.locator("#v-a")).to_have_text("1")

    # Island `b` is still HTML. The click goes nowhere now and must arrive when it hydrates.
    page.click("#inc-b")
    expect(page.locator("#v-b")).to_have_text("0")
    page.set_viewport_size({"width": 500, "height": 700})
    expect(page.locator("#v-b")).to_have_text("1", timeout=30_000)
    # And it arrives once: the queue keeps only what it did not dispatch.
    page.click("#inc-b")
    expect(page.locator("#v-b")).to_have_text("2")
    assert page.locator("#v-a").text_content() == "1", "the replay reached the wrong island"


def test_a_static_page_typed_into_the_runner_still_mounts(server, page: Page, runner):
    """No boot tag and no loader: the runner is handed a program, so `when="never"` mounts."""
    import json
    import urllib.parse

    fragment = urllib.parse.quote(json.dumps({"code": RUNNER_PROGRAM, "markup": ""}))
    page.goto(f"{server}/build/island-runner/runner.html#{fragment}")
    expect(page.locator("#page")).to_contain_text("a static page", timeout=30_000)
    # And the island is the component, rendered where it stands: there is nothing to defer
    # on a page nobody built.
    expect(page.locator("#badge")).to_have_text("island")
    assert page.locator("fr-island").count() == 0
