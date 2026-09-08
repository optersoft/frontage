"""`examples/spectrum`: `frontage.dsp` in a page — an FFT, a spectrogram and a filter."""

from playwright.sync_api import Page, expect


def test_the_signal_is_analysed_in_the_page(server, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/spectrum/index.html")
    expect(page.locator("#rms")).to_be_visible(timeout=45_000)

    # The spectrogram is drawn straight onto the canvas by the library: one frame per column,
    # one bin per row, and none of those numbers ever reached Python.
    size = page.evaluate("() => { const c = document.getElementById('spectrogram'); return [c.width, c.height]; }")
    assert size == [253, 129], size
    expect(page.locator("#rows")).to_contain_text("253")
    expect(page.locator("#bins")).to_contain_text("129")
    # The power spectrum is a chart beside it.
    assert page.locator("canvas").count() >= 2

    loud = float(page.inner_text("#rms").split()[-1])
    assert 0.3 < loud < 1.5, loud

    # Filtering re-runs the whole analysis from the same loaded signal.
    page.click("#filter")
    expect(page.locator("#filter")).to_have_text("filtering")
    expect(page.locator("#rms")).not_to_have_text(f"RMS\n{loud}")
    assert errors == []


def test_a_narrow_band_leaves_almost_nothing(server, page: Page):
    """The filter is real: keep 1,900–2,000 Hz of a signal that has nothing there, and the
    loudness collapses."""
    page.goto(f"{server}/examples/spectrum/index.html")
    expect(page.locator("#rms")).to_be_visible(timeout=45_000)
    before = float(page.inner_text("#rms").split()[-1])

    page.eval_on_selector(
        "#low input", "el => { el.value = 1900; el.dispatchEvent(new Event('input', {bubbles: true})); }"
    )
    page.eval_on_selector(
        "#high input", "el => { el.value = 2000; el.dispatchEvent(new Event('input', {bubbles: true})); }"
    )
    expect(page.locator("#band")).to_have_text("1900–2000 Hz")
    page.click("#filter")
    expect(page.locator("#filter")).to_have_text("filtering")
    after = float(page.inner_text("#rms").split()[-1])
    # A hundred hertz of noise out of two thousand: what is left is a fraction of the whole.
    assert after < before / 3, (before, after)
