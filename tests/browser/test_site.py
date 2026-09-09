"""A site in Chromium: six pages of HTML, and the one page that boots a runtime."""

import functools
import http.server
import shutil
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"


@pytest.fixture(scope="module")
def site():
    """The example site, built and served **at a root of its own**.

    Not under the suite's server like the other fixtures: a site's links are absolute
    (`/blog/`), because a site is deployed at a root, and serving it from a subdirectory
    would be testing something nobody ships.
    """
    out = BUILD / "site"
    if out.exists():
        shutil.rmtree(out)
    command = [sys.executable, "-m", "frontage", "site", str(ROOT / "examples" / "site"), "--out", str(out), "--quiet"]
    subprocess.run(command, check=True, cwd=ROOT, capture_output=True)

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

    class Threaded(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = Threaded(("127.0.0.1", 0), functools.partial(Quiet, directory=str(out)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_the_pages_are_files_and_the_links_between_them_work(page: Page, site):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    asked = []
    page.on("request", lambda r: asked.append(r.url))
    base = site

    page.goto(f"{base}/")
    expect(page).to_have_title("Notes")
    expect(page.locator(".index li")).to_have_count(3)

    page.click("nav a:has-text('Blog')")
    expect(page).to_have_title("Blog — Notes")
    page.click("nav a:has-text('About')")
    expect(page).to_have_title("About — Notes")
    # The page asked for `site`, so the build handed it one.
    expect(page.locator("main")).to_contain_text("It has 6 pages")

    page.goto(f"{base}/blog/a-site-of-files/")
    expect(page).to_have_title("A site of files — Notes")
    expect(page.locator("blockquote")).to_have_count(1)
    assert [u for u in asked if "/_frontage/" in u] == [], "a page of prose fetched the runtime"
    assert errors == []


def test_the_one_page_with_an_island_boots_the_runtime_and_no_other_does(page: Page, site):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    asked = []
    page.on("request", lambda r: asked.append(r.url))
    page.set_viewport_size({"width": 900, "height": 400})
    page.goto(f"{site}/blog/one-island-per-site/")

    # The island is well down the post, so nothing has asked for a runtime yet. Checked
    # rather than assumed: the loader arms a `visible` island 200px early, so a test that
    # cannot see where the island *is* would pass for the wrong reason on another font.
    top = page.evaluate("() => document.querySelector('.box').getBoundingClientRect().top")
    assert top > 600, f"the island is {top}px down, not below the fold: this cannot prove deferral"
    page.wait_for_timeout(400)
    assert [u for u in asked if "/_frontage/" in u and not u.endswith("island.js")] == []

    page.locator(".box").scroll_into_view_if_needed()
    page.wait_for_selector("fr-island[data-fr-mounted]", state="attached", timeout=30_000)
    page.click("#react")
    expect(page.locator("#react-count")).to_have_text(" 1 so far")
    assert len([u for u in asked if u.endswith(".wasm")]) == 1
    assert [u for u in asked if "widgets" in u], "the island's module was not a chunk"
    assert errors == []
