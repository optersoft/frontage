"""The Python half. It knows about signals and elements; `_browser/index.js` knows about Leaflet.

The same twenty-line shape every wrapper here follows — a `NodeRef` for the element the library
owns, an `Effect` that redraws when the points accessor changes, and an `on_cleanup` so the
library lets go when the view does — plus the one thing a map has that a chart does not: the
viewport is *state*, and this reports it back.
"""

# `map` is the name `frontage build` registers this component under, so the JavaScript half
# arrives as an ordinary Python module. Aliased on import so the builtin `map` is untouched.
import map as _js
from frontage import Effect, NodeRef, h, on_cleanup
from frontage.runtime import create_proxy, to_js

__all__ = ["map_view"]


def map_view(points=None, *, on_click=None, on_move=None, height=400, cls=None, style=None, **options):
    """A map of `points`, which is an accessor or a plain sequence.

    A point is `[lat, lon]`, or a mapping with `lat`/`lon` (`lng` and `latitude`/`longitude`
    are accepted too, so a row out of a dataset usually needs no reshaping). A mapping may also
    carry `popup`, `tooltip`, `color`, `radius`, `opacity` and `weight`; the same names given
    as keyword arguments set the default for every point.

    `on_click(lat, lon)` fires on the map. `on_move(south, west, north, east, zoom)` fires
    whenever the viewport settles, and once when the map is first ready — which is what lets
    the rest of the page filter itself to what is actually on screen.

    View: `center` and `zoom` place the map, or it fits itself to the points. Either way it is
    placed **once**, so points arriving later never yank the map away from a reader who has
    panned it. Pass `follow=True` if refitting on every change is genuinely what you want.

    Tiles: `tiles` is a URL template, defaulting to OpenStreetMap's, with `attribution` beside
    it. `tiles=None` draws the points on a plain background and asks the network for nothing.
    """
    ref = NodeRef()
    proxies = []

    def bridged(fn):
        if fn is None:
            return None
        proxy = create_proxy(fn)
        proxies.append(proxy)
        return proxy

    click, move = bridged(on_click), bridged(on_move)

    def redraw():
        seq = points() if callable(points) else points  # tracked: a write here redraws
        node = ref()
        if node is not None:
            _js.draw(node, to_js(list(seq) if seq else []), to_js(options), click, move)

    Effect(redraw)

    def release():
        node = ref()
        if node is not None:
            _js.destroy(node)
        for proxy in proxies:
            # MicroPython's proxies free themselves; Pyodide's need telling. Same shape the
            # framework's own `add_listener` uses.
            destroy = getattr(proxy, "destroy", None)
            if destroy is not None:
                destroy()

    on_cleanup(release)
    size = height if isinstance(height, str) else f"{height}px"
    return h.div(ref=ref, cls=f"fr-map {cls}" if cls else "fr-map", style=style or f"height: {size}")
