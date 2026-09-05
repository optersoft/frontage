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


class HtmlNode:
    """A node of `HtmlRenderer`: an element with a tag, or text with `tag=None`."""

    def __init__(self, tag, text=None):
        self.tag = tag
        self.text = text
        self.attrs = {}
        self.children = []
        self.parent = None

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
        out.append(">")
        if self.tag in _VOID:
            return "".join(out)
        for child in self.children:
            out.append(child.to_html())
        out.append(f"</{self.tag}>")
        return "".join(out)


class HtmlRenderer(Renderer):
    """Renders into plain Python nodes that serialise to HTML. No browser involved."""

    def create_element(self, tag):
        return HtmlNode(tag)

    def create_text(self, text):
        return HtmlNode(None, str(text))

    def replace_text(self, node, text):
        node.text = str(text)

    def set_property(self, node, name, value):
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

    def count(self, op):
        return sum(1 for entry in self.log if entry[0] == op)


__all__ = ["HtmlNode", "HtmlRenderer", "RecordingRenderer", "Renderer", "escape"]
