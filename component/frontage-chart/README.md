# frontage-chart

Charts for [frontage](https://academy.optersoft.com/python/frontage), on
[uPlot](https://github.com/leeoniya/uPlot): `line_chart`, `area_chart`, `bar_chart`,
`scatter_chart`.

```sh
pip install frontage-chart
```

```py
import math

from frontage import Signal, h, mount
from frontage_chart import line_chart

n = Signal(2000)


def series():
    return [list(range(n())), [math.sin(i / 40) for i in range(n())]]


mount(lambda: line_chart(series, height=260, labels=["sine"]), "#app")
```

A chart takes an **accessor**, not data: it redraws when that accessor changes and at no other
time. That is the point of drawing a chart in this framework rather than in one that re-runs a
script to change a number.

uPlot is 41 KB gzipped and renders to canvas; 20,000 points redraw in about 68 ms. The long
tail — pie, sankey, radar, treemap — belongs behind a separate, heavier dependency, not here.

uPlot is vendored (MIT, see `frontage_chart/_browser/uplot.js`), so a build needs no network
and an app has no CDN in its critical path.

## Typed arrays

`draw` takes plain lists from Python, or `Float64Array`s that arrived from a server — what
`frontage-polars`' `series` hands back — and draws those as they are, with no copy.
