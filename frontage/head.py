"""What a page says about itself: `Title` and `Meta`, written from the component that knows.

Both render nothing. In the browser they write to `document` from a render effect, so a title
over a signal follows it and a route's title changes when the route does. Each is a stack: the
innermost one on the page wins, and when it goes the one under it comes back, so leaving a
route that set a title does not leave its title behind.

Off the browser they record what they were given instead, and `frontage prerender` writes it
into the page's `<head>` — which is the whole point, because a crawler, a link preview and a
search result read the HTML and never run the page.

    from frontage.head import Meta, Title

    def article(post):
        return h.article(
            Title(lambda: post()["headline"]),
            Meta(lambda: post()["summary"], name="description"),
            h.h1(lambda: post()["headline"]),
        )

`Route(path, component, title=…)` is the same thing said once, for a whole route.

`Tag` is the third one, for everything a page's head carries that is not words: the canonical
URL, the hreflang set, the favicons, a licence link, a JSON-LD graph, an inline script that
has to run before first paint. A layout that returns one of those as a plain element puts a
`<link>` in the *body*, which is where this was found — so a layout writes

    from frontage.head import Tag

    Tag(h.link(rel="canonical", href=url))

and it renders nothing where it stands.
"""

from .reactive import RenderEffect, on_cleanup
from .runtime import document, in_browser

__all__ = ["Meta", "Tag", "Title", "current_title", "snapshot"]

# Every live entry, innermost last, by slot: `None` is the title, a `(attribute, name)` pair is
# one meta tag. The last entry of a slot is what the page shows.
_stack = {}
#: What the prerenderer takes: the same thing, off the browser, where there is no document.
_title = [None]
_meta = []
#: Whole elements a page put in its head — a `<link>`, a `<script>`, a JSON-LD graph. Kept as
#: HTML rather than as views, because that is what the prerenderer has to write and the
#: element is built where the layout stands, with a renderer of its own.
_tags = []


def _value(value):
    return value() if callable(value) else value


def _apply(slot):
    entries = _stack.get(slot)
    text = _value(entries[-1][0]) if entries else None
    if slot is None:
        _write_title(text)
    else:
        _write_meta(slot, text)


def _write_title(text):
    if not in_browser:
        _title[0] = text
        return
    document.title = "" if text is None else str(text)


def _write_meta(slot, content):
    attribute, name = slot
    if not in_browser:
        kept = [item for item in _meta if (item[0], item[1]) != slot]
        del _meta[:]
        _meta.extend(kept)
        if content is not None:
            _meta.append((attribute, name, str(content)))
        return
    selector = f"meta[{attribute}='{name}']"
    tag = document.querySelector(selector)
    if content is None:
        if tag is not None:
            tag.remove()
        return
    if tag is None:
        tag = document.createElement("meta")
        tag.setAttribute(attribute, name)
        document.head.appendChild(tag)
    tag.setAttribute("content", str(content))


def _register(slot, value):
    """Push an entry, keep it up to date, and take it away with its owner."""
    entry = [value]
    _stack.setdefault(slot, []).append(entry)

    def update():
        entry[0] = value
        _apply(slot)

    RenderEffect(update)

    def remove():
        entries = _stack.get(slot) or []
        if entry in entries:
            entries.remove(entry)
        if not entries:
            _stack.pop(slot, None)
        _apply(slot)

    on_cleanup(remove)


def Title(value):
    """The page's title, a string or an accessor. Renders nothing."""
    _register(None, value)
    return None


def Meta(content, name=None, property=None):  # noqa: A002 - `property` is the attribute's name
    """One `<meta>` tag, by `name=` or by `property=` (Open Graph). Renders nothing."""
    if (name is None) == (property is None):
        raise TypeError("Meta needs exactly one of name= or property=")
    slot = ("name", name) if name is not None else ("property", property)
    _register(slot, content)
    return None


def _html_of(element):
    """One head element as HTML, rendered here and now with a renderer of its own.

    Off the browser a head tag has nowhere to go — the page's own renderer is drawing the
    body — so it is serialised at the point it is declared and the prerenderer splices the
    string into `<head>`. Static by nature: nothing in a head tag is reactive.
    """
    from .renderer import HtmlRenderer
    from .view import _build_nodes

    # Built, not mounted: a mount inside the page's own render pass defers its DOM work to
    # the scheduler, and this has to answer with the markup now. Nothing in a head tag is
    # reactive, so there is nothing for an owner to hold.
    return "".join(node.to_html() for node in _build_nodes(element, HtmlRenderer()))


def Tag(element):
    """One whole element in the page's `<head>` — a `<link>`, a `<script>`, a JSON-LD graph.

    `Title` and `Meta` cover what a page says about itself in words; this is for everything
    else a crawler reads and only the layout knows: the canonical URL, the hreflang set, the
    favicons, the licence link, an inline script that has to run before first paint.

    Renders nothing where it stands, like the other two, and goes away with its owner.
    """
    if element is None:
        return None
    if not in_browser:
        markup = _html_of(element)
        _tags.append(markup)

        def forget_tag():
            if markup in _tags:
                _tags.remove(markup)

        on_cleanup(forget_tag)
        return None
    from .view import mount

    handle = mount(lambda: element, document.head, clear=False)
    on_cleanup(handle.dispose)
    return None


def current_title():
    """What the page calls itself right now, from the innermost `Title` — or None."""
    entries = _stack.get(None)
    return _value(entries[-1][0]) if entries else None


def snapshot():
    """What the page said about itself, for the prerenderer. Off the browser only."""
    return {"title": _title[0], "meta": list(_meta), "tags": list(_tags)}


def forget():
    """Start again: the prerenderer renders many routes in one process."""
    _stack.clear()
    _title[0] = None
    del _meta[:]
    del _tags[:]
