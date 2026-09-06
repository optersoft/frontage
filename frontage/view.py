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

Hydration: a renderer with `hydration_markers` (the prerenderer's `HtmlRenderer`) fences each
hole's content between `<!--[-->` and its `<!--h-->` marker and keeps `data-fr-h`; a renderer
carrying a `hydration` object (the browser's, while `mount(hydrate=True)` runs) adopts the
nodes it finds inside those fences, in order, instead of creating them, then drops the fence
and whatever nothing adopted.
"""

from . import reactive
from .errors import format_exception
from .reactive import Context, Owner, RenderEffect, Signal, get_owner, on_cleanup, provide, spawn, use
from .renderer import HtmlRenderer, escape

__all__ = [
    "Element",
    "Mounted",
    "NodeRef",
    "Text",
    "build",
    "component",
    "emit",
    "h",
    "mount",
    "render_to_string",
    "text",
]

_UNSET = object()
_current_renderer = None  # the renderer of the hole being computed; control flow builds with it

# Elements are built by compiling their static structure to one HTML string, cloning it in one
# renderer operation and binding only the holes. Set False to build node by node (the
# benchmark compares the two).
TEMPLATES = True

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

# Holes built with no parent yet (a component returning `Show(...)` directly): marker id ->
# the function that places their content once the marker itself has been inserted.
_floating = {}


def _insert(renderer, parent, node, anchor=None):
    """Insert `node`, then let a floating hole whose marker this is fill in."""
    renderer.insert_node(parent, node, anchor)
    fill = _floating.pop(id(node), None)
    if fill is not None:
        fill()


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


_ids = [0]
_mounts = [0]
_ID_SCOPE = Context(None, internal=True)


class _IdScope:
    """Where `unique_id` counts from inside a mount: the mount's name (its target's id) and a
    counter of its own, so two mounts on one page, or two interpreters, never hand out the
    same id, and a prerendered mount and its hydration count alike."""

    def __init__(self, name):
        self.name = name
        self.n = 0


def unique_id(prefix="fr"):
    """An id unique in this page, `fr-app-1`, `fr-app-2`, … inside a mount into `#app` (and
    `fr-1`, `fr-2`, … outside any mount): for `label for=`, `aria-describedby` and whatever
    else must name an element. The `widgets` give their controls one."""
    scope = use(_ID_SCOPE)
    if scope is not None:
        scope.n += 1
        return f"{prefix}-{scope.name}-{scope.n}"
    _ids[0] += 1
    return f"{prefix}-{_ids[0]}"


def component(fn):
    """Mark a function as a component: each call runs under its own `Owner`, so what the
    component created is disposed together when the view that holds it goes away."""

    name = getattr(fn, "__name__", None)

    def wrapper(*args, **kwargs):
        owner = Owner()
        owner.name = name
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
            _insert(renderer, parent, node, anchor)
    return nodes


def _text_node(value, renderer):
    """A text node for `value`: the next one in the prerendered HTML while hydrating."""
    hyd = getattr(renderer, "hydration", None)
    if hyd is not None and hyd.active:
        node = hyd.claim_text(str(value))
        if node is not None:
            return node
    return renderer.create_text(value)


def _build_nodes(view, renderer, cache=None):
    """The list of live nodes for a view. A hole contributes its marker node. `cache` lets a
    caller that builds many like-shaped views (a `For`) reuse one compiled Template."""
    if isinstance(view, Text):
        return [_text_node(view.value, renderer)]
    if isinstance(view, Mounted):
        return list(view.nodes)
    if isinstance(view, Element):
        if TEMPLATES and getattr(renderer, "supports_templates", True):
            return [_build_template(view, renderer, cache)]
        node = renderer.create_element(view.tag)
        _apply_attrs(node, view.attrs, renderer)
        for child in view.children:
            if callable(child):
                _mount_hole(node, child, renderer)
            else:
                for n in _build_nodes(child, renderer):
                    _insert(renderer, node, n)
        return [node]
    if isinstance(view, (list, tuple)):
        out = []
        for item in _children(view):
            out.extend(_build_nodes(item, renderer))
        return out
    if callable(view):
        # A hole with no parent yet (a component returning control flow directly): its
        # marker is the node; the content follows once the marker is inserted somewhere.
        return [_mount_hole(None, view, renderer)]
    return [_text_node(view, renderer)]


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
    return [_text_node(value, renderer)]


# --- templates ------------------------------------------------------------------------------


class Template:
    """A compiled Element shape: the HTML skeleton plus, per dynamic element in document
    order, its tag, static attributes and dynamic attribute names. `extract(element)` walks a
    fresh Element tree of the same shape and returns its hole values without building any
    strings, or `None` if the shape differs (then the caller compiles that tree instead).
    A `For` keeps one Template per row function, so a thousand rows compile once."""

    def __init__(self, html, specs):
        self.html = html
        self.specs = specs  # per element in pre-order: (tag, static attrs dict, dynamic raw names)
        self.tag = specs[0][0] if specs else None

    def extract(self, element):
        element_holes = []
        child_holes = []
        specs = self.specs
        cursor = [0]

        def walk(el):
            i = cursor[0]
            if i >= len(specs):
                return False
            tag, static, dynamic = specs[i]
            cursor[0] = i + 1
            if el.tag != tag or len(el.attrs) != len(static) + len(dynamic):
                return False
            values = []
            for raw in dynamic:
                value = el.attrs.get(raw, _UNSET)
                if value is _UNSET or (not callable(value) and _static_kind(raw, value)):
                    return False
                values.append((raw, value))
            for name, expected in static.items():
                value = el.attrs.get(name, _UNSET)
                if value is _UNSET or value != expected or callable(value):
                    return False
            if dynamic:
                element_holes.append(values)
            if tag in _VOID:
                return True
            for child in el.children:
                if isinstance(child, Element):
                    if not walk(child):
                        return False
                else:
                    child_holes.append(child)
            return True

        if not walk(element) or cursor[0] != len(specs):
            return None
        return element_holes, child_holes


def _static_kind(raw, value):
    kind, _ = _classify(raw)
    return kind == "attr" or (kind == "class-dict" and not isinstance(value, dict))


def _compile(element):
    """(Template, element_holes, child_holes) for an Element tree.

    Static attributes go into the HTML. An element with anything dynamic (a bound attribute,
    an event, a ref, a binding) gets `data-fr-h="<n>"`, numbered in document order, and its
    dynamic attributes are listed in `element_holes[n]`. Every child that is not an element
    (text, a callable, prebuilt nodes) becomes a `<!--h-->` marker and an entry of
    `child_holes`, in document order. Text is a hole too, so that rows of a list with
    different labels share one template.
    """
    parts = []
    element_holes = []
    child_holes = []
    specs = []

    def walk(el):
        dynamic = []
        static = {}
        parts.append("<")
        parts.append(el.tag)
        for raw, value in el.attrs.items():
            kind, name = _classify(raw)
            if callable(value) or not _static_kind(raw, value):
                dynamic.append((raw, value))
            else:
                static[raw] = value
                if value is True:
                    parts.append(" " + name)
                elif value is not None and value is not False:
                    parts.append(f' {name}="{escape(value, quote=True)}"')
        specs.append((el.tag, static, [raw for raw, _ in dynamic]))
        if dynamic:
            parts.append(f' data-fr-h="{len(element_holes)}"')
            element_holes.append(dynamic)
        parts.append(">")
        if el.tag in _VOID:
            return
        for child in el.children:
            if isinstance(child, Element):
                walk(child)
            else:
                child_holes.append(child)
                parts.append("<!--h-->")
        parts.append(f"</{el.tag}>")

    walk(element)
    return Template("".join(parts), specs), element_holes, child_holes


def _build_template(element, renderer, cache=None):
    """Instantiate `element` from a Template: `cache` (a dict) keeps the last Template so a
    like-shaped element skips compilation."""
    template = cache.get("template") if cache is not None else None
    holes = template.extract(element) if template is not None else None
    if holes is None:
        template, element_holes, child_holes = _compile(element)
        if cache is not None:
            cache["template"] = template
    else:
        assert template is not None
        element_holes, child_holes = holes
    hyd = getattr(renderer, "hydration", None)
    hydrating = hyd is not None and hyd.active
    root = None
    elements, markers = [], []
    if hyd is not None and hydrating:
        root = hyd.claim_element(template.tag)
        if root is not None and (element_holes or child_holes):
            elements, markers = hyd.find_holes(root)  # skips the fenced spans of nested content
    if root is None:
        root = renderer.clone_template(template.html)
        if element_holes or child_holes:
            elements, markers = renderer.find_holes(root)
    if element_holes or child_holes:
        for i in range(len(element_holes)):
            node = elements[i]
            for raw, value in element_holes[i]:
                _apply_attr(node, raw, value, renderer)
            if not getattr(renderer, "hydration_markers", False):
                renderer.set_property(node, "data-fr-h", None)  # the marker has done its job
        for i in range(len(child_holes)):
            marker = markers[i]
            child = child_holes[i]
            parent = renderer.parent(marker)
            if isinstance(child, Text):
                # Static text keeps its marker in prerendered HTML, so hydration can adopt it.
                previous = renderer.previous_sibling(marker) if hydrating else None
                if previous is not None and renderer.is_text(previous):
                    renderer.replace_text(previous, child.value)
                    renderer.remove_node(parent, marker)  # as a fresh build would have
                elif getattr(renderer, "hydration_markers", False) or hydrating:
                    renderer.insert_node(parent, renderer.create_text(child.value), marker)
                else:
                    renderer.replace_node(parent, renderer.create_text(child.value), marker)
            elif isinstance(child, Mounted):
                for n in child.nodes:
                    _insert(renderer, parent, n, marker)
            else:
                _mount_hole(parent, child, renderer, marker)
    return root


class _HoleState:
    def __init__(self):
        self.current = []  # the nodes currently placed before the marker
        self.text = None  # the single text node, when the value is text
        self.pending = None  # a result waiting for the marker to be inserted (floating holes)
        self.hydrated = False  # the first compute under hydration has happened
        self.start = None  # the `<!--[-->` fence, from compute to the apply that removes it
        self.adopted = None  # the prerendered text node a text value adopted
        self.claimed = None  # what that compute adopted, for the leftover sweep
        self.fenced = False  # prerendering: the fence has been written

    def take_pending(self):
        result, self.pending = self.pending, None
        return result


def _mount_hole(parent, accessor, renderer, marker=None):
    """A reactive child position: a marker node, and an effect applying the insert rules.

    With `parent=None` the hole floats: the marker is returned and the content is placed
    before it as soon as `_insert` puts the marker somewhere. Returns the marker."""
    hyd = getattr(renderer, "hydration", None)
    fencing = getattr(renderer, "hydration_markers", False)
    if marker is None:
        if hyd is not None and hyd.active:
            marker = hyd.claim_hole()  # a floating hole: its fence and marker are in place
        if marker is None:
            marker = renderer.create_marker() if fencing else renderer.create_text("")
            if parent is not None:
                renderer.insert_node(parent, marker)
    state = _HoleState()

    def compute():
        global _current_renderer
        saved, _current_renderer = _current_renderer, renderer
        start = None
        if hyd is not None and not state.hydrated:
            state.hydrated = True
            start = hyd.start_of(marker)
            if start is not None:
                hyd.push(renderer.next_sibling(start))
        try:
            value = accessor()
            # Strings and numbers are the common case: keep one text node and update it.
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                text = str(value)
                if hyd is not None and start is not None:
                    state.adopted = hyd.claim_text(text)
                return ("text", text)
            return ("nodes", _normalize(value, renderer))
        finally:
            _current_renderer = saved
            if hyd is not None and start is not None:
                state.claimed = hyd.pop()
                state.start = start

    def apply(result, prev):
        target = parent if parent is not None else renderer.parent(marker)
        if target is None:
            # Not inserted anywhere yet: keep the result; `_insert` calls back when it is.
            state.pending = result
            _floating[id(marker)] = lambda: apply(state.take_pending(), None)
            return
        if fencing and not state.fenced:
            state.fenced = True
            renderer.insert_node(target, renderer.create_marker("["), marker)
        kind, payload = result
        if kind == "text":
            if state.text is not None:
                if prev is None or prev[1] != payload:
                    renderer.replace_text(state.text, payload)
                return
            node = state.adopted if state.adopted is not None else renderer.create_text(payload)
            state.adopted = None
            _reconcile(target, state.current, [node], marker, renderer)
            state.current = [node]
            state.text = node
            _finish_hydration(state, target, marker, hyd)
            return
        state.text = None
        _reconcile(target, state.current, payload, marker, renderer)
        state.current = payload
        _finish_hydration(state, target, marker, hyd)

    def on_screen():
        target = parent if parent is not None else renderer.parent(marker)
        return target is not None and renderer.is_connected(target)

    RenderEffect(compute, apply, target=on_screen)

    def cleanup():
        _floating.pop(id(marker), None)
        if parent is None:
            # A floating hole's owner disposes it while the marker is still in place; the
            # content it placed before the marker is nobody else's to remove.
            target = renderer.parent(marker)
            if target is not None:
                for node in state.current:
                    renderer.remove_node(target, node)
                state.current = []
                state.text = None

    on_cleanup(cleanup)
    return marker


def _finish_hydration(state, target, marker, hyd):
    """After the first apply of a hydrated hole: drop the fence and what nobody adopted."""
    start, state.start = state.start, None
    if start is not None:
        hyd.finish(target, start, marker, state.claimed or [], state.current)
        state.claimed = None


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
        _insert(renderer, parent, node, anchor)
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
    elif kind == "capture":
        _listen(node, name, value, renderer, capture=True)
    elif kind == "bind":
        _bind(node, name, value, renderer)
    elif kind == "class-dict":
        if callable(value):
            RenderEffect(
                value,
                lambda classes, prev: _apply_class_dict(node, classes, prev, renderer),
                target=lambda: renderer.is_connected(node),
            )
        elif isinstance(value, dict):
            _apply_class_dict(node, value, None, renderer)
        else:
            renderer.set_property(node, "class", value)
    elif callable(value):
        RenderEffect(
            value, lambda v, prev: _set(node, kind, name, v, renderer), target=lambda: renderer.is_connected(node)
        )
    else:
        _set(node, kind, name, value, renderer)


_classified = {}


def _classify(raw):
    """(kind, name) for a builder keyword or a template attribute name. Memoized: it runs
    once per attribute per element built, and MicroPython pays for every string test."""
    found = _classified.get(raw)
    if found is None:
        found = _classify_uncached(raw)
        _classified[raw] = found
    return found


def _classify_uncached(raw):
    if raw == "ref":
        return "ref", raw
    if raw in ("cls", "class_", "class"):
        return "class-dict", "class"
    for prefix, kind in (
        ("oncapture_", "capture"),
        ("oncapture:", "capture"),
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
            if kind in ("class", "style", "event", "capture", "bind", "prop"):
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


def _listen(node, event, handler, renderer, capture=False):
    owner = get_owner()

    def call(ev):
        result = handler(ev)
        # An `async def` handler returns a coroutine: run it as a task owned here, so its
        # errors reach the nearest Errored and it is cancelled if this view goes away.
        if hasattr(result, "send") and hasattr(result, "throw"):
            spawn(result, owner)

    remove = renderer.add_listener(node, event, call, capture)
    on_cleanup(remove)


def emit(node, name, detail=None):
    """Dispatch a custom event named `name` from `node`, bubbling, with `detail`; a parent
    listens with `on_<name>` (or `on:<name>` in a template)."""
    renderer = _current_renderer or _renderer_of(node)
    renderer.dispatch_event(node, name, detail)


def _renderer_of(node):
    if hasattr(node, "fire"):
        return HtmlRenderer()
    from .dom import DomRenderer

    return DomRenderer()


def _bind(node, what, signal, renderer):
    """Two-way binding between a form control and a `Signal`."""
    if not isinstance(signal, Signal):
        raise TypeError(f"bind:{what} needs a Signal")

    def on_screen():
        return renderer.is_connected(node)

    if what == "value":
        RenderEffect(
            signal, lambda v, prev: renderer.set_property(node, "value", "" if v is None else v), target=on_screen
        )
        _listen(node, "input", lambda ev: signal.set(ev.target.value), renderer)
    elif what == "checked":
        RenderEffect(signal, lambda v, prev: renderer.set_property(node, "checked", bool(v)), target=on_screen)
        _listen(node, "change", lambda ev: signal.set(bool(ev.target.checked)), renderer)
    elif what == "group":
        # A radio: checked when the signal equals this input's value.
        RenderEffect(
            signal,
            lambda v, prev: renderer.set_property(node, "checked", str(v) == str(_value_of(node))),
            target=on_screen,
        )
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


def mount(view, parent, renderer=None, debug=True, fallback=None, clear=True, hydrate=None, scope=None):
    """Build `view` under `parent` with its own root `Owner`; returns a handle with `dispose()`.

    `parent` is emptied first — a "Loading…" placeholder in the HTML is the usual reason it
    is not — unless `clear=False`, which appends after whatever is already there.

    A target that `python -m frontage prerender` wrote (it carries `data-fr-hydrate`) is
    hydrated instead: the view adopts the HTML already on screen, node by node, binds it, and
    replays the clicks and input made before Python was ready. `hydrate=True/False` forces
    either way. On CPython with a selector, `mount` registers the view for the prerenderer.

    Pass a *function* (a component, or `lambda: app(...)`) rather than a built view: it runs
    inside the root owner, so everything it creates (components, resources, control flow)
    is disposed with the mount. A view built beforehand still mounts, but owners created
    while building it belong to nobody and outlive the mount.

    `parent` is a renderer node. With no renderer, the browser's `DomRenderer` is used and
    `parent` may be a CSS selector. An error nothing caught renders, in debug mode, the
    traceback in a `<pre class="frontage-error">`; otherwise `fallback` (a view, or a
    function of the error), or a one-line notice. `debug` also switches the development
    warnings (a read after an await, a write inside a tracked computation, a `For` that
    rebuilds every row). `scope` names the mount for `unique_id` (default: the target's id).
    """
    reactive.DEBUG = bool(debug)
    if scope is None and isinstance(parent, str) and parent.startswith("#"):
        scope = parent[1:]
    if renderer is None or isinstance(parent, str):
        from .runtime import in_browser, prerender

        if not in_browser:
            if prerender.active and isinstance(parent, str):
                prerender.mounts.append((parent, view, debug, fallback))
                return _Root(Owner(parent=None), [])
            raise RuntimeError(
                "mount needs a browser: pass a renderer and a node (HtmlRenderer in tests), "
                "or render the page with `python -m frontage prerender`"
            )
        from .dom import DomRenderer, resolve

        renderer = renderer or DomRenderer()
        parent = resolve(parent)
    if hydrate is None:
        hydrate = renderer.hydratable(parent)
    root_marker = None
    if hydrate:
        clear = False
        hyd = renderer.begin_hydration(parent)
        from .aio import _set_hydration_values

        _set_hydration_values(hyd.data)
        root_marker = hyd.root_marker(parent)
    if clear:
        while (child := renderer.first_child(parent)) is not None:
            renderer.remove_node(parent, child)
    renderer.mark_root(parent)  # what hangs from here is on screen: a transition waits for it
    owner = Owner(parent=None)

    def page(exc, reset):
        if debug:
            return h.pre(format_exception(exc), cls="frontage-error")
        if callable(fallback) and not hasattr(fallback, "tag"):
            return fallback(exc, reset)
        return fallback if fallback is not None else h.p("Something went wrong.", cls="frontage-error")

    def root():
        from .flow import Errored

        _mounts[0] += 1
        provide(_ID_SCOPE, _IdScope(scope if scope is not None else str(_mounts[0])))
        # The root is a hole holding an Errored boundary, so nothing wraps the user's view;
        # a factory runs inside that boundary's owner and is disposed with the mount.
        _mount_hole(parent, Errored(page, view), renderer, root_marker)

    try:
        owner.run(root)
    finally:
        if hydrate:
            from .aio import _set_hydration_values

            _set_hydration_values(None)
            renderer.end_hydration()
    return _Root(owner, [])


def render_to_string(view, hydration_markers=False):
    """The view as HTML, with no browser. Holes render their current value; with
    `hydration_markers` the HTML carries the fences a browser hydrates from."""
    renderer = HtmlRenderer(hydration_markers=hydration_markers)
    root = renderer.create_element("div")
    handle = mount(view, root, renderer)
    html = "".join(child.to_html(comments=hydration_markers) for child in root.children)
    handle.dispose()
    return html
