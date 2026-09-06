"""An issue tracker: the whole framework in one app, for the browser suite to drive.

Routes with a layout, params and a query string; a list in a Store kept by `reconcile` and
rendered by a keyed `For`; a detail loaded by an async memo over a `query` the route preloads;
`Loading` and `Errored` boundaries with a retry; a done toggle that is `Optimistic` inside a
`transition`; a delete behind a `Portal` modal and an `Action`; a create form on `ActionForm`
with a `State` for its fields and the widgets; `is_routing` and `is_pending` as a progress
bar; an `interval` ticker. The server is pretend: dicts and `asyncio.sleep`. Issue 13 cannot
be loaded, so the error path has something to show.
"""

import asyncio

from frontage import (
    A,
    ActionForm,
    Effect,
    Errored,
    For,
    Loading,
    Match,
    Memo,
    Optimistic,
    Portal,
    Redirect,
    Resource,
    Route,
    Router,
    Show,
    Signal,
    State,
    Store,
    Switch,
    component,
    computed,
    field,
    h,
    in_browser,
    interval,
    is_pending,
    mount,
    reconcile,
    transition,
    use_navigate,
    use_params,
    use_query,
)
from frontage.router import query, use_is_routing, use_router
from frontage.widgets import select, text_input

# --- the pretend server ------------------------------------------------------------------------

LATENCY = 0.15
ISSUES = [
    {"id": 1, "title": "Signals lose a subscriber after dispose", "priority": "high", "done": False},
    {"id": 2, "title": "For flickers on a swap", "priority": "medium", "done": False},
    {"id": 3, "title": "Document the insert rules", "priority": "low", "done": True},
    {"id": 4, "title": "Router: scroll restoration on back", "priority": "medium", "done": True},
    {"id": 13, "title": "The one that cannot be loaded", "priority": "high", "done": False},
]
next_id = [14]
requests = Signal(0)  # every call to the server counts, so a test can see the cache work


async def _call():
    requests.update(lambda n: n + 1)
    await asyncio.sleep(LATENCY)


async def list_issues():
    await _call()
    return [dict(i) for i in ISSUES]


async def load_issue(iid):
    await _call()
    for issue in ISSUES:
        if issue["id"] == iid:
            if iid == 13:
                raise LookupError("issue 13 is cursed")
            return dict(issue)
    raise LookupError(f"no issue {iid}")


async def create_issue(fields):
    await _call()
    issue = {"id": next_id[0], "title": fields["title"], "priority": fields["priority"], "done": False}
    next_id[0] += 1
    ISSUES.append(issue)
    return dict(issue)


async def set_done(iid, done):
    await _call()
    for issue in ISSUES:
        if issue["id"] == iid:
            issue["done"] = done
            return dict(issue)
    raise LookupError(f"no issue {iid}")


async def delete_issue(iid):
    await _call()
    ISSUES[:] = [i for i in ISSUES if i["id"] != iid]


get_issue = query(load_issue)
get_list = query(list_issues)


def refresh():
    """Forget every cached answer: the next read asks the server again."""
    get_issue.revalidate()
    get_list.revalidate()


# --- shared state ------------------------------------------------------------------------------

store = Store({"issues": []})  # the list on screen; `reconcile` keeps rows across refetches
version = Signal(0)  # bumped after a create or a delete; the list and the details depend on it
pending = Signal(None)  # (issue id, done) that the server has not confirmed yet


async def confirm_write(write):
    """The write in flight, as an async memo every reader depends on: while it runs, a
    reader that asks for fresh data waits (NotReady), and when it lands the caches are
    dropped, so the refetch that follows sees the new state. A transition around the
    write holds the page meanwhile; an `Optimistic` shows the intended value."""
    if write is not None:
        await set_done(*write)
        refresh()
    return write


confirmed = Memo(lambda: confirm_write(pending()))


def preload_issue(params, location, intent):
    return get_issue(int(params["id"]))


