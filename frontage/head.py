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
"""

from .reactive import RenderEffect, on_cleanup
from .runtime import document, in_browser

__all__ = ["Meta", "Title", "snapshot"]

# Every live entry, innermost last, by slot: `None` is the title, a `(attribute, name)` pair is
# one meta tag. The last entry of a slot is what the page shows.
_stack = {}
#: What the prerenderer takes: the same thing, off the browser, where there is no document.
_title = [None]
_meta = []


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


def snapshot():
    """What the page said about itself, for the prerenderer. Off the browser only."""
    return {"title": _title[0], "meta": list(_meta)}


def forget():
    """Start again: the prerenderer renders many routes in one process."""
    _stack.clear()
    _title[0] = None
    del _meta[:]
