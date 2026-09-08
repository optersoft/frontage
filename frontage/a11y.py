"""The parts of a single-page app a screen reader cannot see happen.

A page that swaps its content without reloading tells the browser nothing: the URL changes,
the main region is replaced, and a screen reader goes on reading what it was reading. Two
things fix most of it, and the router does both.

`announce(text)` writes into a polite live region — one `<div>` at the end of the body, off
screen, `aria-live="polite"` — which is how an assistive technology hears that the page is now
a different page. `focus(selector)` moves focus to the new region, so the next Tab starts
there instead of back at the top of the browser chrome.

Neither does anything off the browser, and neither shows.
"""

from .runtime import document, in_browser

__all__ = ["announce", "focus", "title"]

_REGION_ID = "fr-live-region"
_OFF_SCREEN = "position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0"


def region():
    """The page's polite live region, made on first use."""
    node = document.getElementById(_REGION_ID)
    if node is None:
        node = document.createElement("div")
        node.id = _REGION_ID
        node.setAttribute("aria-live", "polite")
        node.setAttribute("aria-atomic", "true")
        node.setAttribute("style", _OFF_SCREEN)
        document.body.appendChild(node)
    return node


def title():
    """What the document calls itself, which is what `frontage.head`'s `Title` writes."""
    return str(document.title) if in_browser else ""


def announce(text):
    """Say `text` to a screen reader, without showing it to anyone else."""
    if not in_browser or not text:
        return
    node = region()
    # Emptied first: setting the same text twice in a row is not a change, and a live region
    # only speaks what changed — which is exactly what two visits to the same route look like.
    node.textContent = ""
    node.textContent = str(text)


def focus(selector):
    """Move focus to the first element matching `selector`, if there is one.

    The element is made focusable (`tabindex="-1"`) if it is not already, and the page is not
    scrolled: focus is about where the next Tab goes, and the router has its own opinion about
    scrolling.
    """
    if not in_browser or not selector:
        return
    node = document.querySelector(selector)
    if node is None:
        return
    if not node.hasAttribute("tabindex"):
        node.setAttribute("tabindex", "-1")
    try:
        node.focus({"preventScroll": True})
    except Exception:
        node.focus()
