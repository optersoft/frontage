"""Control flow as components: `Show`, `For`, `Switch`/`Match`, `Loading`, `Errored`,
`Dynamic`, `Portal`.

Each returns a callable, which is what a child position treats as a hole. Each builds its
branches or rows under owners of its own, so a row that leaves disposes only itself, and the
hole they live in moves existing nodes instead of recreating them.
"""

from . import reactive
from .reactive import ERRORS, LOADING, Memo, Owner, Signal, get_owner, on_cleanup, provide, run_with_owner, untrack
from .view import Mounted, _build_nodes

__all__ = ["Dynamic", "Errored", "For", "Loading", "Match", "Portal", "Show", "Switch"]


class _Branch:
    """What a control-flow accessor keeps between runs: the mounted branch's owner, its
    nodes, and the key that chose it."""

    def __init__(self):
        self.owner = None
        self.nodes = []
        self.key = None

    def dispose(self):
        if self.owner is not None:
            self.owner.dispose()
            self.owner = None


class _Renderers:
    """The renderer a control-flow accessor should build with is the one of the hole it
    lives in. The view layer sets it around each hole's compute; this holds it."""

    current = None


def _build(view, renderer, cache=None):
    return _build_nodes(view, renderer, cache)


def Show(when, children, fallback=None, keyed=False):
    """Mount `children` while `when()` is truthy, else `fallback`. The mounted branch is kept
    across re-runs unless the condition flips (or, with `keyed=True`, the value changes).
    `children` may be a view, or a function of the value."""
    raw = Memo(when)
    condition = raw if keyed else Memo(lambda: bool(raw()))
    state = _Branch()
    # Branches belong to whoever created the Show, not to the hole's effect: the hole
    # re-runs on every flip and disposes what it owns first, which must not be the branch.
    home = get_owner()
    on_cleanup(state.dispose)

    def accessor():
        from . import view as _view

        renderer = _view._current_renderer
        key = condition()
        value = raw.peek()
        if state.owner is not None and state.key == key:
            return Mounted(state.nodes)
        state.dispose()
        owner = Owner(parent=home)
        branch = children if value else fallback
        if callable(branch) and not hasattr(branch, "tag"):
            content = run_with_owner(owner, lambda: _call_branch(branch, value))
        else:
            content = branch
        nodes = run_with_owner(owner, lambda: _build(content, renderer)) if content is not None else []
        state.key, state.owner, state.nodes = key, owner, nodes
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
    key and `key="id"` reads that item key; `key=False` is index mode: rows are reused by position and `children` receives an
    accessor for the item and a plain index. Otherwise `children(item, index)` where `index`
    is an accessor.
    """
    rows = {}  # key -> dict(owner, nodes, index, item)
    order = []
    home = get_owner()  # rows belong here, not to the hole's effect (see Show)
    template_cache = {}  # rows share one compiled Template when their shape matches
    identity = [False]  # some item was keyed by id(): the case the debug warning watches
    warned = [False]
    on_cleanup(lambda: [row["owner"].dispose() for row in rows.values()])

    def key_of(item, i):
        if key is False:
            return i
        if key is None:
            try:
                hash(item)
                return item
            except TypeError:
                identity[0] = True
                return id(item)
        if isinstance(key, str):
            return item[key]
        return key(item)

    def accessor():
        from . import view as _view

        renderer = _view._current_renderer
        items = list(each() or [])
        previous = len(rows)
        new_order = []
        seen = set()
        survived = 0
        for i, item in enumerate(items):
            k = key_of(item, i)
            if k in seen:
                raise ValueError(f"For: duplicate key {k!r}")
            seen.add(k)
            new_order.append(k)
            row = rows.get(k)
            if row is None:
                row = _make_row(item, i, key is False, children, renderer, home, template_cache)
                rows[k] = row
            else:
                survived += 1
                if row["index"].peek() != i:
                    row["index"]._write(i)
                if key is False and row["item"].peek() is not item:
                    row["item"]._write(item)
        if reactive.DEBUG and identity[0] and previous and items and survived == 0 and not warned[0]:
            # Every row was rebuilt: the items are fresh objects each time (dicts rebuilt in a
            # handler), so identity keys never match. The fix is a key.
            warned[0] = True
            reactive.warn(
                f"For: none of the {previous} rows survived an update, so every row was rebuilt "
                "(focus and scroll with it). The items are keyed by identity; give For a key= "
                '(key="id", or a function) that survives a rebuilt item.'
            )
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


def _is(a, b):
    return a is b


def _make_row(item, i, index_mode, children, renderer, home, cache):
    owner = Owner(parent=home)
    index = Signal(i)
    item_signal = Signal(item, equal=_is)

    def make():
        if index_mode:
            view = children(item_signal, i)
        else:
            view = children(item, index)
        return _build(view, renderer, cache)

    nodes = run_with_owner(owner, untrack, make)
    return {"owner": owner, "nodes": nodes, "index": index, "item": item_signal}


# --- Switch / Match ---------------------------------------------------------------------------


def Match(when, children):
    """One case of a `Switch`: `(when, children)`."""
    return (when, children)


def Switch(cases, fallback=None):
    """Mount the children of the first case whose `when()` is truthy, else `fallback`. The
    mounted branch is kept until a different case wins."""
    cases = list(cases)
    home = get_owner()
    state = _Branch()
    on_cleanup(state.dispose)

    def which():
        for i in range(len(cases)):
            when = cases[i][0]
            if when() if callable(when) else when:
                return i
        return -1

    index = Memo(which)

    def accessor():
        from . import view as _view

        renderer = _view._current_renderer
        key = index()
        if state.owner is not None and state.key == key:
            return Mounted(state.nodes)
        state.dispose()
        owner = Owner(parent=home)
        branch = cases[key][1] if key >= 0 else fallback
        content = (
            run_with_owner(owner, lambda: untrack(branch))
            if callable(branch) and not hasattr(branch, "tag")
            else branch
        )
        nodes = run_with_owner(owner, lambda: _build(content, renderer)) if content is not None else []
        state.key, state.owner, state.nodes = key, owner, nodes
        return Mounted(nodes)

    return accessor


# --- Loading / Errored ------------------------------------------------------------------------


class _LoadingScope:
    def __init__(self, keep=False):
        self.pending = Signal(0)
        self.keep = keep
        self._resources = []

    def add(self, resource, refreshing=False):
        if self.keep and refreshing:
            return
        if resource not in self._resources:
            self._resources.append(resource)
            self.pending._write(self.pending.peek() + 1)

    def remove(self, resource):
        if resource in self._resources:
            self._resources.remove(resource)
            self.pending._write(self.pending.peek() - 1)


def Loading(fallback, children, keep=False):
    """Show `fallback` while any `Resource` read beneath `children` is loading. The children
    are built once and kept; only which of the two is in the DOM changes. With `keep=True`
    only a resource's *first* load shows the fallback: a refetch keeps the content on screen
    (the resource returns its previous value meanwhile, and `loading()` says it is refreshing)."""
    scope = _LoadingScope(keep)
    home = get_owner()
    owner = Owner(parent=home)
    content_state = _Branch()
    fallback_state = _Branch()
    on_cleanup(fallback_state.dispose)

    def build_children(renderer):
        def make():
            provide(LOADING, scope)
            content = untrack(children) if callable(children) and not hasattr(children, "tag") else children
            return _build(content, renderer)

        return run_with_owner(owner, make)

    def accessor():
        from . import view as _view

        renderer = _view._current_renderer
        if content_state.owner is None:
            content_state.owner = owner
            content_state.nodes = build_children(renderer)
        if scope.pending() > 0:
            if fallback_state.owner is None:
                fb_owner = Owner(parent=home)
                content = untrack(fallback) if callable(fallback) and not hasattr(fallback, "tag") else fallback
                fallback_state.owner = fb_owner
                fallback_state.nodes = (
                    run_with_owner(fb_owner, lambda: _build(content, renderer)) if content is not None else []
                )
            return Mounted(fallback_state.nodes)
        return Mounted(content_state.nodes)

    return accessor


class _ErrorScope:
    def __init__(self):
        self.error = Signal(None, equal=lambda a, b: a is b)

    def handle(self, exc):
        self.error.set(exc)


def Errored(fallback, children):
    """Catch exceptions raised in computations and handlers beneath `children`; render
    `fallback(error, reset)` instead until `reset()` is called, which rebuilds the children."""
    scope = _ErrorScope()
    home = get_owner()
    state = _Branch()
    on_cleanup(state.dispose)

    def reset():
        scope.error.set(None)

    def accessor():
        from . import view as _view

        renderer = _view._current_renderer
        error = scope.error()
        state.dispose()
        owner = Owner(parent=home)

        def make():
            if error is not None:
                content = (
                    untrack(fallback, error, reset) if callable(fallback) and not hasattr(fallback, "tag") else fallback
                )
                return _build(content, renderer) if content is not None else []
            provide(ERRORS, scope)
            try:
                content = untrack(children) if callable(children) and not hasattr(children, "tag") else children
                return _build(content, renderer) if content is not None else []
            except Exception as exc:
                # Raised while building (not inside a computation, which routes itself):
                # record it; this accessor re-runs at once and renders the fallback.
                scope.handle(exc)
                return []

        nodes = run_with_owner(owner, make)
        state.owner, state.nodes = owner, nodes
        return Mounted(nodes)

    return accessor


# --- Dynamic / Portal -------------------------------------------------------------------------


def Dynamic(component, **props):
    """Render whatever component (a function returning a view, or a tag name) `component()`
    currently yields, rebuilding when it changes."""
    which = Memo(component) if callable(component) and not hasattr(component, "tag") else Memo(lambda: component)
    home = get_owner()
    state = _Branch()
    on_cleanup(state.dispose)

    def accessor():
        from . import view as _view

        renderer = _view._current_renderer
        target = which()
        if state.owner is not None and state.key is target:
            return Mounted(state.nodes)
        state.dispose()
        owner = Owner(parent=home)

        def make():
            if isinstance(target, str):
                return _build(_view.h(target, **props), renderer)
            return _build(untrack(lambda: target(**props)), renderer) if target is not None else []

        nodes = run_with_owner(owner, make)
        state.key, state.owner, state.nodes = target, owner, nodes
        return Mounted(nodes)

    return accessor


def Portal(target, children):
    """Build `children` into another node (`target`: a node or, in the browser, a selector)
    while this hole stays empty; removed when the owner goes. A selector target is a browser
    thing: the prerenderer leaves it empty and the browser builds it on mount."""
    home = get_owner()
    owner = Owner(parent=home)
    state = _Branch()

    def accessor():
        from . import view as _view
        from .runtime import in_browser

        renderer = _view._current_renderer
        assert renderer is not None
        if isinstance(target, str) and not in_browser:
            return Mounted([])
        if state.owner is None:
            node = target
            if isinstance(target, str):
                from .dom import resolve

                node = resolve(target)

            def make():
                hyd = getattr(renderer, "hydration", None)
                if hyd is not None:
                    hyd.push(None)  # the portal's nodes are not in the prerendered target
                try:
                    content = untrack(children) if callable(children) and not hasattr(children, "tag") else children
                    nodes = _build(content, renderer)
                finally:
                    if hyd is not None:
                        hyd.pop()
                for n in nodes:
                    _view._insert(renderer, node, n)
                return nodes

            state.owner = owner
            state.nodes = run_with_owner(owner, make)
            r = renderer
            owner.on_cleanup(lambda: [r.remove_node(node, n) for n in state.nodes])
        return Mounted([])

    return accessor
