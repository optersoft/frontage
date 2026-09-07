"""The Python half of the chart component: uPlot, as a function that takes accessors.

The pattern is `examples/chart/plot.py`'s, with one addition this app needs: the *options*
are reactive too, because the number of series changes when a year is toggled off. A
`NodeRef` for the element the library owns, an `Effect` that redraws when either accessor
changes, and an `on_cleanup` so the library lets go when the view does.
"""

import chartlib  # registered by the loader from data-fr-js

from frontage import Effect, NodeRef, h, on_cleanup
from frontage.runtime import to_js


def chart(data, options=None, **fixed):
    """`data` returns [x[], y1[], …]; `options` is a dict or an accessor returning one."""
    ref = NodeRef()

    def draw():
        columns = data()  # tracked, so a signal write redraws
        settings = dict(fixed)
        if options is not None:
            settings.update(options() if callable(options) else options)
        node = ref()
        if node is not None:
            chartlib.draw(node, to_js(columns), to_js(settings))

    Effect(draw)
    on_cleanup(lambda: chartlib.destroy(ref()) if ref() is not None else None)
    return h.div(ref=ref, cls="fr-chart")
