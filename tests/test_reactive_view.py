"""SPEC §6, W1–W7 and W13, through HtmlRenderer and RecordingRenderer. No browser."""

import pytest

from frontage import Memo, NodeRef, RecordingRenderer, Signal, Store, component, h, mount, render_to_string
from frontage.flow import For, Show


def mounted(view, renderer=None):
    """Mount `view` into a fresh root; returns (root node, renderer, handle)."""
    renderer = renderer or RecordingRenderer()
    root = (
        renderer.inner.create_element("div")
        if isinstance(renderer, RecordingRenderer)
        else renderer.create_element("div")
    )
    handle = mount(view, root, renderer)
    return root, renderer, handle


def html(root):
    return "".join(c.to_html() for c in root.children)


# W1, W2 -------------------------------------------------------------------------------------
def test_signal_child_updates_one_text_node_in_place():
    count = Signal(1)
    root, r, _ = mounted(h.p("n=", count))
    assert html(root) == "<p>n=1</p>"
    r.log.clear()
    count.set(2)
    assert html(root) == "<p>n=2</p>"
    assert [op[0] for op in r.log] == ["replace_text"]


def test_lambda_and_memo_children_are_holes():
    n = Signal(2)
    double = Memo(lambda: n() * 2)
    root, r, _ = mounted(h.p(lambda: f"{n()} x 2 = ", double))
    assert html(root) == "<p>2 x 2 = 4</p>"
    n.set(3)
    assert html(root) == "<p>3 x 2 = 6</p>"


def test_hole_rules_none_bool_element_list():
    v = Signal(None)
    root, r, _ = mounted(h.div(v))
    assert html(root) == "<div></div>"
    v.set(True)
    assert html(root) == "<div></div>"
    v.set(h.b("x"))
    assert html(root) == "<div><b>x</b></div>"
    v.set(["a", h.i("b"), None, 3])
    assert html(root) == "<div>a<i>b</i>3</div>"
    v.set("plain")
    assert html(root) == "<div>plain</div>"


def test_static_children_around_a_hole_stay_put():
    v = Signal("mid")
    root, r, _ = mounted(h.div(h.span("before"), v, h.span("after")))
    assert html(root) == "<div><span>before</span>mid<span>after</span></div>"
    v.set(h.em("new"))
    assert html(root) == "<div><span>before</span><em>new</em><span>after</span></div>"


# W3 --------------------------------------------------------------------------------------------
def test_a_change_touches_only_its_hole():
    a, b = Signal("a"), Signal("b")
    root, r, _ = mounted(h.ul(h.li(a), h.li(b), h.li("static")))
    r.log.clear()
    a.set("A")
    assert r.log == [("replace_text", "A")]
    assert html(root) == "<ul><li>A</li><li>b</li><li>static</li></ul>"


# W4 --------------------------------------------------------------------------------------------
def test_bound_attribute_property_class_and_style():
    title = Signal("t1")
    value = Signal("v1")
    active = Signal(False)
    color = Signal("red")
    root, r, _ = mounted(
        h.input(title=title, prop_value=value, class_active=active, style_color=color, cls="base", id="x")
    )
    node = root.children[0]
    assert node.attrs["title"] == "t1" and node.props["value"] == "v1"
    assert node.attrs["class"] == "base" and node.styles["color"] == "red"
    r.log.clear()
    active.set(True)
    assert node.attrs["class"] == "base active"
    title.set("t2")
    color.set(None)
    value.set("v2")
    assert node.attrs["title"] == "t2" and "color" not in node.styles and node.props["value"] == "v2"
    assert r.count("toggle_class") == 1 and r.count("set_style") == 1


def test_class_dict_toggles_only_what_changed():
    flags = Signal({"a": True, "b": False})
    root, r, _ = mounted(h.div(cls=flags))
    node = root.children[0]
    assert node.attrs["class"] == "a"
    r.log.clear()
    flags.set({"a": True, "b": True})
    assert r.log == [("toggle_class", "b", True)]
    assert node.attrs["class"] == "a b"


def test_boolean_attributes_and_none():
    on = Signal(True)
    root, r, _ = mounted(h.button("go", disabled=on, hidden=None))
    assert html(root) == "<button disabled>go</button>"
    on.set(False)
    assert html(root) == "<button>go</button>"


