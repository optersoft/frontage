"""End to end, in Chromium: the page asks, the server answers, nothing big travels."""

import json
import urllib.request

from playwright.sync_api import Page, expect


def test_the_dashboard_fills_from_the_server_and_a_signal_reasks(trips, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    requests = []
    page.on("request", lambda r: requests.append(r.url) if "/api/" in r.url else None)

    page.goto(f"{trips}/")
    expect(page.locator("#m-trips .fr-metric-value")).to_have_text("500,000", timeout=30_000)
    expect(page.locator("canvas").first).to_be_visible()
    expect(page.locator("#grid .fr-table-footer")).to_have_text("500,000 rows")
    expect(page.locator("#grid .fr-tr:not(.fr-head)").first).to_contain_text("2024-")

    # Four questions, none of them the dataset.
    asked = [u.split("/api/")[1] for u in requests]
    assert sorted(a.split("?")[0] for a in asked if not a.startswith("events")) == [
        "frame/by_hour",
        "frame/daily",
        "frame/summary",
        "rows/trips",
    ]
    assert any(a.startswith("events") for a in asked)

    # A borough: the four refetch with the new argument and the page updates in place.
    before = len(requests)
    page.select_option("#borough", "Queens")
    expect(page.locator("#m-trips .fr-metric-value")).not_to_have_text("500,000")
    trips_in_queens = int(page.locator("#m-trips .fr-metric-value").inner_text().replace(",", ""))
    assert 80_000 < trips_in_queens < 100_000  # 18% of 500k, give or take the dice
    expect(page.locator("#grid .fr-table-footer")).to_have_text(f"{trips_in_queens:,} rows")
    assert all("borough=Queens" in u for u in requests[before:] if "/api/" in u and "events" not in u)
    assert errors == []


def test_the_grid_asks_for_a_window_and_the_server_sorts(trips, page: Page):
    page.goto(f"{trips}/")
    expect(page.locator("#grid .fr-table-footer")).to_have_text("500,000 rows", timeout=30_000)
    rows = page.locator("#grid .fr-tr:not(.fr-head)")
    assert rows.count() <= 40

    # Sort by fare, descending: two clicks, two requests, and the top row is the priciest.
    fare = page.locator("#grid .fr-th", has_text="Fare")
    fare.click()
    fare.click()
    expect(fare).to_have_class("fr-th fr-sorted")
    expect(fare).to_contain_text("▾")
    page.wait_for_function(
        "() => parseFloat(document.querySelector('#grid .fr-rows .fr-tr').children[5].textContent) > 60"
    )

    # Scroll far into the frame: the elements do not follow the row count, and the rows sit
    # where the server put them. (Chromium serialises the inline style as
    # `translateY(1.27996e+07px)`, so parse it rather than match it.)
    page.evaluate(
        "() => { const v = document.querySelector('#grid .fr-viewport'); v.scrollTop = 32 * 400000; v.dispatchEvent(new Event('scroll')); }"
    )
    page.wait_for_function(
        "() => parseFloat(document.querySelector('#grid .fr-rows .fr-tr').style.transform.slice(11)) > 12_000_000"
    )
    assert rows.count() <= 40

    # Search goes to the server too, and the count is the server's.
    page.fill("#search", "Staten")
    expect(page.locator("#grid .fr-table-footer")).not_to_have_text("500,000 rows", timeout=10_000)
    count = int(page.locator("#grid .fr-table-footer").inner_text().split()[0].replace(",", ""))
    assert 15_000 < count < 25_000


def test_a_change_on_the_server_reaches_the_page_without_a_reload(trips, page: Page):
    page.goto(f"{trips}/")
    expect(page.locator("#m-trips .fr-metric-value")).to_have_text("500,000", timeout=30_000)
    with urllib.request.urlopen(urllib.request.Request(f"{trips}/demo/append?n=2500", method="POST")) as r:
        assert json.load(r)["rows"] == 502_500
    expect(page.locator("#m-trips .fr-metric-value")).to_have_text("502,500", timeout=10_000)
    expect(page.locator("#grid .fr-table-footer")).to_have_text("502,500 rows")
