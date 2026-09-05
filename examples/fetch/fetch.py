"""Resource, Loading and Errored: async data as reactive values, with no server involved.
`load` pretends to be a request: it waits, then answers or fails depending on the user id."""

import asyncio

from frontage import Errored, Loading, Resource, Signal, component, h, mount

USERS = {1: "Ada Lovelace", 2: "Grace Hopper", 3: "Margaret Hamilton"}


async def load(user_id):
    await asyncio.sleep(0.3)
    if user_id == 99:
        raise RuntimeError(f"no such user: {user_id}")
    return {"id": user_id, "name": USERS.get(user_id, f"user {user_id}")}


@component
def app():
    user_id = Signal(1)
    user = Resource(load, source=user_id)

    def pick(uid):
        return lambda ev: user_id.set(uid)

    return h.div(
        h.p(
            h.button("Ada", on_click=pick(1), id="u1"),
            h.button("Grace", on_click=pick(2), id="u2"),
            h.button("Nobody", on_click=pick(99), id="u99"),
            h.button("Refetch", on_click=lambda ev: user.refetch(), id="refetch"),
        ),
        h.p(lambda: f"state: {user.state()}", id="state"),
        Errored(
            lambda exc, reset: h.p(
                "failed: ",
                str(exc),
                " ",
                h.button("retry", on_click=lambda ev: (user_id.set(1), reset()), id="retry"),
                id="error",
            ),
            lambda: h.div(Loading(h.p("loading…", id="loading"), lambda: h.h2(lambda: user()["name"], id="name"))),
        ),
    )


mount(app, "#app")
