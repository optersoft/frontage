"""0.3.0: unique ids, the owner tree, `Loading(keep=True)`, `is_routing` while preloads run."""

import asyncio

from frontage import Effect, RecordingRenderer, Signal, component, h, mount, tree, unique_id
from frontage.aio import Resource
from frontage.flow import Loading
from frontage.router import Route, Router
from frontage.widgets import checkbox, slider, text_input


def mounted(view):
    r = RecordingRenderer()
    root = r.inner.create_element("div")
    return root, r, mount(view, root, r)


def html(root):
    return "".join(c.to_html() for c in root.children)


def test_unique_id_counts_up_per_prefix():
    a, b = unique_id(), unique_id()
    assert a != b and a.startswith("fr-") and b.startswith("fr-")
    assert unique_id("x").startswith("x-")


def test_widgets_link_label_and_control():
    name = Signal("")
    root, r, _ = mounted(lambda: text_input(name, "Name"))
    out = html(root)
    uid = out.split('for="')[1].split('"')[0]
    assert uid.startswith("fr-") and f'id="{uid}"' in out
    root2, _, _ = mounted(lambda: text_input(name, "Name", id="who"))
    assert 'for="who"' in html(root2) and 'id="who"' in html(root2)
    root3, _, _ = mounted(lambda: h.div(checkbox(Signal(False), "Ok"), slider(Signal(3), "Vol")))
    assert html(root3).count("for=") == 3  # the checkbox label, the slider label and its output


def test_tree_names_components_and_computations():
    @component
    def child():
        Effect(lambda: None)
        return h.b("x")

    @component
    def app():
        return h.div(child(), child())

    root, r, handle = mounted(app)
    text = tree(handle)
    lines = text.splitlines()
    assert lines[0] == "Owner"
    assert sum(1 for line in lines if line.strip() == "app") == 1
    assert sum(1 for line in lines if line.strip() == "child") == 2
    assert any("Effect" in line for line in lines)
    assert tree(handle, depth=0) == "Owner"


def test_loading_keep_shows_fallback_only_on_the_first_load():
    async def scenario():
        gate = asyncio.Event()
        source = Signal(1)

        async def fetch(n):
            await gate.wait()
            gate.clear()
            return f"value {n}"

        def app():
            data = Resource(fetch, source=source)
            return h.div(Loading(h.i("wait"), lambda: h.b(data)), Loading(h.i("wait"), lambda: h.b(data), keep=True))

        root, r, _ = mounted(app)
        assert html(root).count("<i>wait</i>") == 2
        gate.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert html(root).count("<b>value 1</b>") == 2
        source.set(2)
        await asyncio.sleep(0)
        out = html(root)
        assert out.count("<i>wait</i>") == 1 and out.count("<b>value 1</b>") == 1
        gate.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert html(root).count("<b>value 2</b>") == 2

    asyncio.run(scenario())


def test_is_routing_stays_up_while_a_navigation_preloads():
    async def scenario():
        gate = asyncio.Event()
        seen = []

        async def preload(params, location, intent):
            seen.append(intent)
            await gate.wait()

        router = Router(
            Route("/", lambda: h.p("home")), Route("/slow", lambda: h.p("slow"), preload=preload), mode="memory"
        )
        states = []
        Effect(lambda: states.append(router.is_routing()))
        root, r, _ = mounted(router)
        await asyncio.sleep(0)
        assert states == [False]
        router.navigate("/slow")
        await asyncio.sleep(0)
        assert seen == ["navigate"] and router.is_routing.peek() is True
        gate.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert router.is_routing.peek() is False
        assert states == [False, True, False]
        # A route with no preload settles within the navigation itself.
        router.navigate("/")
        await asyncio.sleep(0)
        assert router.is_routing.peek() is False

    asyncio.run(scenario())


def test_for_takes_a_key_name():
    from frontage import For

    rows = Signal([{"id": 1, "t": "a"}, {"id": 2, "t": "b"}])

    def row(item, index):
        return h.li(item["t"])

    root, r, _ = mounted(lambda: h.ul(For(rows, row, key="id")))
    first = root.children[0].children
    li_a = [c for c in first if getattr(c, "tag", None) == "li"][0]
    rows.set([{"id": 2, "t": "b"}, {"id": 1, "t": "a"}])
    lis = [c for c in root.children[0].children if getattr(c, "tag", None) == "li"]
    assert [c.to_html() for c in lis] == ["<li>b</li>", "<li>a</li>"] and lis[1] is li_a