# --- pages -------------------------------------------------------------------------------------


@component
def layout(children):
    routing = use_is_routing()
    return h.div(
        h.header(
            A("/", "Tracker", id="brand", end=True),
            h.nav(A("/issues", "Issues", id="nav-issues"), A("/new", "New", id="nav-new")),
            h.div(cls="bar", class_busy=lambda: routing() or is_pending(), id="bar"),
        ),
        h.main(children),
        h.div(id="modal"),
        h.footer(lambda: f"requests: {requests()}", id="requests"),
        id="layout",
    )


@component
def dashboard():
    issues = Resource(lambda v: get_list(), source=version)
    open_count = Memo(lambda: sum(1 for i in issues() if not i["done"]))
    done_count = Memo(lambda: sum(1 for i in issues() if i["done"]))
    tick = interval(1)

    def by_priority(level):
        return lambda: sum(1 for i in issues() if i["priority"] == level and not i["done"])

    return h.section(
        h.h2("Dashboard"),
        Loading(
            h.p("loading…", id="loading"),
            lambda: h.div(
                h.p(h.b(open_count, id="open"), " open, ", h.b(done_count, id="done"), " done"),
                h.ul(
                    h.li("high: ", by_priority("high"), id="high"),
                    h.li("medium: ", by_priority("medium"), id="medium"),
                    h.li("low: ", by_priority("low"), id="low"),
                ),
                h.p(A("/issues", "See the issues", id="to-issues")),
            ),
        ),
        h.p(lambda: f"on this page for {tick()} s", id="tick"),
        id="dashboard",
    )


@component
def issues(children):
    params = use_query()
    text = Signal("")
    status = Signal("all")
    fresh = Resource(lambda _: get_list(), source=lambda: (version(), confirmed()))
    # Every refetch is merged into the store, so a row whose id survives keeps its node.
    Effect(fresh, lambda data, prev: reconcile(store.issues, data, key="id"))

    def wanted():
        want = status()
        needle = text().lower()
        out = []
        for issue in store.issues:
            if want == "open" and issue["done"] or want == "done" and not issue["done"]:
                continue
            if needle and needle not in issue["title"].lower():
                continue
            out.append(issue)
        return out

    visible = Memo(wanted)
    navigate = use_navigate()

    def row(issue, index):
        iid = issue["id"]
        return h.li(
            A(f"/issues/{iid}", lambda: issue["title"], id=f"issue-{iid}"),
            " ",
            Switch(
                [
                    Match(lambda: issue["done"], h.span("done", cls="tag done")),
                    Match(lambda: issue["priority"] == "high", h.span("high", cls="tag high")),
                ],
                fallback=h.span(lambda: issue["priority"], cls="tag"),
            ),
            class_done=lambda: issue["done"],
        )

    def on_status(ev):
        # The filter lives in the query string, so a reload keeps it.
        navigate("/issues?status=" + ev.target.value if ev.target.value != "all" else "/issues")

    # A query value is a list (a key may repeat): the first one is the filter.
    Effect(lambda: params().get("status", ["all"])[0], lambda value, prev: status.set(value))
    return h.section(
        h.h2("Issues"),
        h.div(
            text_input(text, "Search", id="search", placeholder="title…"),
            h.label(
                "Status ",
                h.select(
                    h.option("all", value="all"),
                    h.option("open", value="open"),
                    h.option("done", value="done"),
                    prop_value=status,
                    on_change=on_status,
                    id="status",
                ),
            ),
            cls="filters",
        ),
        Loading(
            h.p("loading…", id="loading"),
            lambda: Show(
                lambda: len(visible()) > 0,
                h.ul(For(visible, row, key="id"), id="list"),
                fallback=h.p("Nothing matches.", id="empty"),
            ),
            keep=True,
        ),
        h.div(children, id="detail"),
        id="issues",
    )


@component
def pick():
    return h.p("Pick an issue.", id="pick")


