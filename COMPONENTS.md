# Beating Streamlit: the component strategy

**Status: a plan, 2026-09-07. The numbers in §1 are measured, and the thing they were measured
on is committed: `examples/chart/`, with a browser test. Everything from §4 on is unbuilt.**

Streamlit owns "a Python developer wants a data app by Friday". This document is about taking
that, and it argues the way in is not to copy Streamlit's surface but to attack the one thing
it cannot fix: its architecture puts Python on a server, and every attempt to move it into the
browser has been an attempt to carry the server along.

## 0. The four findings, if you read nothing else

**The job is smaller than it looks.** Streamlit ships about 115 public commands. But 52 are
plain HTML with no dependency and 12 more are one small library each, so **about 56% of the
surface is reachable for well under 400 KB** — and nearly half of that is markup nobody has
written yet. The remaining 44% is roughly 6 that want the scientific stack and 14 that want a
server. Constraints we chose, not a backlog (§3, §8).

**The case for Rust is concrete now, not hypothetical.** The rule is to reach for it only where
the work is bulk computation behind a coarse boundary, and the gallery supplies the example:
**GW Quickview** plots gravitational-wave spectrograms and is blocked *only* by `scipy.signal`
and `gwpy`. The FFT and the filtering are the app. One module, a buffer in, a spectrogram out —
the exact shape a 1.00 µs crossing rewards, and the most impressive thing on the list to run
with no server at all (§7).

**The strongest argument is one we had not thought to make.** A Streamlit app is a process
holding sessions, and it had no authentication until February 2025 — asked for on the 2019
launch thread. A security vendor's scan in December 2025 found 14,995 addresses running it and
well over ten thousand apps open to the public, Verizon call data among them. It still collects
usage statistics by default. **A frontage app is a directory of static files**: no process, no
session, nothing listening. It cannot be left unauthenticated because there is nothing to
authenticate to. That is a difference of kind, and it gives the component protocol its second
rule — a component may never phone home (§2b).

**And what we let go is named rather than left silent.** Model-inference demos need 100 MB to
1 GB of weights. LLM chat apps are blocked by the API key, not by compute. Both are real
limits. But the third one I had wrong: database dashboards are *not* out of reach, and it is
not even a procurement question, because Optersoft already has both halves. **Supabase** puts
row-level security between the browser and the data and pushes changes over Realtime, which
answers Streamlit's live-dashboard case without a server of ours. **Turso Cloud** puts the
database *in the page*, which buys offline-first apps Streamlit cannot build at any price (§7b).

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
| a map | +46 KB | Leaflet: points, popups, and a viewport the app reads |
| a rich chart | +~100 KB | ECharts tree-shaken: pie, radar, sankey, heatmap, gauge |
| analytics | +7.0 MB | DuckDB-wasm: SQL over Parquet, multi-GB, opt-in |

A dashboard with charts and a grid lands near 800 KB and boots in well under a second. Only an
app that genuinely wants SQL over a Parquet file pays the 7 MB.

That last figure is measured and it is **more than double what this document estimated**, which
is the second time an estimate here has been wrong in the same direction — see the map row. The
correction matters because 7 MB is not "a heavier tier", it is eleven times the entire
framework, and it changes when the answer is right rather than merely available. §6 item 8 says
where that leaves it.

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

**✅ Built, 2026-09-07.** `frontage build` discovers components by entry point, copies each
`_browser/` beside the runtime, merges a `data-fr-js` declaration into the boot tag (author's
entries win), links a stylesheet if there is one, and packs the component's Python under its
package path so `import frontage_chart` resolves in the page. `--component NAME=PATH` uses one
before it is published, which is how you develop one. A browser test builds an app against a
package laid out exactly as a published one would be and asserts the chart draws and stays
reactive. It took an afternoon, not a week, because the three pieces it rests on were already
there.

Two dev-server bugs fell out of it, both the same mistake: serving a *built* directory,
`frontage serve` was synthesising `app.tar` and intercepting `_frontage/` sub-paths, so it
served a different app than `build` produced. Disk now wins over synthesis; synthesis is what
happens when there is nothing built, which is the dev loop.

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

