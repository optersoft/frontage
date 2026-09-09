"""Three languages in Chromium: switching between them, on the page you are on, with no runtime."""

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
def locales():
    """`examples/locales`, built and served at a root of its own (its links are absolute)."""
    out = BUILD / "locales"
    if out.exists():
        shutil.rmtree(out)
    command = [
        sys.executable,
        "-m",
        "frontage",
        "site",
        str(ROOT / "examples" / "locales"),
        "--out",
        str(out),
        "--quiet",
    ]
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


def test_the_switcher_stays_on_the_page_you_are_on(page: Page, locales):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    asked = []
    page.on("request", lambda r: asked.append(r.url))

    page.goto(f"{locales}/")
    expect(page).to_have_title("Tres")
    assert page.evaluate("() => document.documentElement.lang") == "en"

    page.click("nav.locales a:has-text('Español')")
    assert page.url.endswith("/es/")
    assert page.evaluate("() => document.documentElement.lang") == "es"

    # Down to a post, then across the languages: the switcher moves you sideways, never home.
    page.click("nav a:has-text('Notas')")
    page.click("ul.index a")
    assert page.url.endswith("/es/blog/one-tree/")
    expect(page).to_have_title("Un árbol, tres idiomas")

    page.click("nav.locales a:has-text('Català')")
    assert page.url.endswith("/ca/blog/one-tree/")
    expect(page).to_have_title("Un arbre, tres idiomes")
    assert page.evaluate("() => document.documentElement.lang") == "ca"

    page.click("nav.locales a:has-text('English')")
    assert page.url.endswith("/blog/one-tree/")
    expect(page).to_have_title("One tree, three languages")

    # The language you are reading is not a link to itself.
    expect(page.locator("nav.locales .current")).to_have_text("English")
    assert [u for u in asked if "/_frontage/" in u] == [], "a switcher of links fetched a runtime"
    assert errors == []


def test_a_crawler_is_told_the_three_pages_are_one_page(page: Page, locales):
    page.goto(f"{locales}/es/blog/one-tree/")
    found = page.eval_on_selector_all(
        'link[rel="alternate"]', "els => els.map(e => [e.hreflang, new URL(e.href).pathname])"
    )
    assert found == [
        ["en", "/blog/one-tree/"],
        ["es", "/es/blog/one-tree/"],
        ["ca", "/ca/blog/one-tree/"],
        ["x-default", "/blog/one-tree/"],
    ]
