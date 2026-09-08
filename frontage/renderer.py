"""The seam between the view layer and whatever it draws on.

A `Renderer` is the small set of operations the view layer needs from a document: create
nodes, place them, change their text and properties, walk them. The browser gets a DOM
renderer (M1); tests and servers get `HtmlRenderer`, whose nodes are plain Python objects
that serialise to HTML. `RecordingRenderer` wraps another renderer and keeps a log of every
operation, which is how a test asserts *how little* a change touched.
"""

_VOID = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


def escape(text, quote=False):
    text = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if quote:
        text = text.replace('"', "&quot;")
    return text


class Renderer:
    """The operations a renderer provides. Subclasses implement every method."""

    def create_element(self, tag):
        raise NotImplementedError

    def create_text(self, text):
        raise NotImplementedError

    def replace_text(self, node, text):
        raise NotImplementedError

    def set_property(self, node, name, value):
        """Set an attribute or property; `None` removes it, `True`/`False` toggle a boolean."""
        raise NotImplementedError

    def insert_node(self, parent, node, anchor=None):
        """Insert `node` under `parent` before `anchor`, or append when `anchor` is None."""
        raise NotImplementedError

    def remove_node(self, parent, node):
        raise NotImplementedError

    def is_text(self, node):
        raise NotImplementedError

    def parent(self, node):
        raise NotImplementedError

    def mark_root(self, node):
        """`node` is a mount target: what hangs from it is on screen (`is_connected`)."""

    def is_connected(self, node):
        """True when `node` is on the page (under a mount target, or in the document). A
        transition applies effects on such nodes at its commit and builds the rest at once.
        Unknown counts as on screen."""
        return True

    def first_child(self, node):
        raise NotImplementedError

    def next_sibling(self, node):
        raise NotImplementedError

    def toggle_class(self, node, name, on):
        """Add or remove one class without touching the others."""
        raise NotImplementedError

    def set_style(self, node, prop, value):
        """Set one style property; `None` removes it."""
        raise NotImplementedError

    def add_listener(self, node, event, handler, capture=False):
        """Attach `handler(event)`; returns a function that detaches it."""
        raise NotImplementedError

    def replace_node(self, parent, new, old):
        raise NotImplementedError

    def dispatch_event(self, node, name, detail=None):
        """Fire a bubbling custom event named `name` from `node` with `detail`."""
        raise NotImplementedError

    def clone_template(self, html):
        """A fresh copy of the single root element described by `html`, in one operation;
        the parse happens once per distinct string."""
        raise NotImplementedError

    def real_node(self, node):
        """The node itself, for a renderer whose nodes are the real thing; a streaming
        renderer answers the DOM node behind an id (a `ref`, a direct listener)."""
        return node

    def find_holes(self, root, n_elements=0, n_markers=0):
        """`(elements, markers)`: the elements carrying `data-fr-h`, ordered by that index,
        and the comment markers `<!--h-->` in document order, `root` included."""
        raise NotImplementedError

    def previous_sibling(self, node):
        raise NotImplementedError

    # -- hydration (the browser renderer implements these; others never hydrate) ------------

    hydration = None  # a `dom.Hydration` while `mount(hydrate=True)` runs
    hydration_markers = False  # write the fences hydration reads (the prerenderer's HtmlRenderer)

    def hydratable(self, node):
        return False

    def begin_hydration(self, node):
        raise NotImplementedError

    def end_hydration(self):
        raise NotImplementedError


class HtmlNode:
    """A node of `HtmlRenderer`: an element with a tag, or text with `tag=None`."""

    def __init__(self, tag, text=None, comment=False):
        self.tag = tag
        self.text = text
        self.comment = comment
        self.attrs = {}
        self.props = {}  # DOM properties (value, checked, …) live apart from attributes
        self.styles = {}
        self.listeners = {}  # event -> list of handlers, for tests to fire
        self.children = []
        self.parent = None

    def __getattr__(self, name):
        # DOM properties read like attributes on a real node (`ev.target.value`); mirror that.
        props = self.__dict__.get("props")
        if props is not None and name in props:
            return props[name]
        raise AttributeError(name)

    def fire(self, event, **fields):
        """Deliver a fake event to this node's listeners (tests only). Bubbles to parents."""
        ev = FakeEvent(event, self, **fields)
        node = self
        while node is not None and not ev.stopped:
            for handler in list(node.listeners.get(event, [])):
                handler(ev)
            node = node.parent
        return ev

    def to_html(self, comments=False):
        if self.tag is None:
            if self.comment:
                return f"<!--{self.text}-->" if comments else ""
            return escape(self.text)
        out = ["<", self.tag]
        for name, value in self.attrs.items():
            if value is True:
                out.append(f" {name}")
            elif value is False or value is None:
                continue
            else:
                out.append(f' {name}="{escape(value, quote=True)}"')
        if self.styles:
            css = ";".join(f"{k}:{v}" for k, v in self.styles.items())
            out.append(f' style="{escape(css, quote=True)}"')
        out.append(">")
        if self.tag in _VOID:
            return "".join(out)
        for child in self.children:
            out.append(child.to_html(comments))
        out.append(f"</{self.tag}>")
        return "".join(out)


