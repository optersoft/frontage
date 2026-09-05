"""M5: widgets, State, interval/poll, reconcile. No browser."""

import asyncio

import pytest

from frontage import For, RecordingRenderer, Signal, Store, h, mount
from frontage.aio import interval, poll
from frontage.state import State, computed, field
from frontage.store import reconcile
from frontage.widgets import button, checkbox, number_input, radio_group, select, slider, text_input, textarea


def mounted(view):
    r = RecordingRenderer()
    root = r.inner.create_element("div")
    handle = mount(view, root, r)
    return root, r, handle


def html(root):
    return "".join(c.to_html() for c in root.children)


def find(node, tag, n=0):
    hits = []

    def walk(x):
        for c in getattr(x, "children", []):
            if c.tag == tag:
                hits.append(c)
            walk(c)

    walk(node)
    return hits[n]


# widgets -------------------------------------------------------------------------------------
def test_text_input_and_textarea_bind_both_ways():
    name, notes = Signal("ann"), Signal("")
    root, r, _ = mounted(lambda: h.div(text_input(name, "Name"), textarea(notes)))
    inp = find(root, "input")
    assert inp.props["value"] == "ann" and inp.attrs["type"] == "text" and "Name" in html(root)
    inp.props["value"] = "bob"
    inp.fire("input")
    assert name() == "bob"
    ta = find(root, "textarea")
    ta.props["value"] = "hi"
    ta.fire("input")
    assert notes() == "hi"


def test_number_input_parses_and_clears():
    n = Signal(3)
    root, r, _ = mounted(lambda: number_input(n, "N", min=0))
    inp = find(root, "input")
    assert inp.props["value"] == 3
    inp.props["value"] = "4.5"
    inp.fire("input")
    assert n() == 4.5
    inp.props["value"] = "7"
    inp.fire("input")
    assert n() == 7 and isinstance(n(), int)
    inp.props["value"] = ""
    inp.fire("input")
    assert n() is None
    inp.props["value"] = "x"
    inp.fire("input")
    assert n() is None


def test_slider_and_checkbox():
    level, on = Signal(10), Signal(False)
    root, r, _ = mounted(lambda: h.div(slider(level, "Level", max=50, step=5), checkbox(on, "On")))
    rng = find(root, "input", 0)
    assert (
        rng.attrs["type"] == "range" and rng.attrs["max"] == "50" and rng.props["value"] == 10
    )  # attributes are strings once in HTML
    rng.props["value"] = "25"
    rng.fire("input")
    assert level() == 25 and "25" in find(root, "output").to_html()
    box = find(root, "input", 1)
    box.props["checked"] = True
    box.fire("change")
    assert on() is True


def test_select_and_radio_group():
    plan = Signal("free")
    colour = Signal("red")
    root, r, _ = mounted(
        lambda: h.div(
            select(plan, ["free", ("pro", "Pro plan")], "Plan"), radio_group(colour, ["red", "blue"], "Colour")
        )
    )
    sel = find(root, "select")
    opts = [c for c in sel.children if c.tag == "option"]
    assert [o.attrs["value"] for o in opts] == ["free", "pro"] and opts[1].to_html().endswith("Pro plan</option>")
    assert opts[0].props["selected"] is True and opts[1].props["selected"] is False
    sel.props["value"] = "pro"
    sel.fire("change")
    assert plan() == "pro" and opts[1].props["selected"] is True
    radios = [c for c in [find(root, "fieldset")] for c in c.children if c.tag == "label"]
    blue = [c for c in radios[1].children if c.tag == "input"][0]
    blue.fire("change")
    assert colour() == "blue"
    assert find(root, "legend").to_html() == "<legend>Colour</legend>"


def test_button_widget():
    hits = []
    root, r, _ = mounted(lambda: button("Go", on_click=lambda ev: hits.append(1)))
    b = find(root, "button")
    assert b.attrs["type"] == "button"
    b.fire("click")
    assert hits == [1]


def test_widgets_require_signals():
    with pytest.raises(TypeError):
        text_input("not a signal")


# State ---------------------------------------------------------------------------------------
class Counter(State):
    count = field(0)
    step = field(1)
    tags = field(default_factory=list)

    @computed
    def double(self):
        return self.count * 2

    def inc(self, ev=None):
        self.count += self.step


def test_state_fields_are_signals_and_computed_are_memos():
    c = Counter(step=2)
    root, r, _ = mounted(lambda: h.p(c.signal("count"), "/", lambda: c.double))
    assert html(root) == "<p>0/0</p>"
    c.inc()
    assert c.count == 2 and c.double == 4 and html(root) == "<p>2/4</p>"
    c.count = 10
    assert html(root) == "<p>10/20</p>"
    assert c.memo("double")() == 20 and c.snapshot() == {"count": 10, "step": 2, "tags": []}
    assert Counter().tags is not c.tags  # a default_factory per instance


def test_state_rejects_unknown_fields():
    with pytest.raises(TypeError):
        Counter(nope=1)
    c = Counter()
    with pytest.raises(AttributeError):
        c.other = 1  # ty: ignore[unresolved-attribute] -- the runtime error is the point


def test_state_inheritance():
    class Named(Counter):
        name = field("x")

    n = Named(name="y")
    assert n.name == "y" and n.count == 0


# interval / poll -----------------------------------------------------------------------------
def test_interval_ticks_and_stops_with_its_owner():
    async def scenario():
        from frontage import Owner

        with Owner(parent=None) as owner:
            tick = interval(0.01)
        await asyncio.sleep(0.05)
        n = tick()
        assert n >= 2
        owner.dispose()
        await asyncio.sleep(0.03)
        assert tick() == n

    asyncio.run(scenario())


def test_poll_refetches_on_the_interval():
    async def scenario():
        calls = []

        async def fetch():
            calls.append(1)
            return len(calls)

        from frontage import Owner

        with Owner(parent=None) as owner:
            value = poll(fetch, 0.01)
        await asyncio.sleep(0.05)
        assert len(calls) >= 3 and value() == len(calls)
        owner.dispose()

    asyncio.run(scenario())


# reconcile -----------------------------------------------------------------------------------
def test_reconcile_keeps_rows_by_key_and_updates_fields():
    store = Store({"rows": [{"id": 1, "name": "ann", "age": 30}, {"id": 2, "name": "bob", "age": 40}]})
    root, r, _ = mounted(
        lambda: h.ul(
            For(
                lambda: store.rows,
                lambda row, i: h.li(lambda: row["name"], " ", lambda: row["age"]),
                key=lambda x: x["id"],
            )
        )
    )
    li_ann, li_bob = [c for c in find(root, "ul").children if c.tag == "li"]
    r.log.clear()
    reconcile(
        store.rows,
        [{"id": 2, "name": "bob", "age": 41}, {"id": 1, "name": "ann", "age": 30}, {"id": 3, "name": "cy", "age": 20}],
    )
    lis = [c for c in find(root, "ul").children if c.tag == "li"]
    assert lis[0] is li_bob and lis[1] is li_ann  # moved, not rebuilt
    assert html(root) == "<ul><li>bob 41</li><li>ann 30</li><li>cy 20</li></ul>"
    assert r.count("clone_template") == 1  # only cy was built
    assert r.count("replace_text") == 1  # only bob's age changed
    reconcile(store.rows, [{"id": 1, "name": "ann", "age": 30}])
    assert html(root) == "<ul><li>ann 30</li></ul>"
