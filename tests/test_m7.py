"""0.5.0: the debug warnings (SPEC E2), async memos, transitions and optimistic writes,
`is_pending`, `is_routing` across a route's resources, ids per mount, the prerender crawl and
the console script. No browser."""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from frontage import (
    Effect,
    Errored,
    For,
    Loading,
    Memo,
    Optimistic,
    RecordingRenderer,
    Resource,
    Signal,
    component,
    h,
    is_pending,
    mount,
    reactive,
    transition,
    unique_id,
    untrack,
    use_transition,
)
from frontage.aio import Action
from frontage.cli.prerender import links_in, prerender, render_mount
from frontage.router import Route, Router

ROOT = Path(__file__).resolve().parents[1]


def mounted(view, **kw):
    r = RecordingRenderer()
    root = r.inner.create_element("div")
    return root, r, mount(view, root, r, **kw)


def html(root):
    return "".join(c.to_html() for c in root.children)


async def settle(n=4):
    for _ in range(n):
        await asyncio.sleep(0)


@pytest.fixture(autouse=True)
def debug_on():
    reactive._warned.clear()
    reactive.DEBUG = True
    yield
    reactive.DEBUG = True


# --- E2: the three warnings --------------------------------------------------------------------


def test_warns_on_a_signal_read_after_the_first_await(capsys):
    async def scenario():
        user = Signal(1)
        suffix = Signal("!")

        async def fetch(uid):
            await asyncio.sleep(0)
            return f"user-{uid}{suffix()}"  # not a dependency: nothing re-runs when it changes

        profile = Resource(fetch, source=user)
        root, _, _ = mounted(h.p(Loading(h.i("…"), lambda: h.b(profile))))
        await settle()
        assert html(root) == "<p><b>user-1!</b></p>"

    asyncio.run(scenario())
    err = capsys.readouterr().err
    assert "Resource(fetch)" in err and "after the first await" in err


def test_reads_before_the_await_and_peeks_do_not_warn(capsys):
    async def scenario():
        user = Signal(1)
        suffix = Signal("!")

        async def fetch(uid):
            await asyncio.sleep(0)
            return f"user-{uid}{suffix.peek()}"

        profile = Resource(fetch, source=user)
        root, _, _ = mounted(h.p(Loading(h.i("…"), lambda: h.b(profile))))
        await settle()
        assert html(root) == "<p><b>user-1!</b></p>"

    asyncio.run(scenario())
    assert capsys.readouterr().err == ""


def test_warns_once_on_a_write_inside_a_tracked_computation(capsys):
    a = Signal(1)
    b = Signal(0)

    def compute():
        b.set(a() * 2)

    Effect(compute)
    err = capsys.readouterr().err
    assert "written inside a tracked computation (Effect compute)" in err
    a.set(2)
    assert capsys.readouterr().err == "" and b() == 4


def test_writes_in_the_effect_phase_or_under_untrack_do_not_warn(capsys):
    a = Signal(1)
    b = Signal(0)
    c = Signal(0)
    Effect(a, lambda v, prev: b.set(v))
    Effect(lambda: untrack(lambda: c.set(a.peek())))
    a.set(5)
    assert (b(), c()) == (5, 1) and capsys.readouterr().err == ""


def test_mount_debug_false_silences_the_warnings(capsys):
    a = Signal(1)
    b = Signal(0)
    mounted(h.p("x"), debug=False)
    Effect(lambda: b.set(a()))
    assert capsys.readouterr().err == ""
    reactive.DEBUG = True


def test_for_warns_when_no_row_survives_an_update(capsys):
    items = Signal([{"n": 1}, {"n": 2}])
    root, _, _ = mounted(h.ul(For(items, lambda item, i: h.li(str(item["n"])))))
    assert capsys.readouterr().err == ""
    items.set([{"n": 2}, {"n": 1}])  # rebuilt dicts: identity keys never match
    err = capsys.readouterr().err
    assert "For: none of the 2 rows survived" in err and "key=" in err
    items.set([{"n": 3}])
    assert capsys.readouterr().err == ""  # once per For
    keyed = Signal([{"id": 1}])
    mounted(h.ul(For(keyed, lambda item, i: h.li("x"), key="id")))
    keyed.set([{"id": 1}])
    assert capsys.readouterr().err == ""


# --- async memos --------------------------------------------------------------------------------


def test_async_memo_tracks_the_reads_made_before_the_coroutine(capsys):
    async def scenario():
        uid = Signal(1)
        calls = []

        async def load(n):
            calls.append(n)
            await asyncio.sleep(0)
            return f"user-{n}"

        name = Memo(lambda: load(uid()))
        root, _, _ = mounted(h.p(Loading(h.i("…"), lambda: h.b(name))))
        assert html(root) == "<p><i>…</i></p>" and name.loading() is True
        await settle()
        assert html(root) == "<p><b>user-1</b></p>" and name.loading() is False and calls == [1]
        uid.set(2)
        assert name.loading() is True and name.peek() == "user-1"
        await settle()
        assert html(root) == "<p><b>user-2</b></p>" and calls == [1, 2]

    asyncio.run(scenario())
    assert capsys.readouterr().err == ""


