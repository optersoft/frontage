"""The view tree and the `h` builder. M0: static structure only; reactivity lands in M1.

A view is a tree of `Element` and `Text` nodes that knows nothing about a document. The
builder makes one in two ways that produce the same tree: the call form,
`h.div(h.p("hi"), cls="x")`, and the `with` form, where elements created inside a
`with h.div():` block become its children. `build(view, renderer)` draws the tree through
a `Renderer`; `render_to_string(view)` is that with `HtmlRenderer`.
"""

from .renderer import HtmlRenderer


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


_stack = []

# Keyword spellings the builder accepts for names Python cannot write as-is.
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
        elif isinstance(item, (Element, Text)):
            out.append(item)
        else:
            out.append(Text(item))
    return out


class _TagFactory:
    def __init__(self, tag):
        self.tag = tag

    def __call__(self, *children, **attrs):
        element = Element(self.tag, {_attr_name(k): v for k, v in attrs.items()}, _children(children))
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


def build(view, renderer, parent=None):
    """Draw `view` through `renderer`, under `parent` when given. Returns the node."""
    if isinstance(view, Text):
        node = renderer.create_text(view.value)
    elif isinstance(view, Element):
        node = renderer.create_element(view.tag)
        for name, value in view.attrs.items():
            renderer.set_property(node, name, value)
        for child in view.children:
            build(child, renderer, node)
    else:
        node = renderer.create_text(view)
    if parent is not None:
        renderer.insert_node(parent, node)
    return node


def render_to_string(view):
    """The view as HTML, with no browser involved."""
    return build(view, HtmlRenderer()).to_html()


__all__ = ["Element", "Text", "build", "h", "render_to_string", "text"]
