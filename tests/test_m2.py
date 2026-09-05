"""SPEC §4 C16–C17, §6 W8–W11, W14–W16, §7 A1–A5, §9 E1. No browser."""

import asyncio

import pytest

from frontage import Effect, Memo, NotReady, RecordingRenderer, Signal, emit, h, mount, render_to_string
from frontage.aio import Action, Resource
from frontage.flow import Dynamic, Errored, For, Loading, Match, Portal, Show, Switch
from frontage.template import html as t_html


def mounted(view, **kw):
    renderer = RecordingRenderer()
    root = renderer.inner.create_element("div")
    handle = mount(view, root, renderer, **kw)
    return root, renderer, handle


def html(root):
    return "".join(c.to_html() for c in root.children)


def find(node, tag):
    """The first element with `tag` below `node` (holes leave marker text nodes around)."""
    for child in node.children:
        if child.tag == tag:
            return child
        if child.tag is not None:
            found = find(child, tag)
            if found is not None:
                return found
    return None


async def settle(n=3):
    for _ in range(n):
        await asyncio.sleep(0)


# A1, A2, W9 --------------------------------------------------------------------------------
def test_resource_loads_reloads_on_source_and_drives_loading():
    async def scenario():
        user = Signal(1)
        calls = []

        async def fetch(uid):
            calls.append(uid)
            await asyncio.sleep(0)
            return {"name": f"user-{uid}"}

        profile = Resource(fetch, source=user)
        root, r, _ = mounted(h.div(Loading(h.i("loading"), lambda: h.b(lambda: profile()["name"]))))
        assert html(root) == "<div><i>loading</i></div>"
        assert profile.loading() is True and profile.state() == "pending"
        await settle()
        assert html(root) == "<div><b>user-1</b></div>"
        assert profile.state() == "ready" and profile.loading() is False
        user.set(2)
        assert profile.state() == "refreshing"
        assert html(root) == "<div><i>loading</i></div>"
        await settle()
        assert html(root) == "<div><b>user-2</b></div>" and calls == [1, 2]
        profile.mutate({"name": "local"})
        assert html(root) == "<div><b>local</b></div>"
        profile.refetch()
        await settle()
        assert calls == [1, 2, 2] and html(root) == "<div><b>user-2</b></div>"

    asyncio.run(scenario())


def test_resource_without_source_runs_once_and_initial_value():
    async def scenario():
        async def fetch():
            await asyncio.sleep(0)
            return 42

        r = Resource(fetch, initial=0)
        assert r() == 0 and r.state() == "refreshing"  # an initial value is served while loading
        await settle()
        assert r() == 42

    asyncio.run(scenario())


# A3 (documented rule), A5 ------------------------------------------------------------------
def test_resource_task_is_cancelled_with_its_owner():
    async def scenario():
        started, finished = [], []

        async def fetch():
            started.append(1)
            await asyncio.sleep(0.05)
            finished.append(1)
            return 1

        from frontage import component

        @component
        def view():
            res = Resource(fetch)
            return h.div(lambda: str(res()))

        root, r, handle = mounted(view)  # the factory runs inside the mount's owner
        await settle()
        handle.dispose()
        await asyncio.sleep(0.1)
        assert started == [1] and finished == []

    asyncio.run(scenario())


# A4 -----------------------------------------------------------------------------------------
def test_action_pending_value_input_and_error():
    async def scenario():
        async def save(item):
            await asyncio.sleep(0)
            if item == "bad":
                raise ValueError("no")
            return f"saved {item}"

        action = Action(save)
        seen = []
        Effect(lambda: seen.append((action.pending(), action.value())))
        action.dispatch("x")
        assert action.pending() is True and action.input() == "x"
        await settle()
        assert action.value() == "saved x" and action.pending() is False
        action.dispatch("bad")
        await settle()
        assert isinstance(action.error(), ValueError) and action.pending() is False
        assert seen[0] == (False, None) and seen[-1][0] is False

    asyncio.run(scenario())


