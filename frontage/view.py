"""The view tree, the `h` builder, and how a view becomes live nodes.

A view is a tree of `Element` and `Text` nodes that knows nothing about a document. The
builder makes one two ways that produce the same tree: the call form, `h.div(h.p("hi"),
cls="x")`, and the `with` form, where elements created inside `with h.div():` become its
children.

`build(view, renderer, parent)` draws a view through a `Renderer`. Where a child or an
attribute value is a callable (a `Signal`, a `Memo`, a lambda), it becomes a *hole*: a
`RenderEffect` that re-applies the insert rules when what the callable read changes, and
touches nothing else. The insert rules for a child hole: a string or number updates one text
node in place; `None` and booleans render nothing; an `Element` or `Text` is built and
mounted; a `Mounted` (nodes control flow already built) is placed; a list is flattened and
reconciled against the current nodes by identity, moving nodes rather than recreating them.

Attribute keywords carry their kind in a prefix: `on_click` (an event), `prop_value` (a DOM
property, the form inputs need), `class_active` (toggle one class), `style_color`,
`bind_value` / `bind_checked` / `bind_group` (two-way), `ref` (a `NodeRef`). Anything else
is an attribute; `cls` and `class_` spell `class`, and `class` may be a dict of toggles.
"""

from .reactive import Owner, RenderEffect, Signal, on_cleanup
from .renderer import HtmlRenderer

__all__ = [
    "Element",
    "Mounted",
    "NodeRef",
    "Text",
    "build",
    "component",
    "h",
    "mount",
    "render_to_string",
    "text",
]

_UNSET = object()
_current_renderer = None  # the renderer of the hole being computed; control flow builds with it


class Text:
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Text({self.value!r})"


class Element:
    def __init__(self, tag, attrs, children):
        self.tag = tag
        self.attrs = attrs
        self.children = children

    def __repr__(self):
        return f"Element({self.tag!r}, {self.attrs!r}, {self.children!r})"

    # The `with` form: elements built inside the block are appended to this one.
    def __enter__(self):
        _stack.append(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        _stack.pop()
        return False


class Mounted:
    """Nodes that control flow has already built; a child hole places them as they are."""

    def __init__(self, nodes):
        self.nodes = nodes


class NodeRef:
    """Holds the live node of the element it is passed to as `ref=`; `None` before mount."""

    def __init__(self):
        self.current = None

    def __call__(self):
        return self.current


_stack = []

_ATTR_ALIASES = {"cls": "class", "class_": "class", "for_": "for"}


def _attr_name(name):
    if name in _ATTR_ALIASES:
        return _ATTR_ALIASES[name]
    if name.endswith("_"):
        name = name[:-1]
    return name.replace("_", "-")


def _children(items):
    out = []
    for item in items:
        if item is None or item is True or item is False:
            continue
        if isinstance(item, (list, tuple)):
            out.extend(_children(item))
        elif isinstance(item, (Element, Text, Mounted)) or callable(item):
            out.append(item)
        else:
            out.append(Text(item))
    return out


class _TagFactory:
    def __init__(self, tag):
        self.tag = tag

    def __call__(self, *children, **attrs):
        element = Element(self.tag, attrs, _children(children))
        if _stack:
            _stack[-1].children.append(element)
        return element


class _Builder:
    def __getattr__(self, tag):
        return _TagFactory(tag.rstrip("_").replace("_", "-"))

    def __call__(self, tag, *children, **attrs):
        return _TagFactory(tag)(*children, **attrs)


h = _Builder()


def text(value):
    """A text node; inside a `with` block it is appended like an element."""
    node = Text(value)
    if _stack:
        _stack[-1].children.append(node)
    return node


def component(fn):
    """Mark a function as a component: each call runs under its own `Owner`, so what the
    component created is disposed together when the view that holds it goes away."""

    def wrapper(*args, **kwargs):
        owner = Owner()
        return owner.run(fn, *args, **kwargs)

    try:  # MicroPython functions have no writable __name__
        wrapper.__name__ = fn.__name__
    except (AttributeError, TypeError):
        pass
    return wrapper


# --- building -------------------------------------------------------------------------------


def build(view, renderer, parent=None, anchor=None):
    """Draw `view` through `renderer` under `parent` (before `anchor`). Returns the nodes."""
    nodes = _build_nodes(view, renderer)
    if parent is not None:
        for node in nodes:
            renderer.insert_node(parent, node, anchor)
    return nodes


def _build_nodes(view, renderer):
    """The list of live nodes for a view. A hole contributes its marker node."""
    if isinstance(view, Text):
        return [renderer.create_text(view.value)]
    if isinstance(view, Mounted):
        return list(view.nodes)
    if isinstance(view, Element):
        node = renderer.create_element(view.tag)
        _apply_attrs(node, view.attrs, renderer)
        for child in view.children:
            if callable(child):
                _mount_hole(node, child, renderer)
            else:
                for n in _build_nodes(child, renderer):
                    renderer.insert_node(node, n)
        return [node]
    if isinstance(view, (list, tuple)):
        out = []
        for item in _children(view):
            out.extend(_build_nodes(item, renderer))
        return out
    if callable(view):
        # A hole at the top level: it needs a parent to live in; give it a fragment marker.
        raise TypeError("a callable view needs a parent element; wrap it in h.div(...) or mount it")
    return [renderer.create_text(view)]


def _normalize(value, renderer):
    """Resolve a hole's value to a list of live nodes, running callables (tracked)."""
    if value is None or value is True or value is False:
        return []
    if callable(value) and not isinstance(value, (Element, Text, Mounted)):
        return _normalize(value(), renderer)
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_normalize(item, renderer))
        return out
    if isinstance(value, Mounted):
        return list(value.nodes)
    if isinstance(value, (Element, Text)):
        return _build_nodes(value, renderer)
    return [renderer.create_text(value)]


