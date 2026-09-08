# Faster than React: the 0.10 plan, and the evidence for it

**Status: a plan, 2026-09-08. Everything in §1–§4 is measured — on the committed examples, on
the pinned interpreter, and on seven custom builds of MicroPython made for this document
(`ports/webassembly`, master at `v1.30.0-preview-59`, whose stock PyScript variant rebuilds to
443,772 bytes against the shipped 446,411). §5 onward is unbuilt. This supersedes
`BUNDLE.md` (folded in as §5–§7) and the three-release order it proposed: everything here
ships as one release, 0.10.0.**

The goal is not "a Python framework that is not embarrassing". It is a framework that a
JavaScript developer would choose on its numbers: smaller and faster to first paint than
the Rust ones, as fast as Solid on updates, within reach of React on construction, with a
dev loop that keeps state across an edit. C and WebAssembly are what make that possible,
and the whole argument of this document is that the slow part of frontage was never the
browser, the bridge or the wasm: it is Python executing the framework's own code, and that
code can stop being Python without the app author noticing.

## 0. The decision, in five sentences

**One distribution**: the components become subpackages of `frontage`, no more `frontage-*`
projects on PyPI, server halves are extras. **A page ships the closure of what it imports**,
as bytecode, in content-hashed chunks, and a route can load on demand the way React
Router's `lazy` does. **The interpreter is ours to build**: a `frontage` variant of the
MicroPython wasm port is 36% smaller over the wire and **almost five times faster on a
Python call** than the upstream build, because upstream never optimises at link time,
implements every Python exception through JavaScript longjmp trampolines instead of wasm's
own exception handling, and freezes 27 library packages the framework does not import. **The framework's hot path moves into C inside that
build** — signals, effects, owners, template holes, keyed lists — while the API and every
app stay ordinary Python, because a call inside C is free and a C call into a Python closure
costs a tenth of the same call made from Python. **The dev server keeps state across a
swap**, and a devtools panel shows the reactive graph, because those are the two things a
React developer would miss first.

## 1. Where the time and the bytes go today, measured

**Bytes.** Every gallery page ships 642 KB before its own code; 270 KB over the wire:

| file | raw | gzip | brotli |
|---|---|---|---|
| `micropython.wasm` (upstream 1.28.0-6) | 446,411 | 195,812 | 169,788 |
| `micropython.mjs` | 108,321 | 30,386 | — |
| `frontage.tar` (17 modules, 63,934 bytes of `.mpy`) | 81,920 | 41,134 | — |
| `boot.js` | 6,050 | 2,810 | — |

The framework is imported whole (`__init__.py` pulls twelve of seventeen modules) and
shipped whole; a typical example reaches 8 modules and 43 KB of the 64. App code ships as
source and is parsed at boot (`tracker.py` is 12,765 bytes of source, 6,600 of bytecode).
A component ships whole when imported at all, and `examples/uber` puts Leaflet and 133 KB
of data on the first paint of every page because nothing can be deferred.

**Time.** From `DESIGN.md` §12 and the js-framework-benchmark table the Rust research
pulled (Chrome 152, 2026-09-01, medians, ms):

| | vanilla | Solid | React 19 | Leptos 0.7 | Dioxus 0.7 | **frontage 0.9** |
|---|---|---|---|---|---|---|
| wire size (brotli) | 2.5 K | 4.5 K | 51.4 K | 48.8 K | 114.9 K | **~235 K** |
| first paint | 52.7 | 47.3 | 221.4 | 231.2 | 525.8 | **52–72** |
| create 1,000 rows | 20.6 | 21.4 | 23.7 | 25.1 | 24.2 | **171** (no paint) |
| partial update | 9.8 | 10.3 | 14.0 | 11.2 | 11.7 | 3.3 (no throttle) |
| swap two rows | 10.9 | 12.6 | 89.9 | 12.0 | 14.4 | 16–18 (no throttle) |

The benchmark's own breakdown says what "create" is made of: of vanilla's 24.9 ms total in
the 2025 run, **1.6 ms is script** and the rest is the browser's layout and paint, which no
framework avoids; React's script share is 6.9 ms, Solid's 2.4, Leptos's 7.2, Dioxus's 6.0.
So "faster than React on construction" means **the framework's own work for 1,000 rows in
under 7 ms** — about 7 µs a row, all in. React's real weakness is swap (113 ms in that
run, its own paint storm), where frontage's 16 ms already wins.

Two things are already true. Frontage's first paint beats every Rust framework by 3–8×
and matches Solid, because one wasm file streams and compiles while the Rust ones link
hundreds of KB of monomorphised code. And updates are competitive, because the reactive
graph is fine-grained. The one number that is not is construction: **171 ms against 24**.

