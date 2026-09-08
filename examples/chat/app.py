"""A chat over a server that streams: the log, the box, and a rating on every answer.

The page holds the conversation and the transport; `server.py` holds the model and the key.
Run both:

    uvicorn server:app --app-dir examples/chat --port 8001
    frontage serve examples/chat --proxy /api=http://127.0.0.1:8001
"""

from frontage import Show, h, mount
from frontage.chat import Chat, chat_input, feedback, message
from frontage.layout import container, spinner

chat = Chat("/api/chat", system="You are a terse teaching assistant. Two sentences at most.")


def turn(item, index):
    """One exchange. The answer's `feedback` sits under the bubble, on the turn itself."""
    if item.role == "user":
        return message("user", item.text)
    return h.div(message("assistant", item.text), feedback(item), cls="fr-turn")


def log():
    from frontage import For

    return h.div(
        For(chat.messages, turn),
        Show(chat.pending, lambda: spinner("Thinking…")),
        Show(lambda: chat.error() is not None, lambda: h.p(lambda: str(chat.error()), cls="failed")),
        cls="fr-chat-log",
        role="log",
        aria_live="polite",
    )


mount(
    lambda: container(
        h.h1("Ask"),
        log(),
        chat_input(chat.ask, placeholder="Ask something…", disabled=chat.pending),
    ),
    "#app",
)
