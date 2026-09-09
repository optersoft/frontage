"""A content page in Chromium: prose from Markdown, and an island that came out of it.

The page is `examples/blog`, prerendered. Nothing in it runs in the browser until a reader
scrolls to the one `::: island` container in one of the posts.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"


@pytest.fixture(scope="module")
def blog():
    out = BUILD / "content-blog"
    if out.exists():
        shutil.rmtree(out)
    command = [sys.executable, "-m", "frontage", "prerender", str(ROOT / "examples" / "blog"), "--out", str(out)]
    subprocess.run(command, check=True, cwd=ROOT, capture_output=True)
    return out


def test_the_posts_are_html_and_the_island_is_not_fetched_until_it_is_seen(server, page: Page, blog):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    asked = []
    page.on("request", lambda r: asked.append(r.url))
    page.set_viewport_size({"width": 900, "height": 600})
    page.goto(f"{server}/build/content-blog/index.html")

    # Three posts, read from disk, checked by a schema and rendered by markdown-it — none of
    # which the browser knows anything about.
    expect(page.locator(".index li")).to_have_count(3)
    expect(page.locator("article")).to_have_count(3)
    expect(page.locator("blockquote")).to_have_count(1)
    # Newest first: the front matter's dates decided the order at build time.
    expect(page.locator(".index li").first).to_contain_text("An island in prose")

    page.wait_for_timeout(500)
    assert [u for u in asked if "/_frontage/" in u and not u.endswith("island.js")] == [], (
        "a page of prose fetched the runtime"
    )

    # The island came out of a `::: island` container in one post's Markdown.
    asked.clear()
    page.locator(".box").scroll_into_view_if_needed()
    page.wait_for_selector("fr-island[data-fr-mounted]", state="attached", timeout=30_000)
    page.click("button:has-text('Useful')")
    expect(page.locator(".box span")).to_have_text(" 1 so far")
    assert len([u for u in asked if u.endswith(".wasm")]) == 1
    assert [u for u in asked if "widgets" in u], "the island's module was not a chunk"
    assert errors == []
