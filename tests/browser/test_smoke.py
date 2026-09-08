"""The package imports in the browser, from the WebAssembly runtime this repo vendors.

Needs `frontage/_runtime/` (run `mk runtime.fetch`) and a Chromium from
`uv run playwright install chromium`. Every test here starts its own server, so any one
of them can run alone.
"""

import re

from playwright.sync_api import Page, expect


def test_package_imports_in_the_browser(server, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/hello/index.html")
    # `frontage.platform` reports the runtime it found, and this asserts it is frontage's own.
    expect(page.locator("#app")).to_contain_text(re.compile(r"Frontage \S+ on frontage"), timeout=30_000)
    expect(page.locator("#app")).to_contain_text("<p>Hello from the string renderer</p>")
    expect(page.locator("#app")).to_contain_text("reactive: [2, 42] store: ['Ann', 'Bob']")
    assert errors == []