class FakeEvent:
    """What `HtmlNode.fire` delivers: enough of a DOM event for handlers under test."""

    def __init__(self, type, target, **fields):
        self.type = type
        self.target = target
        self.stopped = False
        self.default_prevented = False
        for k, v in fields.items():
            setattr(self, k, v)

    def stopPropagation(self):
        self.stopped = True

    def preventDefault(self):
        self.default_prevented = True


try:  # the template path needs an HTML parser; CPython has one, MicroPython does not
    import html.parser as _html_parser  # noqa: F401

    _CAN_PARSE = True
except ImportError:
    _CAN_PARSE = False


class HtmlRenderer(Renderer):
    """Renders into plain Python nodes that serialise to HTML. No browser involved.

    With `hydration_markers=True` (what `python -m frontage prerender` uses) every hole is
    fenced by comments, `<!--[-->` before its content and `<!--h-->` after, and elements keep
    their `data-fr-h`, so a browser can adopt the HTML instead of building it (`to_html`
    with `comments=True` writes the fences)."""

    # Without an HTML parser (MicroPython) the view layer builds node by node instead.
    supports_templates = _CAN_PARSE

    def __init__(self, hydration_markers=False):
        self.hydration_markers = hydration_markers

    def create_element(self, tag):
        return HtmlNode(tag)

    def create_marker(self, text="h"):
        """A comment node: a hole marker that survives serialisation."""
        return HtmlNode(None, text, comment=True)

    def previous_sibling(self, node):
        siblings = node.parent.children if node.parent else []
        i = siblings.index(node) - 1
        return siblings[i] if i >= 0 else None

    def create_text(self, text):
        return HtmlNode(None, str(text))

    def replace_text(self, node, text):
        node.text = str(text)

    PROPERTIES = ("value", "checked", "selected", "disabled", "textContent")

    def set_property(self, node, name, value):
        if name in self.PROPERTIES:
            node.props[name] = value
            if name == "disabled":  # also an attribute, so it serialises
                self._attr(node, name, bool(value))
            return
        self._attr(node, name, value)

    def _attr(self, node, name, value):
        if value is None or value is False:
            node.attrs.pop(name, None)
        else:
            node.attrs[name] = value

    def insert_node(self, parent, node, anchor=None):
        if node.parent is not None:
            node.parent.children.remove(node)
        node.parent = parent
        if anchor is None:
            parent.children.append(node)
        else:
            parent.children.insert(parent.children.index(anchor), node)

    def remove_node(self, parent, node):
        parent.children.remove(node)
        node.parent = None

    def is_text(self, node):
        return node.tag is None

    def parent(self, node):
        return node.parent

    def mark_root(self, node):
        node._root = True  # a plain attribute: MicroPython has no writable instance __dict__

    def is_connected(self, node):
        while node is not None:
            if getattr(node, "_root", False):
                return True
            node = node.parent
        return False

    def first_child(self, node):
        return node.children[0] if node.children else None

    def next_sibling(self, node):
        siblings = node.parent.children if node.parent else []
        i = siblings.index(node) + 1
        return siblings[i] if i < len(siblings) else None

    def toggle_class(self, node, name, on):
        classes = [c for c in str(node.attrs.get("class", "")).split() if c]
        if on and name not in classes:
            classes.append(name)
        if not on and name in classes:
            classes.remove(name)
        if classes:
            node.attrs["class"] = " ".join(classes)
        else:
            node.attrs.pop("class", None)

    def set_style(self, node, prop, value):
        if value is None or value is False:
            node.styles.pop(prop, None)
        else:
            node.styles[prop] = value

    def add_listener(self, node, event, handler, capture=False):
        node.listeners.setdefault(event, []).append(handler)

        def remove():
            handlers = node.listeners.get(event, [])
            if handler in handlers:
                handlers.remove(handler)

        return remove

    def dispatch_event(self, node, name, detail=None):
        node.fire(name, detail=detail)

    def replace_node(self, parent, new, old):
        i = parent.children.index(old)
        if new.parent is not None:
            new.parent.children.remove(new)
        parent.children[i] = new
        new.parent = parent
        old.parent = None

    _templates = {}

    def clone_template(self, html):
        tree = HtmlRenderer._templates.get(html)
        if tree is None:
            tree = _parse(html)
            HtmlRenderer._templates[html] = tree
        return _copy(tree)

    def find_holes(self, root, n_elements=0, n_markers=0):
        elements = {}
        markers = []

        def walk(node):
            if node.tag is None:
                if node.comment and node.text == "h":
                    markers.append(node)
                return
            index = node.attrs.get("data-fr-h")
            if index is not None:
                elements[int(index)] = node
            for child in node.children:
                walk(child)

        walk(root)
        return [elements[i] for i in sorted(elements)], markers


