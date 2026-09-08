"""Two routes, and only one of them is in the page when it loads.

`lazy=` names a module instead of a component. `frontage build` leaves that module — and
everything only it imports — out of the first payload and writes it beside the page; the
browser asks for it the first time someone goes there, and `A` starts the fetch on hover, so
the click usually lands on a chunk that has already arrived. Until it does, the nearest
`Loading` shows its fallback, exactly as a route waiting for data does.
"""

from frontage import A, Errored, Loading, Route, Router, h, mount
from frontage.head import Meta, Title
from frontage.router import use_router


def home():
    return h.div(
        h.h1("Home"),
        h.p("This page is the whole download. The report is not.", cls="note"),
        id="home",
    )


def shell(children):
    router = use_router()
    return h.div(
        # What the page calls itself when no route says otherwise, and what a link preview
        # reads. A route with a `title=` of its own wins while it is on screen.
        Title("Lazy routes"),
        Meta("One route in a chunk of its own, fetched when someone asks for it.", name="description"),
        h.nav(
            A("/", "Home"),
            A("/report", "Report", id="to-report"),
            # A chunk in flight counts toward `is_routing`, exactly as a route's own data does.
            h.span(lambda: "loading…" if router.is_routing() else "", id="status", cls="note"),
        ),
        Errored(
            lambda error, reset: h.div(
                h.p(f"The report did not arrive: {error}", id="failed"), h.button("Retry", on_click=lambda _: reset())
            ),
            lambda: Loading(h.p("loading the report…", id="waiting"), lambda: children),
        ),
    )


mount(
    Router(
        Route("/", home, title="Lazy routes"),
        Route("/report", lazy="pages.report", title="Report — lazy routes"),
        root=shell,
        mode="hash",
    ),
    "#app",
)
