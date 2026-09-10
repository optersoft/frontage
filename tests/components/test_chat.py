"""`frontage.chat`: the conversation, the two views, and the server half's wire format."""

import asyncio
import json
from pathlib import Path

import pytest

import frontage.chat
from frontage import h
from frontage.chat import STYLESHEET, Chat, ChatError, Message, chat_input, chat_log, feedback, message
from frontage.chat._server import DONE
from frontage.chat.server import ChatRequestError, Conversation, parse, sse
from frontage.testing import App


def echo(reply="hello there"):
    """A transport that streams `reply` one word at a time, as a server would."""

    async def send(messages, on_token):
        for word in reply.split():
            await asyncio.sleep(0)
            on_token(word + " ")

    return send


# -- the conversation ---------------------------------------------------------------------------


def test_a_chat_needs_a_transport():
    with pytest.raises(TypeError, match="endpoint URL or a send="):
        Chat()


def test_ask_adds_two_turns_and_streams_into_the_second():
    chat = Chat(send=echo("one two"))

    def view():
        return chat_log(chat)

    with App(view) as app:
        app.run(lambda: chat.ask("hi"))
        turns = chat.messages.peek()
        assert [t.role for t in turns] == ["user", "assistant"]
        assert turns[0].text.peek() == "hi"
        assert turns[1].text.peek() == "one two "
        assert app.find_all(".fr-msg")[1].text == "one two"


def test_the_payload_carries_the_system_turn_and_never_shows_it():
    chat = Chat(send=echo("ok"), system="Answer in Catalan.")
    with App(lambda: chat_log(chat)) as app:
        app.run(lambda: chat.ask("hola"))
        assert chat.payload()[0] == {"role": "system", "content": "Answer in Catalan."}
        assert len(app.find_all(".fr-msg")) == 2  # the system turn is not a bubble


def test_an_empty_or_concurrent_ask_does_nothing():
    chat = Chat(send=echo())
    assert chat.ask("   ") is None
    assert chat.messages.peek() == []
    chat.pending.set(True)
    assert chat.ask("hi") is None


def test_a_failing_transport_lands_in_error_and_stops_pending():
    async def broken(messages, on_token):
        raise ChatError(502, "the model is down")

    chat = Chat(send=broken)
    with App(lambda: chat_log(chat)) as app:
        app.run(lambda: chat.ask("hi"))
        assert isinstance(chat.error.peek(), ChatError)
        assert chat.error.peek().status == 502
        assert chat.pending.peek() is False


def test_clear_empties_the_conversation():
    chat = Chat(send=echo())
    chat.add("user", "hi")
    chat.clear()
    assert chat.messages.peek() == []


def test_a_token_touches_one_text_node_and_no_other_bubble():
    """The reason this component exists: an answer that grows does not rebuild the log."""
    chat = Chat(send=echo())
    first = chat.add("assistant", "earlier")
    reply = chat.add("assistant", "")
    with App(lambda: chat_log(chat)) as app:
        before = app.find_all(".fr-msg")[0]._node
        app.run(lambda: reply.append("tok"))
        assert app.find_all(".fr-msg")[1].text == "tok"
        assert app.find_all(".fr-msg")[0]._node is before  # same node object: never rebuilt
        assert first.text.peek() == "earlier"


# -- the views ----------------------------------------------------------------------------------


def test_message_renders_its_role_as_a_class():
    with App(lambda: message("user", "hi")) as app:
        assert app.find(".fr-msg").classes == ["fr-msg", "fr-msg-user"]
        assert app.find(".fr-msg-body").text == "hi"


def test_an_empty_log_shows_what_it_was_given():
    chat = Chat(send=echo())
    with App(lambda: chat_log(chat, empty=h.p("Ask me something", cls="hint"))) as app:
        assert app.find(".hint").text == "Ask me something"
        chat.add("user", "hi")
        app.settle()
        assert app.query(".hint") is None


def test_chat_input_sends_and_clears():
    sent = []
    with App(lambda: chat_input(sent.append)) as app:
        app.type(".fr-chat-text", "hello")
        app.submit("form")
        assert sent == ["hello"]
        assert app.find(".fr-chat-text").value == ""


def test_chat_input_ignores_an_empty_submit():
    sent = []
    with App(lambda: chat_input(sent.append)) as app:
        app.submit("form")
        assert sent == []


def test_chat_input_disables_itself_while_an_answer_is_in_flight():
    chat = Chat(send=echo())
    with App(lambda: chat_input(chat.ask, disabled=chat.pending)) as app:
        assert not app.find(".fr-chat-send").disabled
        chat.pending.set(True)
        app.settle()
        assert app.find(".fr-chat-send").disabled
        assert app.find(".fr-chat-text").disabled


