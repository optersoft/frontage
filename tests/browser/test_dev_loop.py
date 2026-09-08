"""What a save does, in Chromium: a swap, and the two ways an edit can be wrong."""

from playwright.sync_api import Page, expect

OVERLAY = "#frontage-dev-overlay"


def test_an_edit_swaps_the_page_without_reloading_it(editable, page: Page):
    base, app = editable
    page.goto(f"{base}/index.html")
    expect(page.locator("#value")).to_have_text("Value: 0, doubled: 0", timeout=30_000)
    page.click("#inc")
    expect(page.locator("#value")).to_have_text("Value: 1, doubled: 2")
    page.evaluate("window.__stillHere = true")  # a reload would take this with it

    source = app / "counter.py"
    source.write_text(source.read_text().replace('"Value: "', '"Count: "'))
    expect(page.locator("#value")).to_contain_text("Count: 0", timeout=30_000)
    assert page.evaluate("window.__stillHere") is True, "the page reloaded instead of swapping"
    assert page.locator(OVERLAY).count() == 0


def test_a_file_that_does_not_compile_shows_the_compiler_and_keeps_the_page(editable, page: Page):
    base, app = editable
    page.goto(f"{base}/index.html")
    expect(page.locator("#value")).to_have_text("Value: 0, doubled: 0", timeout=30_000)

    page.click("#inc")
    expect(page.locator("#value")).to_have_text("Value: 1, doubled: 2")

    source = app / "counter.py"
    good = source.read_text()
    source.write_text(good + "\ndef broken(:\n")
    expect(page.locator(OVERLAY)).to_be_visible(timeout=30_000)
    expect(page.locator(OVERLAY)).to_contain_text("counter.py does not compile")
    # Nothing was torn down: the page underneath is the one that worked, with its state.
    expect(page.locator("#value")).to_have_text("Value: 1, doubled: 2")

    source.write_text(good)
    expect(page.locator(OVERLAY)).to_have_count(0, timeout=30_000)
    expect(page.locator("#value")).to_have_text("Value: 0, doubled: 0")


def test_a_swap_that_raises_shows_the_traceback(editable, page: Page):
    base, app = editable
    page.goto(f"{base}/index.html")
    expect(page.locator("#value")).to_have_text("Value: 0, doubled: 0", timeout=30_000)

    source = app / "counter.py"
    good = source.read_text()
    source.write_text(good + "\nraise ValueError('not today')\n")
    expect(page.locator(OVERLAY)).to_be_visible(timeout=30_000)
    expect(page.locator(OVERLAY)).to_contain_text("not today")
    expect(page.locator(OVERLAY)).to_contain_text("counter.py raised while the page was rebuilding")

    source.write_text(good)
    expect(page.locator(OVERLAY)).to_have_count(0, timeout=30_000)
    expect(page.locator("#value")).to_have_text("Value: 0, doubled: 0")


MODULE_STATE = """from frontage import Signal, h, mount

count = Signal(0)

mount(
    lambda: h.div(
        h.button("+", on_click=lambda ev: count.update(lambda n: n + 1), id="inc"),
        h.span("{label}: ", count, id="value"),
    ),
    "#app",
)
"""


def test_module_level_state_survives_a_swap(editable, page: Page):
    """The signal is module-level, so its value is the user's, not the source's; the counter
    inside a component is rebuilt, which is the same rule seen from the other side."""
    base, app = editable
    source = app / "counter.py"
    source.write_text(MODULE_STATE.format(label="Value"))
    page.goto(f"{base}/index.html")
    expect(page.locator("#value")).to_have_text("Value: 0", timeout=30_000)
    page.click("#inc")
    page.click("#inc")
    expect(page.locator("#value")).to_have_text("Value: 2")

    source.write_text(MODULE_STATE.format(label="Count"))
    expect(page.locator("#value")).to_have_text("Count: 2", timeout=30_000)


VIEW_TRANSITION_APP = """from frontage import A, Route, Router, h, mount

mount(
    Router(
        Route("/", lambda: h.h1("Home", id="home")),
        Route("/next", lambda: h.h1("Next", id="next")),
        root=lambda children: h.div(A("/", "home", id="to-home"), A("/next", "next", id="to-next"), children),
        mode="hash",
        view_transition=True,
    ),
    "#app",
)
"""


def test_a_router_can_commit_inside_a_view_transition(editable, page: Page):
    """`view_transition=True` hands the commit to `document.startViewTransition`, so the
    browser animates one page into the next. The page must change either way — the API is a
    progressive enhancement, and the test proves both halves: it was called, and it worked."""
    base, app = editable
    (app / "counter.py").write_text(VIEW_TRANSITION_APP)
    page.add_init_script(
        "window.__vt = 0;"
        "const original = document.startViewTransition && document.startViewTransition.bind(document);"
        "if (original) document.startViewTransition = (cb) => { window.__vt++; return original(cb); };"
    )
    page.goto(f"{base}/index.html")
    expect(page.locator("#home")).to_be_visible(timeout=30_000)
    page.click("#to-next")
    expect(page.locator("#next")).to_be_visible(timeout=30_000)
    assert page.evaluate("window.__vt") >= 1, "the commit did not go through startViewTransition"