1. ✅ **`frontage-chart`** (uPlot). Line, area, bar, scatter. Covers `st.line_chart`,
   `st.area_chart`, `st.bar_chart`, `st.scatter_chart` — the majority of gallery apps.
   Built 2026-09-07 in `~/optersoft/frontage-component`.
2. ✅ **`frontage-table`**. A virtualised grid over a list of dicts: sort, filter, column
   formatting. This is `st.dataframe`, and it is the element most reached for after a chart.
   Built 2026-09-07 in **pure Python, no JavaScript** — virtualisation is a memo over a scroll
   signal, which is what a fine-grained framework is for. 50,000 rows: **235 ms cold, 623 KB,
   21 row elements in the DOM**.
3. ✅ **`frontage-layout`**. `columns`, `tabs`, `expander`, `container`, `metric`, `progress`,
   `spinner`, `divider`. Pure Python and 2.5 KB of CSS, no dependency, and it is what makes an
   app look like an app. Built 2026-09-07. A dashboard on these two: **78 ms to drawn, 730 KB
   over 12 requests**.
4. ✅ **`frontage-map`**. `st.map`'s job, plus the part Streamlit cannot do: `on_move` reports
   the viewport back as state, so a table, a count and a chart follow the map as it is panned,
   with no rerun. Built 2026-09-07. **On Leaflet, not MapLibre**, which is a correction to this
   document's own estimate above: MapLibre measures **275 KB gzipped**, larger than the whole
   framework, and it buys vector tiles, WebGL styling and 3D — none of which is what a data app
   draws. Leaflet is **42 KB**, the same size as frontage itself, and points on a basemap is its
   entire job. Canvas markers rather than the default icon, so tens of thousands stay
   interactive and **no image is ever requested**. Vector tiles remain available later as a
   separate, heavier component; making it the default would have charged every map six times
   over for a feature most never use.

   It is also **the one component that touches the network at runtime**, because a basemap comes
   from a tile server. That is the caller's request rather than a phone-home, the provider is
   theirs to name, and `tiles=None` draws the points on a plain background and asks for nothing
   — so an air-gapped app is still possible. The rule in the components README was amended to
   say *uninvited*, and no other component may reach the network at all.
4b. ✅ **`frontage-schema`**. Out of order, because it is not a Streamlit element at all: it is
   the thing every form and every `fetch` was missing. A schema is a tree of types with fields
   as pairs (`record(("name", text(min=1)), ("email", email()), ("age", optional(integer()), None))`),
   `validate` returns the value and a list of `(path, message)` pairs, `coerce=True` reads a
   form's strings, `sample=N` checks a big array's two ends, and `Form(User)` gives a field a
   signal and a message that waits until the visitor has typed. Built 2026-09-07, pure Python,
   no JavaScript. **Pydantic stays on CPython** — MicroPython keeps no `__annotations__` — and
   crosses as JSON Schema, compiled by the `frontage-schema` command; `justrach/dhi` was
   measured and rejected (TODO). Walking a value costs ten times its `json.loads`, 13 µs a row.
5. **`frontage-echarts`**. Pie, radar, sankey, heatmap, gauge, treemap — the long tail, behind
   one bigger dependency that only apps needing it pay for.
6. **`frontage-supabase`**. A `Resource` per table, typed filters, errors that say when
   row-level security refused rather than when the network did, and **Realtime as a signal** —
   the database pushes, one chart redraws. Because Supabase's data API is PostgREST, the same
   component serves a self-hosted PostgREST by changing a URL. §7b: this is what turns
   "internal tool over a database" from out of reach into ordinary, and the academy teaches
   both halves already.
7. **`frontage-turso`**. The database in the page: OPFS persistence, sync to Turso Cloud, and
   therefore **offline-first data apps**, which is a category Streamlit cannot enter. 3.6 MB
   gzipped, opt-in, on the engine the fleet already runs.