**And that number is Python, not the browser.** `DESIGN.md` §12 measured it with a null
renderer: 124 of 160 ms are Python execution, ~330 calls per row at 0.2–0.25 µs each. This
document adds the two measurements that decide where those calls go:

*The app author's share is under a millisecond.* Under node on the pinned interpreter,
evaluating the row's t-string 1,000 times costs 0.36 ms; creating the two accessor closures
per row, 0.17 ms. Everything else in the 124 ms is the framework calling itself.

*The bridge is cheap.* In Chromium, building 1,000 rows of the benchmark's markup:

| | ms |
|---|---|
| JavaScript, `createElement` per node (the floor) | 1.10 |
| MicroPython, one FFI call per DOM operation (13 per row, 13,000 crossings) | 6.20 |
| MicroPython, the same operations encoded in a buffer, one crossing | 3.70 |

Thirteen thousand crossings cost five milliseconds. Batching them into one saves two and a
half, and most of what is left is Python building the buffer. The Rust frameworks reach
vanilla speed with very different bridges (Dioxus batches, Leptos does not); the bridge was
never the lever here either.

So the target is the framework's Python. Two ways to make it cheaper: make every call
cheaper (§2), and make most of them disappear (§3).

## 2. The interpreter: a frontage build of MicroPython

Every page pays for the interpreter, so it was worth building it ourselves and measuring.
Two rounds of custom builds of `ports/webassembly` in `emscripten/emsdk` in Docker (the port
builds in seconds at `-j10`; `make submodules` first), timed under node with the same
micro-benchmarks in the same run, and checked by importing the framework and running a
signal, a memo, an effect and a render on each. The first round, on master at
`v1.30.0-preview-59`, found the link and the frozen library; the second, on `v1.28.0`
proper, found the exception mechanism, and its best build was then verified in Chromium
against the browser suite.

| build | wasm raw | gzip | brotli | glue gzip | µs per Python call | µs per method call |
|---|---|---|---|---|---|---|
| upstream, the `pyscript` variant | 443,772 | 194,882 | 168,815 | 30,386 | 0.248 | 0.295 |
| frozen library cut to `asyncio` | 388,236 | 160,472 | 138,408 | | 0.255 | 0.303 |
| + `-Oz` at compile **and link** | 309,982 | 145,040 | 124,794 | 26,192 | 0.152 | 0.194 |
| + eleven unused C modules off | 274,868 | 126,831 | 109,912 | 26,192 | 0.152 | 0.195 |
| `-O3`, library cut, modules off | 294,701 | 134,104 | 115,830 | 26,379 | 0.132 | 0.174 |
| **lean + `SUPPORT_LONGJMP=wasm`, `-Os`/`-Oz` (the one)** | **265,620** | **124,706** | **107,977** | 25,005 | **0.052** | **0.070** |

The last row is the whole story. Same run, upstream against it: a Python call 0.248 →
0.052 µs (4.8×), a method call 0.295 → 0.070 (4.2×), an object 0.399 → 0.129 (3.1×), the
row t-string 0.43 → 0.20; the interpreter report's own suite adds 3.8× on raise/catch and
2.8× on generators. And it is the smallest binary of the set.

What the table says:

- **Upstream's exceptions go through JavaScript.** The port links with
  `SUPPORT_LONGJMP=emscripten`: MicroPython's `nlr` is `setjmp`/`longjmp`, so every call out
  of a function that contains a `setjmp` — the bytecode loop, every `nlr_push` site — goes
  through a JavaScript `invoke_*` trampoline, and the binary carries eleven of them as
  imports. `SUPPORT_LONGJMP=wasm` uses wasm's own exception handling instead: **3–5× on
  every call the interpreter makes**, a smaller binary, and it is one flag at compile and
  link. Its floor is Safari 15.2, Chrome 95, Firefox 100 — below Vite's own baseline
  (Safari 16.4). It is also what a Rust static library linked into the build needs, since
  Rust has emitted wasm exceptions by default since December 2025.
- **Upstream never optimises at link time.** The Makefile sets `-Os` on the C compile and
  nothing on the link, so Binaryen never runs over the whole program and `ASSERTIONS` stays
  on. An optimisation level in `LDFLAGS` alone makes the interpreter smaller and 1.6× faster
  on a call; with wasm exceptions in place, `-O2`/`-O3` on top buys nothing measurable and
  costs 20 KB, so the build is `-Os` compile, `-Oz` link.
