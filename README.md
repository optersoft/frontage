# frontage-components

Components for [frontage](https://github.com/optersoft/frontage): the display and layout
elements a data app needs, each a separate package that costs nothing until it is imported.

| package | cost to the browser | what it is |
|---|---|---|
| [`frontage-layout`](frontage-layout/) | 2.5 KB of CSS | `columns`, `tabs`, `expander`, `container`, `metric`, `progress`, `spinner`, `divider` — pure Python, no dependency |
| [`frontage-chart`](frontage-chart/) | 41 KB gzipped | `line_chart`, `area_chart`, `bar_chart`, `scatter_chart`, on uPlot |

```sh
pip install frontage-layout frontage-chart
```

That is the whole install. `frontage build` discovers each package by its entry point, copies
its browser assets, links its stylesheet, and packs its Python — so `from frontage_chart import
line_chart` resolves inside the page with nothing to configure.

## Why separate packages

Streamlit charges for its whole runtime whether an app uses one widget or eighty. Here a
component is a dependency: a dashboard with charts and layout lands near 800 KB and starts in
under a tenth of a second, and an app that needs neither pays nothing for them. The reasoning,
the measurements and the rest of the catalogue are in frontage's `COMPONENTS.md`.

## Writing one

A component is a Python package that also ships browser assets:

```
frontage_thing/
    __init__.py          the Python API — returns Elements, takes accessors
    _browser/
        index.js         the module `data-fr-js` registers (required)
        index.css        linked from the page if present
```

plus one line of metadata:

```toml
[project.entry-points."frontage.components"]
thing = "frontage_thing"
```

`frontage_chart/plot.py` is the pattern in twenty lines: a `NodeRef` for the element the
library owns, an `Effect` that redraws when its data accessor changes, and an `on_cleanup` so
the library lets go when the view does.

Two rules that are not obvious:

- **Take an accessor, not data.** `line_chart(series)` redraws when `series` changes and at no
  other time. Taking a value throws away the reason to use this framework.
- **Never phone home.** A frontage app is a directory of static files with nothing listening;
  one component that makes an uninvited request gives that property away for all of them.

And one that cost an afternoon to find: **MicroPython does not preserve dict insertion order**,
so any API where the order of a mapping is visible must take pairs. `tabs` refuses a dict and
says why.

## Development

```sh
uv sync --all-groups     # frontage and both packages, editable, from the checkouts beside this
uv run pytest -q
uv run ruff check .
```

`frontage build APP --component thing=path/to/frontage_thing` builds against a component that
is not installed yet, which is how you try one before publishing it.

Apache 2.0. uPlot is vendored under `frontage-chart/frontage_chart/_browser/` (MIT).