# W13 (events, through the fake renderer) ----------------------------------------------------
def test_click_handler_and_stop_propagation():
    hits = []
    root, r, _ = mounted(
        h.div(h.button("in", on_click=lambda ev: hits.append("button")), on_click=lambda ev: hits.append("div"))
    )
    button = root.children[0].children[0]
    button.fire("click")
    assert hits == ["button", "div"]  # bubbles
    hits.clear()
    root2, _, _ = mounted(
        h.div(
            h.button("in", on_click=lambda ev: (hits.append("b"), ev.stopPropagation())),
            on_click=lambda ev: hits.append("d"),
        )
    )
    root2.children[0].children[0].fire("click")
    assert hits == ["b"]


def test_event_listeners_are_removed_on_dispose():
    hits = []
    root, r, handle = mounted(h.button("x", on_click=lambda ev: hits.append(1)))
    button = root.children[0]
    handle.dispose()
    button.fire("click")
    assert hits == []


def test_bind_value_two_way():
    name = Signal("ann")
    root, r, _ = mounted(h.input(bind_value=name))
    node = root.children[0]
    assert node.props["value"] == "ann"
    node.props["value"] = "bob"
    node.fire("input")
    assert name() == "bob"
    name.set("cy")
    assert node.props["value"] == "cy"


def test_bind_checked_and_group():
    on = Signal(False)
    color = Signal("red")
    root, r, _ = mounted(
        h.form(
            h.input(type_="checkbox", bind_checked=on),
            h.input(type_="radio", value="red", bind_group=color),
            h.input(type_="radio", value="blue", bind_group=color),
        )
    )
    box, red, blue = root.children[0].children
    assert box.props["checked"] is False and red.props["checked"] is True and blue.props["checked"] is False
    box.props["checked"] = True
    box.fire("change")
    assert on() is True
    blue.fire("change")
    assert color() == "blue" and blue.props["checked"] is True and red.props["checked"] is False


def test_bind_requires_a_signal():
    with pytest.raises(TypeError):
        mounted(h.input(bind_value=lambda: 1))


def test_node_ref_holds_the_element():
    ref = NodeRef()
    root, r, _ = mounted(h.input(ref=ref))
    assert ref.current is root.children[0] and ref() is ref.current


# W5 --------------------------------------------------------------------------------------------
def test_component_runs_once_under_its_own_owner():
    runs = []
    s = Signal(0)

    @component
    def counter(label):
        runs.append(label)
        return h.span(label, ": ", s)

    root, r, handle = mounted(h.div(counter("a"), counter("b")))
    assert html(root) == "<div><span>a: 0</span><span>b: 0</span></div>"
    s.set(1)
    assert runs == ["a", "b"]  # never re-run; only the holes updated
    assert html(root) == "<div><span>a: 1</span><span>b: 1</span></div>"


def test_component_accepts_keyword_arguments():
    @component
    def greet(name, punct="!"):
        return h.b(name, punct)

    assert render_to_string(greet(name="ann", punct="?")) == "<b>ann?</b>"


# W6 --------------------------------------------------------------------------------------------
def test_show_toggles_without_rebuilding_the_kept_branch():
    on = Signal(True)
    builds = []

    def content():
        builds.append(1)
        return h.b("yes")

    root, r, _ = mounted(h.div(Show(on, content, fallback=h.i("no"))))
    assert html(root) == "<div><b>yes</b></div>" and builds == [1]
    on.set(False)
    assert html(root) == "<div><i>no</i></div>"
    on.set(True)
    assert html(root) == "<div><b>yes</b></div>" and builds == [1, 1]  # rebuilt after being disposed
    on.set(True)
    assert builds == [1, 1]  # no change, no rebuild


def test_show_children_may_receive_the_value():
    user = Signal(None)
    root, r, _ = mounted(h.div(Show(user, lambda u: h.b("hi ", u), fallback="anon")))
    assert html(root) == "<div>anon</div>"
    user.set("ann")
    assert html(root) == "<div><b>hi ann</b></div>"


def test_show_keyed_rebuilds_on_value_change():
    user = Signal("ann")
    builds = []

    def content(u):
        builds.append(u)
        return h.b(u)

    root, r, _ = mounted(h.div(Show(user, content, keyed=True)))
    user.set("bob")
    assert builds == ["ann", "bob"] and html(root) == "<div><b>bob</b></div>"


