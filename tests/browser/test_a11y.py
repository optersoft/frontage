"""Focus, in Chromium: where the next Tab starts after a navigation."""

from playwright.sync_api import Page, expect

FOCUS_APP = """from frontage import A, Route, Router, h, mount

mount(
    Router(
        Route("/", lambda: h.h1("Home", id="home")),
        Route("/next", lambda: h.h1("Next", id="next")),
        root=lambda children: h.div(
            h.nav(A("/", "home", id="to-home"), A("/next", "next", id="to-next")),
            h.main(children, id="main"),
        ),
        mode="hash",
        focus="main",
    ),
    "#app",
)
"""


def test_focus_moves_into_the_new_content(editable, page: Page):
    base, app = editable
    (app / "counter.py").write_text(FOCUS_APP)
    page.goto(f"{base}/index.html")
    expect(page.locator("#home")).to_be_visible(timeout=30_000)

    page.click("#to-next")
    expect(page.locator("#next")).to_be_visible(timeout=30_000)
    assert page.evaluate("document.activeElement && document.activeElement.id") == "main"
    # Made focusable to receive it, and only because it was not already.
    assert page.get_attribute("main", "tabindex") == "-1"