def _mount_hole(parent, accessor, renderer):
    """A reactive child position: a marker node, and an effect applying the insert rules."""
    marker = renderer.create_text("")
    renderer.insert_node(parent, marker)
    state = {"current": [], "text": None}

    def compute():
        global _current_renderer
        saved, _current_renderer = _current_renderer, renderer
        try:
            value = accessor()
            # Strings and numbers are the common case: keep one text node and update it.
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                return ("text", str(value))
            return ("nodes", _normalize(value, renderer))
        finally:
            _current_renderer = saved

    def apply(result, prev):
        kind, payload = result
        if kind == "text":
            if state["text"] is not None:
                if prev is None or prev[1] != payload:
                    renderer.replace_text(state["text"], payload)
                return
            node = renderer.create_text(payload)
            _reconcile(parent, state["current"], [node], marker, renderer)
            state["current"] = [node]
            state["text"] = node
            return
        state["text"] = None
        _reconcile(parent, state["current"], payload, marker, renderer)
        state["current"] = payload

    RenderEffect(compute, apply)


def _reconcile(parent, current, new, marker, renderer):
    """Make the nodes before `marker` be exactly `new`, moving what already exists.

    Nodes only in `current` are removed. Of the rest, the longest run that is already in the
    right relative order stays put; every other node is moved into place with one insert.
    So a swap of two rows costs two inserts, and an append costs only the new nodes.
    """
    if _same_nodes(current, new):
        return
    new_ids = {id(node): i for i, node in enumerate(new)}
    kept = []  # nodes of `current` that survive, in their current order
    for node in current:
        if id(node) in new_ids:
            kept.append(node)
        else:
            renderer.remove_node(parent, node)
    # Indices into `new` of the surviving nodes, in current DOM order; the longest increasing
    # subsequence of that is the set of nodes that need not move.
    positions = [new_ids[id(node)] for node in kept]
    stay = set(_lis(positions))
    # Walk `new` from the end so the anchor (the following node) is already final.
    anchor = marker
    for i in range(len(new) - 1, -1, -1):
        node = new[i]
        if i in stay:
            anchor = node
            continue
        renderer.insert_node(parent, node, anchor)
        anchor = node


def _same_nodes(a, b):
    if len(a) != len(b):
        return False
    for i in range(len(a)):  # no zip(strict=...): MicroPython's zip has no strict
        if a[i] is not b[i]:
            return False
    return True


def _lis(seq):
    """Values of a longest strictly increasing subsequence of `seq` (patience sorting)."""
    if not seq:
        return []
    tails = []  # index into seq of the smallest tail of an increasing run of each length
    prev = [-1] * len(seq)
    for i, value in enumerate(seq):
        lo, hi = 0, len(tails)
        while lo < hi:
            mid = (lo + hi) // 2
            if seq[tails[mid]] < value:
                lo = mid + 1
            else:
                hi = mid
        if lo > 0:
            prev[i] = tails[lo - 1]
        if lo == len(tails):
            tails.append(i)
        else:
            tails[lo] = i
    out = []
    i = tails[-1]
    while i != -1:
        out.append(seq[i])
        i = prev[i]
    out.reverse()
    return out


def _index_of(nodes, node):
    for i, candidate in enumerate(nodes):
        if candidate is node:
            return i
    return -1


# --- attributes -----------------------------------------------------------------------------


def _apply_attrs(node, attrs, renderer):
    for raw_name, value in attrs.items():
        _apply_attr(node, raw_name, value, renderer)