def test_feedback_toggles_and_reports():
    turn = Message("assistant", "hi")
    seen = []
    with App(lambda: feedback(turn, on_rate=lambda t, r: seen.append(r))) as app:
        app.click("[aria-label=Good answer]")
        assert turn.rating.peek() == "up"
        assert app.find_all(".fr-rate")[0].classes == ["fr-rate", "fr-on"]
        app.click("[aria-label=Good answer]")  # clicking the current rating clears it
        assert turn.rating.peek() is None
        assert seen == ["up", None]


def test_every_class_the_package_emits_is_in_the_stylesheet():
    chat = Chat(send=echo())
    turn = chat.add("assistant", "hi")
    view = lambda: h.div(chat_log(chat), chat_input(chat.ask), feedback(turn))  # noqa: E731
    with App(view) as app:
        emitted = set()
        for node in app.find_all("div") + app.find_all("button") + app.find_all("input") + app.find_all("form"):
            emitted.update(node.classes)
    missing = {c for c in emitted if c.startswith("fr-") and f".{c}" not in STYLESHEET}
    assert not missing


def test_the_shipped_stylesheet_matches_style_py():
    """`_browser/index.css` is generated from `style.py`; two copies drift."""
    shipped = Path(frontage.chat.__file__).parent / "_browser" / "index.css"
    assert shipped.read_text() == STYLESHEET


# -- the server half ----------------------------------------------------------------------------


def test_sse_json_encodes_so_a_newline_survives():
    assert sse("a\nb") == 'data: "a\\nb"\n\n'


@pytest.mark.parametrize(
    "payload,message",
    [
        ([], "must be an object"),
        ({}, "non-empty list"),
        ({"messages": []}, "non-empty list"),
        ({"messages": ["hi"]}, "turn 0 is not an object"),
        ({"messages": [{"role": "root", "content": "x"}]}, "role must be one of"),
        ({"messages": [{"role": "user", "content": 7}]}, "content must be a string"),
    ],
)
def test_a_posted_conversation_is_checked(payload, message):
    with pytest.raises(ChatRequestError, match=message):
        parse(payload)


def test_the_caps_are_enforced():
    with pytest.raises(ChatRequestError, match="too many turns"):
        parse({"messages": [{"role": "user", "content": "x"}] * 3}, max_turns=2)
    with pytest.raises(ChatRequestError, match="longer than"):
        parse({"messages": [{"role": "user", "content": "abcdef"}]}, max_chars=3)


def test_stream_frames_end_with_done():
    chat = Conversation()

    @chat.reply
    async def answer(messages):
        assert messages == [{"role": "user", "content": "hi"}]
        yield "one "
        yield "two"

    async def collect():
        return [frame async for frame in chat.stream({"messages": [{"role": "user", "content": "hi"}]})]

    frames = asyncio.run(collect())
    assert frames == ['data: "one "\n\n', 'data: "two"\n\n', "data: [DONE]\n\n"]


def test_a_conversation_with_no_reply_says_so():
    chat = Conversation()

    async def collect():
        return [f async for f in chat.stream({"messages": [{"role": "user", "content": "hi"}]})]

    with pytest.raises(RuntimeError, match="@chat.reply"):
        asyncio.run(collect())


def test_the_route_streams_and_refuses_a_bad_body():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    chat = Conversation()

    @chat.reply
    async def answer(messages):
        yield messages[-1]["content"].upper()

    app = fastapi.FastAPI()
    app.include_router(chat.router())
    client = TestClient(app)

    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == 'data: "HI"\n\ndata: [DONE]\n\n'

    bad = client.post("/api/chat", json={"messages": [{"role": "root", "content": "hi"}]})
    assert bad.status_code == 400
    assert "role must be one of" in bad.json()["detail"]


# --- the same conversation on frontage's own server (API.md §6.2's gate) ---------------------


def test_a_conversation_runs_on_frontage_api():
    """`Conversation.stream` is an async generator, unchanged; only the transport differs."""
    from frontage_api.testing import Client

    chat = Conversation()

    @chat.reply
    async def answer(messages):
        for word in ("hello", " ", "there"):
            yield word

    client = Client(chat.api())
    reply = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert reply.status == 200
    assert reply.header("content-type") == "text/event-stream"

    frames = asyncio.run(_collect(reply.body))
    assert frames[-1] == DONE
    assert "".join(json.loads(f[6:]) for f in frames[:-1]) == "hello there"


async def _collect(chunks):
    out = []
    while True:
        piece = await chunks.next()
        if piece is None:
            return out
        out.append(piece.decode())


def test_a_bad_conversation_is_400_on_frontage_api_too():
    from frontage_api.testing import Client

    chat = Conversation()

    @chat.reply
    async def answer(messages):
        yield "never"

    reply = Client(chat.api()).post("/api/chat", json={"messages": []})
    assert reply.status == 400
    assert "non-empty" in reply.json()["detail"]