- **The frozen library is 35 KB of gzip nobody imports.** The `pyscript` variant freezes 27
  packages from micropython-lib (`unittest`, `tarfile`, `logging`, `datetime`, `pathlib`, …).
  The framework imports `sys`, `asyncio`, `js`, `jsffi`, `json`, `io`; the components add
  `struct`, `re`, `math`, `array` (their `datetime`, `decimal`, `inspect` and `collections`
  imports are all in `_server.py`, the CPython half); nothing imports the rest. They
  live in the data section, which is why `wasm-opt -Oz` on the shipped binary saves 53 KB
  raw and only 4 KB gzipped: post-processing cannot remove data, only a build can.
- **Nothing else in the flags is a lever.** Computed goto is a no-op in wasm (the binary
  differs by 8 bytes; every dispatch is a `br_table`); the map lookup cache and the
  attribute fast path are already on at this ROM level; `-flto` grows the binary; and the
  GC knobs (`gc.threshold`, heap size) do nothing here because in this port a collection
  only runs when control returns to JavaScript — inside one synchronous run the heap just
  grows, in 128 MiB splits. That last fact also explains why trimming allocations never
  measured (`DESIGN.md` §12): there are no GC pauses inside a create.
- **Eleven C modules off** (`help`, `hashlib`, `cryptolib`, `deflate`, `uctypes`, `framebuf`,
  the special math functions, the extra random functions, `heapq`, `platform`, complex
  numbers) are 20 KB of gzip. `binascii` stays (an example uses it); `re` and `json` stay.
- **The glue drops from 30 to 25 KB gzip** with the link optimised and `-sENVIRONMENT=web`,
  and to **17 KB gzip / 15 KB brotli** with terser's `--mangle --toplevel`, which upstream
  does not run. `--closure 1` breaks the port's post-link `cat` of its JS files and would
  need them moved to `--post-js` for little beyond what mangling gives; skip it.
- **Brotli, not gzip**, and Cloudflare Pages already compresses `application/wasm` at the
  edge (Brotli on paid plans, zstd on Free), so nothing needs pre-compressing there; a
  `.wasm.br` beside the file cannot even be expressed in `_headers`. The prod check is one
  `curl -I` for `content-encoding`. The site's numbers should be quoted in brotli.

So the floor moves from **226 KB gzip of interpreter to 142 KB**, and from 196 KB brotli to
**123 KB**, and every Python call the framework still makes runs four to five times faster.
The C module probe in §3 was built into the first-round variant (`fr-h`, 295,123 bytes): a
C module costs nothing measurable.

**On the real page**, `tools/profile_rows.py` in Chromium, the committed framework
unchanged, upstream interpreter against the chosen build:

| phase (ms) | upstream | lean, wasm exceptions |
|---|---|---|
| method call, per 10,000 | 2.3 | 0.8 |
| 1,000 row trees, no renderer | 18.9 | 8.7 |
| `For` of 1,000, null renderer | 102.4 | 44.0 |
| **`For` of 1,000, DOM, templates (the create)** | **139.1** | **71.1** |
| swap two rows | 12.1 | 4.4 |
| update every tenth row | 3.3 | 1.4 |
| 1,000 effects created and disposed | 12.9 | 4.8 |
| 1,000 text holes, null renderer | 16.2 | 6.6 |

A create halves and a swap drops to a third — React's swap is 90–113 ms — before a line of
the framework changes. The one calibration that did not move, an `isinstance` against a
tuple that misses (24.8 → 24.6 ms per 10,000), is C-side subclass walking, and the hot
paths already avoid it. Note what the faster interpreter exposes: the null-renderer create
is 44 ms and the DOM one 71, so **27 ms is now the DOM side** — the bridge, and a
JavaScript proxy allocated for every one of the 11,000 nodes Python holds. §4 takes that up.

**A newer upstream exists**: the npm package is at `1.29.0-6` (2026-08-24) against the pin's
`1.28.0-6`; the variant applies to either. The variant is **out of tree** — `VARIANT_DIR=`
points the port's Makefile at three files in this repository (`mpconfigvariant.h`, `.mk`,
`manifest.py`) — so the checkout is an unmodified upstream tag and there is nothing to fork
or rebase.

**What it costs us**: a `variants/frontage/` directory of two files in a MicroPython
checkout (upstream accepts variants; ours can live in this repository and be applied to a
pinned upstream commit at build time), a `mk runtime.build` that runs the Docker build and
commits the artefacts, and a browser run per bump — the same discipline as the current
pin, plus two minutes. The pinned commit stays upstream's; nothing is forked.