# C16, C17, W10 ------------------------------------------------------------------------------
def test_not_ready_ends_a_computation_quietly():
    ready = Signal(False)
    data = Signal(None)

    def compute():
        if not ready():
            raise NotReady
        return data()

    m = Memo(compute)
    assert m() is None
    data.set("x")
    ready.set(True)
    assert m() == "x"


def test_errored_catches_compute_errors_and_resets():
    bad = Signal(False)

    def body():
        if bad():
            raise ValueError("boom")
        return "fine"

    root, r, _ = mounted(
        h.div(Errored(lambda exc, reset: h.b("caught ", str(exc), on_click=lambda ev: reset()), lambda: h.p(body)))
    )
    assert html(root) == "<div><p>fine</p></div>"
    bad.set(True)
    assert html(root) == "<div><b>caught boom</b></div>"
    bad.set(False)
    find(root, "b").fire("click")  # reset
    assert html(root) == "<div><p>fine</p></div>"


def test_resource_error_reaches_the_nearest_errored():
    async def scenario():
        async def fetch():
            await asyncio.sleep(0)
            raise RuntimeError("down")

        res = Resource(fetch)
        root, r, _ = mounted(h.div(Errored(lambda exc, reset: h.b(str(exc)), lambda: h.p(lambda: res()))))
        await settle()
        assert html(root) == "<div><b>down</b></div>"
        assert res.state() == "errored"

    asyncio.run(scenario())


def test_uncaught_error_renders_the_debug_page():
    root, r, _ = mounted(h.p(lambda: 1 / 0))
    assert "ZeroDivisionError" in html(root) and 'class="frontage-error"' in html(root)


# W14 ----------------------------------------------------------------------------------------
def test_async_handler_runs_as_a_task_and_errors_reach_errored():
    async def scenario():
        hits = []

        async def on_click(ev):
            await asyncio.sleep(0)
            hits.append("done")
            raise RuntimeError("late")

        root, r, _ = mounted(h.div(Errored(lambda exc, reset: h.b(str(exc)), lambda: h.button("x", on_click=on_click))))
        find(root, "button").fire("click")
        assert hits == []
        await settle()
        assert hits == ["done"] and html(root) == "<div><b>late</b></div>"

    asyncio.run(scenario())


# W8, W11 --------------------------------------------------------------------------------------
def test_switch_mounts_the_first_true_case():
    mode = Signal("a")
    root, r, _ = mounted(
        h.div(
            Switch(
                [Match(lambda: mode() == "a", h.i("A")), Match(lambda: mode() == "b", lambda: h.b("B"))],
                fallback="none",
            )
        )
    )
    assert html(root) == "<div><i>A</i></div>"
    mode.set("b")
    assert html(root) == "<div><b>B</b></div>"
    mode.set("z")
    assert html(root) == "<div>none</div>"


def test_dynamic_switches_component_or_tag():
    which = Signal("b")
    root, r, _ = mounted(h.div(Dynamic(which, id="x")))
    assert html(root) == '<div><b id="x"></b></div>'
    which.set(lambda id: h.i("comp ", id))
    assert html(root) == "<div><i>comp x</i></div>"


def test_portal_renders_elsewhere_and_cleans_up():
    r = RecordingRenderer()
    elsewhere = r.inner.create_element("aside")
    root = r.inner.create_element("div")
    handle = mount(lambda: h.div(Portal(elsewhere, h.b("modal")), "here"), root, r)
    assert html(root) == "<div>here</div>" and elsewhere.to_html() == "<aside><b>modal</b></aside>"
    handle.dispose()
    assert elsewhere.to_html() == "<aside></aside>"


# W15, capture -------------------------------------------------------------------------------------
def test_custom_events_bubble_to_a_parent_listener():
    got = []
    root, r, _ = mounted(h.div(h.button("x", id="b"), on_picked=lambda ev: got.append(ev.detail)))
    emit(find(root, "button"), "picked", {"n": 1})
    assert got == [{"n": 1}]


def test_capture_prefix_registers_a_capture_listener():
    root, r, _ = mounted(h.div("x", oncapture_click=lambda ev: None))
    assert ("add_listener", "click") in r.log


