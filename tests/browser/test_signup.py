"""frontage-schema in Chromium: the form's messages appear as the visitor types, the submit
waits for a clean record, and the same schema reports a pasted document by path. Built with
the real `frontage build`, served as the static directory it is."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "signup"
sys.path.insert(0, str(ROOT / "tests"))


@pytest.fixture(scope="module")
def signup(tmp_path_factory):
    from live import free_port

    out = tmp_path_factory.mktemp("signup")
    subprocess.run([sys.executable, "-m", "frontage", "build", str(EXAMPLE), "--out", str(out), "--quiet"], check=True)
    assert (out / "_frontage" / "components" / "schema" / "index.js").is_file(), "the component was not discovered"
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=out,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import socket

    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("the static server did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait()


def test_the_form_speaks_when_typed_in_and_submits_a_parsed_record(signup, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{signup}/")
    expect(page.locator("#name")).to_be_visible(timeout=30_000)

    # Nothing is said before the visitor types, even though the record is invalid.
    expect(page.locator("#e-name")).to_have_text("")
    expect(page.locator("#save")).to_be_disabled()

    page.fill("#email", "nope")
    expect(page.locator("#e-email")).to_have_text("not an email address")
    expect(page.locator("#e-name")).to_have_text("")  # untouched: still silent

    page.fill("#email", "ada@example.com")
    expect(page.locator("#e-email")).to_have_text("")
    page.fill("#name", "  Ada ")
    page.fill("#age", "36")
    page.fill("#website", "example.com")
    expect(page.locator("#e-website")).to_have_text("not a URL")
    expect(page.locator("#save")).to_be_disabled()
    page.fill("#website", "")
    expect(page.locator("#save")).to_be_enabled()

    page.click("#save")
    expect(page.locator("#saved")).to_contain_text('"age": 36')
    # Parsed, not compared as text: MicroPython's `json.dumps` writes the keys in its own order.
    assert json.loads(page.locator("#saved").inner_text()) == {
        "name": "Ada",  # stripped, and the age is an int though the input handed over a string
        "email": "ada@example.com",
        "age": 36,
        "role": "user",
        "website": None,
    }
    assert errors == []


def test_a_submit_on_an_untouched_form_shows_every_message(signup, page: Page):
    page.goto(f"{signup}/")
    expect(page.locator("#name")).to_be_visible(timeout=30_000)
    page.evaluate("document.querySelector('form').requestSubmit()")
    expect(page.locator("#e-name")).to_have_text("at least 1 characters")
    expect(page.locator("#e-email")).to_have_text("not an email address")
    expect(page.locator("#saved")).to_have_count(0)


def test_the_same_schema_reports_a_pasted_document_by_path(signup, page: Page):
    page.goto(f"{signup}/")
    expect(page.locator("#check")).to_be_visible(timeout=30_000)
    page.click("#check")
    expect(page.locator("#verdict")).to_have_text("4 errors")
    items = page.locator("#report li")
    expect(items).to_have_count(4)
    expect(items.nth(0)).to_have_text("$[1].name: at least 1 characters")
    expect(items.nth(1)).to_have_text("$[1].email: not an email address")
    expect(items.nth(2)).to_have_text("$[1].age: must be greater than 0")
    expect(items.nth(3)).to_have_text("$[1].role: must be one of 'admin', 'user'")

    page.fill("#json", '[{"name": "Ada", "email": "ada@example.com"}]')
    page.click("#check")
    expect(page.locator("#verdict")).to_have_text("valid")
    expect(items).to_have_count(0)

    page.fill("#json", "{not json")
    page.click("#check")
    expect(page.locator("#verdict")).to_have_text("1 errors")
