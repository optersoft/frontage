"""Control flow as components: `Show` and `For` (M1); `Switch`, `Loading`, `Errored` follow.

Both return a callable, which is what a child position treats as a hole. Each builds its
branches or rows under owners of its own, so a row that leaves disposes only itself, and the
hole they live in moves existing nodes instead of recreating them.
"""

from .reactive import Memo, Owner, Signal, get_owner, on_cleanup, run_with_owner, untrack
from .view import Mounted, _build_nodes

__all__ = ["For", "Show"]


class _Renderers:
    """The renderer a control-flow accessor should build with is the one of the hole it
    lives in. The view layer sets it around each hole's compute; this holds it."""

    current = None


def _build(view, renderer):
    return _build_nodes(view, renderer)


def Show(when, children, fallback=None, keyed=False):
    """Mount `children` while `when()` is truthy, else `fallback`. The mounted branch is kept
    across re-runs unless the condition flips (or, with `keyed=True`, the value changes).
    `children` may be a view, or a function of the value."""
    raw = Memo(when)
    condition = raw if keyed else Memo(lambda: bool(raw()))
    state = {"key": None, "owner": None, "nodes": None}
    # Branches belong to whoever created the Show, not to the hole's effect: the hole
    # re-runs on every flip and disposes what it owns first, which must not be the branch.
    home = get_owner()
    on_cleanup(lambda: state["owner"] is not None and state["owner"].dispose())

    def accessor():
        from . import view as _view

        renderer = _view._current_renderer
        key = condition()
        value = raw.peek()
        if state["owner"] is not None and state["key"] == key:
            return Mounted(state["nodes"])
        if state["owner"] is not None:
            state["owner"].dispose()
        owner = Owner(parent=home)
        branch = children if value else fallback
        if callable(branch) and not hasattr(branch, "tag"):
            content = run_with_owner(owner, lambda: _call_branch(branch, value))
        else:
            content = branch
        nodes = run_with_owner(owner, lambda: _build(content, renderer)) if content is not None else []
        state.update(key=key, owner=owner, nodes=nodes)
        return Mounted(nodes)

    return accessor


def _call_branch(fn, value):
    """Call a Show branch with the value if it takes one argument, else without.

    CPython and Pyodide expose `__code__.co_argcount`; MicroPython's code objects do not, so
    there the call with the value is tried first and a TypeError falls back to the
    no-argument form."""
    argcount = getattr(getattr(fn, "__code__", None), "co_argcount", None)
    if argcount is not None:
        return untrack(fn, value) if argcount >= 1 else untrack(fn)
    try:
        return untrack(fn, value)
    except TypeError:
        return untrack(fn)


def For(each, children, key=None, fallback=None):
    """One row per item of `each()`, keyed so unchanged rows keep their nodes.

    `key=None` keys by the item itself (identity for unhashable items); `key=fn` extracts a
    key; `key=False` is index mode: rows are reused by position and `children` receives an
    accessor for the item and a plain index. Otherwise `children(item, index)` where `index`
    is an accessor.
    """
    rows = {}  # key -> dict(owner, nodes, index, item)
    order = []
    home = get_owner()  # rows belong here, not to the hole's effect (see Show)
    on_cleanup(lambda: [row["owner"].dispose() for row in rows.values()])

    def key_of(item, i):
        if key is False:
            return i
        if key is None:
            try:
                hash(item)
                return item
            except TypeError:
                return id(item)
        return key(item)

    def accessor():
        from . import view as _view

        renderer = _view._current_renderer
        items = list(each() or [])
        new_order = []
        seen = set()
        for i, item in enumerate(items):
            k = key_of(item, i)
            if k in seen:
                raise ValueError(f"For: duplicate key {k!r}")
            seen.add(k)
            new_order.append(k)
            row = rows.get(k)
            if row is None:
                row = _make_row(item, i, key is False, children, renderer, home)
                rows[k] = row
            else:
                if row["index"].peek() != i:
                    row["index"].set(i)
                if key is False and row["item"].peek() is not item:
                    row["item"].set(item)
        for k in list(rows):
            if k not in seen:
                rows.pop(k)["owner"].dispose()
        order[:] = new_order
        nodes = []
        for k in new_order:
            nodes.extend(rows[k]["nodes"])
        if not nodes and fallback is not None:
            return fallback
        return Mounted(nodes)

    return accessor


def _make_row(item, i, index_mode, children, renderer, home):
    owner = Owner(parent=home)
    index = Signal(i)
    item_signal = Signal(item, equal=lambda a, b: a is b)

    def make():
        if index_mode:
            view = children(item_signal, i)
        else:
            view = children(item, index)
        return _build(view, renderer)

    nodes = run_with_owner(owner, lambda: untrack(make))
    return {"owner": owner, "nodes": nodes, "index": index, "item": item_signal}
