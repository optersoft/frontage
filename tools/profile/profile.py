# ruff: noqa: B007, B015, B018, B023  (the calibration loops are deliberately pointless)
"""Where the time goes in the rows benchmark, phase by phase, on whichever interpreter loads
this page (`/profile/?type=mpy|py` under tools/serve.py; tools/profile_rows.py drives it).

Each phase is timed on its own with performance.now() around it, three runs, median:
data (the dicts), elements (1,000 `row()` trees, no renderer), store (the write, nobody
subscribed), then a `For` over the store mounted with three renderers: the DOM node by node,
a renderer that does nothing (the Python side alone: view + reactive + store), and the DOM
through templates (what the example does). Then swap and update on the DOM mount."""

from pyscript import document, window

from frontage import Signal, Store, h, mount, selector
from frontage import view as _view
from frontage.dom import DomRenderer
from frontage.flow import For
from frontage.renderer import Renderer

ADJ = ["pretty", "large", "big", "small", "tall", "short", "long", "handsome", "plain", "quaint"]
COL = ["red", "yellow", "blue", "green", "pink", "brown", "purple", "white", "black", "orange"]
NOUN = ["table", "chair", "house", "bbq", "desk", "car", "pony", "cookie", "sandwich", "burger"]
next_id = [1]


def make_rows(n):
    out = []
    for i in range(n):
        rid = next_id[0]
        next_id[0] += 1
        out.append({"id": rid, "label": f"{ADJ[i % 10]} {COL[(i * 7) % 10]} {NOUN[(i * 3) % 10]}"})
    return out


class _N:
    __slots__ = ()


def _noop():
    pass


class NullRenderer(Renderer):
    """Every operation is a Python method call that does nothing: the bridge removed."""

    supports_templates = False

    def create_element(self, tag):
        return _N()

    def create_text(self, text):
        return _N()

    def replace_text(self, node, text):
        pass

    def set_property(self, node, name, value):
        pass

    def insert_node(self, parent, node, anchor=None):
        pass

    def remove_node(self, parent, node):
        pass

    def is_text(self, node):
        return False

    def parent(self, node):
        return None

    def mark_root(self, node):
        pass

    def is_connected(self, node):
        return True

    def first_child(self, node):
        return None

    def next_sibling(self, node):
        return None

    def toggle_class(self, node, name, on):
        pass

    def set_style(self, node, prop, value):
        pass

    def add_listener(self, node, event, handler, capture=False):
        return _noop  # the remover the view registers as a cleanup

    def replace_node(self, parent, new, old):
        pass

    def dispatch_event(self, node, name, detail=None):
        pass


selected = Signal(None)
is_selected = selector(selected)


def row(r, index):
    rid = r["id"]
    return h.tr(
        h.td(str(rid), cls="col-md-1"),
        h.td(h.a(lambda: r["label"], on_click=lambda ev: selected.set(rid)), cls="col-md-4"),
        h.td(h.a("×", on_click=lambda ev: None, cls="remove", aria_label="remove"), cls="col-md-1"),
        h.td(cls="col-md-6"),
        class_danger=lambda: is_selected(rid),
    )


def now():
    return window.performance.now()


def median3(fn):
    ts = []
    for _ in range(3):
        t0 = now()
        fn()
        ts.append(now() - t0)
    ts.sort()
    return ts[1]


lines = []


def report(name, ms):
    lines.append(f"{name:<44}{ms:>9.1f} ms")
    document.getElementById("out").textContent = "\n".join(lines)


def phase_data():
    make_rows(1000)


def phase_elements():
    rows = make_rows(1000)

    def build():
        for r in rows:
            row(r, lambda: 0)

    return build


def phase_store():
    state = Store({"rows": []})
    rows = make_rows(1000)
    return lambda: state.set(lambda d: d.__setitem__("rows", list(rows)))


def row_static(r, index):
    rid = r["id"]
    return h.tr(
        h.td(str(rid), cls="col-md-1"),
        h.td(h.a(r["label"]), cls="col-md-4"),
        h.td(h.a("×", cls="remove", aria_label="remove"), cls="col-md-1"),
        h.td(cls="col-md-6"),
    )


def row_holes_only(r, index):
    rid = r["id"]
    return h.tr(
        h.td(str(rid), cls="col-md-1"),
        h.td(h.a(lambda: r["label"]), cls="col-md-4"),
        h.td(h.a("×", cls="remove", aria_label="remove"), cls="col-md-1"),
        h.td(cls="col-md-6"),
        class_danger=lambda: is_selected(rid),
    )