# W16 -----------------------------------------------------------------------------------------
def test_template_string_static_and_dynamic_positions():
    count = Signal(3)
    active = Signal(False)

    def dec(ev):
        count.update(lambda n: n - 1)

    view = t_html(t"""
        <div class="counter" data-x="1">
            <button on:click={dec} id="dec">-</button>
            <span>Value: {count}! fixed {count():>4}</span>
            <input bind:value={Signal("x")} disabled/>
            <p class="a {count}" class:on={active}>{"a" if count() else "b"}</p>
        </div>
    """)
    root, r, _ = mounted(view)
    assert (
        html(root)
        == '<div class="counter" data-x="1"><button id="dec">-</button><span>Value: 3! fixed    3</span><input disabled></p></div>'.replace(
            "</p>", '<p class="a 3">a</p>'
        )
    )
    root.children[0].children[0].fire("click")
    assert "Value: 2!" in html(root) and 'class="a 2"' in html(root)
    active.set(True)
    assert 'class="a 2 on"' in html(root)


def test_template_plan_is_cached_per_call_site():
    from frontage import template as tpl

    before = len(tpl._plans)
    for i in range(3):
        t_html(t"<p>{i}</p>")
    assert len(tpl._plans) == before + 1


def test_template_multiple_roots_views_and_lists():
    inner = h.b("in")
    view = t_html(t"<p>{inner}</p><ul>{[h.li(str(i)) for i in range(2)]}</ul>")
    assert isinstance(view, list) and len(view) == 2
    assert render_to_string(view[0]) == "<p><b>in</b></p>"
    assert render_to_string(view[1]) == "<ul><li>0</li><li>1</li></ul>"


def test_template_errors_on_unclosed_and_mismatched_tags():
    with pytest.raises(ValueError):
        t_html(t"<div><p></div>")
    with pytest.raises(ValueError):
        t_html(t"<div>")


def test_template_with_show_and_for():
    items = Signal(["a", "b"])
    on = Signal(True)
    view = t_html(t"<ul>{For(items, lambda item, i: h.li(item))}</ul><p>{Show(on, h.b('yes'), fallback='no')}</p>")
    root, r, _ = mounted(view)
    assert html(root) == "<ul><li>a</li><li>b</li></ul><p><b>yes</b></p>"
    on.set(False)
    assert html(root).endswith("<p>no</p>")


def test_reading_a_pending_resource_raises_not_ready_and_a_refresh_keeps_the_old_value():
    async def scenario():
        gate = Signal(1)

        async def fetch(n):
            await asyncio.sleep(0)
            return n * 10

        res = Resource(fetch, source=gate)
        with pytest.raises(NotReady):
            res()
        await settle()
        assert res() == 10
        gate.set(2)
        assert res() == 10 and res.state() == "refreshing"
        await settle()
        assert res() == 20

    asyncio.run(scenario())


def test_a_resource_created_inside_a_hole_is_reported_not_hung():
    async def scenario():
        async def fetch():
            return 1

        with pytest.raises(RuntimeError, match="reactive update loop"):
            mounted(h.div(lambda: str(Resource(fetch)())))

    from frontage import reactive

    old = reactive.FLUSH_LIMIT
    reactive.FLUSH_LIMIT = 200
    try:
        asyncio.run(scenario())
    finally:
        reactive.FLUSH_LIMIT = old


def test_a_component_may_return_control_flow_directly():
    on = Signal(True)
    from frontage import component

    @component
    def gate():
        return Show(on, h.b("open"), fallback=h.i("closed"))

    root, r, _ = mounted(lambda: h.div(gate(), " | ", gate()))
    assert html(root) == "<div><b>open</b> | <b>open</b></div>"
    on.set(False)
    assert html(root) == "<div><i>closed</i> | <i>closed</i></div>"


def test_a_floating_hole_at_the_root_of_a_branch():
    which = Signal("a")
    root, r, _ = mounted(
        lambda: Switch([Match(lambda: which() == "a", lambda: Show(Signal(True), h.b("A")))], fallback=h.i("none"))
    )
    assert html(root) == "<b>A</b>"
    which.set("b")
    assert html(root) == "<i>none</i>"
