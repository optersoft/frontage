"""The Python half of a chart component: uPlot, as an importable Python function.

The pattern a component follows: a `NodeRef` for the element the library owns, an `Effect`
that redraws when the data signal changes, and an `on_cleanup` so the library lets go when
the view does. Nothing here knows what uPlot is.
"""

import chartlib  # registered by the loader from data-fr-js

from frontage import Effect, NodeRef, h, on_cleanup
from frontage.runtime import to_js


def line_chart(data, **options):
    """`data` is an accessor returning [x[], y1[], ...]; the chart redraws when it changes."""
    ref = NodeRef()

    def draw():
        series = data()  # tracked, so a signal write redraws
        node = ref()
        if node is not None:
            chartlib.draw(node, to_js(series), to_js(options))

    Effect(draw)
    on_cleanup(lambda: chartlib.destroy(ref()) if ref() is not None else None)
    return h.div(ref=ref, cls="fr-chart")
