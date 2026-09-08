"""Charts for frontage, on uPlot: line, area, scatter and bar, to ~100k points.

uPlot rather than something bigger because it is 41 KB gzipped and renders to canvas, and
because a chart component's job is to be small enough that adding one is not a decision. The
long tail — pie, sankey, radar, treemap — belongs behind a separate, heavier dependency.

A chart takes an *accessor*, not data. `line_chart(series)` redraws when `series` changes and
at no other time, which is the whole reason to draw a chart in this framework rather than one
that re-runs a script.
"""

from .plot import area_chart, bar_chart, line_chart, scatter_chart

__all__ = ["area_chart", "bar_chart", "line_chart", "scatter_chart"]