def test_async_memo_keeps_the_previous_value_under_loading_keep():
    async def scenario():
        uid = Signal(1)

        async def load(n):
            await asyncio.sleep(0)
            return f"user-{n}"

        name = Memo(lambda: load(uid()))
        root, _, _ = mounted(h.p(Loading(h.i("…"), lambda: h.b(name), keep=True)))
        await settle()
        uid.set(2)
        assert html(root) == "<p><b>user-1</b></p>"
        await settle()
        assert html(root) == "<p><b>user-2</b></p>"

    asyncio.run(scenario())


def test_async_memo_error_reaches_the_nearest_errored():
    async def scenario():
        async def load():
            await asyncio.sleep(0)
            raise LookupError("nope")

        broken = Memo(lambda: load())
        root, _, _ = mounted(
            h.div(Errored(lambda exc, reset: h.b(str(exc)), lambda: h.p(Loading(h.i("…"), lambda: h.span(broken)))))
        )
        await settle()
        assert html(root) == "<div><b>nope</b></div>" and isinstance(broken.error(), LookupError)

    asyncio.run(scenario())


def test_async_memo_supersedes_a_run_still_in_flight():
    async def scenario():
        uid = Signal(1)
        gates = {1: asyncio.Event(), 2: asyncio.Event()}
        finished = []

        async def load(n):
            await gates[n].wait()
            finished.append(n)
            return f"user-{n}"

        name = Memo(lambda: load(uid()))
        root, _, _ = mounted(h.p(Loading(h.i("…"), lambda: h.b(name))))
        await settle()
        uid.set(2)  # the first coroutine is cancelled with the memo's previous run
        gates[1].set()
        gates[2].set()
        await settle()
        assert html(root) == "<p><b>user-2</b></p>" and finished == [2]

    asyncio.run(scenario())


# --- transitions ----------------------------------------------------------------------------------


def test_transition_holds_the_page_until_the_refetch_settles():
    async def scenario():
        uid = Signal(1)
        gate = asyncio.Event()

        async def load(n):
            if n == 2:
                await gate.wait()
            await asyncio.sleep(0)
            return f"user-{n}"

        user = Resource(load, source=uid)
        root, _, _ = mounted(h.div(h.p(lambda: f"id {uid()}", id="id"), Loading(h.i("…"), lambda: h.b(lambda: user()))))
        await settle()
        before = '<div><p id="id">id 1</p><b>user-1</b></div>'
        assert html(root) == before
        t = transition(lambda: uid.set(2))
        assert t.pending() is True and is_pending() is True and is_pending(t) is True
        await settle()
        assert html(root) == before  # neither the id nor a fallback: the page waits
        assert user.state() == "refreshing" and uid() == 2
        gate.set()
        await settle()
        assert html(root) == '<div><p id="id">id 2</p><b>user-2</b></div>'
        assert t.pending() is False and is_pending() is False
        await t.wait()

    asyncio.run(scenario())


def test_transition_without_async_work_commits_at_once():
    a = Signal(1)
    root, _, _ = mounted(h.p(a))
    seen = []
    t = transition(lambda: a.set(2))
    t.on_commit(lambda: seen.append("done"))
    assert html(root) == "<p>2</p>" and t.pending() is False and seen == ["done"]


def test_optimistic_shows_at_once_and_reverts_when_the_transition_commits():
    async def scenario():
        version = Signal(0)
        gate = asyncio.Event()

        async def load(v):
            if v:
                await gate.wait()
            await asyncio.sleep(0)
            return 3 + v

        likes = Resource(load, source=version)
        liked = Optimistic(False)

        def label():
            return "liked!" if liked() else f"{likes()} likes"

        root, _, _ = mounted(h.p(Loading(h.i("…"), lambda: h.b(label))))
        await settle()
        assert html(root) == "<p><b>3 likes</b></p>"

        def like():
            liked.set(True)
            version.set(1)

        t = transition(like)
        await settle()
        assert html(root) == "<p><b>liked!</b></p>" and t.pending() is True
        gate.set()
        await settle()
        assert html(root) == "<p><b>4 likes</b></p>" and liked() is False and t.pending() is False

    asyncio.run(scenario())


def test_use_transition_and_is_pending_on_targets():
    async def scenario():
        gate = asyncio.Event()
        n = Signal(0)

        async def load(v):
            if v:
                await gate.wait()
            return v

        data = Resource(load, source=n)
        pending, start = use_transition()
        await settle()
        assert pending() is False and is_pending(data) is False
        t = start(lambda: n.set(1))
        assert pending() is True and is_pending(data) is True and is_pending(t) is True
        gate.set()
        await settle()
        assert pending() is False and is_pending(data) is False

        async def save(x):
            return x

        action = Action(save)
        assert is_pending(action) is False
        assert is_pending(object()) is False

    asyncio.run(scenario())


