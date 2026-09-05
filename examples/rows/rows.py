"""The js-framework-benchmark rows example: the numbers behind DESIGN.md §12.

Buttons run each operation and the #stats line reports wall time and how many renderer
operations (bridge crossings) it took, so tools/bench.py can read both.
"""

from pyscript import window

from frontage import Signal, Store, component, h, mount, selector
from frontage.dom import DomRenderer
from frontage.flow import For

ADJECTIVES = [
    "pretty",
    "large",
    "big",
    "small",
    "tall",
    "short",
    "long",
    "handsome",
    "plain",
    "quaint",
    "clean",
    "elegant",
    "easy",
    "angry",
    "crazy",
    "helpful",
    "mushy",
    "odd",
    "unsightly",
    "adorable",
    "important",
    "inexpensive",
    "cheap",
    "expensive",
    "fancy",
]
COLOURS = ["red", "yellow", "blue", "green", "pink", "brown", "purple", "brown", "white", "black", "orange"]
NOUNS = [
    "table",
    "chair",
    "house",
    "bbq",
    "desk",
    "car",
    "pony",
    "cookie",
    "sandwich",
    "burger",
    "pizza",
    "mouse",
    "keyboard",
]

state = Store({"rows": []})
selected = Signal(None)
is_selected = selector(selected)
next_id = [1]
seed = [42]


def rand(n):
    seed[0] = (seed[0] * 1103515245 + 12345) & 0x7FFFFFFF
    return seed[0] % n


def make_rows(n):
    out = []
    for _ in range(n):
        out.append(
            {
                "id": next_id[0],
                "label": f"{ADJECTIVES[rand(len(ADJECTIVES))]} {COLOURS[rand(len(COLOURS))]} {NOUNS[rand(len(NOUNS))]}",
            }
        )
        next_id[0] += 1
    return out


class CountingDomRenderer(DomRenderer):
    """Counts renderer calls, i.e. bridge crossings. Explicit overrides: MicroPython has no
    `__getattribute__` hook."""

    ops = 0

    def create_element(self, tag):
        CountingDomRenderer.ops += 1
        return DomRenderer.create_element(self, tag)

    def create_text(self, text):
        CountingDomRenderer.ops += 1
        return DomRenderer.create_text(self, text)

    def replace_text(self, node, text):
        CountingDomRenderer.ops += 1
        return DomRenderer.replace_text(self, node, text)

    def set_property(self, node, name, value):
        CountingDomRenderer.ops += 1
        return DomRenderer.set_property(self, node, name, value)

    def insert_node(self, parent, node, anchor=None):
        CountingDomRenderer.ops += 1
        return DomRenderer.insert_node(self, parent, node, anchor)

    def remove_node(self, parent, node):
        CountingDomRenderer.ops += 1
        return DomRenderer.remove_node(self, parent, node)

    def toggle_class(self, node, name, on):
        CountingDomRenderer.ops += 1
        return DomRenderer.toggle_class(self, node, name, on)

    def set_style(self, node, prop, value):
        CountingDomRenderer.ops += 1
        return DomRenderer.set_style(self, node, prop, value)

    def add_listener(self, node, event, handler, capture=False):
        CountingDomRenderer.ops += 1
        return DomRenderer.add_listener(self, node, event, handler, capture)


renderer = CountingDomRenderer()

# ?templates=0 builds node by node instead of cloning templates, so tools/bench.py can compare.
if "templates=0" in str(window.location.search):
    from frontage import view as _view

    _view.TEMPLATES = False
stats = Signal("")


def timed(name, fn):
    def handler(ev):
        CountingDomRenderer.ops = 0
        t0 = window.performance.now()
        fn()
        dt = window.performance.now() - t0
        stats.set(f"{name}: {dt:.1f} ms, {CountingDomRenderer.ops} ops")

    return handler


def create(n):
    return lambda: state.set(lambda d: d.__setitem__("rows", make_rows(n)))


def append(n):
    return lambda: state.set(lambda d: d.rows.extend(make_rows(n)))


def update_every_tenth():
    def apply(d):
        for i in range(0, len(d.rows), 10):
            d.rows[i]["label"] = d.rows[i]["label"] + " !!!"

    state.set(apply)


def swap():
    def apply(d):
        if len(d.rows) > 998:
            a, b = d.rows[1], d.rows[998]
            d.rows[1] = b
            d.rows[998] = a

    state.set(apply)


def clear():
    state.set(lambda d: d.__setitem__("rows", []))


def remove(row_id):
    def apply(d):
        for i, r in enumerate(d.rows):
            if r["id"] == row_id:
                d.rows.pop(i)
                return

    state.set(apply)


def row(r, index):
    rid = r["id"]
    return h.tr(
        h.td(str(rid), cls="col-md-1"),
        h.td(h.a(lambda: r["label"], on_click=lambda ev: selected.set(rid)), cls="col-md-4"),
        h.td(
            h.a("×", on_click=lambda ev: remove(rid), cls="remove", aria_label="remove"),
            cls="col-md-1",
        ),
        h.td(cls="col-md-6"),
        class_danger=lambda: is_selected(rid),
    )


@component
def app():
    return h.div(
        h.div(
            h.button("Create 1,000 rows", id="run", on_click=timed("create 1,000", create(1000))),
            h.button("Create 10,000 rows", id="runlots", on_click=timed("create 10,000", create(10000))),
            h.button("Append 1,000 rows", id="add", on_click=timed("append 1,000", append(1000))),
            h.button("Update every 10th row", id="update", on_click=timed("update every 10th", update_every_tenth)),
            h.button("Clear", id="clear", on_click=timed("clear", clear)),
            h.button("Swap Rows", id="swaprows", on_click=timed("swap", swap)),
            cls="buttons",
        ),
        h.p(stats, id="stats"),
        h.table(
            h.tbody(For(lambda: state.rows, row, key=lambda r: r["id"]), id="tbody"),
            cls="table table-hover table-striped test-data",
        ),
    )


mount(app, "#app", renderer=renderer)
