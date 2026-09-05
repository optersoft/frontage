"""The package imports under both browser interpreters, served from a local PyScript.

Needs `tools/pyscript/<version>/` (run `mk pyscript.fetch`) and a Chromium from
`uv run playwright install chromium`. Every test here starts its own server, so any one
of them can run alone.
"""

import re

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
def test_package_imports_in_the_browser(server, page: Page, interpreter):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/hello/index.html?type={interpreter}")
    expected = "micropython" if interpreter == "mpy" else "pyodide"
    expect(page.locator("#app")).to_contain_text(re.compile(rf"Frontage \S+ on {expected}"), timeout=60_000)
    expect(page.locator("#app")).to_contain_text("<p>Hello from the string renderer</p>")
    expect(page.locator("#app")).to_contain_text("reactive: [2, 42] store: ['Ann', 'Bob']")
    assert errors == []
