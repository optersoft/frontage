# frontage-components

Components for [frontage](https://github.com/optersoft/frontage): the display and layout
elements a data app needs, each a separate package that costs nothing until it is imported.

| package | cost to the browser | what it is |
|---|---|---|
| [`frontage-layout`](frontage-layout/) | 2.5 KB of CSS | `columns`, `tabs`, `expander`, `container`, `metric`, `progress`, `spinner`, `divider` — pure Python, no dependency |
| [`frontage-chart`](frontage-chart/) | 41 KB gzipped | `line_chart`, `area_chart`, `bar_chart`, `scatter_chart`, on uPlot |
| [`frontage-table`](frontage-table/) | 1.5 KB of CSS | a **virtualised, sortable grid** — 50,000 rows, 21 elements, no JavaScript; or a **windowed source**, when the rows live on a server |
| [`frontage-polars`](frontage-polars/) | 0.6 KB of JavaScript | **polars on the server, small answers in the page**: named queries behind a FastAPI router, a `Resource` per query in the browser, windows for the grid, and a Server-Sent Events stream so a change on the server reaches every page. The one package here with a server half, and it is opt-in (`[server]`) |
| [`frontage-map`](frontage-map/) | 46 KB gzipped | `map_view`, on Leaflet — points, popups, and **a viewport the app can read** |

```sh
pip install frontage-layout frontage-chart frontage-table frontage-map
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
  one component that makes an *uninvited* request gives that property away for all of them.
  `frontage-map` is the one component that fetches anything at runtime, because a basemap comes
  from a tile server and there is no way around that. The rule it keeps instead: the request is
  the thing the caller asked for, the server is the caller's to choose, and `tiles=None` turns
  it off. Nothing else may reach the network at all.

And one that cost an afternoon to find: **MicroPython does not preserve dict insertion order**,
so any API where the order of a mapping is visible must take pairs. `tabs` refuses a dict and
says why.

## Releasing

Each package versions and releases on its own, because a shared version would force a pointless
release of the other two whenever one changed. A tag names the package it releases:

```sh
# bump `version` in frontage-chart/pyproject.toml, commit, then
git tag -a frontage-chart-v0.1.0 -m "frontage-chart 0.1.0" && git push origin frontage-chart-v0.1.0
```

CI checks the tag against the version in that package's `pyproject.toml`, builds it, asserts the
wheel actually contains `_browser/index.js` — a component that loses its browser half installs
and imports perfectly and then does nothing in a page — and publishes over OIDC.

⚠ **Nothing publishes until three trusted publishers exist on PyPI**, one per package, at
<https://pypi.org/manage/account/publishing/>. Owner `optersoft`, repository
`frontage-component`, workflow `ci.yml` for all three — and **a different environment for each,
named after its own package**:

| PyPI project | environment |
|---|---|
| `frontage-layout` | `frontage-layout` |
| `frontage-chart` | `frontage-chart` |
| `frontage-table` | `frontage-table` |

The differing environment is not decoration. A *pending* publisher is unique on
`(owner, repo, workflow, environment)`, so three that share one environment collide and the
second is refused with *"A pending trusted publisher matching this configuration has already
been registered for a different project name"* — the monorepo case,
[pypi/warehouse#16920](https://github.com/pypi/warehouse/issues/16920). The workflow reads the
package out of the tag and selects the matching environment.

All three names were unclaimed on 2026-09-07. A missing publisher fails with `422
invalid-publisher` and uploads nothing, so the version stays claimable and re-running the job
succeeds once it is registered.

## Development

```sh
uv sync --all-groups     # frontage and both packages, editable, from the checkouts beside this
uv run pytest -q
uv run ruff check .
```

`frontage build APP --component thing=path/to/frontage_thing` builds against a component that
is not installed yet, which is how you try one before publishing it.

Apache 2.0. uPlot is vendored under `frontage-chart/frontage_chart/_browser/` (MIT).
