# Beating Streamlit: the component strategy

**Status: a plan, 2026-09-07. The numbers in §1 are measured, from a working prototype built
in `build/chart/` — which is gitignored and therefore gone; §5 says what replaces it. The
measurements are real and were taken on the boot this repository ships. Everything from §4 on
is unbuilt.**

Streamlit owns "a Python developer wants a data app by Friday". This document is about taking
that, and it argues the way in is not to copy Streamlit's surface but to attack the one thing
it cannot fix: its architecture puts Python on a server, and every attempt to move it into the
browser has been an attempt to carry the server along.

## 1. What the prototype already shows

A dashboard — two sliders, a live line chart, data built in Python — using
[uPlot](https://github.com/leeoniya/uPlot) as a frontage component through `data-fr-js`.
Chromium, this laptop:

| | frontage prototype | stlite (Streamlit in Pyodide) |
|---|---|---|
| downloaded | **946 KB**, 10 requests | ~50 MB for the playground app |
| cold start to a drawn chart | **96 ms** | tens of seconds |
| interaction model | fine-grained: a slider moves one memo and redraws one canvas | the whole script re-runs |

Redraw, slider moved to first pixel, two series:

| points per series | slider to redrawn |
|---|---|
| 2,000 | 6 ms |
| 5,000 | 22 ms |
| 10,000 | 38 ms |
| 20,000 | 68 ms |

The component is 40 lines of JavaScript and 20 of Python. uPlot itself is 41 KB gzipped.

That is the whole thesis in one measurement: **two orders of magnitude less download and
three fewer of latency, because there is no server and no CPython.**

## 2. What Streamlit actually is

Worth being precise, because the parts are not equally strong.

**The good part is the ergonomics.** `st.slider("n", 1, 100)` returns an int. No callback, no
state wiring, no component lifecycle. A scientist writes a dashboard top to bottom like a
script, and that is genuinely hard to beat.

**The weak part is how it delivers them.** The script re-runs from the top on every
interaction, and `st.cache_data` exists to paper over that. State is a dictionary keyed by
widget identity. Layout is a handful of containers. The app needs a Python process per
session.

**The part that does not survive contact with the browser** is everything below the API:
pandas, numpy, scikit-learn, pyarrow, matplotlib. stlite proves it can be dragged in, at
~50 MB, and proves what still breaks — no TensorFlow, no `requests`, `time.sleep` is a no-op.

## 3. Where frontage stands today

**Ahead**: boot (52 ms against tens of seconds), size, no server, fine-grained updates,
prerendering, a real router, static hosting. A dev loop that swaps a module into a running page.

**Behind, and this is the whole gap**: Streamlit ships about eighty display and input elements.
Frontage ships nine form controls. There is no chart, no table, no map, no metric, no layout
primitive, no file uploader. An app that shows data has nothing to show it with.

**Not competing**: pandas, scikit-learn, and the scientific stack. Chasing those means
becoming stlite, which means becoming 50 MB. §7 says what to do instead.

## 4. The strategy: pay for what you show

Streamlit's cost is fixed and up front — you download the runtime whether you use one widget or
eighty. Frontage's should be proportional and lazy:

| tier | cost | what it buys |
|---|---|---|
| the framework | 0.64 MB | reactivity, router, form controls, prerendering |
| a chart | +41 KB | uPlot: line, area, bar, scatter, to ~100k points |
| a table | +~60 KB | virtualised grid, sort, filter, column config |
| a map | +~200 KB | MapLibre, vector tiles, markers, layers |
| a rich chart | +~100 KB | ECharts tree-shaken: pie, radar, sankey, heatmap, gauge |
| analytics | +~3.2 MB | DuckDB-wasm: SQL over Parquet, multi-GB, opt-in |

A dashboard with charts and a grid lands near 800 KB and boots in well under a second. Only an
app that genuinely wants SQL over a Parquet file pays the 3.2 MB, and even that is a fraction
of stlite's floor.

**The rule this encodes**: a component is a dependency, not a feature of the framework. It
ships separately, versions separately, and costs nothing until imported.

## 5. `frontage-component`: the protocol

The prototype works but wires everything by hand — vendored `.js` beside the app, a
`data-fr-js` attribute typed by the author, the Python half copied in. That does not scale to
a catalogue. What is missing is a way to `pip install` a component and have it just work.

**A component is a Python package that also ships browser assets.**

```
frontage_chart/
    __init__.py          # the Python API: line_chart(data, **options) -> Element
    _browser/
        chart.js         # the glue: owns the library, exposes the smallest surface
        uplot.esm.js     # vendored, or bundled in
        chart.css
```

It declares itself through a package entry point, which is build-time metadata on CPython and
so costs the browser nothing:

```toml
[project.entry-points."frontage.components"]
chart = "frontage_chart"
```

`frontage build` then:

1. discovers every installed component,
2. copies its `_browser/` into `dist/_frontage/components/<name>/`,
3. appends `<name>=./_frontage/components/<name>/<entry>.js` to the boot tag's `data-fr-js`,
4. packs the component's **Python** modules into `app.tar` under their package path, so
   `import frontage_chart` works in the browser,
5. links any declared stylesheet from the page.

The author writes `pip install frontage-chart`, then `from frontage_chart import line_chart`.
Nothing else.

**Everything this needs already exists.** `data-fr-js` loads and registers the JavaScript;
`registerJsModule` makes it a real Python import; `build` already copies and packs. The work
is discovery and packing, not new machinery — call it a week, not a milestone.

**The component author's contract**, which the prototype already demonstrates: a `NodeRef` for
the element the library owns, an `Effect` that redraws when its data accessor changes, and an
`on_cleanup` that lets the library go. Twenty lines. Compare Streamlit's component model,
which is a React project, a build step, an iframe and a bidirectional message protocol.

**Where it lives**: the protocol belongs in frontage, because `build` implements it. The
components belong in their own repository — they carry third-party dependencies and release on
their own cadence. One repository with a package per component, following the chapter-repo
convention already used for the academy.

## 6. What to build, in order

Ordered by how much of Streamlit's gallery each unlocks per kilobyte.

1. **`frontage-chart`** (uPlot). Line, area, bar, scatter. Covers `st.line_chart`,
   `st.area_chart`, `st.bar_chart`, `st.scatter_chart` — the majority of gallery apps.
2. **`frontage-table`**. A virtualised grid over a list of dicts: sort, filter, column
   formatting, row selection. This is `st.dataframe`, and it is the element most reached for
   after a chart. Virtualisation is the whole trick; 100k rows must not mean 100k DOM nodes.
3. **`frontage-layout`**. `columns`, `tabs`, `expander`, `sidebar`, `metric`, `progress`,
   `spinner`. Pure Python and CSS, no dependency, and it is what makes an app look like an app.
4. **`frontage-map`** (MapLibre). `st.map` and `st.pydeck_chart`'s common case.
5. **`frontage-echarts`**. Pie, radar, sankey, heatmap, gauge, treemap — the long tail, behind
   one bigger dependency that only apps needing it pay for.
6. **`frontage-data`** (DuckDB-wasm). SQL over Parquet and CSV, in the browser, over files the
   user drops in. This is the one that goes somewhere Streamlit cannot follow without a server.

A `frontage.widgets` pass belongs alongside: date, time, colour, file upload, multiselect,
toggle. Those are plain HTML controls and cost nothing.

## 7. Rust and WebAssembly: where it actually pays

Tempting to write all of this in Rust. Mostly wrong, and the measurements say why.

**A crossing costs 1.00 µs** — four MicroPython method calls (DESIGN §12, and
`examples/wasm/`). Cheap. But the two modules have **separate linear memories**, so anything
but a number is copied through JavaScript. That single fact decides everything:

**Do not** write a chart library in Rust. uPlot is 41 KB, mature, and already faster than
anything worth writing; a Rust rewrite would still have to call out to JavaScript to touch the
canvas, so the path gets *longer*, not shorter. The same goes for the grid and the map.

**Do** reach for Rust where the work is bulk computation on data already in wasm memory, with
a coarse call boundary:

- **Aggregation and filtering over columnar data.** Hand a Rust module an Arrow buffer once,
  then ask it coarse questions — group by, rolling mean, quantiles, resample. One call in, one
  small answer out. This is exactly the shape the crossing cost rewards, and exactly what
  Streamlit does with pandas on a server.
- **Decoding.** Parquet, CSV at scale, image formats.
- **A domain hot loop** an application actually has: a simulation step, a solver, a codec.
  Tens of kilobytes, and the binding is already proven.

**The honest ordering**: DuckDB-wasm at ~3.2 MB compressed already does the first bullet
better than we would, and it is opt-in. Write Rust when a measurement says DuckDB is the wrong
shape or too heavy for the job — not before. The framework's own history is the precedent:
section 8.6 proposed a JavaScript shim, milestone 5 measured it and declined.

**What we should build in Rust regardless** is the thing nobody ships: a small, documented
`frontage-wasm` template — `wasm-pack`, the glue, the Python wrapper, the `data-fr-js` line —
so that "call your Rust from your app" is a fifteen-minute exercise. That is a differentiator
Streamlit has no answer to, because Streamlit's Python is on a server where the wasm cannot go.

## 8. What we will not do

- **Chase the scientific stack.** No pandas, no scikit-learn, no matplotlib. Wanting those
  means wanting Pyodide, which means 13.8 MB before app code, and stlite already occupies that
  position. Say so plainly in the docs rather than half-supporting it.
- **Copy `st.*` names.** Frontage is reactive; Streamlit is a re-run. An API that looks the
  same but behaves differently is worse than one that looks different.
- **A server.** The constraint that produced the 96 ms boot is the constraint that says no.

## 9. What would make this real

The order matters more than the dates.

| step | why it is first |
|---|---|
| the `frontage-component` protocol in `build` | nothing else can ship as a package until it exists |
| `frontage-chart` and `frontage-layout` | the smallest pair that makes a credible dashboard |
| a gallery of three rebuilt Streamlit apps, with the numbers beside each | the claim in §1 is only worth what it is demonstrated on |
| `frontage-table` | the second thing every data app reaches for |
| the `frontage-wasm` template | the differentiator, once there is an audience for it |

The gallery is the marketing and the test suite at once. Pick apps that are honest matches —
dashboards over data a browser can hold — and publish the download size and cold start next to
each, because those are the numbers Streamlit cannot answer.
