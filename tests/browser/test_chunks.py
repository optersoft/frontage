"""A route in a chunk of its own, in Chromium: what a visitor downloads, and when."""

import json

from playwright.sync_api import Page, expect


def chunk_requests(urls):
    """The chunk's own modules among these requests, by module name."""
    names = set()
    for url in urls:
        name = url.rsplit("/", 1)[-1]
        if name.startswith("pages"):
            names.add(".".join(name.split(".")[:-2]) if name.count(".") > 2 else name.split(".")[0])
    return names


def test_the_chunk_arrives_on_the_first_visit_to_its_route(lazy, page: Page):
    base, out, _ = lazy
    manifest = json.loads((out / "_frontage" / "manifest.json").read_text())
    assert manifest["chunks"] == {"pages.report": ["pages", "pages.report", "pages.rides"]}
    assert not [name for name in manifest["modules"] if name.startswith("pages")]

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    asked = []
    page.on("request", lambda r: asked.append(r.url))

    page.goto(f"{base}/index.html")
    expect(page.locator("#home")).to_be_visible(timeout=30_000)
    assert chunk_requests(asked) == set(), "the chunk travelled with the first payload"

    asked.clear()
    page.click("#to-report")
    expect(page.locator("#report")).to_be_visible(timeout=30_000)
    expect(page.locator("#summary")).to_have_text("600 rides, busiest at 02:00")
    assert chunk_requests(asked) == {"pages", "pages.report", "pages.rides"}

    # Back and forward again: the chunk is in the interpreter, so nothing is asked twice.
    asked.clear()
    page.go_back()
    expect(page.locator("#home")).to_be_visible()
    page.click("#to-report")
    expect(page.locator("#report")).to_be_visible()
    assert chunk_requests(asked) == set()
    assert errors == []


def test_a_hover_starts_the_fetch_before_the_click(lazy, page: Page):
    base, _, _ = lazy
    asked = []
    page.on("request", lambda r: asked.append(r.url))
    page.goto(f"{base}/index.html")
    expect(page.locator("#home")).to_be_visible(timeout=30_000)

    asked.clear()
    page.hover("#to-report")
    page.wait_for_function(
        "() => performance.getEntriesByType('resource').some(e => e.name.includes('pages.report'))",
        timeout=10_000,
    )
    assert chunk_requests(asked) == {"pages", "pages.report", "pages.rides"}


def test_while_the_chunk_is_in_flight_the_route_is_not_ready(lazy, page: Page):
    """The wait is the framework's own: the nearest `Loading` shows its fallback and the
    fetch counts toward `is_routing`, exactly as a route waiting for data does."""
    base, _, server = lazy
    server.chunk = "slow"
    try:
        page.goto(f"{base}/index.html")
        expect(page.locator("#home")).to_be_visible(timeout=30_000)
        page.click("#to-report")
        expect(page.locator("#waiting")).to_be_visible(timeout=10_000)
        expect(page.locator("#status")).to_have_text("loading…")
        expect(page.locator("#report")).to_be_visible(timeout=30_000)
        expect(page.locator("#status")).to_have_text("")
    finally:
        server.chunk = ""


def test_a_chunk_that_does_not_arrive_reaches_the_errored_boundary(lazy, page: Page):
    base, _, server = lazy
    server.chunk = "gone"
    try:
        page.goto(f"{base}/index.html")
        expect(page.locator("#home")).to_be_visible(timeout=30_000)
        page.click("#to-report")
        expect(page.locator("#failed")).to_contain_text("404", timeout=30_000)
    finally:
        server.chunk = ""