**Verified**: with the chosen build's `micropython.mjs` and `.wasm` swapped into
`frontage/_runtime/`, the browser suite — the examples, hydration, the tracker, the smoke
test, 21 tests — passes unchanged (15 s), and so does it on the first-round `-O3` build.
The lean variant as measured also switches off `re`, `binascii`, `random` and `select`;
`re` and `binascii` go back in for the components and one example (a few KB). The
component repository's browser tests are the remaining run.

## 3. The framework core in C

The Rust frameworks are fast because the framework is compiled code and only the app is
dynamic. MicroPython allows exactly that split: a **user C module** (`USER_C_MODULES`,
`MP_REGISTER_MODULE`) compiled into the interpreter, with types, methods and callbacks into
Python. The probe built for this document — a `Signal` type with `get`, `set`, `__call__`,
a `drive` that calls a Python closure in a loop — measured, same run, `-O3` build:

| operation, 100,000 times | Python | C | ratio |
|---|---|---|---|
| method `.get()` | 0.215 µs | 0.153 µs | 1.4× |
| `__call__` (an accessor read) | 0.177 | 0.102 | 1.7× |
| method `.set()` | 0.312 | 0.151 | 2.1× |
| plain function call | 0.144 | 0.077 | 1.9× |
| object allocation | 0.349 | 0.186 | 1.9× |
| **a loop calling a Python closure** | 0.121 | **0.015** | **8×** |

The first five rows are the cost of the *bytecode loop dispatching a call*, and C halves
it. The last row is the one that matters: **when C is the caller, a Python closure costs
15 ns**, and a call from C to C costs nothing the benchmark can see. The 330 calls a row
costs today are framework calling framework — `_children`, `_build_nodes`, `_normalize`,
`_mount_hole`, `RenderEffect.__init__`, `Owner` bookkeeping, `_mark`, `_flush`. In C those
are function calls at C prices, and the only Python left per row is the author's t-string
(0.36 µs) and the hole accessors the C effect calls (15 ns each).

**Expected**: starting from the 71 ms the interpreter alone gives (§2), of which 44 is
framework Python and 27 the DOM side. User code is under 1 ms per 1,000 rows; the C core
takes the 44 to the low single digits; §4 takes the 27 to the 4–6 ms the op-buffer
measurement showed. That is a script share around **10 ms against React's 6.9, Leptos's 7.2
and Solid's 2.4**, before the browser's layout and paint, which are the same for everyone.
Within reach of React, not promised, and `tools/profile_rows.py` decides. Swaps and updates
are already ahead: 4.4 ms and 1.4 ms on the chosen interpreter against React's 90 and 14.

**The precedent is in this exact port.** The LVGL binding — an entire C UI toolkit exposed
to MicroPython through a generated module, LVGL allocating from MicroPython's GC heap and
keeping Python callables alive in GC-allocated structs — runs under Emscripten in
`ports/webassembly` at sim.lvgl.io, and `ulab` reports 40–50× over pure Python for its
array operations. `py.mk` processes `USER_C_MODULES` for every Make port; the probe above
needed nothing but a directory and a flag.

**What it changes for development**: an edit to the core is a wasm rebuild, two minutes in
Docker, where today it is a page reload. The Python implementation stays the one the tests,
the prerenderer and CPython run, and it stays importable in the browser behind a flag
(§12), so the module-swap loop is untouched for everything that is not the core itself.

**What moves to C, and what does not.**

| in C (`frontage/_core`, one module) | stays Python |
|---|---|
| `Signal`, `Memo`, `Effect`, `RenderEffect`, `Owner`, the two-phase graph, `_mark`/`_flush`, `batch`, cleanup, error routing | `Transition`, `Optimistic`, `spawn`, context, the boundaries — control flow that runs per navigation, not per row |
| `Template` compile/clone, `_mount_hole`, `_reconcile` + `_lis`, `_apply_attrs`, `_children`/`_build_nodes`/`_normalize` | `html(t"…")` parsing (cached per call site), `h`, `Element`/`Text` as the author sees them |
| `For` row ownership and index signals; `Store` proxies over dicts and lists | `Show`, `Switch`, `Loading`, `Errored`, `Portal`, `Dynamic`, the router, `Resource`, `Action`, widgets, `State` |
| the DOM op stream and event delegation (calling `js` from C, or filling the op buffer) | `HtmlRenderer`, `RecordingRenderer`, prerender, hydration's cursor |

The API does not change: `Signal`, `Memo`, `Effect` keep their names and signatures, and
`frontage/reactive.py` becomes `from ._core import Signal, …` with the Python implementation
kept behind it for CPython, where the tests, the prerenderer and the language server run.
**Two implementations of `SPEC.md`'s C-lines, one in C and one in Python, and the same test
suite runs against both** — the Python one under pytest, the C one under node with the
built interpreter — is the guard that keeps them one framework. `RecordingRenderer`'s
operation counts, the property the whole design is measured by, apply to both.

