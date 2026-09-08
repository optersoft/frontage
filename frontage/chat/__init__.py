"""A chat interface: the column of messages, the box at the bottom, and a reply that types
itself.

A chat is the one interface where a rerun framework pays for its architecture in public.
Streamlit rebuilds the whole page for every token of a streaming answer, which is why its
chat example holds the conversation in `st.session_state` and re-draws every bubble to add
one word to the last. Here **each message owns a signal**, so a token appends to one text
node and the twenty messages above it are not touched.

    from frontage.chat import Chat, chat_input, chat_log

    chat = Chat("/api/chat")

    view = h.div(chat_log(chat), chat_input(chat.ask, disabled=chat.pending))

`Chat` is the conversation and the transport; `chat_log` and `chat_input` are views over it,
and either can be replaced by your own without touching the other. Nothing here knows what a
language model is: the server half decides that, and the page posts a conversation and reads
back text.

**The key never comes to the page.** A frontage app is static files that anyone can read, so
an API key in one is an API key published. `frontage.chat.server` is the other half — a
FastAPI app that holds the key and streams the answer as Server-Sent Events.
"""

from frontage import For, Show, Signal, h, spawn
from frontage.runtime import CPYTHON, create_proxy, platform

from .style import STYLESHEET

__all__ = ["STYLESHEET", "Chat", "ChatError", "Message", "chat_input", "chat_log", "feedback", "message"]

USER = "user"
ASSISTANT = "assistant"
SYSTEM = "system"


class ChatError(Exception):
    """The server refused or failed: `.status` and its message."""

    def __init__(self, status, message):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


class Message:
    """One turn. `text` is a `Signal`, which is the whole point: a streamed answer writes it
    token by token and only the text node that reads it changes."""

    def __init__(self, role, text="", id=None):
        self.role = role
        self.text = Signal(text)
        self.rating = Signal(None)  # None, "up" or "down"
        self.id = id

    def append(self, chunk):
        self.text.update(lambda current: current + chunk)

    def value(self):
        """The turn as the server wants it: a plain dict, the text read out of the signal."""
        return {"role": self.role, "content": self.text.peek()}

    def __repr__(self):
        return f"Message({self.role!r}, {self.text.peek()!r})"


class Chat:
    """The conversation, and the one call that adds to it.

    `endpoint` is the URL of a `frontage.chat.server` app. `send` replaces the transport
    with `async (messages, on_token) -> None`, which is how the tests run without a server
    and how you plug in something that is not HTTP.

    `system` is the instruction prepended to what the server is sent, and never shown.
    """

    def __init__(self, endpoint=None, send=None, system=None, history=None):
        if endpoint is None and send is None:
            raise TypeError("Chat needs an endpoint URL or a send= transport")
        self.endpoint = endpoint
        self._send = send or self._post
        self.system = system
        self.messages = Signal(list(history or []))
        self.pending = Signal(False)
        self.error = Signal(None)
        self._abort = None

    # -- the conversation ---------------------------------------------------------------------

    def add(self, role, text=""):
        """Append a turn and return it. The list signal changes; the turns already in it do
        not, so `For` adds one row and rebuilds nothing."""
        turn = Message(role, text, id=len(self.messages.peek()))
        self.messages.update(lambda current: current + [turn])
        return turn

    def clear(self):
        self.stop()
        self.messages.set([])
        self.error.set(None)

    def stop(self):
        """Abandon the answer in flight. The half-written turn stays: it was said."""
        if self._abort is not None:
            self._abort()
            self._abort = None
        self.pending.set(False)

    def payload(self):
        """What the server is sent: the system instruction, if any, then every turn."""
        turns = [{"role": SYSTEM, "content": self.system}] if self.system else []
        return turns + [turn.value() for turn in self.messages.peek()]

    # -- asking -------------------------------------------------------------------------------

    def ask(self, text):
        """Add the reader's turn, then stream the answer into a turn of its own.

        Safe to hand straight to `chat_input`: it returns immediately and the work happens
        in a task owned by the component, so leaving the page cancels the request.
        """
        text = (text or "").strip()
        if not text or self.pending.peek():
            return None
        self.error.set(None)
        self.add(USER, text)
        reply = self.add(ASSISTANT, "")
        self.pending.set(True)
        return spawn(self._stream(reply))

    async def _stream(self, reply):
        try:
            await self._send(self.payload(), reply.append)
        except Exception as exc:  # noqa: BLE001 — every failure is the page's to show
            self.error.set(exc)
            if not reply.text.peek():
                reply.append("…")
        finally:
            self._abort = None
            self.pending.set(False)

    async def _post(self, messages, on_token):
        """The browser transport: one POST, the answer read as it arrives."""
        if platform == CPYTHON:
            raise ChatError(0, "no transport on CPython: pass send= to Chat()")
        import json

        import chat as _js  # ty: ignore[unresolved-import]  # the JavaScript half, registered by the build

        request = _js.stream(self.endpoint, json.dumps({"messages": messages}), create_proxy(on_token))
        self._abort = request.abort
        try:
            response = await request.promise
        except BaseException:
            request.abort()
            raise
        status = int(response.status)
        if status != 200:
            raise ChatError(status, str(response.text))