# W7 --------------------------------------------------------------------------------------------
def test_for_keeps_nodes_for_surviving_keys_and_moves_them():
    items = Signal([1, 2, 3])
    root, r, _ = mounted(h.ul(For(items, lambda item, index: h.li(str(item)))))
    ul = root.children[0]
    li1, li2, li3 = [c for c in ul.children if c.tag == "li"]
    assert html(root) == "<ul><li>1</li><li>2</li><li>3</li></ul>"
    r.log.clear()
    items.set([3, 1, 2])
    assert html(root) == "<ul><li>3</li><li>1</li><li>2</li></ul>"
    assert [c for c in ul.children if c.tag == "li"] == [li3, li1, li2]  # same nodes, moved
    assert r.count("create_element") == 0
    items.set([1, 2])
    assert html(root) == "<ul><li>1</li><li>2</li></ul>"
    assert r.count("remove_node") == 1


def test_for_index_is_reactive_and_rows_dispose_individually():
    items = Signal(["a", "b", "c"])
    disposed = []

    def row(item, index):
        from frontage import on_cleanup

        on_cleanup(lambda: disposed.append(item))
        return h.li(lambda: f"{index()}:{item}")

    root, r, _ = mounted(h.ul(For(items, row)))
    assert html(root) == "<ul><li>0:a</li><li>1:b</li><li>2:c</li></ul>"
    items.set(["c", "a"])
    assert html(root) == "<ul><li>0:c</li><li>1:a</li></ul>"
    assert disposed == ["b"]


def test_for_with_key_function_and_fallback():
    users = Signal([{"id": 1, "name": "ann"}])
    root, r, _ = mounted(h.ul(For(users, lambda u, i: h.li(u["name"]), key=lambda u: u["id"], fallback=h.li("empty"))))
    li = [c for c in root.children[0].children if c.tag == "li"][0]
    users.set([{"id": 1, "name": "ann"}, {"id": 2, "name": "bob"}])
    assert [c for c in root.children[0].children if c.tag == "li"][0] is li  # id 1 kept its node
    users.set([])
    assert html(root) == "<ul><li>empty</li></ul>"


def test_for_index_mode_reuses_rows_by_position():
    items = Signal(["a", "b"])
    root, r, _ = mounted(h.ul(For(items, lambda item, i: h.li(item), key=False)))
    r.log.clear()
    items.set(["A", "B"])
    assert html(root) == "<ul><li>A</li><li>B</li></ul>"
    assert r.count("create_element") == 0 and r.count("replace_text") == 2


def test_for_duplicate_keys_are_an_error():
    items = Signal([1, 1])
    with pytest.raises(ValueError):
        mounted(h.ul(For(items, lambda item, i: h.li(item))))


def test_for_over_a_store_list():
    store = Store({"todos": ["x"]})
    root, r, _ = mounted(h.ul(For(lambda: store.todos, lambda t, i: h.li(t))))
    store.set(lambda d: d.todos.append("y"))
    assert html(root) == "<ul><li>x</li><li>y</li></ul>"


# render_to_string still works with holes ----------------------------------------------------
def test_render_to_string_renders_current_hole_values():
    s = Signal(5)
    assert render_to_string(h.p("n=", s)) == "<p>n=5</p>"


# reconciliation cost (SPEC W2, W7) -----------------------------------------------------------
def rows_of(root):
    return [c for c in root.children[0].children if c.tag == "li"]


def test_swap_costs_two_moves_and_append_costs_only_new_nodes():
    items = Signal(list(range(1000)))
    root, r, _ = mounted(h.ul(For(items, lambda item, i: h.li(str(item)))))
    before = rows_of(root)
    r.log.clear()
    swapped = list(range(1000))
    swapped[1], swapped[998] = swapped[998], swapped[1]
    items.set(swapped)
    assert r.count("insert_node") == 2 and r.count("remove_node") == 0 and r.count("create_element") == 0
    after = rows_of(root)
    assert after[1] is before[998] and after[998] is before[1] and after[0] is before[0]
    r.log.clear()
    items.set(swapped + list(range(1000, 1010)))
    assert r.count("create_element") == 10 and r.count("insert_node") == 10 + 10  # a text and an li per row


def test_reverse_and_clear_and_remove_one():
    items = Signal([1, 2, 3, 4, 5])
    root, r, _ = mounted(h.ul(For(items, lambda item, i: h.li(str(item)))))
    r.log.clear()
    items.set([5, 4, 3, 2, 1])
    assert html(root) == "<ul><li>5</li><li>4</li><li>3</li><li>2</li><li>1</li></ul>"
    assert r.count("insert_node") == 4 and r.count("create_element") == 0
    r.log.clear()
    items.set([5, 4, 2, 1])
    assert r.count("remove_node") == 1 and r.count("insert_node") == 0
    r.log.clear()
    items.set([])
    assert r.count("remove_node") == 4 and html(root) == "<ul></ul>"