**Why C and not Rust for the core.** The core talks to MicroPython's object model —
`mp_obj_t`, `mp_call_function_n_kw`, GC roots, qstrs — which is a C API, and a MicroPython
C module is a documented, supported shape with `lvgl` and `ulab` as large precedents. Rust
can be linked into the same Emscripten build (`wasm32-unknown-emscripten`, a `staticlib`)
and is the right tool for a *component* that computes in bulk behind a coarse boundary
(`COMPONENTS.md` §7), which it already is; for the core it would be a second FFI around the
first. Effort is not the constraint; two languages around one object model is.

**Why not a separate wasm module for the core.** Two wasm modules have two memories, and
every value between them is copied through JavaScript (the `data-fr-js` rule in
`CLAUDE.md`). The core has to share the interpreter's heap to hold Python objects at all.

## 4. The DOM stream

§1 measured the raw bridge: 13,000 crossings cost 5 ms, an op buffer 2.5 ms less. But the
profile in §2 shows the framework's DOM path costing 27 ms on the fast interpreter, five
times the raw crossings, and the difference is **what Python holds**: a `jsffi` proxy per
node — 11,000 of them for the benchmark — each an allocation on both sides and an entry in
the proxy table, kept alive as long as the element is. The Rust frameworks never hold a DOM
node: Dioxus addresses nodes by a small integer (`ElementId`) in a JavaScript-side array
and the wasm side owns nothing but the number.

So the design, once the core is C:

- **Nodes are integers.** The core allocates ids; `boot.js` keeps `nodes[id]`. Python (and
  C) never hold a proxy for an element the framework created. `NodeRef` and event handlers
  that want the real node ask for it by id, which is the one place a proxy is made.
- **Operations are a byte stream** in wasm memory — sledgehammer's shape: one byte per op,
  tag and attribute names as small integers, strings concatenated and decoded once per
  flush with `TextDecoder`, static strings interned by pointer, a cursor for "the node just
  created" so most ops carry no id at all. One crossing per batch, at the end of a flush.
- **Templates stay, and get cheaper.** Leptos dropped `<template>` cloning and pays
  `createElement` per node; frontage's 11 operations per row against 31 without it is its
  edge. A `For` row becomes one `cloneNode(true)` and a fixed hole walk expressed as ops.
- **Events stay delegated**; a delegated dispatch hands the C core an id and an event, and
  the core finds the handler.

Target for the DOM side: the 4–6 ms of §1, from 27.

**Off the main thread is not for us.** An interpreter in a Worker with the DOM applied on
the main thread (worker-dom, Partytown, neo.mjs) buys responsiveness during long
constructions at the price of every synchronous read — `value`, `getBoundingClientRect`,
focus — and a `postMessage` per event. Once construction is 30 ms there is nothing to hide.
The op buffer keeps the option open at no cost; nothing else should be built for it.

## 5. One distribution

```
frontage/
    reactive.py  view.py  …            the framework's Python (CPython, and the fallback)
    _core/                             the C module: sources, built into the interpreter
    _runtime/                          micropython.{mjs,wasm} — our build — boot.js, the image
    chart/       __init__.py  plot.py       _browser/index.js  uplot.js  index.css
    table/  layout/  map/  schema/  supabase/  remote/   (remote: the polars client)
    cli/  lsp/                              CPython only
```

- **Imports**: `from frontage.chart import line_chart`. React Router 7 folded
  `react-router-dom` into `react-router` with a `react-router/dom` subpath for the same
  reason: with a bundler that ships only what is imported, separate packages were a cost
  with no remaining benefit.
- **Server halves are extras**: `pip install "frontage[polars]"` for `frontage/remote/_server.py`.
  The underscore rule stays.
- **Assets ride in the wheel**, ~240 KB more on a wheel downloaded once per machine.
- **No entry points for our own components**; discovery is the package tree. The
  `frontage.components` entry point and `--component NAME=PATH` stay for third parties.
- **One version**, the one the ten chapter repos already pin.
- **The five published names** (`frontage-layout` 0.1.0, `-chart` 0.1.1, `-table` 0.2.0,
  `-map` 0.1.0, `-polars` 0.2.0) stay frozen at their last version, with no shim release:
  decided 2026-09-08. `schema` and `supabase` never ship under their own names. The
  `frontage-component` repository merges into this one with history.

## 6. The page gets the closure of what it imports

`frontage build` gains an analysis pass on CPython:

1. **Parse, never import**: `ast` over the entry and every module it names, following every
   import form at any depth, into the app, `frontage.*` and third-party components. The
   regex in `required()` goes.
