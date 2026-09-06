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


def _bundle():
    found = sorted(ROOT.glob("tools/pyscript/*/pyscript"))
    return found[-1] if found else None


@pytest.fixture(scope="module")
def prerendered():
    """`build/hydrate-<example>/` for the examples this module loads; served at /build/."""
    bundle = _bundle()
    if bundle is None:
        pytest.skip("no local PyScript: run `mk pyscript.fetch`")
    for name in ("counter", "fetch"):
        out = BUILD / f"hydrate-{name}"
        if out.exists():
            shutil.rmtree(out)
        # The command line itself, in a subprocess: Playwright's loop is running in this one.
        command = [sys.executable, "-m", "frontage", "prerender", str(ROOT / "examples" / name), "--out", str(out)]
        subprocess.run(command + ["--pyscript", str(bundle)], check=True, cwd=ROOT, capture_output=True)
    return "/build"


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
def test_counter_hydrates_and_replays_early_clicks(server, page: Page, interpreter, prerendered):
    warnings = []
    page.on("console", lambda m: warnings.append(m.text) if m.type in ("warning", "error") else None)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}{prerendered}/hydrate-counter/index.html?type={interpreter}")
    value = page.locator("#value")
    # On screen from the HTML, before any Python runs; tag the node to prove it survives.
    expect(value).to_have_text("Value: 0, doubled: 0", timeout=2_000)
    page.evaluate("document.querySelector('#value').dataset.keep = '1'")
    page.click("#inc")  # queued by the page, replayed once mounted
    expect(value).to_have_text("Value: 1, doubled: 2", timeout=60_000)
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


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
def test_fetch_hydrates_without_refetching(server, page: Page, interpreter, prerendered):
    states = []
    page.on("console", lambda m: states.append(m.text) if "hydration" in m.text else None)
    page.goto(f"{server}{prerendered}/hydrate-fetch/index.html?type={interpreter}")
    expect(page.locator("#name")).to_have_text("Ada Lovelace", timeout=2_000)  # from the HTML
    expect(page.locator("#state")).to_have_text("state: ready")
    assert page.evaluate("!!document.querySelector('script[data-fr-data]')") is True
    # Once Python mounts it consumes the data block; the state never leaves ready.
    page.wait_for_function("!document.querySelector('script[data-fr-data]')", timeout=60_000)
    expect(page.locator("#state")).to_have_text("state: ready")
    page.click("#u2")
    expect(page.locator("#name")).to_have_text("Grace Hopper", timeout=10_000)
    assert states == []
