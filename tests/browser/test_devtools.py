"""The devtools panel, in Chromium: it is in the page, it stays out of the way, and it reads
the ownership tree from inside the interpreter."""

from playwright.sync_api import Page, expect

PANEL = "#frontage-devtools"


def test_the_panel_is_installed_hidden_and_opens_on_the_shortcut(editable, page: Page):
    base, _ = editable
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{base}/index.html")
    expect(page.locator("#value")).to_have_text("Value: 0, doubled: 0", timeout=30_000)

    # Installed, and invisible until asked for: a dev panel that covers the page is worse
    # than no dev panel.
    expect(page.locator(PANEL)).to_have_count(1, timeout=10_000)
    expect(page.locator(PANEL)).to_be_hidden()

    page.keyboard.press("Control+Shift+D")
    expect(page.locator(PANEL)).to_be_visible()
    body = page.locator(PANEL + "-body")
    expect(body).to_contain_text("#app")
    expect(body).to_contain_text("owners")
    # The counter's own component is in the tree the panel read.
    expect(body).to_contain_text("counter")

    page.keyboard.press("Control+Shift+D")
    expect(page.locator(PANEL)).to_be_hidden()
    assert errors == []


def test_the_panel_is_not_in_a_built_page(editable, page: Page, tmp_path):
    """It is compiled by the dev server and run in the page; a build never sees it."""
    import subprocess
    import sys
    from pathlib import Path

    _, app = editable
    out = tmp_path / "built"
    root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, "-m", "frontage", "build", str(app), "--out", str(out), "--quiet"],
        check=True,
        cwd=root,
    )
    names = [p.name for p in (out / "_frontage").iterdir()]
    assert not any("devtools" in name for name in names), names
