"""The Python half. It knows about signals and elements; `_browser/index.js` knows about uPlot.

The pattern any wrapper follows, and it is twenty lines: a `NodeRef` for the element the
library owns, an `Effect` that redraws when the data accessor changes, and an `on_cleanup` so
the library lets go when the view does.
"""

# `chart` is the name `frontage build` registers this component under, so the JavaScript half
# arrives as an ordinary Python module.
import chart as _js
from frontage import Effect, NodeRef, h, on_cleanup
from frontage.runtime import to_js

__all__ = ["area_chart", "bar_chart", "line_chart", "scatter_chart"]


def _chart(kind, data, cls=None, **options):
    ref = NodeRef()
    options["kind"] = kind

    def draw():
        series = data() if callable(data) else data  # tracked: a write here redraws
        node = ref()
        if node is not None:
            _js.draw(node, to_js(series), to_js(options))

    Effect(draw)
    on_cleanup(lambda: _js.destroy(ref()) if ref() is not None else None)
    return h.div(ref=ref, cls=f"fr-chart {cls}" if cls else "fr-chart")


def line_chart(data, **options):
    """`data` is an accessor returning `[x[], y1[], …]`; the first list is the x axis."""
    return _chart("line", data, **options)


def area_chart(data, **options):
    return _chart("area", data, **options)


def scatter_chart(data, **options):
    return _chart("scatter", data, **options)


def bar_chart(data, **options):
    return _chart("bar", data, **options)