8. **`frontage-data`** (DuckDB-wasm). SQL over Parquet and CSV, in the browser, over files the
   user drops in. This is the one that goes somewhere Streamlit cannot follow without a server.
   **Not started, and it should not be next.** Measured on the newest stable release, 1.32.0,
   in the shape an app actually ships — feature-detect, then fetch one engine:

   | | raw | transferred |
   |---|---|---|
   | `duckdb-eh.wasm` | 34.2 MB | **6.76 MB** |
   | `duckdb-browser-eh.worker.js` | 773 KB | 189 KB |
   | `duckdb-browser.mjs` | 32 KB | 8.5 KB |

   About **7.0 MB**, against this document's earlier guess of 3.2 MB. The older `mvp` build,
   for browsers without wasm exception handling, is 7.7 MB on its own; ship both unconditionally
   and it is 14.6 MB.

   Three things follow. First, it is **eleven times the whole framework**, so it is not a
   component a dashboard adds casually — it is the entire point of the app or it is the wrong
   tool. Second, **threading needs cross-origin isolation**: `frontage serve` already sends
   `Cross-Origin-Opener-Policy: same-origin` and `Cross-Origin-Embedder-Policy: require-corp`
   (`cli/serve.py:361`), but a static host does not, so a component that is fast in development
   and single-threaded on GitLab Pages would be a trap unless the docs say so first. Third, the
   §7b answers — PostgREST/Supabase, and Turso at 3.6 MB — already cover the data cases that
   have a database behind them, at a fraction of the cost.

   What is genuinely only DuckDB's: a Parquet or CSV file the user drags in, queried locally,
   with nothing uploaded anywhere. That is a real and defensible niche. It is a worse first
   answer to "how does a frontage app get data" than either §7b option, which is why it is
   last on this list rather than first.

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

## 7b. When an app does need a server, which one

I wrote earlier that database dashboards were out of reach because a browser has no raw
sockets. That is true about sockets and wrong about the conclusion, and the correction matters
because "internal tool over a database" is a large share of what Streamlit is used for.

**The short answer is that Optersoft already owns both halves, so this is not a procurement
decision: Supabase for hosted data, Turso Cloud for offline-first.** The rest of this section
is why, and why not Neon.

**For data: PostgREST.** It generates an HTTP API from a Postgres schema, and it is a finished
piece of software you deploy rather than a server you write. A frontage app talks to it with
`Resource` and `fetch`, like any other API.

The important part is not the transport, it is where the authorisation lives. **PostgREST
enforces Postgres row-level security**, so the policy sits in the database next to the data and
applies to every client that ever connects. Compare Streamlit, which holds a connection string
in a process and expects you to write the access control yourself in Python, in an app that had
no authentication at all until 2025. The static-files property of §2b survives intact: nothing
of *ours* is listening, and the boundary is the database's own policy engine rather than an
application we would have to keep correct.

Optersoft already teaches this. The academy's module 0486, *Accés a dades*, has a PostgREST
chapter at `data/postgres/postgrest` and covers Supabase — which is PostgREST with
authentication and realtime bolted on — so the pairing has teaching material before it has
users. A `frontage-postgrest` component (typed queries, a `Resource` per table, RLS-aware
errors) is a strong candidate for the catalogue in §6.

**Supabase is PostgREST with the missing halves attached, and we have it.** Its data API *is*
PostgREST, so one frontage component serves both: point it at a self-hosted PostgREST or at a
Supabase project and nothing above the transport changes. What Supabase adds is exactly what a
browser-only app needs and PostgREST alone does not provide — an authentication service that
issues the JWT, and Realtime.

**Realtime is the part worth dwelling on**, because it answers Streamlit's live-dashboard case
outright. Streamlit's answer to changing data is to re-run the script, on a timer if need be.
With Supabase the database pushes over a websocket, one signal takes the value, and one chart
redraws. No server of ours, no polling, and the fine-grained graph doing what it was built for.

The client is 0.64 MB unpacked. And the teaching material is not thin: **Supabase appears in 48
academy files**, with sections of its own under `cloud/` and `kotlin/`, and
`data/postgres/row-level-security` is a chapter referenced across the curriculum. The concept
this whole section rests on is already taught.

**Neon: no.** Technically fine — Neon RLS with `pg_session_jwt` supports apps that are, in
their words, *"entirely client-side, without needing a server or backend"*, and the driver is a
0.43 MB package. But it solves what Supabase already solves here, adds a third vendor, and
still needs a separate auth provider (Clerk, Auth0) to issue the JWT that Supabase issues
itself. Worth revisiting only if an app needs Postgres branching or scale-to-zero badly enough
to pay for the extra moving part.

