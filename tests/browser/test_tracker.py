"""The tracker example end to end: routes, a keyed list kept by reconcile, a memo-loaded
detail, a transactional done toggle (Optimistic + transition), a Portal modal, an action that
redirects, a State-backed form, an Errored boundary, and the not-found route. Both interpreters."""

import pytest
from playwright.sync_api import Page, expect


def requests(page):
    return int((page.locator("#requests").text_content() or "requests: 0").split(":")[1])


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
def test_tracker(server, page: Page, interpreter):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/tracker/index.html?type={interpreter}")

    # Dashboard: memos over a Resource; the interval ticks.
    expect(page.locator("#open")).to_have_text("3", timeout=90_000)
    expect(page.locator("#done")).to_have_text("2")
    expect(page.locator("#high")).to_have_text("high: 2")
    expect(page.locator("#tick")).to_contain_text("for 1 s", timeout=5_000)

    # The list: the store, For(key="id"), the search signal and the status in the query string.
    page.click("#to-issues")
    expect(page.locator("#pick")).to_be_visible()
    expect(page.locator("#list li")).to_have_count(5)
    page.fill("#search", "swap")
    expect(page.locator("#list li")).to_have_count(1)
    page.fill("#search", "zzz")
    expect(page.locator("#empty")).to_be_visible()
    page.fill("#search", "")
    page.select_option("#status", "done")
    page.wait_for_function("location.href.includes('status=done')")
    expect(page.locator("#list li")).to_have_count(2)
    page.select_option("#status", "all")
    expect(page.locator("#list li")).to_have_count(5)

    # The detail: an async memo over the query the route preloaded; the toggle is a write the
    # detail and the list both wait for, shown optimistically meanwhile.
    page.click("#issue-2")
    expect(page.locator("#title")).to_have_text("For flickers on a swap")
    expect(page.locator("#state")).to_have_text("open")
    page.click("#toggle")
    expect(page.locator("#state")).to_have_text("done")  # at once: the Optimistic value
    expect(page.locator("#toggle")).to_have_text("mark open")
    expect(page.locator("#list li.done")).to_have_count(3, timeout=10_000)  # the list refetched and merged
    expect(page.locator("#state")).to_have_text("done")  # the committed data agrees
    page.click("#toggle")
    expect(page.locator("#list li.done")).to_have_count(2, timeout=10_000)
    expect(page.locator("#state")).to_have_text("open")

    # The query cache: a detail already loaded costs no request.
    page.click("#issue-1")
    expect(page.locator("#title")).to_have_text("Signals lose a subscriber after dispose")
    n = requests(page)
    page.click("#issue-2")
    expect(page.locator("#title")).to_have_text("For flickers on a swap")
    assert requests(page) == n

    # The error path: a failed load reaches the Errored boundary, the rest of the app stands.
    page.evaluate("location.hash = '#/issues/13'")
    expect(page.locator("#error")).to_contain_text("cursed", timeout=10_000)
    expect(page.locator("#list li")).to_have_count(5)
    page.click("#retry")
    expect(page.locator("#error")).to_contain_text("cursed", timeout=10_000)

    # The modal is a Portal into #modal; the delete is an action that redirects.
    page.evaluate("location.hash = '#/issues/3'")
    expect(page.locator("#title")).to_have_text("Document the insert rules")
    page.click("#delete")
    expect(page.locator("#modal #dialog")).to_be_visible()
    page.click("#cancel-delete")
    expect(page.locator("#dialog")).to_have_count(0)
    page.click("#delete")
    page.click("#confirm-delete")
    expect(page.locator("#pick")).to_be_visible(timeout=10_000)
    expect(page.locator("#list li")).to_have_count(4)

    # The form: a State with a computed validity, widgets, ActionForm, Redirect to the new issue.
    page.click("#nav-new")
    expect(page.locator("#create")).to_be_disabled()
    page.fill("#new-title", "Write the tracker test")
    page.select_option("#new-priority", "high")
    expect(page.locator("#create")).to_be_enabled()
    page.click("#create")
    expect(page.locator("#title")).to_have_text("Write the tracker test", timeout=10_000)
    expect(page.locator("#priority")).to_have_text("priority: high")
    expect(page.locator("#list li")).to_have_count(5)
    expect(page.locator("#list li .tag.high")).to_have_count(3)

    page.evaluate("location.hash = '#/nowhere'")
    expect(page.locator("#missing")).to_be_visible()
    assert errors == []
