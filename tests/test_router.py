"""SPEC §8 U1–U10 in memory mode. No browser."""

import asyncio

import pytest

from frontage import RecordingRenderer, Signal, h, mount
from frontage.router import (
    A,
    ActionForm,
    Location,
    Navigate,
    Redirect,
    Route,
    Router,
    form_data,
    match_routes,
    parse_query,
    query,
    use_before_leave,
    use_location,
    use_match,
    use_params,
    use_query,
    use_router,
)


def html(root):
    return "".join(c.to_html() for c in root.children)


def wrap(inner):
    """The router renders its outlet with no wrapper element."""
    return inner


def find_all(node, tag):
    out = []
    for child in getattr(node, "children", []):
        if child.tag == tag:
            out.append(child)
        out.extend(find_all(child, tag))
    return out


def mounted(router):
    r = RecordingRenderer()
    root = r.inner.create_element("div")
    handle = mount(router, root, r)
    return root, r, handle


# matching and URLs --------------------------------------------------------------------------------
def test_matching_params_index_and_wildcards():
    routes = [
        Route("/", "home"),
        Route(
            "/users",
            "users",
            children=[Route(":id", "user", children=[Route("", "info"), Route("posts", "posts")]), Route("", "list")],
        ),
        Route("*rest", "missing"),
    ]
    assert [m.route.component for m in match_routes(routes, "/")] == ["home"]
    assert [m.route.component for m in match_routes(routes, "/users")] == ["users", "list"]
    chain = match_routes(routes, "/users/7/posts")
    assert [m.route.component for m in chain] == ["users", "user", "posts"]
    assert chain[-1].params == {"id": "7"} and chain[1].prefix == "/users/7"
    assert match_routes(routes, "/nope/x")[-1].params == {"rest": "nope/x"}
    assert match_routes([Route("/only")], "/other") is None


def test_location_and_query_parsing():
    loc = Location("/a/b/?x=1&y=two%20words&z&x=2#top")
    assert loc.pathname == "/a/b" and loc.search == "?x=1&y=two%20words&z&x=2" and loc.hash == "#top"
    assert loc.query == {"x": ["1", "2"], "y": ["two words"], "z": [""]}
    assert parse_query("") == {} and Location("").pathname == "/"


# U1, U3, U2 ------------------------------------------------------------------------------------------
def make_app():
    built = []

    def layout(children):
        built.append("layout")
        return h.div(h.h1("Contacts"), children, cls="layout")

    def contact():
        built.append("contact")
        params = use_params()
        return h.p(lambda: "contact " + params()["id"], cls="contact")

    def select():
        built.append("select")
        return h.p("select one")

    def home():
        built.append("home")
        return h.p("home")

    router = Router(
        Route("/", home),
        Route("/contacts", layout, children=[Route(":id", contact), Route("", select)]),
        fallback=lambda: h.p("not found"),
        mode="memory",
    )
    return router, built


def test_nested_routes_render_into_the_parent_and_only_changed_levels_rebuild():
    router, built = make_app()
    root, r, _ = mounted(router)
    assert html(root) == wrap("<p>home</p>") and built == ["home"]
    router.navigate("/contacts")
    assert html(root) == wrap('<div class="layout"><h1>Contacts</h1><p>select one</p></div>')
    assert built == ["home", "layout", "select"]
    router.navigate("/contacts/ann")
    assert html(root) == wrap('<div class="layout"><h1>Contacts</h1><p class="contact">contact ann</p></div>')
    assert built == ["home", "layout", "select", "contact"]  # the layout was kept
    layout_node = find_all(root, "div")[0]
    router.navigate("/contacts/bob")
    assert html(root).endswith("contact bob</p></div>")
    assert built[-1] == "contact" and built.count("contact") == 1  # same route: params updated in place
    assert find_all(root, "div")[0] is layout_node
    router.navigate("/missing")
    assert html(root) == wrap("<p>not found</p>")


def test_query_location_and_match_hooks():
    seen = {}

    def page():
        seen["query"] = use_query()
        seen["location"] = use_location()
        seen["match"] = use_match("/items/:id")
        return h.p("x")

    router = Router(Route("*", page), mode="memory", initial="/items/3?sort=asc")
    mounted(router)
    assert seen["query"]() == {"sort": ["asc"]} and seen["location"]().pathname == "/items/3"
    assert seen["match"]() == {"id": "3"}
    router.navigate("/other?sort=desc")
    assert seen["query"]() == {"sort": ["desc"]} and seen["match"]() is None


# U5 -------------------------------------------------------------------------------------------------
def test_navigate_back_forward_and_replace():
    router, _ = make_app()
    root, r, _ = mounted(router)
    router.navigate("/contacts")
    router.navigate("/contacts/ann")
    router.back()
    assert router.location().pathname == "/contacts" and "select one" in html(root)
    router.forward()
    assert router.location().pathname == "/contacts/ann"
    router.navigate("/contacts/zed", replace=True)
    router.back()
    assert router.location().pathname == "/contacts"


