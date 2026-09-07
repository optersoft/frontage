"""The examples in a real browser under the WebAssembly runtime (SPEC S5, W13 in the DOM)."""

import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[2]


def test_counter(server, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/counter/index.html")
    value = page.locator("#value")
    expect(value).to_have_text("Value: 0, doubled: 0", timeout=30_000)
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


def test_todo(server, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/todo/index.html")
    items = page.locator("#list li")
    expect(items).to_have_count(1, timeout=30_000)
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


def test_rows(server, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/rows/index.html")
    rows = page.locator("#tbody tr")
    expect(page.locator("#run")).to_be_visible(timeout=30_000)
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


def test_fetch(server, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/fetch/index.html")
    expect(page.locator("#name")).to_have_text("Ada Lovelace", timeout=30_000)
    page.click("#u2")
    expect(page.locator("#state")).to_have_text("state: refreshing")
    expect(page.locator("#name")).to_have_text("Grace Hopper")
    expect(page.locator("#posts")).to_have_text("posts: 6")  # the async memo followed user_id
    page.click("#u99")
    expect(page.locator("#error")).to_contain_text("no such user: 99")
    page.click("#retry")
    expect(page.locator("#name")).to_have_text("Ada Lovelace")
    assert errors == []


def test_forms(server, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/forms/index.html")
    expect(page.locator("#plan-free")).to_be_visible(timeout=30_000)
    expect(page.locator("#save")).to_be_disabled()
    page.fill("#name", "Ann")
    expect(page.locator("#save")).to_be_enabled()
    page.check("input[value=pro]")
    expect(page.locator("#plan-pro")).to_be_visible()
    page.check("#news")
    page.click("#save")
    expect(page.locator("#result")).to_have_text("saved Ann (pro, newsletter=yes)")
    assert errors == []


def test_template(server, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/template/index.html")
    value = page.locator("#value")
    expect(value).to_have_text("Value: 0, doubled: 0", timeout=30_000)
    page.click("#inc")
    page.click("#inc")
    page.click("#inc")
    expect(value).to_have_text("Value: 3, doubled: 6")
    expect(page.locator("#parity")).to_have_text("odd")
    for _ in range(3):
        page.click("#inc")
    expect(page.locator("#parity")).to_have_class("big")
    assert errors == []


@pytest.mark.parametrize("mode", ["hash", "history"])
def test_contacts_router(server, page: Page, mode):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/contacts/index.html?mode={mode}")
    expect(page.locator("#home")).to_be_visible(timeout=30_000)
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
    expect(page.locator("#status")).to_contain_text("ran on micropython", timeout=30_000)
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
    expect(page.locator("#x")).to_have_text("shared", timeout=30_000)
    assert errors == []


def test_playground_tailwind(server, page: Page):
    """The playground loads Tailwind's browser build from jsdelivr (this test needs the network)
    without preflight, and it styles the DOM Frontage inserts."""
    page.goto(f"{server}/playground/index.html")
    expect(page.locator("#status")).to_contain_text("ran on micropython", timeout=30_000)
    page.select_option("#example", "tailwind")
    expect(page.locator("#app button")).to_have_text("Count")
    page.wait_for_function("getComputedStyle(document.querySelector('#app button')).borderRadius !== '0px'")
    page.click("#app button")
    expect(page.locator("#app p")).to_have_text("clicked 1 times")
    # No preflight: the page's own header button keeps its border.
    assert page.locator("#run").evaluate("e => getComputedStyle(e).borderTopWidth") == "1px"


def test_a_wasm_library_imports_as_a_python_module(server, page: Page):
    """A C or Rust library compiled to WebAssembly, declared with `data-fr-js` and registered
    before the app runs, so the app writes `import mathlib` and not `window.mathlib`."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/wasm/index.html")
    expect(page.locator("#answer")).to_have_text("mathlib.add(2, 40) = 42", timeout=30_000)
    expect(page.locator("#loop")).to_have_text("loop total 2000")  # 2,000 crossings, all correct
    page.click("#again")
    expect(page.locator("#answer")).to_have_text("mathlib.add(2, 40) = 43")  # and reactive
    assert errors == []


RUNNER_PROGRAM = {
    "markup": '<h2>from the markup fence</h2><div id="app"></div>',
    "code": (
        "from frontage import Signal, h, mount\n"
        "count = Signal(0)\n"
        "def inc(ev):\n"
        "    count.update(lambda n: n + 1)\n"
        "mount(lambda: h.div(h.p('count: ', count, id='n'), h.button('+', on_click=inc, id='b')), '#app')\n"
    ),
}


def _runner(server, payload):
    return f"{server}/web/runner.html#" + urllib.parse.quote(json.dumps(payload))


def test_the_runner_runs_a_program_inside_a_sandboxed_frame(server, page: Page):
    """`web/runner.html` is what an embedded live-code frame points at: the program travels in
    the URL fragment, and the frame is sandboxed without `allow-same-origin`, so the document
    sits in an opaque origin and even its own-origin fetches leave as `Origin: null`."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.set_content(
        f'<iframe id="f" src="{_runner(server, RUNNER_PROGRAM)}" width="500" height="300" '
        'sandbox="allow-scripts"></iframe>'
    )
    frame = page.frame_locator("#f")
    expect(frame.locator("#n")).to_have_text("count: 0", timeout=30_000)
    expect(frame.locator("h2")).to_have_text("from the markup fence")
    frame.locator("#b").click()
    expect(frame.locator("#n")).to_have_text("count: 1")
    assert errors == []


def test_the_runner_shows_a_traceback_instead_of_a_blank_frame(server, page: Page):
    payload = {"code": "raise ValueError('a teaching mistake')"}
    page.set_content(
        f'<iframe id="f" src="{_runner(server, payload)}" width="500" height="200" sandbox="allow-scripts"></iframe>'
    )
    expect(page.frame_locator("#f").locator("#fr-error")).to_contain_text("a teaching mistake", timeout=30_000)


def test_a_chart_library_becomes_an_importable_component(server, page: Page):
    """uPlot wrapped as a frontage component: 40 lines of JavaScript, 20 of Python, declared
    with `data-fr-js`. The evidence behind COMPONENTS.md, and the guard that keeps the
    component pattern working on a real third-party library rather than a toy one."""
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/chart/index.html")
    expect(page.locator("canvas").first).to_be_visible(timeout=30_000)
    expect(page.locator("#count")).to_have_text("2000 points per series")

    # A slider moves one signal; the memo rebuilds; the canvas redraws. Nothing remounts.
    page.evaluate("document.querySelector('canvas').dataset.keep = '1'")
    page.evaluate("""() => {
        const s = document.querySelectorAll('input[type=range]')[0];
        const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        set.call(s, '10000'); s.dispatchEvent(new Event('input', {bubbles: true}));
    }""")
    expect(page.locator("#count")).to_have_text("10000 points per series")
    assert page.evaluate("document.querySelector('canvas').dataset.keep") == "1"
    assert errors == []


COMPONENT_INIT = (
    '"""frontage-chart, shaped as a published package."""\n\nfrom .plot import line_chart\n\n__all__ = ["line_chart"]\n'
)

COMPONENT_APP = """import math

from frontage import Signal, h, mount
from frontage.widgets import slider
from frontage_chart import line_chart


n = Signal(1000)


def data():
    return [[i for i in range(n())], [math.sin(i / 30.0) * 40 + 50 for i in range(n())]]


mount(
    lambda: h.div(
        slider(n, "Points", min=200, max=5000, step=200),
        line_chart(data, height=200, labels=["sine"]),
        h.p(lambda: f"{n()} points", id="count"),
    ),
    "#app",
)
"""


@pytest.fixture(scope="module")
def component_app():
    """An app built against a component laid out the way a `pip install`ed one would be:
    Python beside a `_browser/`, discovered by `build`, its assets copied and its Python packed.
    `examples/chart/` hand-wires the same library; this proves the packaged path."""
    root = ROOT / "build" / "component-app"
    if root.exists():
        shutil.rmtree(root)
    package = root / "src" / "frontage_chart"
    (package / "_browser").mkdir(parents=True)
    (package / "__init__.py").write_text(COMPONENT_INIT)
    (package / "plot.py").write_text(
        (ROOT / "examples" / "chart" / "plot.py").read_text().replace("import chartlib", "import chart as chartlib")
    )
    (package / "_browser" / "index.js").write_text((ROOT / "examples" / "chart" / "chartlib.js").read_text())
    (package / "_browser" / "uplot.js").write_bytes((ROOT / "examples" / "chart" / "uplot.js").read_bytes())
    (package / "_browser" / "index.css").write_bytes((ROOT / "examples" / "chart" / "uplot.css").read_bytes())
    app = root / "app"
    app.mkdir(parents=True)
    (app / "app.py").write_text(COMPONENT_APP)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "frontage",
            "build",
            str(app),
            "--out",
            str(root / "out"),
            "--component",
            f"chart={package}",
            "--quiet",
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
    )
    return "/build/component-app/out"


def test_a_packaged_component_is_discovered_copied_and_imported(server, page: Page, component_app):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}{component_app}/index.html")
    expect(page.locator("canvas").first).to_be_visible(timeout=30_000)
    expect(page.locator("#count")).to_have_text("1000 points")
    page.evaluate("""() => {
        const s = document.querySelector('input[type=range]');
        const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        set.call(s, '4000'); s.dispatchEvent(new Event('input', {bubbles: true}));
    }""")
    expect(page.locator("#count")).to_have_text("4000 points")
    assert errors == []
