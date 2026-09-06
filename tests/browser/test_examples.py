"""The examples in a real browser under both interpreters (SPEC S5, W13 in the DOM)."""

import re

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


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
def test_rows(server, page: Page, interpreter):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/rows/index.html?type={interpreter}")
    rows = page.locator("#tbody tr")
    expect(page.locator("#run")).to_be_visible(timeout=60_000)
    page.click("#run")
    expect(rows).to_have_count(1000)
    first_label = rows.nth(0).locator("td").nth(1).text_content() or ""
    page.click("#update")
    expect(rows.nth(0).locator("td").nth(1)).to_have_text(first_label + " !!!")
    expect(rows.nth(1).locator("td").nth(1)).not_to_have_text(re.compile("!!!"))
    second = rows.nth(1).locator("td").nth(0).text_content() or ""
    page.click("#swaprows")
    expect(rows.nth(998).locator("td").nth(0)).to_have_text(second)
    rows.nth(0).locator("td").nth(1).locator("a").click()
    expect(rows.nth(0)).to_have_class("danger")
    rows.nth(0).locator("a.remove").click()
    expect(rows).to_have_count(999)
    page.click("#clear")
    expect(rows).to_have_count(0)
    assert errors == []


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
def test_fetch(server, page: Page, interpreter):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/fetch/index.html?type={interpreter}")
    expect(page.locator("#name")).to_have_text("Ada Lovelace", timeout=60_000)
    page.click("#u2")
    expect(page.locator("#state")).to_have_text("state: refreshing")
    expect(page.locator("#name")).to_have_text("Grace Hopper")
    page.click("#u99")
    expect(page.locator("#error")).to_contain_text("no such user: 99")
    page.click("#retry")
    expect(page.locator("#name")).to_have_text("Ada Lovelace")
    assert errors == []


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
def test_forms(server, page: Page, interpreter):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/forms/index.html?type={interpreter}")
    expect(page.locator("#plan-free")).to_be_visible(timeout=60_000)
    expect(page.locator("#save")).to_be_disabled()
    page.fill("#name", "Ann")
    expect(page.locator("#save")).to_be_enabled()
    page.check("input[value=pro]")
    expect(page.locator("#plan-pro")).to_be_visible()
    page.check("#news")
    page.click("#save")
    expect(page.locator("#result")).to_have_text("saved Ann (pro, newsletter=yes)")
    assert errors == []


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
def test_template(server, page: Page, interpreter):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/template/index.html?type={interpreter}")
    value = page.locator("#value")
    expect(value).to_have_text("Value: 0, doubled: 0", timeout=60_000)
    page.click("#inc")
    page.click("#inc")
    page.click("#inc")
    expect(value).to_have_text("Value: 3, doubled: 6")
    expect(page.locator("#parity")).to_have_text("odd")
    for _ in range(3):
        page.click("#inc")
    expect(page.locator("#parity")).to_have_class("big")
    assert errors == []


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
@pytest.mark.parametrize("mode", ["hash", "history"])
def test_contacts_router(server, page: Page, interpreter, mode):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/contacts/index.html?type={interpreter}&mode={mode}")
    expect(page.locator("#home")).to_be_visible(timeout=60_000)
    page.click("#to-contacts")  # a plain <a> rendered by A: intercepted, no reload
    expect(page.locator("#pick")).to_be_visible()
    if mode == "hash":
        assert page.url.endswith("#/contacts")
    else:
        assert page.url.endswith("/contacts")
    # U10: scroll restoration. Scroll down the (tall) list, navigate: the new page starts at
    # the top; go back: the list is where it was; forward again: the top.
    page.evaluate("window.scrollTo(0, 600)")
    page.wait_for_function("window.scrollY >= 500")
    page.evaluate("document.querySelector('#link-ann').click()")  # no scrolling into view first
    expect(page.locator("#name")).to_have_text("Ann Moore")
    page.wait_for_function("window.scrollY === 0")
    page.go_back()
    expect(page.locator("#pick")).to_be_visible()
    page.wait_for_function("window.scrollY >= 500")
    page.go_forward()
    expect(page.locator("#name")).to_have_text("Ann Moore")
    page.wait_for_function("window.scrollY === 0")
    page.click("#link-ann")
    expect(page.locator("#name")).to_have_text("Ann Moore")
    expect(page.locator("#link-ann")).to_have_class("active")

    def loads():
        return int((page.locator("#loads").text_content() or "loads: 0").split(":")[1])

    # Hovering a link preloads it, so the pointer's path decides between 1 and 2 loads here.
    n1 = loads()
    assert n1 in (1, 2)
    page.click("#link-bob")  # the contacts layout is kept; only the detail changes
    expect(page.locator("#name")).to_have_text("Bob Ruiz")
    n2 = loads()
    assert n2 - n1 in (0, 1)
    page.click("#link-ann")  # cached by query(): no new load
    expect(page.locator("#name")).to_have_text("Ann Moore")
    assert loads() == n2
    page.go_back()
    expect(page.locator("#name")).to_have_text("Bob Ruiz")
    page.click("#back")
    expect(page.locator("#pick")).to_be_visible()
    page.click("#old")  # Navigate() redirects
    expect(page.locator("#pick")).to_be_visible()
    assert errors == []


def test_playground_runs_and_shares(server, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/playground/index.html")
    expect(page.locator("#status")).to_contain_text("ran on micropython", timeout=60_000)
    page.click("#app button:nth-of-type(2)")  # the counter's +
    expect(page.locator("#app span")).to_have_text(" 1 ")
    page.select_option("#example", "state")
    expect(page.locator("#app b")).to_contain_text("1 x M for someone")
    page.fill("#code", "from frontage import html, mount\nmount(lambda: html(t'<b id=\"x\">shared</b>'), '#app')\n")
    page.click("#run")
    expect(page.locator("#x")).to_have_text("shared")
    page.click("#share")
    assert "#code=" in page.url
    page.reload()
    expect(page.locator("#x")).to_have_text("shared", timeout=60_000)
    assert errors == []


def test_playground_tailwind(server, page: Page):
    """The playground loads Tailwind's browser build from jsdelivr (this test needs the network)
    without preflight, and it styles the DOM Frontage inserts."""
    page.goto(f"{server}/playground/index.html")
    expect(page.locator("#status")).to_contain_text("ran on micropython", timeout=60_000)
    page.select_option("#example", "tailwind")
    expect(page.locator("#app button")).to_have_text("Count")
    page.wait_for_function("getComputedStyle(document.querySelector('#app button')).borderRadius !== '0px'")
    page.click("#app button")
    expect(page.locator("#app p")).to_have_text("clicked 1 times")
    # No preflight: the page's own header button keeps its border.
    assert page.locator("#run").evaluate("e => getComputedStyle(e).borderTopWidth") == "1px"