@component
def issue():
    # Keyed on the id: a new id rebuilds the detail, so an Errored boundary left showing a
    # failure for one issue does not stand in front of the next one.
    params = use_params()
    return Show(lambda: params()["id"], lambda iid: detail(int(iid)), keyed=True)


@component
def detail(iid):
    data = Memo(lambda: (version(), confirmed(), get_issue(iid))[2])
    done_now = Optimistic(None)  # what the toggle shows before the server has answered
    router = use_router()
    confirm = Signal(False)

    def done():
        shown = done_now()
        return data()["done"] if shown is None else shown

    def toggle(ev):
        target = not done()

        def go():
            done_now.set(target)  # shows now; reverts when the transition commits
            pending.set((iid, target))  # the write; `confirmed` runs it, `data` waits for it

        transition(go)

    async def remove(fields):
        await delete_issue(iid)
        refresh()
        version.update(lambda v: v + 1)
        raise Redirect("/issues")

    delete = router.action(remove)

    def failed(exc, reset):
        return h.p(
            "could not load: ", str(exc), " ", h.button("retry", on_click=lambda ev: reset(), id="retry"), id="error"
        )

    def modal():
        return Portal(
            "#modal",
            h.div(
                h.p(lambda: f"Delete “{data()['title']}”?"),
                h.button("Delete", on_click=lambda ev: delete.dispatch({}), id="confirm-delete"),
                h.button("Keep", on_click=lambda ev: confirm.set(False), id="cancel-delete"),
                cls="dialog",
                id="dialog",
            ),
        )

    return Errored(
        failed,
        lambda: Loading(
            h.p("loading…", id="loading-issue"),
            lambda: h.article(
                h.h3(lambda: data()["title"], id="title"),
                h.p("priority: ", lambda: data()["priority"], id="priority"),
                h.p(
                    h.button(lambda: "mark open" if done() else "mark done", on_click=toggle, id="toggle"),
                    " ",
                    h.span(lambda: "done" if done() else "open", id="state"),
                    lambda: " (saving…)" if is_pending() else "",
                ),
                h.p(h.button("Delete…", on_click=lambda ev: confirm.set(True), id="delete")),
                Show(confirm, modal),
                A("..", "back to the list", id="back"),
            ),
        ),
    )


class Draft(State):
    title = field("")
    priority = field("medium")

    @computed
    def valid(self):
        return len(self.title.strip()) >= 3


@component
def new_issue():
    draft = Draft()
    router = use_router()

    async def save(fields):
        created = await create_issue({"title": draft.title.strip(), "priority": draft.priority})
        refresh()
        version.update(lambda v: v + 1)
        raise Redirect(f"/issues/{created['id']}")

    action = router.action(save)

    def can_submit():
        return draft.valid and not action.pending()

    return h.section(
        h.h2("New issue"),
        ActionForm(
            action,
            text_input(draft.signal("title"), "Title", id="new-title", placeholder="at least three characters"),
            select(draft.signal("priority"), ["low", "medium", "high"], "Priority", id="new-priority"),
            h.button(
                lambda: "Saving…" if action.pending() else "Create",
                type_="submit",
                disabled=lambda: not can_submit(),
                id="create",
            ),
            id="new-form",
        ),
        id="new",
    )


@component
def missing():
    return h.p("No such page.", id="missing")


if in_browser:
    from frontage.runtime import window

    mode = "history" if "mode=history" in str(window.location.search) else "hash"
    base = str(window.location.pathname).rsplit("/", 1)[0] if mode == "history" else ""
else:
    mode, base = "hash", ""

router = Router(
    Route("/", dashboard),
    Route("/issues", issues, children=[Route(":id", issue, preload=preload_issue), Route("", pick)]),
    Route("/new", new_issue),
    Route("*", missing),
    mode=mode,
    base=base,
    root=layout,
    transition=True,
)

mount(router, "#app")
