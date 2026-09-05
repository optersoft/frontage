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


class HtmlNode:
    """A node of `HtmlRenderer`: an element with a tag, or text with `tag=None`."""

    def __init__(self, tag, text=None):
        self.tag = tag
        self.text = text
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

    def to_html(self):
        if self.tag is None:
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
            out.append(child.to_html())
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


class HtmlRenderer(Renderer):
    """Renders into plain Python nodes that serialise to HTML. No browser involved."""

    def create_element(self, tag):
        return HtmlNode(tag)

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

    def count(self, op):
        return sum(1 for entry in self.log if entry[0] == op)


__all__ = ["FakeEvent", "HtmlNode", "HtmlRenderer", "RecordingRenderer", "Renderer", "escape"]