2. **Resolve `from frontage import Signal`** through `frontage/_exports.py`, a table the
   runtime `__getattr__` in `__init__.py` also uses (PEP 562 is verified on this MicroPython
   build), so the build's reading of a name and the interpreter's are one data structure.
   `import frontage` + `frontage.X` resolves the same way; a name the walk cannot attribute
   means the whole package, printed.
3. **Close the graph and pack that set** as `.mpy` (`mpy-cross -O2 -s`), app included.
   Sources are still copied beside `index.html`, readable; the archive boots.
4. **A component's `_browser/` and its `data-fr-js` line and stylesheet** come only when a
   module of it is reached.
5. **Print what was dropped.** `__import__(f"pages.{x}")` is invisible to the walk and fails
   in the browser with a bare `ImportError`; `# frontage: include pages.*` or `--include` is
   the escape hatch, as `import.meta.glob` is for Vite.

Nothing inside a module is removed — Python has no safe dead-code elimination below the
module — so the rule for component authors, ours first, is **one separately useful feature
per module**. `frontage.schema`'s 28 KB `__init__` is the case to fix on the way in.

Measured on the examples: a typical app reaches 8 of 17 framework modules (43 KB of 64);
app code halves when compiled; a component's JavaScript comes along only when reached.

## 7. Chunks: split by route, hashed, preloaded

**Two archives, both content-hashed.** The first plan folded the framework into the app
archive; the bundler research corrected it. Vite's vendor-chunk rule applies: the
framework's reached subset is `frontage.<hash>.tar`, so an app edit never invalidates it,
and the app's closure is `app.<hash>.tar`. `micropython.wasm` and `.mjs` keep a stable,
query-free URL hashed by *their* content, shared across apps on a site, and are loaded with
`instantiateStreaming` so V8's code cache applies (modules over 128 KB, exact URL). The
HTML is the one mutable file (`Cache-Control: no-cache`); everything hashed is `immutable`.
Today `web/_headers` sets no caching at all on `/_frontage/*`.

**`Route("/map", lazy="pages.map")`** — React Router's `lazy`, the same shape because the
shape is what composes:

- **Build**: `pages.map`'s closure minus the main chunk becomes `chunks/pages.map.<hash>.tar`
  with any component only it reaches. A module reached by two chunk roots gets a **shared
  chunk** (Rollup's rule; Python needs it more than JS, because `sys.modules` must hold a
  module exactly once, so duplication is a correctness bug), merged below 20 KB into the
  chunk that loads first (the number webpack, Parcel and Rolldown converged on). Framework
  modules a chunk reaches and the main chunk does not are hoisted into the main chunk: a
  chunk that brought its own `reactive` would be two frameworks in one page.