# --- views -------------------------------------------------------------------------------------


def message(role, text, cls=None, **attrs):
    """One bubble. `text` may be an accessor, and should be: that is what lets a streamed
    answer grow without the bubble being rebuilt."""
    classes = f"fr-msg fr-msg-{role}" + (f" {cls}" if cls else "")
    return h.div(h.div(text, cls="fr-msg-body"), cls=classes, **attrs)


def chat_log(chat, empty=None, cls=None, **attrs):
    """The column of bubbles, oldest first, `system` turns left out because they are not
    addressed to the reader."""

    def visible():
        return [turn for turn in chat.messages() if turn.role != SYSTEM]

    def row(turn, index):
        return message(turn.role, turn.text)

    return h.div(
        Show(lambda: bool(visible()), lambda: For(visible, row), empty),
        cls="fr-chat-log" + (f" {cls}" if cls else ""),
        role="log",
        aria_live="polite",
        **attrs,
    )


def chat_input(on_send, placeholder="Message…", label="Send", disabled=None, cls=None, **attrs):
    """The box at the bottom. Submitting clears it and calls `on_send(text)`.

    A `<form>`, so Enter submits and a screen reader is told what the control is, and the
    button is a real submit button rather than a div with a click handler.
    """
    draft = Signal("")

    def send(ev):
        ev.preventDefault()
        text = draft.peek()
        if not text.strip():
            return
        draft.set("")
        on_send(text)

    def is_disabled():
        return bool(disabled()) if callable(disabled) else bool(disabled)

    return h.form(
        h.input(
            bind_value=draft,
            cls="fr-chat-text",
            placeholder=placeholder,
            aria_label=placeholder,
            autocomplete="off",
            disabled=is_disabled,
        ),
        h.button(label, type="submit", cls="fr-chat-send", disabled=is_disabled),
        on_submit=send,
        cls="fr-chat-input" + (f" {cls}" if cls else ""),
        **attrs,
    )


def feedback(turn, on_rate=None, cls=None, **attrs):
    """Thumbs on one turn, bound to its `rating` signal. Clicking the current rating clears it.

    `on_rate(turn, rating)` is called after the signal is written, which is where a store or
    a POST goes.
    """

    def rate(value):
        def handler(ev):
            turn.rating.update(lambda current: None if current == value else value)
            if on_rate is not None:
                on_rate(turn, turn.rating.peek())

        return handler

    def button_class(value):
        return lambda: "fr-rate fr-on" if turn.rating() == value else "fr-rate"

    return h.div(
        h.button("👍", on_click=rate("up"), cls=button_class("up"), type="button", aria_label="Good answer"),
        h.button("👎", on_click=rate("down"), cls=button_class("down"), type="button", aria_label="Bad answer"),
        cls="fr-feedback" + (f" {cls}" if cls else ""),
        **attrs,
    )
