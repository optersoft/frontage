"""A form and a server that agree, because they are reading the same object.

`Signup` is declared once, in `contract.py`, and both halves import it — the record is plain
`frontage.schema`, which runs in the page and on the server alike. So a bound the page
enforces is the bound the server enforces: change `seats` to `le=20` there and both halves
move together, with no second copy to forget.

⚠ The contract is its own module for a reason `contract.py` explains: importing `server.py`
here would ship the server into the browser and fail at boot.

The page also watches `/seats`, a Server-Sent Events route, so a number on it changes while
nobody reloads.

Run it:

    frontage-api server.py --app-dir examples/api --addr 127.0.0.1:8000
    frontage serve examples/api --proxy /api=http://127.0.0.1:8000
"""

import json

from contract import Signup  # the contract, and the only module both halves import

from frontage import Action, Effect, Loading, Resource, Signal, h, mount
from frontage.flow import For, Show
from frontage.runtime import in_browser, to_js, window
from frontage.schema.form import Form
from frontage.widgets import button, number_input, text_input

API = "/api"


async def send(method, path, body=None):
    """One request. `frontage.schema` has already said the body is well formed, so a 422 here
    would mean the two halves disagree — which is exactly the bug this example exists to make
    impossible."""
    options = {"method": method, "headers": {"content-type": "application/json"}}
    if body is not None:
        options["body"] = json.dumps(body)
    response = await window.fetch(API + path, to_js(options))
    text = await response.text()
    if not response.ok:
        raise RuntimeError(str(response.status) + ": " + text)
    return json.loads(text) if text else None


taken = Signal(0)
left = Signal(None)
form = Form(Signup)

signups = Resource(lambda _: send("GET", "/signups"), source=lambda: taken())


async def _create(value):
    await send("POST", "/signups", value)
    taken.set(taken() + 1)  # the listing's source, so it reloads and nothing else moves


create = Action(_create)


def watch_seats():
    """The SSE route, read with the browser's own `EventSource`. A server that pushes is not
    a different programming model here: it sets a signal, and the holes that read it move."""
    if not in_browser:
        return
    stream = window.EventSource.new(API + "/seats")

    def arrived(event):
        if str(event.data).startswith("[DONE]"):
            stream.close()
            return
        left.set(json.loads(str(event.data))["left"])

    stream.onmessage = arrived


def line(row, _index):
    return h.li(row["name"] + " — " + str(row["seats"]) + " seat(s)")


def field(name, label, widget=text_input):
    return h.p(
        widget(form.signal(name), label),
        h.span(form.message(name), class_="error"),
    )


def view():
    return h.div(
        h.h1("Sign up"),
        h.p(
            "Seats left: ",
            h.strong(lambda: "…" if left() is None else str(left())),
            class_="seats",
        ),
        h.form(
            field("name", "Name"),
            field("email", "Email"),
            field("seats", "Seats", number_input),
            field("note", "Note"),
            button("Sign up", type="submit", disabled=lambda: not form.valid() or create.pending()),
            on_submit=form.submit(create),
        ),
        Show(create.error, lambda: h.p("The server refused it: " + str(create.error()), class_="error")),
        h.h2("Taken so far"),
        Loading(
            lambda: h.p("…"),
            lambda: h.ul(For(lambda: signups()["signups"], line, key="id")),
            keep=True,
        ),
    )


Effect(watch_seats)
mount(view, "#app")
