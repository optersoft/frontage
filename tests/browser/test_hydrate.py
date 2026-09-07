"""Prerendered pages hydrate: the HTML is on screen before Python, the app adopts it instead
of rebuilding it, resources do not refetch, and early clicks are replayed."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"


@pytest.fixture(scope="module")
def prerendered():
    """`build/hydrate-<example>/` for the examples this module loads; served at /build/."""
    for name in ("counter", "fetch", "tracker"):
        out = BUILD / f"hydrate-{name}"
        if out.exists():
            shutil.rmtree(out)
        # The command line itself, in a subprocess: Playwright's loop is running in this one.
        command = [sys.executable, "-m", "frontage", "prerender", str(ROOT / "examples" / name), "--out", str(out)]
        subprocess.run(command, check=True, cwd=ROOT, capture_output=True)
    return "/build"


MISMATCH_APP = """import frontage.debug  # the per-node report, in the console
from frontage import Signal, h, mount

count = Signal(0)
mount(lambda: h.div(h.p("n=", count, id="n"), lambda: h.b("hole content", id="hole")), "#app")
"""


@pytest.fixture(scope="module")
def mismatched():
    """`build/hydrate-mismatch/`: a prerendered page whose HTML was edited afterwards, so the
    view finds an `<i>` where it wrote a `<b>`."""
    src = BUILD / "src-mismatch"
    out = BUILD / "hydrate-mismatch"
    for d in (src, out):
        if d.exists():
            shutil.rmtree(d)
    src.mkdir(parents=True)
    # No index.html on purpose: `build` writes one, so this exercises the boot shape the
    # command actually emits rather than a copy of it that can quietly go stale.
    (src / "app.py").write_text(MISMATCH_APP)
    command = [sys.executable, "-m", "frontage", "prerender", str(src), "--out", str(out)]
    subprocess.run(command, check=True, cwd=ROOT, capture_output=True)
    page_html = (out / "index.html").read_text()
    assert '<b id="hole">hole content<!--h--></b>' in page_html
    (out / "index.html").write_text(
        page_html.replace('<b id="hole">hole content<!--h--></b>', "<i>hole content<!--h--></i>")
    )
    return "/build"


def test_debug_import_reports_each_hydration_mismatch(server, page: Page, mismatched):
    warnings = []
    page.on("console", lambda m: warnings.append(m.text) if m.type in ("warning", "error") else None)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}{mismatched}/hydrate-mismatch/index.html")
    expect(page.locator("#n")).to_have_text("n=0", timeout=2_000)
    page.wait_for_function("!document.querySelector('#app').hasAttribute('data-fr-hydrate')", timeout=30_000)
    expect(page.locator("#hole")).to_have_text("hole content")  # rebuilt as the view says
    expect(page.locator("#app i")).to_have_count(0)  # the server's <i> was dropped
    report = [w for w in warnings if w.startswith("hydration:")]
    assert any("2 node(s) differed" in w for w in report), report
    assert any("expected <b>, found <i>" in w for w in report), report
    assert any("dropped <i>" in w for w in report), report
    assert errors == []


def test_counter_hydrates_and_replays_early_clicks(server, page: Page, prerendered):
    warnings = []
    page.on("console", lambda m: warnings.append(m.text) if m.type in ("warning", "error") else None)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}{prerendered}/hydrate-counter/index.html")
    value = page.locator("#value")
    # On screen from the HTML, before any Python runs; tag the node to prove it survives.
    expect(value).to_have_text("Value: 0, doubled: 0", timeout=2_000)
    page.evaluate("document.querySelector('#value').dataset.keep = '1'")
    page.click("#inc")  # queued by the page, replayed once mounted
    expect(value).to_have_text("Value: 1, doubled: 2", timeout=30_000)
    assert page.evaluate("document.querySelector('#value').dataset.keep") == "1"
    page.click("#inc")
    expect(value).to_have_text("Value: 2, doubled: 4")
    expect(page.locator("#parity")).to_have_text("even")
    assert page.evaluate("document.querySelector('#app').hasAttribute('data-fr-hydrate')") is False
    # The fences and the `data-fr-h` hints are gone; the hole markers stay, as in any build.
    fences = page.evaluate(
        "(() => { const w = document.createTreeWalker(document.querySelector('#app'), 128); let n = 0;"
        " while (w.nextNode()) if (w.currentNode.data === '[') n++; return n; })()"
    )
    assert fences == 0
    assert page.evaluate("document.querySelectorAll('[data-fr-h]').length") == 0
    assert errors == [] and not [w for w in warnings if "hydration" in w]


def test_fetch_hydrates_without_refetching(server, page: Page, prerendered):
    states = []
    page.on("console", lambda m: states.append(m.text) if "hydration" in m.text else None)
    page.goto(f"{server}{prerendered}/hydrate-fetch/index.html")
    expect(page.locator("#name")).to_have_text("Ada Lovelace", timeout=2_000)  # from the HTML
    expect(page.locator("#posts")).to_have_text("posts: 3")  # the async memo's value, settled on the server
    expect(page.locator("#state")).to_have_text("state: ready")
    # Assert against what the server sent, not against the live DOM: Python consumes the
    # block on mount, and since 0.9.0 it boots fast enough to win that race.
    served = page.request.get(f"{server}{prerendered}/hydrate-fetch/index.html").text()
    assert "data-fr-data" in served and '"memos":[[' in served
    # Once Python mounts it consumes the data block; the state never leaves ready.
    page.wait_for_function("!document.querySelector('script[data-fr-data]')", timeout=30_000)
    expect(page.locator("#state")).to_have_text("state: ready")
    page.click("#u2")
    expect(page.locator("#name")).to_have_text("Grace Hopper", timeout=10_000)
    expect(page.locator("#posts")).to_have_text("posts: 6")
    assert states == []


def test_tracker_dashboard_hydrates_and_navigates(server, page: Page, prerendered):
    warnings = []
    page.on("console", lambda m: warnings.append(m.text) if "hydration" in m.text else None)
    page.goto(f"{server}{prerendered}/hydrate-tracker/index.html")
    expect(page.locator("#open")).to_have_text("3", timeout=2_000)  # from the HTML, before Python
    expect(page.locator("#high")).to_have_text("high: 2")
    page.wait_for_function("!document.querySelector('#app').hasAttribute('data-fr-hydrate')", timeout=30_000)
    page.click("#to-issues")  # the router took over the prerendered page
    expect(page.locator("#list li")).to_have_count(5, timeout=10_000)
    assert warnings == []
