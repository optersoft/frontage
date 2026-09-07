# Beating Streamlit: the component strategy

**Status: a plan, 2026-09-07. The numbers in §1 are measured, and the thing they were measured
on is committed: `examples/chart/`, with a browser test. Everything from §4 on is unbuilt.**

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

**And the re-run is not a wart, it is the design**, which is why waiting for it to be fixed is
not a strategy. Streamlit's own issue #5827, open since December 2022 with 96 reactions,
answers a request to stop re-running with *"This touches on the fundamental of Streamlit… No
guarantees that we'll do this anytime soon!"* Its then Head of Developer Relations drew the
scale line himself on Reddit in 2021: Streamlit is production-grade *"for use cases where fewer
than 10's of thousands of simultaneous open connections are needed"*, and *"Sending a GB of
data over to the browser is going to be slow"*.

What practitioners report follows from that one decision. From r/dataengineering: components
are not isolated, so *"you can break the component A by doing something with the component B in
a very different place"*, and *"when that happens there is zero ways to debug the issue"*. From
r/ExperiencedDevs: *"you can't define endpoints, any components or styles not already in it,
multi pages are a hassle… and the page re runs the entire python script every time it is
refreshed."* Posit — a competitor, so read it as such — demonstrates that styling one button
means reaching out of an iframe with `window.parent.document.querySelectorAll('button')` and
concludes *"this is the best way to change the style of an individual element in Streamlit"*.

**One market signal worth more than any opinion.** Hugging Face Spaces, the largest host of ML
demos, shipped a custom Streamlit frontend and roughly a dozen Streamlit changelog entries
between 2021 and 2023. Then, dated 2025-04-30: *"Deprecate Streamlit SDK — Streamlit is no
longer provided as a default built-in SDK option. Streamlit applications are now created using
the Docker template."*

## 2b. The argument we had not thought to make: there is nothing to leave open

This one is not about features, and it is the strongest thing on the list.

A Streamlit app is a Python process holding sessions. It had no authentication at all until
`st.login` shipped in February 2025 — asked for on the 2019 launch thread, filed as an issue
that December. UpGuard (a security vendor, and this is their scan, not ours) reported in
December 2025 that they found **14,995 unique IP addresses** running Streamlit and *"well over
ten thousand Streamlit applications granting access to the public"*, including call-performance
data for Verizon brands, which they disclosed.

Streamlit also collects usage statistics by default: `browser.gatherUsageStats` is `True` in
`config.py` on `develop` today, seven years after the launch thread asked for it to be opt-in.
Posit makes the GDPR argument against that; they are a competitor and say so.

**A frontage app is a directory of static files.** No process, no session, no socket, no
telemetry, nothing listening. It cannot be left unauthenticated because there is nothing to
authenticate to, and it cannot leak a dashboard because the dashboard is the visitor's own
browser. Where an app does need private data, the data stays on whatever already serves it and
the page is a client like any other.

That is a difference of kind rather than degree, and it is worth saying plainly in the
documentation, because the people who feel it most are exactly the ones with data worth
protecting.

## 3. Where frontage stands today

**Ahead**: boot (52 ms against tens of seconds), size, no server, fine-grained updates,
prerendering, a real router, static hosting. A dev loop that swaps a module into a running page.

**Behind, and this is the whole gap**: Streamlit ships about **115** public `st.*` commands.
Frontage ships nine form controls. There is no chart, no table, no map, no metric, no layout
primitive, no file uploader. An app that shows data has nothing to show it with.

The gap is smaller than 115 sounds, and this is the number that should decide how much effort
this is worth:

| bucket | count | what it costs us |
|---|---|---|
| plain HTML — text, inputs, layout, status, media | ~52 | time only, no dependency |
| one small library each — charts, table, map | ~12 | under 400 KB for all three |
| the scientific stack — `pyplot`, `pydeck_chart`, pandas input contracts | ~6 | out of scope (§8) |
| a server by construction — `secrets`, `connection`, `login`, cache tied to a process | ~14 | declined, not missing |

**About 56% of Streamlit's surface is reachable for well under 400 KB**, and nearly half of
that is plain HTML we simply have not written. The rest is not a backlog; it is two deliberate
constraints.

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

**The second rule, from §2b**: a component may not phone home. No telemetry, default or
otherwise. A static site that quietly makes requests is the one way to give away the property
that section describes.

## 5. `frontage-component`: the protocol

`examples/chart/` works but wires everything by hand — vendored `.js` beside the app, a
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

**The component author's contract**, which `examples/chart/plot.py` already demonstrates: a `NodeRef` for
the element the library owns, an `Effect` that redraws when its data accessor changes, and an
`on_cleanup` that lets the library go. Twenty lines. Compare Streamlit's component model,
which is a React project, a build step, an iframe and a bidirectional message protocol.

**Where it lives**: the protocol belongs in frontage, because `build` implements it. The
components belong in their own repository — they carry third-party dependencies and release on
their own cadence. One repository with a package per component, following the chapter-repo
convention already used for the academy.

## 6. What to build, in order

Ordered by how much of Streamlit's gallery each unlocks per kilobyte. The gallery divides
cleanly: its top third is dashboards over data, which is ours to take; the rest needs a model
runtime or a server, and §8 says why we let those go.

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

- **Signal processing.** The research turned up the concrete first case: the gallery's
  **GW Quickview**, which plots gravitational-wave spectrograms, is blocked only by `scipy.signal`
  and `gwpy` — the FFT and filtering *are* the app. One Rust module taking a buffer and
  returning a spectrogram is the whole port, and it is precisely the shape the crossing cost
  rewards. It is also the most impressive thing on the list to be able to say we run with no
  server at all.
- **Aggregation and filtering over columnar data.** Hand a Rust module an Arrow buffer once,
  then ask it coarse questions — group by, rolling mean, quantiles, resample. One call in, one
  small answer out. Exactly what Streamlit does with pandas on a server.
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
  Two whole gallery categories go with it, and it is more honest to name them than to pretend
  they are coming. **LLM chat apps** — the fastest-growing category — are blocked not by
  compute but by the API key: calling a model provider from the browser exposes it, and hiding
  it is exactly what Streamlit's server does. **Database-backed dashboards** are blocked
  because a browser has no raw sockets. Both are reachable only through an HTTP API someone
  else runs, which is a fine thing to document and a dishonest thing to claim.
- **Model inference.** Face-GAN, YOLO and the image-model explorers need TensorFlow or PyTorch
  and 100 MB to 1 GB of weights. ONNX Runtime Web is the only path and the download dominates
  regardless. Not a framework gap.

## 9. What would make this real

The order matters more than the dates.

| step | why it is first |
|---|---|
| the `frontage-component` protocol in `build` | nothing else can ship as a package until it exists |
| `frontage-chart` and `frontage-layout` | the smallest pair that makes a credible dashboard |
| a gallery of three rebuilt Streamlit apps, with the numbers beside each | the claim in §1 is only worth what it is demonstrated on. The research names the honest targets: **Uber NYC Pickups** (needs the map component; its 180 MB CSV becomes a sliced Parquet), a **filter-and-chart dashboard** (which `examples/chart/` almost is already), and **GW Quickview** once the DSP module exists |
| `frontage-table` | the second thing every data app reaches for |
| the `frontage-wasm` template | the differentiator, once there is an audience for it |

The gallery is the marketing and the test suite at once. Pick apps that are honest matches —
dashboards over data a browser can hold — and publish the download size and cold start next to
each, because those are the numbers Streamlit cannot answer.