# --- the router across a route's resources ------------------------------------------------------


def test_is_routing_stays_up_while_the_new_routes_resources_load():
    async def scenario():
        gate = asyncio.Event()

        async def load():
            await gate.wait()
            return "data"

        def page():
            data = Resource(load)
            return h.p(Loading(h.i("…"), lambda: h.b(data)))

        router = Router(Route("/", lambda: h.p("home")), Route("/page", page), mode="memory")
        root, _, _ = mounted(router)
        assert router.is_routing() is False
        router.navigate("/page")
        await settle()
        assert router.is_routing() is True and html(root) == "<p><i>…</i></p>"
        gate.set()
        await settle()
        assert router.is_routing() is False and html(root) == "<p><b>data</b></p>"

    asyncio.run(scenario())


# --- ids per mount ---------------------------------------------------------------------------------


def test_unique_id_counts_per_mount_named_after_the_target():
    ids = []

    @component
    def app():
        ids.append(unique_id())
        return h.p("x")

    r = RecordingRenderer()
    root = r.inner.create_element("div")
    mount(app, root, r, scope="app")
    mount(app, root, r, scope="other")
    mount(app, root, r)
    assert ids[0] == "fr-app-1" and ids[1] == "fr-other-1"
    assert ids[2].startswith("fr-") and ids[2] not in ids[:2]
    outside = unique_id()
    assert len(outside.split("-")) == 2


def test_prerender_names_the_id_scope_after_the_selector():
    @component
    def app():
        return h.label("x", for_=unique_id())

    inner, values = asyncio.run(render_mount(app, True, None, 5, "#box"))
    assert 'for="fr-box-1"' in inner and values == []


# --- the crawl ---------------------------------------------------------------------------------------


def test_links_in_keeps_the_hrefs_that_are_routes_of_the_mounted_router():
    router = Router(
        Route("/", lambda: None),
        Route("/contacts", lambda: None, children=[Route(":id", lambda: None), Route("", lambda: None)]),
        mode="memory",
    )
    inner = (
        '<a href="/contacts">c</a><a href="/contacts/ann?x=1">a</a><a href="/nope">n</a>'
        '<a href="https://x.y/">e</a><a href="#top">t</a><a href="/contacts/">c2</a>'
    )
    assert links_in(inner, router) == ["/contacts", "/contacts/ann"]
    hashed = Router(Route("/", lambda: None), Route("/about", lambda: None), mode="hash")
    assert links_in('<a href="#/about">a</a><a href="/about">no</a>', hashed) == ["/about"]
    assert links_in('<a href="/a">a</a><a href="b">b</a>', lambda: None) == ["/a"]


def test_prerender_crawl_renders_the_routes_the_pages_link_to(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.html").write_text('<html><body><div id="app"></div><script src="./app.py"></script></body></html>')
    (app / "app.py").write_text(
        "from frontage import A, Route, Router, h, mount\n"
        "router = Router(\n"
        "    Route('/', lambda: h.p('home ', A('/about', 'about'))),\n"
        "    Route('/about', lambda: h.p('about ', A('/team', 'team'), A('/', 'home'))),\n"
        "    Route('/team', lambda: h.p('team')),\n"
        "    mode='hash',\n"
        ")\n"
        "mount(router, '#app')\n"
    )
    results = prerender(app, tmp_path / "out", bundle_pyscript=False, crawl=True)
    assert [r.path for r in results] == ["/", "/about", "/team"]
    assert (tmp_path / "out" / "team" / "index.html").exists()
    assert "team" in (tmp_path / "out" / "team" / "index.html").read_text()


# --- the console script -----------------------------------------------------------------------------


def test_console_script_is_declared_and_runs(monkeypatch, capsys):
    from frontage import __version__, cli

    assert 'frontage = "frontage.cli:script"' in (ROOT / "pyproject.toml").read_text()
    monkeypatch.setattr(sys, "argv", ["frontage", "version"])
    assert cli.script() == 0 and capsys.readouterr().out.strip() == __version__
    assert cli.PROG == "frontage" and "usage: frontage <command>" in cli.usage()
    cli.PROG = "python -m frontage"
    exe = Path(sys.executable).parent / "frontage"
    if exe.exists():
        run = subprocess.run([str(exe), "export", "--help"], capture_output=True, text=True)
        assert run.returncode == 0 and "usage: frontage export" in run.stdout


# --- the debug module -------------------------------------------------------------------------------


def test_debug_module_keeps_the_hydration_details():
    import frontage.debug as debug
    from frontage.dom import Hydration

    hyd = Hydration()
    hyd._note("expected <li>, found the end of the content")
    assert hyd.mismatches == 1 and Hydration.describe(None) == "the end of the content"
    debug.last_hydration = hyd
    assert debug.hydration_report() == ["expected <li>, found the end of the content"]
    debug.last_hydration = None
    assert debug.hydration_report() == []
