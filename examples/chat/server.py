"""The server for `app.py`: one route, one async generator, and the key it would hold.

    uvicorn server:app --app-dir examples/chat --port 8001

With no `OPENAI_API_KEY` in the environment it answers from a canned model, so the example
runs offline and in CI. With one, it streams from the real thing — and the two differ by the
body of `answer`, which is the point: the page does not know or care.
"""

import asyncio
import os

from frontage.chat.server import Conversation

chat = Conversation()

CANNED = (
    "A signal is a value that remembers who read it. "
    "When you write to it, only those readers run again — not the page, not the component, "
    "just the text node or the attribute that asked."
)


@chat.reply
async def answer(messages):
    """An async generator of text chunks. Whatever it yields reaches the page as it is
    yielded, so the reader watches the answer arrive rather than waiting for all of it."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        for word in CANNED.split(" "):
            await asyncio.sleep(0.04)  # a model's pace, so the streaming is visible
            yield word + " "
        return
    async for chunk in _openai(messages, key):
        yield chunk


async def _openai(messages, key):
    """One provider, ~15 lines, so nothing about the shape of this is hidden in a library."""
    import json

    import httpx

    body = {"model": "gpt-4o-mini", "messages": messages, "stream": True}
    headers = {"authorization": "Bearer " + key}
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", "https://api.openai.com/v1/chat/completions", json=body, headers=headers) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                delta = json.loads(line[6:])["choices"][0]["delta"]
                if "content" in delta:
                    yield delta["content"]


# `static=` serves the built page beside the route, which is the deployment with no CORS in
# it. In development `frontage serve --proxy` does the same job without a build.
app = chat.app(static=os.environ.get("CHAT_STATIC") or None)