def _apply_attr(node, raw_name, value, renderer):
    kind, name = _classify(raw_name)
    if kind == "ref":
        value.current = node
    elif kind == "event":
        _listen(node, name, value, renderer)
    elif kind == "bind":
        _bind(node, name, value, renderer)
    elif kind == "class-dict":
        if callable(value):
            RenderEffect(value, lambda classes, prev: _apply_class_dict(node, classes, prev, renderer))
        elif isinstance(value, dict):
            _apply_class_dict(node, value, None, renderer)
        else:
            renderer.set_property(node, "class", value)
    elif callable(value):
        RenderEffect(value, lambda v, prev: _set(node, kind, name, v, renderer))
    else:
        _set(node, kind, name, value, renderer)


def _classify(raw):
    """(kind, name) for a builder keyword or a template attribute name."""
    if raw == "ref":
        return "ref", raw
    if raw in ("cls", "class_", "class"):
        return "class-dict", "class"
    for prefix, kind in (
        ("on_", "event"),
        ("on:", "event"),
        ("prop_", "prop"),
        ("prop:", "prop"),
        ("class_", "class"),
        ("class:", "class"),
        ("style_", "style"),
        ("style:", "style"),
        ("bind_", "bind"),
        ("bind:", "bind"),
        ("attr:", "attr"),
    ):
        if raw.startswith(prefix) and len(raw) > len(prefix):
            rest = raw[len(prefix) :]
            if kind in ("class", "style", "event", "bind", "prop"):
                return kind, rest.replace("_", "-") if kind in ("class", "style") else rest
            return "attr", _attr_name(rest)
    return "attr", _attr_name(raw)


def _set(node, kind, name, value, renderer):
    if kind == "attr":
        renderer.set_property(node, name, value)
    elif kind == "prop":
        renderer.set_property(node, name, value)
    elif kind == "class":
        renderer.toggle_class(node, name, bool(value))
    elif kind == "style":
        renderer.set_style(node, name, value)


def _apply_class_dict(node, classes, prev, renderer):
    if isinstance(classes, dict):
        prev = prev if isinstance(prev, dict) else {}
        for name in set(classes) | set(prev):
            on = bool(classes.get(name))
            if bool(prev.get(name)) != on or name not in prev:
                renderer.toggle_class(node, name, on)
    else:
        renderer.set_property(node, "class", classes)


def _listen(node, event, handler, renderer):
    remove = renderer.add_listener(node, event, handler)
    on_cleanup(remove)


def _bind(node, what, signal, renderer):
    """Two-way binding between a form control and a `Signal`."""
    if not isinstance(signal, Signal):
        raise TypeError(f"bind:{what} needs a Signal")
    if what == "value":
        RenderEffect(signal, lambda v, prev: renderer.set_property(node, "value", "" if v is None else v))
        _listen(node, "input", lambda ev: signal.set(ev.target.value), renderer)
    elif what == "checked":
        RenderEffect(signal, lambda v, prev: renderer.set_property(node, "checked", bool(v)))
        _listen(node, "change", lambda ev: signal.set(bool(ev.target.checked)), renderer)
    elif what == "group":
        # A radio: checked when the signal equals this input's value.
        RenderEffect(signal, lambda v, prev: renderer.set_property(node, "checked", str(v) == str(_value_of(node))))
        _listen(node, "change", lambda ev: signal.set(_value_of(ev.target)), renderer)
    else:
        raise TypeError(f"unknown binding bind:{what}")


def _value_of(node):
    props = getattr(node, "props", None)
    if isinstance(props, dict) and "value" in props:
        return props["value"]
    attrs = getattr(node, "attrs", None)
    if isinstance(attrs, dict) and "value" in attrs:
        return attrs["value"]
    return getattr(node, "value", None)


# --- mounting -------------------------------------------------------------------------------


class _Root:
    def __init__(self, owner, nodes):
        self.owner = owner
        self.nodes = nodes

    def dispose(self):
        self.owner.dispose()


def mount(view, parent, renderer=None):
    """Build `view` under `parent` with its own root `Owner`; returns a handle with `dispose()`.

    `parent` is a renderer node. With no renderer, the browser's `DomRenderer` is used and
    `parent` may be a CSS selector.
    """
    if renderer is None or isinstance(parent, str):
        from .dom import DomRenderer, resolve

        renderer = renderer or DomRenderer()
        parent = resolve(parent)
    owner = Owner(parent=None)
    nodes = owner.run(lambda: build(view, renderer, parent))
    return _Root(owner, nodes)


def render_to_string(view):
    """The view as HTML, with no browser. Holes render their current value."""
    renderer = HtmlRenderer()
    root = renderer.create_element("div")
    handle = mount(view, root, renderer)
    html = "".join(child.to_html() for child in root.children)
    handle.dispose()
    return html