def test_relative_navigation_and_links_resolve_against_the_level():
    def layout(children):
        return h.div(A("ann", "Ann", id="ann"), A("bob", "Bob", id="bob", end=True), children)

    def contact():
        return h.p("c")

    router = Router(
        Route("/contacts", layout, children=[Route(":id", contact), Route("", lambda: h.p("pick"))]),
        mode="memory",
        initial="/contacts",
    )
    root, r, _ = mounted(router)
    links = find_all(root, "a")
    assert [a.attrs["href"] for a in links] == ["/contacts/ann", "/contacts/bob"]
    assert "active" not in links[0].attrs.get("class", "")
    router.navigate("/contacts/ann")
    assert links[0].attrs.get("class") == "active" and "active" not in links[1].attrs.get("class", "")


def test_redirect_from_a_component_and_navigate_component():
    def old():
        raise Redirect("/new")

    router = Router(
        Route("/old", old),
        Route("/new", lambda: h.p("new")),
        Route("/go", lambda: Navigate("/new")),
        mode="memory",
        initial="/old",
    )
    root, r, _ = mounted(router)
    assert router.location().pathname == "/new" and html(root) == wrap("<p>new</p>")
    router.navigate("/go")
    assert router.location().pathname == "/new"


# U6, U7 ------------------------------------------------------------------------------------------------
def test_preload_runs_on_render_and_on_demand():
    calls = []

    def preload(params, location, intent):
        calls.append((params.get("id"), intent))

    router = Router(Route("/u/:id", lambda: h.p("u"), preload=preload), Route("/", lambda: h.p("h")), mode="memory")
    mounted(router)
    router.preload("/u/9")
    assert calls == [("9", "preload")]
    router.navigate("/u/1")
    assert calls == [("9", "preload"), ("1", "navigate")]


def test_query_cache_dedupes_and_revalidates():
    async def scenario():
        runs = []

        async def fetch(n):
            runs.append(n)
            await asyncio.sleep(0)
            return n * 2

        q = query(fetch)
        a, b = await asyncio.gather(q(1), q(1))
        assert (a, b) == (2, 2) and runs == [1]
        assert await q(1) == 2 and runs == [1]
        q.revalidate(1)
        assert await q(1) == 2 and runs == [1, 1]
        q.revalidate()
        assert q.cache == {}

    asyncio.run(scenario())


# U8 ---------------------------------------------------------------------------------------------------
def test_router_action_redirects_and_action_form_gathers_fields():
    async def scenario():
        saved = []

        async def save(data):
            saved.append(data)
            raise Redirect("/done")

        def page():
            action = use_router().action(save)
            return ActionForm(
                action,
                h.input(name="title", value="hello"),
                h.input(name="tag", value="a", type_="checkbox", checked=True),
                h.input(name="tag", value="b", type_="checkbox"),
                h.button("save", type_="submit"),
                id="f",
            )

        router = Router(Route("/", page), Route("/done", lambda: h.p("done")), mode="memory")
        root, r, _ = mounted(router)
        find_all(root, "form")[0].fire("submit")
        for _ in range(3):
            await asyncio.sleep(0)
        assert saved == [{"title": "hello", "tag": "a"}]
        assert router.location().pathname == "/done" and html(root) == wrap("<p>done</p>")

    asyncio.run(scenario())


def test_form_data_lists_repeated_names():
    form = h.form(h.input(name="x", value="1"), h.input(name="x", value="2"))
    from frontage import render_to_string
    from frontage.renderer import HtmlRenderer

    r = HtmlRenderer()
    root = r.create_element("div")
    mount(form, root, r)
    assert form_data(find_all(root, "form")[0]) == {"x": ["1", "2"]}
    assert render_to_string(h.i("ok")) == "<i>ok</i>"


# U9, U10 ----------------------------------------------------------------------------------------------
def test_before_leave_can_cancel_a_navigation():
    dirty = Signal(True)

    def page():
        use_before_leave(lambda to, frm: not dirty())
        return h.p("edit")

    router = Router(Route("/", page), Route("/away", lambda: h.p("away")), mode="memory")
    root, r, _ = mounted(router)
    assert router.navigate("/away") is False and router.location().pathname == "/"
    dirty.set(False)
    assert router.navigate("/away") is True and html(root) == wrap("<p>away</p>")


def test_dispose_removes_the_history_listener():
    router, _ = make_app()
    root, r, handle = mounted(router)
    assert router.mode.listener is not None
    handle.dispose()
    assert router.mode.listener is None


def test_root_component_wraps_the_outlet():
    router = Router(Route("/", lambda: h.p("home")), root=lambda children: h.main(children), mode="memory")
    root, r, _ = mounted(router)
    assert html(root) == "<main><p>home</p></main>"


def test_hooks_outside_a_router_fail_clearly():
    with pytest.raises(RuntimeError):
        use_params()


def test_relative_paths_resolve_dot_segments():
    from frontage.router import _join

    assert _join("/contacts/ann", "..") == "/contacts"
    assert _join("/contacts/ann", "../bob") == "/contacts/bob"
    assert _join("/contacts", "./cy/") == "/contacts/cy"
    assert _join("/", "..") == "/"
    assert _join("/a/b", "/x") == "/x"


def test_base_path_and_document_file_count_as_root():
    router = Router(
        Route("/", lambda: h.p("home")),
        Route("/x", lambda: h.p("x")),
        mode="memory",
        base="/app",
        initial="/app/index.html",
    )
    root, r, _ = mounted(router)
    assert html(root) == "<p>home</p>"
    router.navigate("/x")
    assert router.url() == "/app/x" and html(root) == "<p>x</p>"
    assert router.href("/") == "/app"
