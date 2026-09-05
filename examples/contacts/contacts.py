"""The router: nested routes, params, links, redirects, preload. Hash mode by default (it
works from static hosting); `?mode=history` switches to pushState."""

import asyncio

from pyscript import window

from frontage import A, Loading, Navigate, Resource, Route, Router, Signal, component, h, mount, use_params
from frontage.router import query

CONTACTS = {
    "ann": ("Ann Moore", "ann@example.com"),
    "bob": ("Bob Ruiz", "bob@example.com"),
    "cy": ("Cy Adebayo", "cy@example.com"),
}
loads = Signal(0)  # how many times the "server" was asked; query() keeps it low


async def fetch_contact(cid):
    loads.update(lambda n: n + 1)
    await asyncio.sleep(0.15)
    name, email = CONTACTS[cid]
    return {"id": cid, "name": name, "email": email}


get_contact = query(fetch_contact)


def preload_contact(params, location, intent):
    return get_contact(params["id"])


@component
def home():
    return h.div(
        h.h2("Home"), h.p("A router demo. Pick ", A("/contacts", "contacts", id="to-contacts"), "."), id="home"
    )


@component
def contacts(children):
    return h.div(
        h.h2("Contacts"),
        h.nav(*[A(cid, CONTACTS[cid][0], id=f"link-{cid}") for cid in CONTACTS], id="list"),
        h.section(children, id="detail"),
        h.p(lambda: f"loads: {loads()}", id="loads"),
    )


@component
def contact():
    params = use_params()
    data = Resource(lambda cid: get_contact(cid), source=lambda: params()["id"])
    return Loading(
        h.p("loading…", id="loading"),
        lambda: h.div(
            h.h3(lambda: data()["name"], id="name"),
            h.p(lambda: data()["email"], id="email"),
            A("..", "back to the list", id="back"),
        ),
    )


@component
def pick():
    return h.p("Select a contact.", id="pick")


@component
def missing():
    return h.p("No such page.", id="missing")


mode = "history" if "mode=history" in str(window.location.search) else "hash"
# In history mode the app lives under this page's directory; the router treats the page
# itself as "/". (A deep link needs the host to serve this page for every path under it.)
base = str(window.location.pathname).rsplit("/", 1)[0] if mode == "history" else ""
router = Router(
    Route("/", home),
    Route("/contacts", contacts, children=[Route(":id", contact, preload=preload_contact), Route("", pick)]),
    Route("/old", lambda: Navigate("/contacts")),
    Route("*", missing),
    mode=mode,
    base=base,
    root=lambda children: h.div(
        h.header(A("/", "Frontage contacts", id="brand"), A("/old", "old link", id="old")), children, id="app-root"
    ),
)

mount(router, "#app")
