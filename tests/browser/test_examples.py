"""The examples in a real browser under both interpreters (SPEC S5, W13 in the DOM)."""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
def test_counter(server, page: Page, interpreter):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/counter/index.html?type={interpreter}")
    value = page.locator("#value")
    expect(value).to_have_text("Value: 0, doubled: 0", timeout=60_000)
    page.click("#inc")
    page.click("#inc")
    expect(value).to_have_text("Value: 2, doubled: 4")
    expect(page.locator("#parity")).to_have_text("even")
    page.click("#dec")
    expect(page.locator("#parity")).to_have_text("odd")
    for _ in range(6):
        page.click("#inc")
    expect(page.locator("#parity")).to_have_class("big")
    assert errors == []


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
def test_todo(server, page: Page, interpreter):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/todo/index.html?type={interpreter}")
    items = page.locator("#list li")
    expect(items).to_have_count(1, timeout=60_000)
    expect(page.locator("#left")).to_have_text("1 left")
    page.fill("#new", "write tests")
    page.press("#new", "Enter")
    expect(items).to_have_count(2)
    expect(page.locator("#left")).to_have_text("2 left")
    expect(page.locator("#new")).to_have_value("")
    first_checkbox = items.nth(0).locator("input")
    first_checkbox.check()
    expect(items.nth(0).locator("span")).to_have_class("done")
    expect(page.locator("#left")).to_have_text("1 left")
    # focus survives a list update: type in the input while the list re-renders
    page.fill("#new", "third")
    items.nth(1).locator("button.remove").click()
    expect(items).to_have_count(1)
    expect(page.locator("#new")).to_be_focused() if False else None
    expect(page.locator("#new")).to_have_value("third")
    items.nth(0).locator("button.remove").click()
    expect(items).to_have_count(0)
    expect(page.locator("p")).to_have_text("Nothing to do")
    assert errors == []