def _parse(html):
    """Parse the HTML of a template into HtmlNodes. CPython only (html.parser)."""
    from html.parser import HTMLParser

    class Builder(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self, convert_charrefs=True)
            self.root = None
            self.stack = []

        def _add(self, node):
            if self.stack:
                node.parent = self.stack[-1]
                self.stack[-1].children.append(node)
            elif self.root is None:
                self.root = node

        def handle_starttag(self, tag, attrs):
            node = HtmlNode(tag)
            for name, value in attrs:
                node.attrs[name] = True if value is None else value
            self._add(node)
            if tag not in _VOID:
                self.stack.append(node)

        def handle_endtag(self, tag):
            if self.stack and self.stack[-1].tag == tag:
                self.stack.pop()

        def handle_data(self, data):
            if data:
                self._add(HtmlNode(None, data))

        def handle_comment(self, data):
            self._add(HtmlNode(None, data, comment=True))

    builder = Builder()
    builder.feed(html)
    builder.close()
    return builder.root


def _copy(node):
    clone = HtmlNode(node.tag, node.text, node.comment)
    clone.attrs = dict(node.attrs)
    for child in node.children:
        c = _copy(child)
        c.parent = clone
        clone.children.append(c)
    return clone


class RecordingRenderer(Renderer):
    """Forwards to another renderer and records `(operation, *args)` for every call."""

    def __init__(self, inner=None):
        self.inner = inner or HtmlRenderer()
        self.log = []

    def _record(self, op, *args):
        self.log.append((op,) + args)

    def create_element(self, tag):
        self._record("create_element", tag)
        return self.inner.create_element(tag)

    def create_text(self, text):
        self._record("create_text", text)
        return self.inner.create_text(text)

    def replace_text(self, node, text):
        self._record("replace_text", text)
        return self.inner.replace_text(node, text)

    def set_property(self, node, name, value):
        self._record("set_property", name, value)
        return self.inner.set_property(node, name, value)

    def insert_node(self, parent, node, anchor=None):
        self._record("insert_node")
        return self.inner.insert_node(parent, node, anchor)

    def remove_node(self, parent, node):
        self._record("remove_node")
        return self.inner.remove_node(parent, node)

    def is_text(self, node):
        return self.inner.is_text(node)

    def parent(self, node):
        return self.inner.parent(node)

    def mark_root(self, node):
        self.inner.mark_root(node)

    def is_connected(self, node):
        return self.inner.is_connected(node)

    def first_child(self, node):
        return self.inner.first_child(node)

    def next_sibling(self, node):
        return self.inner.next_sibling(node)

    def toggle_class(self, node, name, on):
        self._record("toggle_class", name, on)
        return self.inner.toggle_class(node, name, on)

    def set_style(self, node, prop, value):
        self._record("set_style", prop, value)
        return self.inner.set_style(node, prop, value)

    def add_listener(self, node, event, handler, capture=False):
        self._record("add_listener", event)
        return self.inner.add_listener(node, event, handler, capture)

    def replace_node(self, parent, new, old):
        self._record("replace_node")
        return self.inner.replace_node(parent, new, old)

    def dispatch_event(self, node, name, detail=None):
        self._record("dispatch_event", name)
        return self.inner.dispatch_event(node, name, detail)

    def clone_template(self, html):
        self._record("clone_template")
        return self.inner.clone_template(html)

    def find_holes(self, root, n_elements=0, n_markers=0):
        self._record("find_holes")
        return self.inner.find_holes(root)

    def count(self, op):
        return sum(1 for entry in self.log if entry[0] == op)


__all__ = ["FakeEvent", "HtmlNode", "HtmlRenderer", "RecordingRenderer", "Renderer", "escape"]
