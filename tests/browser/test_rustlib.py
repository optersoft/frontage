"""`examples/rustlib`: a Rust library of your own, called from Python in the page."""

from playwright.sync_api import Page, expect


def test_the_library_answers_and_the_answers_match_python(server, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/rustlib/index.html")
    expect(page.locator("#mean")).to_be_visible(timeout=30_000)

    # The whole claim of the example: Rust and Python agree, and Rust is much faster at the
    # arithmetic once the numbers are over there.
    mean = page.inner_text("#mean").split()[-1]
    stddev = page.inner_text("#stddev").split()[-1]
    assert f"{mean} and {stddev}" in page.inner_text("#agree")
    ratio = int(page.inner_text("#ratio").split()[-1].rstrip("×"))
    assert ratio >= 2, page.inner_text("#ratio")

    # The crossing is stated separately, because it is the thing that decides the design.
    expect(page.locator("#crossing")).to_contain_text("20,000 crossings")

    # The histogram is recounted in Rust, over numbers it already has.
    expect(page.locator("#bins")).to_have_text("48")
    assert page.locator("#histogram i").count() == 48
    page.click("#more")
    expect(page.locator("#bins")).to_have_text("64")
    assert page.locator("#histogram i").count() == 64
    page.click("#fewer")
    expect(page.locator("#bins")).to_have_text("48")
    assert errors == []
