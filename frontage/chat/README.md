# frontage.chat

A chat interface for [frontage](https://github.com/optersoft/frontage): the column of
messages, the box at the bottom, and an answer that types itself into one text node.

```py
from frontage import h, mount
from frontage.chat import Chat, chat_input, chat_log

chat = Chat("/api/chat")

mount(lambda: h.div(chat_log(chat), chat_input(chat.ask, disabled=chat.pending)), "#app")
```

## Why this is the component that argues for the framework

Streamlit's chat example keeps the conversation in `st.session_state` and re-runs the whole
script for every token of a streaming answer, redrawing twenty bubbles to add one word to the
last. Here **each message owns a `Signal`**, so a token appends to one text node and nothing
else on the page is touched. The test that says so is
`tests/components/test_chat.py::test_a_token_touches_one_text_node_and_no_other_bubble`: it
holds on to the first bubble's node object, streams into the second, and asserts the first
node is the same object afterwards.

## The two halves

`Chat` is the conversation *and* the transport. `chat_log` and `chat_input` are views over it
and neither knows about the other, so replacing one with your own markup is an ordinary
afternoon.

`ask(text)` adds the reader's turn, adds an empty assistant turn, and streams into it. It
returns immediately and does the work in a task owned by the component, so leaving the page
cancels the request.

| | |
|---|---|
| `Chat(endpoint=, send=, system=, history=)` | the conversation; `send` replaces HTTP with `async (messages, on_token)` |
| `chat.messages` | a `Signal` of `Message`, each with a `text` signal and a `rating` signal |
| `chat.pending`, `chat.error` | signals; hand `pending` to `chat_input(disabled=)` |
| `chat.ask(text)`, `.add(role, text)`, `.clear()`, `.stop()` | |
| `chat_log(chat, empty=)` | the bubbles; `system` turns are not shown |
| `chat_input(on_send, placeholder=, label=, disabled=)` | a real `<form>`, so Enter submits |
| `message(role, text)`, `feedback(turn, on_rate=)` | the pieces, for a log of your own |

## The key never comes to the page

A frontage app is a directory of static files that anyone can read, so an API key in one is an
API key published. The server half holds it:

```py
# server.py — pip install "frontage[chat]"
from frontage.chat.server import Conversation

chat = Conversation()


@chat.reply
async def answer(messages):
    async for chunk in my_model(messages):
        yield chunk


app = chat.app(static="dist/chat")
```

`reply` decorates an **async generator** of text chunks; each one reaches the page as it is
yielded. The route is `POST /api/chat`, the answer is Server-Sent Events, and each frame's
payload is JSON — so a token holding a newline survives, which a raw `data:` line would split
in two and lose.

Two things it does deliberately:

- **It does not trust the conversation it is sent.** The page is public and so is this route,
  so the payload is checked before your function sees it: roles from a fixed set, a cap on the
  number of turns and on the total length. `parse()` is public, for an app that mounts its own
  route.
- **It keeps no session.** The whole conversation arrives with every request. That is what
  lets one stateless process serve any number of pages, and why there is nothing here that
  ends up holding strangers' chats in a dictionary that only grows.

## Cost

**1.0 KB of JavaScript gzipped** — one `fetch` and the SSE reader loop, which lives in
JavaScript because pulling a stream across the bridge read by read would cost a crossing per
chunk — plus 0.7 KB of stylesheet and about 200 lines of Python that travel with the rest of
your app. Apache 2.0.