- **Manifest**: a JSON member inside the main archive (no extra request), Vite's shape —
  `file`, `imports`, `css`, `assets` per chunk — so a chunk's dependencies are fetched in
  parallel rather than discovered one level at a time (Vite's waterfall fix).
- **Runtime**: `frontage.chunks.load(name)` is a coroutine: look the chunk up, fetch it
  through `boot.js`, unpack into `/lib`, `import()` and register its JavaScript, link its
  CSS, `__import__` the Python module, return the named attribute (`view` by default).
  The async boundary is an `await` in Python; there is no import hook to write and
  MicroPython has no `sys.meta_path` to write one into.
- **The router owns the wait**: a lazy route is a preload, `_inflight` counts it,
  `is_routing` stays true, the level renders once the module is in. So `Loading` shows its
  fallback, `Router(transition=True)` keeps the old page until the chunk lands, `A`'s hover
  preload fetches the chunk before the click (SvelteKit's default, honouring
  `navigator.connection.saveData`), and a deep link awaits the chunk under the router's
  `fallback`. Fetch the route's `preload` data concurrently with the chunk, not after it —
  Leptos's `lazy_route` learned that one.
- **Prerender** renders lazy routes synchronously on CPython; hydration is tested, not
  designed: the level is not rendered before its module is, which is what the fences need.
- **`serve`** synthesises chunks from disk; `dev.swap` drops lazy modules and clears the
  loader's memory.
- **Preload hints**: `<link rel="preload" as="fetch" crossorigin>` for the archives and the
  wasm — `modulepreload` is for JavaScript modules, not archives — with the exact URL
  `boot.js` will fetch, so the opaque-origin runner frame matches too.
- **Pre-compressed brotli** beside every hashed file, for hosts that serve it.

`examples/uber` becomes the two-route app it should be, and its card is the proof.

## 8. Development: what a React developer would miss first

**State survives a swap.** Today `dev.swap` disposes every mount and re-runs the entry;
signal values do not survive. Every framework that preserves state does it by an identity
the tooling can name: React Fast Refresh keys hook state by call order and resets on a
signature change; Vue keeps state for a template-only edit and remounts for a script edit;
Svelte turned local-state preservation off by default because it was "hard to anticipate".
The rule for frontage, in the same spirit: **module-level `Signal` and `Store` values are
kept across a swap, by qualified name, when the new module defines the same name with the
same type; anything created inside a component function is rebuilt.** That is Vue's split,
and it covers the case that matters — the counter, the store, the selected row — without
guessing at component-local state. A `# frontage: reset` comment forces a clean run. Route,
scroll and the interpreter already survive.

**A template-only edit patches templates.** Dioxus's first hot reload could change anything
inside `rsx!` without a rebuild and kept every signal, and it is the majority of UI edits.
`html(t"…")` is cached per call site by its tuple of literals; when a swap finds that only
the literals of some call sites changed and the interpolations did not, it can replace the
cached `Template`s and re-clone the affected holes in place, keeping every owner and signal.
This is the second tier of the swap, built after the first.

**An error overlay.** A swap that fails leaves the last working page and a console line;
Vite draws the error on the page. `serve` already injects a script; it should draw the
traceback (`format_exception` exists) with the file and line, and clear it on the next
successful swap.

**A devtools panel.** No Rust framework has a reactive-graph inspector and Leptos has an
open issue asking for one; `reactive.tree()` and `debug.py` already have the hooks. A
`/__frontage/devtools` page in `serve`: the owner tree, signal values, effect run counts,
`RecordingRenderer` operation counts per batch, the hydration report. Cheap, and nobody
else has it.

## 9. What React has that this release does not, and what it will

From the gap analysis (`SPEC.md` against React 19, Solid 1.9, Svelte 5), the list that
matters for the audience, and where each lands:

| gap | in 0.10 | how |
|---|---|---|
| a styled component kit | partly | the merged subpackages, Tailwind-styled versions of the nine widgets; the rest is ongoing |
| lazy routes and code splitting | yes | §7 |
| state-preserving hot reload | yes | §8 |
| devtools | yes | §8 |
| head management (`<title>`, meta) | yes | `Title()`/`Meta()` in `view.py`; `DomRenderer` sets `document.title`, `prerender` hoists into `<head>`; `Route(title=)` |
| view transitions | yes | `Router(transition=True)` already batches the commit; wrap it in `document.startViewTransition` |
| typed props and checked holes | partly | a `frontage.pyi` for the public API; the LSP flags a non-callable in a hole |
| form validation in core | yes | `ActionForm(schema=)` / `Resource(schema=)` over `frontage.schema`, per-field error signals |
| accessibility basics | yes | focus the main region on route commit, an `aria-live` announcer, an LSP rule for `<img>` without `alt` |
| an official Tailwind story for apps | yes | `build --tailwind` scanning t-strings; class completion in the LSP |
| docs and onboarding | yes | a "from React" and a "from Streamlit" chapter; the Components chapter rewritten for one package |
| API stability | no | 1.0 follows this release once it has users |
| streaming SSR, server functions, islands, React Native | no, deliberately | the framework owns no server (`COMPONENTS.md` §8); islands are revisited once download is proportional to reached modules, which §6 makes true |

## 10. The roads not taken, with the number that closed each

- **Pyodide** — 844 ms to boot, 1.5 MB; the case `DESIGN.md` §12 already closed.
- **Compiling Python to JavaScript** (Transcrypt, Brython, Skulpt) — a second semantics for
  ints, exceptions, generators and async, and no t-strings; a framework whose dev and
  production interpreters disagree is the worst thing this project could ship.
- **A statically typed Python compiled to wasm** (SPy, mypyc, Codon) — the right idea for a
  *core*, and what §3 does in C today with a stable, supported toolchain. SPy (Cuni,
  Anaconda, full-time) is the one to watch: 100–200× CPython on numeric demos, but its
  author's own status is "super early stage, not even alpha", its `dynamic` type works in
  the interpreter and not the compiler, closures only at compile time, its objects are not
  `mp_obj_t`, and the compile needs clang, so never in the browser. The core is exactly the
  dynamic part — a closure per hole, user callables, exceptions to boundaries — which is
  what it compiles least today. Revisit in 2027 with a one-day probe of a `Signal` in
  `.spy`. Its wasm exports are plain functions, though, so it is already a candidate
  *library* language for `data-fr-js`, beside C and Rust. mypyc and Cython target CPython's C API; Codon's wasm issue has been open since
  2022 with no reply; Nuitka/py2wasm carry CPython inside and are multi-megabyte.
- **Another interpreter.** pocketpy claims parity with CPython 3.9 on x86-64 and is 2–5×
  slower on 32-bit targets, which wasm32 is; its wasm is 480–770 KB (220–240 KB gzip, two measurements), it has no
  `jsffi`, no `async`/`await` in its lexer, no t-strings, and no `finally`, descriptors or
  multiple inheritance. Brython has t-strings and async, at 1.35 MB and 2.5–8.5× slower than
  CPython by its own page; RustPython's wasm demo is 25 MB gzipped. RustPython's JIT cannot run in wasm. Neither moves the floor of §2.
- **Rust linked into the same wasm** — Pyodide proves it links and shows the tax: nightly
  Rust with `-Z emscripten-wasm-eh` and `-Zbuild-std`, an Emscripten version matched to the
  host build exactly, and a hand-written `unsafe` FFI over `mp_obj_t` and `nlr`, because
  there is no PyO3 for MicroPython. It pays the C API's cost and adds a toolchain.
- **`wasm-opt` on the upstream binary** — 53 KB raw, 4 KB gzipped; the size is data, not code.
- **A Worker** — §4.
- **Symbol-level tree shaking** — §6: not safe in Python, and no bundler does it for
  dynamic code either.
- **wasm-split of the interpreter itself** — Emscripten's profile-guided splitting moves
  never-executed functions to a second module; on a 295 KB interpreter whose functions are
  the bytecode VM it would defer error paths and the compiler, and the compiler is needed
  at boot for any app that ships source. A measurement for later, not a plan.

## 11. The release: 0.10.0, everything, in dependency order

Each step has a gate; the gallery cards and `tools/profile_rows.py` are the judges.

1. **The interpreter** (§2): the out-of-tree variant + `mk runtime.build` through Docker,
   on upstream `1.29.0-6`; the suite green on it (it is, on the measured build); commit the
   artefacts; gallery re-measured. Expected on every card: ~85 KB gzip / 73 KB brotli less
   on the wire, a create halved, boot no slower. This step alone is a release's worth.
2. **The core in C** (§3): `frontage/_core`, the reactive graph first (the smallest surface
   with the biggest per-row share), then holes and templates, then `For` and `Store`;
   `reactive.py` re-exports it in the browser; the SPEC tests run under node against it.
   Gate: create 1,000 rows under 20 ms in `profile_rows` (from 71 on the new interpreter
   and 139 today), swap and update no worse than 4.4 and 1.4 ms.
3. **One distribution** (§5): the merge, the subpackages, the extras, the shims, the chapter
   rewrite, the ten chapter repos.
4. **The closure and the chunks** (§6, §7): `_exports.py`, the lazy `__init__`, the `ast`
   walk, bytecode for apps, the two hashed archives, the manifest, `Route(lazy=)`, the
   loader, hover prefetch, preload hints, brotli, `_headers`; `serve` and `swap` follow;
   prerender + hydration of a lazy route under test; `uber` split.
5. **Development** (§8): state across a swap, the error overlay, devtools, then the
   template-only patch.
6. **The React gaps marked "yes" in §9**, each small, each with a chapter line.
7. **Release**: `version.py`, the tag, the wheel; `pip install frontage` is the whole story
   again.

## 12. Risks, and open decisions

**The risk that is real** is the one LVGL's binding lived through: a conservative GC and C
structs holding `mp_obj_t`. Anything allocated with `m_new_obj` is scanned and so roots what
it holds; C globals need `MP_REGISTER_ROOT_POINTER`; a pointer kept anywhere else is a
use-after-free that shows up as a corrupted signal a thousand rows later. The audit of
every `mp_obj_t` field in the core, and the exception paths through `nlr_push` where a
boundary catches a user error, are the two weeks in step 2 that are not writing features.
The suite under node against the built interpreter, with `gc.collect()` forced between
phases, is the guard.

1. **`-O2` bytecode for app code** drops `assert`. Recommendation: yes, with `--debug`.
2. **Which trims** in the interpreter: the eleven modules above are the proposal; a test
   that needs one puts it back. `re`, `json`, `binascii`, `struct`, `math` stay.
3. **The C core's Python fallback in the browser**: keep it importable (`FRONTAGE_PURE=1`
   selects it) so a bug in the C module has a bisect, or delete it from the image to save
   the bytes. Recommendation: keep it, behind the flag, until 1.0.

Decided 2026-09-08, and not open: a page built by 0.9 is **not** kept bootable under a 0.10
`boot.js` (every deployed page is rebuilt), and the five published `frontage-*` names get
**no** shim release.
