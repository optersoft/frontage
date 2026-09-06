"""0.7.0 (M9): async memos as the router's data primitive. An async `Memo` created while a
route renders counts toward `is_routing` like a `Resource`; the prerenderer waits for async
memos and writes their values by ordinal; a hydrating mount hands them back, so the memo
settles without running. No browser."""

import asyncio

from frontage import Loading, Memo, RecordingRenderer, Resource, Signal, component, h, mount, reactive
from frontage.cli.prerender import inject, render_mount
from frontage.dom import Hydration
from frontage.router import Route, Router, query


def mounted(view, **kw):
    r = RecordingRenderer()
    root = r.inner.create_element("div")
    return root, r, mount(view, root, r, **kw)


def html(root):
    return "".join(c.to_html() for c in root.children)


async def settle(n=4):
    for _ in range(n):
        await asyncio.sleep(0)


# --- U13: is_routing ------------------------------------------------------------------------------


def test_is_routing_stays_up_while_the_new_routes_async_memos_load():
    async def scenario():
        gate = asyncio.Event()

        async def load(cid):
            await gate.wait()
            return {"name": cid.upper()}

        get_contact = query(load)

        def page():
            params = Signal({"id": "ann"})
            data = Memo(lambda: get_contact(params()["id"]))
            return h.p(Loading(h.i("…"), lambda: h.b(lambda: data()["name"])))

        router = Router(Route("/", lambda: h.p("home")), Route("/page", page), mode="memory")
        root, _, _ = mounted(router)
        assert router.is_routing() is False
        router.navigate("/page")
        await settle()
        assert router.is_routing() is True and html(root) == "<p><i>…</i></p>"
        gate.set()
        await settle()
        assert router.is_routing() is False and html(root) == "<p><b>ANN</b></p>"
        # A later run of the same memo (the id changed) is not a navigation: is_routing stays down.
        gate.clear()
        assert reactive._navigation is None

    asyncio.run(scenario())


def test_a_disposed_route_releases_the_navigation():
    async def scenario():
        gate = asyncio.Event()

        async def load():
            await gate.wait()
            return 1

        router = Router(Route("/", lambda: h.p("home")), Route("/page", lambda: h.b(Memo(load))), mode="memory")
        root, _, _ = mounted(router)
        router.navigate("/page")
        await settle()
        assert router.is_routing() is True
        router.navigate("/")  # the memo is disposed with its route before it ever settled
        await settle()
        assert router.is_routing() is False and html(root) == "<p>home</p>"

    asyncio.run(scenario())


# --- prerender: async memos settle and are written by ordinal ---------------------------------------


async def _load_name(uid):
    await asyncio.sleep(0.01)
    return {"id": uid, "name": f"user {uid}"}


@component
def profile():
    uid = Signal(7)
    twice = Memo(lambda: uid() * 2)  # a plain memo takes ordinal 0 and is not written
    user = Resource(_load_name, source=uid)
    name = Memo(lambda: _load_name(uid()))  # async: written with its ordinal
    return h.div(
        h.p(twice, id="twice"),
        Loading(h.i("…"), lambda: h.b(lambda: name()["name"] + "/" + user()["name"], id="name")),
    )


def test_render_mount_waits_for_async_memos_and_writes_them_by_ordinal():
    inner, values = asyncio.run(render_mount(profile, True, None, 5.0))
    assert "user 7/user 7" in inner and "…" not in inner
    assert values["resources"] == [{"id": 7, "name": "user 7"}]
    ordinals = [ordinal for ordinal, _ in values["memos"]]
    assert values["memos"] == [[ordinals[0], {"id": 7, "name": "user 7"}]]
    assert ordinals[0] >= 1  # `twice` came first; the exact number is the framework's business
    page = '<html><body><div id="app"></div></body></html>'
    out = inject(page, "#app", inner, values)
    block = out.split('data-fr-data="app">')[1].split("</script>")[0]
    assert '"memos":[[' in block and '"resources":[' in block


def test_render_mount_reports_a_failed_async_memo():
    async def boom():
        await asyncio.sleep(0)
        raise ValueError("no")

    def view():
        return h.p(Loading(h.i("…"), lambda: h.b(Memo(boom))))

    try:
        asyncio.run(render_mount(view, True, None, 5.0))
    except RuntimeError as exc:
        assert "async memo #0 failed: ValueError('no')" in str(exc)
    else:
        raise AssertionError("a failed async memo must fail the build")


# --- hydration: the page's value settles the memo, and the coroutine never runs ------------------


def test_a_hydrated_async_memo_settles_without_running():
    runs = []

    async def load(uid):
        runs.append(uid)
        return {"name": "fetched"}

    reactive._set_memo_hydration([[1, {"name": "from the page"}]])
    try:
        plain = Memo(lambda: 1)  # ordinal 0
        name = Memo(lambda: load(3))  # ordinal 1: the page settled it
        other = Memo(lambda: load(4))  # ordinal 2: nothing for it, so it runs
    finally:
        reactive._set_memo_hydration(None)

    async def scenario():
        assert plain() == 1
        assert name() == {"name": "from the page"} and name.loading() is False and name.is_async()
        assert runs == []
        try:
            other()
        except reactive.NotReady:
            pass
        else:
            raise AssertionError("an unhydrated memo loads")
        await settle()
        assert other() == {"name": "fetched"} and runs == [4]

    asyncio.run(scenario())


def test_hydration_reads_both_data_block_shapes():
    old = Hydration([{"a": 1}])
    assert old.data == [{"a": 1}] and old.memos is None
    new = Hydration({"resources": [], "memos": [[2, "x"]]})
    assert new.data is None and new.memos == [[2, "x"]]
    assert Hydration(None).data is None and Hydration(None).memos is None