**One caution common to every option above**, and it is the way this goes wrong quietly: the
connection role must not hold `BYPASSRLS`. Neon documents it plainly, and it applies equally to
Supabase's service key, which bypasses row-level security by design and must never reach a
browser. The anonymous key is the one that ships.

**Turso is a different answer, and the interesting one.** Not "reach a database over HTTP" but
*put the database in the page*. `@tursodatabase/database-wasm` is SQLite compiled to
WebAssembly with OPFS persistence, and `@tursodatabase/sync-wasm` adds push/pull against Turso
Cloud. Measured from the published package rather than npm's headline figure, which counts
every variant:

| | raw | gzipped |
|---|---|---|
| `turso.wasm32-wasi.wasm` | 11.07 MB | **3.61 MB** |

Opt-in tier-three cost, in the same bracket as DuckDB-wasm's ~3.2 MB, and it buys something
neither of the options above can: **the app keeps working with no network, remembers between
visits, and syncs when it can.** Streamlit cannot enter that category at all — a Streamlit app
is a websocket to a process, so no network means no app. stlite is offline-capable but has no
persistence or sync story and costs ~13 MB before app code.

**And we already run this engine.** `optersoft/turso` wraps the same Rust rewrite, pinned at
`>=0.7.0, <0.8`; the browser package is 0.7.2. The same generation, so the same SQL semantics
and the same hard-won list of gotchas in the `turso` skill — the immature query planner, rowid
reuse after a delete, foreign keys off by default — apply unchanged. That is institutional
knowledge nobody else competing here has. ⚠ It cuts both ways: our own README calls turso
*"SQLite-compatible SQL, alpha-grade engine"* and the browser package is marked BETA. Fine for
a component behind an opt-in dependency; not fine as the default anything.

**For secrets: a Cloudflare Worker.** The one thing a browser genuinely cannot do is hold an
API key. An LLM chat app needs perhaps twenty lines in front of it that add the key and forward
the request. The site already deploys to Cloudflare Pages, so a Pages Function is the
path of least resistance and costs nothing at this scale.

**The framework does not write that server or know of it.** Both answers above are
off-the-shelf things an app points at, and `frontage build` writes a directory of static files
whichever one it is; that is the whole point.

**One case the answers above do not cover, and a component does (2026-09-07): the dataset is
too big to ship and the transform is Python, not SQL.** That is `frontage-polars`, in the
component repo: an author registers ordinary functions that return a polars frame behind a
FastAPI router, the page asks for them by name with parameters from its signals, and what
comes back is an aggregate as columns or one window of rows — never the frame. Nothing the
browser sends is evaluated, a result past a cap answers 413, and push is a Server-Sent Events
stream rather than a WebSocket, because a session per client is Streamlit's model and the
reason to avoid one has not changed. The server half is an extra (`[server]`) the page never
imports; the browser half is 0.6 KB of JavaScript. It is a *component's* server, opt-in, the
way `frontage-turso` would be a component's database — the framework still ships none.

## 8. What we will not do

- **Chase the scientific stack.** No pandas, no scikit-learn, no matplotlib. Wanting those
  means wanting Pyodide, which means 13.8 MB before app code, and stlite already occupies that
  position. Say so plainly in the docs rather than half-supporting it.
- **Copy `st.*` names.** Frontage is reactive; Streamlit is a re-run. An API that looks the
  same but behaves differently is worse than one that looks different.
- **A server in the framework.** The constraint that produced the 96 ms boot is the
  constraint that says no. A *component* may ship an opt-in server half — `frontage-polars`
  does, §7b — but the framework knows of none, and a page built without one is still a
  directory of static files. Two whole gallery categories still go with the rule, and it is
  more honest to name them than to pretend they are coming. **LLM chat apps** — the fastest-growing category — are blocked not by
  compute but by the API key: calling a model provider from the browser exposes it, and hiding
  it is exactly what Streamlit's server does — see §7b, which says what to put there instead.
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