def row_handlers_only(r, index):
    rid = r["id"]
    return h.tr(
        h.td(str(rid), cls="col-md-1"),
        h.td(h.a(r["label"], on_click=lambda ev: selected.set(rid)), cls="col-md-4"),
        h.td(h.a("×", on_click=lambda ev: None, cls="remove", aria_label="remove"), cls="col-md-1"),
        h.td(cls="col-md-6"),
    )


def mounted_for(renderer, templates, row_fn=row, store=True):
    """Mount a For over 1,000 rows with `renderer`; returns (write, handle)."""
    _view.TEMPLATES = templates
    rows = make_rows(1000)
    root = (
        renderer.create_element("tbody") if not isinstance(renderer, DomRenderer) else document.createElement("tbody")
    )
    if store:
        state = Store({"rows": []})
        source = lambda: state.rows  # noqa: E731
        write = lambda: state.set(lambda d: d.__setitem__("rows", rows))  # noqa: E731
    else:
        state = Signal([])
        source = state
        write = lambda: state.set(rows)  # noqa: E731
    handle = mount(lambda: For(source, row_fn, key=lambda r: r["id"]), root, renderer)
    return state, rows, handle, write


def phase_mount(renderer_factory, templates, row_fn=row, store=True):
    def run():
        state, rows, handle, write = mounted_for(renderer_factory(), templates, row_fn, store)
        t0 = now()
        write()
        dt = now() - t0
        handle.dispose()
        return dt

    ts = sorted(run() for _ in range(3))
    return ts[1]


def phase_ops_on_dom():
    state, rows, handle, write = mounted_for(DomRenderer(), True)
    write()

    def swap():
        def apply(d):
            a, b = d.rows[1], d.rows[998]
            d.rows[1] = b
            d.rows[998] = a

        state.set(apply)

    def update():
        def apply(d):
            for i in range(0, len(d.rows), 10):
                d.rows[i]["label"] = d.rows[i]["label"] + " !!!"

        state.set(apply)

    def select():
        selected.set(rows[500]["id"])
        selected.set(rows[501]["id"])

    report("swap two rows (DOM, templates)", median3(swap))
    report("update every 10th (DOM, templates)", median3(update))
    report("select a row, then another (DOM)", median3(select))
    handle.dispose()


class _Obj:
    def __init__(self, a, b, c, d):
        self.a = a
        self.b = b
        self.c = c
        self.d = d

    def method(self, x):
        return x


def calibrate():
    """µs per primitive, 10,000 of each: what a row's budget is made of."""
    o = _Obj(1, 2, 3, 4)

    def calls():
        m = o.method
        for i in range(10000):
            m(i)

    def closures():
        for i in range(10000):
            (lambda: i)

    def objects():
        for i in range(10000):
            _Obj(i, i, i, i)

    def isinstances():
        for i in range(10000):
            isinstance(o, (str, int, float)) or isinstance(o, list) or isinstance(o, _Obj)

    def dicts():
        d = {"a": 1}
        for i in range(10000):
            d.get("b")

    def isinstance_one():
        for i in range(10000):
            isinstance(o, _Obj)

    def isinstance_tuple_miss():
        for i in range(10000):
            isinstance(o, (str, int, float))

    def type_is():
        t = _Obj
        for i in range(10000):
            type(o) is t

    def type_in_set():
        kinds = {str: 1, int: 1, float: 1}
        for i in range(10000):
            type(o) in kinds

    for name, fn in (
        ("method call", calls),
        ("closure", closures),
        ("object (4 attrs)", objects),
        ("3 isinstance", isinstances),
        ("isinstance, one class, hit", isinstance_one),
        ("isinstance, 3-tuple, miss", isinstance_tuple_miss),
        ("type() is", type_is),
        ("type() in dict", type_in_set),
        ("dict miss", dicts),
    ):
        report(f"calibration: {name}, per 10,000", median3(fn))


calibrate()
report("data: make_rows(1000)", median3(phase_data))
report("elements: 1,000 row() trees, no renderer", median3(phase_elements()))
report("store: write 1,000 rows, no subscriber", median3(phase_store()))
report("For, null renderer, node by node", phase_mount(NullRenderer, False))
report("  same, rows in a Signal, not a Store", phase_mount(NullRenderer, False, store=False))
report("  same, static rows (no holes, no handlers)", phase_mount(NullRenderer, False, row_static))
report("  same, holes but no handlers", phase_mount(NullRenderer, False, row_holes_only))
report("  same, handlers but no holes", phase_mount(NullRenderer, False, row_handlers_only))
report("For, DOM, node by node", phase_mount(DomRenderer, False))
report("For, DOM, templates", phase_mount(DomRenderer, True))
phase_ops_on_dom()
document.getElementById("done").hidden = False
