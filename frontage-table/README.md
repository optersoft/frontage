# frontage-table

A virtualised, sortable data grid for [frontage](https://github.com/optersoft/frontage) —
`st.dataframe` without the dataframe.

**Pure Python and 1.5 KB of CSS. No JavaScript, no WebAssembly, no dependency.**

```sh
pip install frontage-table
```

```py
from frontage import Signal, mount
from frontage_table import table

rows = Signal([{"name": "Ada", "qty": 12}, {"name": "Grace", "qty": 7}])

mount(lambda: table(rows, columns=[("name", "Name"), ("qty", "Qty", ",")]), "#app")
```

## Why there is no JavaScript in it

A grid is where component libraries normally reach for a 200 KB dependency. But the expensive
part of a grid is not drawing it — it is *not* drawing the 99,970 rows nobody is looking at,
and a fine-grained reactive framework is already built to do that.

The rows on screen are a fixed set of elements. Scrolling does not create or destroy them; it
changes what they read, and each cell's own text node updates. A hundred-thousand-row table
costs about what a thirty-row one does.

## What it does

- **Virtualised scrolling** over any number of rows.
- **Sorting** by clicking a header; click again to reverse.
- **Filtering** through a `Signal` you own, so your own text input drives it.
- **Column config**: a label, a `str.format` spec or a callable, a width, an alignment.

`rows` is an accessor returning a list of dicts, so the grid recomputes when the data changes
and at no other time.

⚠ Columns are given as **pairs**, never a dict: MicroPython does not preserve insertion order,
so a mapping would shuffle your columns in the browser.

Apache 2.0.

## Rows that stay on a server

`rows` may also be a **windowed source**: any object with `key()` (tracked; changes when the
rows should be re-asked) and `async window(key, offset, limit, sort, descending, search)`
returning `(total, offset, rows)`. The grid then fetches the block it is scrolled to — aligned
to the window size and two windows long, so a small scroll asks for nothing — and leaves
sorting and searching to the server; a header click or a keystroke is one request for a few
dozen rows. Rows are shown where the server put them, so the previous block stays in place
while the next one loads, and the grid carries `fr-loading` meanwhile.

`frontage_polars.Remote.rows` is one such source; PostgREST's `Range` headers would make
another in twenty lines.
