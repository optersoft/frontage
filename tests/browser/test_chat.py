"""frontage.chat in Chromium, against its real server half: a POST, an answer that arrives
token by token, and a log that is not rebuilt while it does.

Built with the real `frontage build` and served by the example's own uvicorn — one process,
one port, no CORS — which is the deployment the chapter teaches.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "chat"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def chat(tmp_path_factory):
    pytest.importorskip("fastapi")
    out = tmp_path_factory.mktemp("chat")
    subprocess.run([sys.executable, "-m", "frontage", "build", str(EXAMPLE), "--out", str(out), "--quiet"], check=True)
    assert (out / "_frontage" / "components" / "chat" / "index.js").is_file(), "the component was not discovered"
    port = _free_port()
    env = dict(os.environ, CHAT_STATIC=str(out))
    env.pop("OPENAI_API_KEY", None)  # the canned model, so this test is offline and repeatable
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app", "--app-dir", str(EXAMPLE), "--port", str(port)]
        + ["--log-level", "warning"],
        env=env,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("the chat server did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait()


def test_the_answer_arrives_a_word_at_a_time(chat, page: Page):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{chat}/")
    expect(page.locator(".fr-chat-text")).to_be_visible(timeout=30_000)

    page.fill(".fr-chat-text", "what is a signal?")
    page.click(".fr-chat-send")

    # The reader's turn is on screen at once — it did not wait for the server.
    expect(page.locator(".fr-msg-user .fr-msg-body")).to_have_text("what is a signal?")
    expect(page.locator(".fr-chat-text")).to_have_value("")
    expect(page.locator(".fr-chat-send")).to_be_disabled()

    body = page.locator(".fr-msg-assistant .fr-msg-body")
    expect(body).to_contain_text("A signal is a value", timeout=10_000)
    partial = body.inner_text()
    expect(body).to_contain_text("just the text node", timeout=10_000)
    assert len(body.inner_text()) > len(partial), "the answer did not grow: it was not streamed"

    expect(page.locator(".fr-chat-send")).to_be_enabled()
    assert errors == []


def test_the_earlier_bubbles_are_not_rebuilt_while_an_answer_streams(chat, page: Page):
    """The claim the component exists to make. A DOM node is tagged from the test's side, and
    if the log were rebuilt for each token the tag would be gone with the node."""
    page.goto(f"{chat}/")
    expect(page.locator(".fr-chat-text")).to_be_visible(timeout=30_000)

    page.fill(".fr-chat-text", "first")
    page.click(".fr-chat-send")
    expect(page.locator(".fr-chat-send")).to_be_enabled(timeout=15_000)
    page.evaluate("document.querySelector('.fr-msg-user .fr-msg-body').dataset.mark = 'kept'")

    page.fill(".fr-chat-text", "second")
    page.click(".fr-chat-send")
    expect(page.locator(".fr-msg-assistant").nth(1)).to_contain_text("A signal", timeout=15_000)
    expect(page.locator(".fr-chat-send")).to_be_enabled(timeout=15_000)

    assert page.evaluate("document.querySelector('.fr-msg-user .fr-msg-body').dataset.mark") == "kept"


def test_a_rating_is_kept_on_the_turn_it_was_given(chat, page: Page):
    page.goto(f"{chat}/")
    expect(page.locator(".fr-chat-text")).to_be_visible(timeout=30_000)
    page.fill(".fr-chat-text", "hello")
    page.click(".fr-chat-send")
    expect(page.locator(".fr-chat-send")).to_be_enabled(timeout=15_000)

    page.click("[aria-label='Good answer']")
    expect(page.locator(".fr-rate").first).to_have_class("fr-rate fr-on")

    page.fill(".fr-chat-text", "again")
    page.click(".fr-chat-send")
    expect(page.locator(".fr-chat-send")).to_be_enabled(timeout=15_000)
    expect(page.locator(".fr-rate").first).to_have_class("fr-rate fr-on")  # still on the first turn
    expect(page.locator(".fr-feedback").nth(1).locator(".fr-rate").first).to_have_class("fr-rate")


def test_the_route_refuses_a_conversation_it_does_not_like(chat, page: Page):
    response = page.request.post(f"{chat}/api/chat", data={"messages": [{"role": "root", "content": "hi"}]})
    assert response.status == 400
    assert "role must be one of" in response.json()["detail"]
