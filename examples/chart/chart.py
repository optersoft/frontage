"""A dashboard, the shape Streamlit's gallery is made of, with no server and no CPython.

The chart is a *component*: `plot.py` and `chartlib.js` wrap uPlot, and the page declares it
with `data-fr-js="chartlib=./chartlib.js"`. Nothing about that wrapping is chart-specific —
it is the pattern any JavaScript or WebAssembly library follows to become importable Python
(see `examples/wasm/` for the same thing on a library you can read in full, and COMPONENTS.md
for where it goes next).

A slider moves one signal; the memo rebuilds; one canvas redraws. Nothing else on the page
recomputes, which is what a re-run-the-script framework cannot say.
"""

import math

from plot import line_chart

from frontage import Memo, Signal, h, mount
from frontage.widgets import slider

points = Signal(2000)
phase = Signal(0)

# The data is a Memo, so the chart redraws when either control moves and at no other time.
series = Memo(
    lambda: [
        [i for i in range(points())],
        [math.sin(i / 40.0 + phase() / 10.0) * 50 + 50 for i in range(points())],
        [math.cos(i / 55.0 + phase() / 10.0) * 30 + 50 for i in range(points())],
    ]
)

mount(
    lambda: h.div(
        h.h1("Frontage dashboard"),
        slider(points, "Points", min=200, max=20000, step=200),
        slider(phase, "Phase", min=0, max=100),
        line_chart(series, height=260, labels=["sine", "cosine"]),
        h.p(lambda: f"{points()} points per series", id="count"),
    ),
    "#app",
)
