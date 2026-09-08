# Rust in frontage: two homes, and what each app ships

**Status: a design, 2026-09-08. Everything in §2 is measured, this morning, on the committed
interpreter (`frontage/_runtime/`, the lean variant on upstream `v1.29.0`) and on six probe
builds made for this document: three Rust modules on `wasm32-unknown-unknown`, three Rust
static libraries linked into the interpreter through `runtime build --c-modules` in the pinned
`emscripten/emsdk:6.0.9`. §3 onward is unbuilt. It amends `FASTER.md` §3 ("why C and not
Rust") and §10 ("Rust linked into the same wasm"), whose premises the probes overturned; the
rest of `FASTER.md` stands, and §6 of this document says where its steps change.**

The question that started it: *reimplement the subpackages — chart, table, and so on, maybe the
core too — in Rust behind a Python interface, so the build can see which Rust code an app uses
and ship a minimal wasm.* Taken literally it is four questions, and they have different
answers: **where** Rust runs (inside the interpreter, or in a module of its own), **what
crosses** the boundary (and what it costs), **what "minimal" means** for a wasm that is not
Python, and **which subpackages are Rust-shaped at all**. The measurements say that most of
the subpackages are not, that the two places Rust can run are good for different things, and
that the interpreter must stay the same file for every app — which is the fact that decides
what "minimal" can mean.

> **Same day, a larger question: `RUNTIME.md`** asks whether the interpreter should be ours
> entirely — a Python runtime in Rust instead of MicroPython. If its spike passes, Home A
> (§3.1) is not a shim inside MicroPython but the runtime itself (`RUNTIME.md` §3.8), and
> Home B (§3.2) and the analysis (§4) stand unchanged. Step 1 below (the sort) is worth doing
> either way.

## 0. The decision, in five sentences

**Rust has two homes.** Inside the interpreter — `frontage/_core`, a `no_std` static library
behind a C shim, linked into our MicroPython build — for code that works on *Python objects*:
the reactive core, and row operations a table does over dicts (sort, filter, group). In a
module of its own — `wasm32-unknown-unknown`, loaded the `data-fr-js` way — for code that
works on *bulk data that never needs to be Python objects*: columns, series, decoded files, a
spectrogram. **The interpreter is one file per frontage version, identical for every app** (it
is what the browser caches across a site), so it ships no per-app anything; **a page ships
the modules its imports reach, cut to the exports its Python calls** — module grain always,
function grain when binaryen is there. **The core moves to Rust, not C**: a stable toolchain
links it today, `no_std` costs a kilobyte, a Python closure called from Rust costs 24 ns and a
Python exception passes through Rust frames untouched, which were the four things `FASTER.md`
§3 assumed against. **Most subpackages stay as they are**: uPlot, Leaflet, CSS and HTTP are
not Rust problems, and the schema validator is smaller as bytecode than it could be as wasm.

## 1. Where Rust could go, and why it is two places

A WebAssembly module owns one linear memory. Python's objects live in the interpreter's;
anything in another module's memory is not a Python object and cannot hold one. That splits
the world cleanly:

| | in the interpreter (`_core`) | a module of its own |
|---|---|---|
| sees | `mp_obj_t`: lists, dicts, closures, signals | its own memory: `f64` columns, bytes |
| calls Python | 24 ns per closure call (measured) | 1 µs per crossing, through JavaScript |
| data in | none — it is already there (`mp_get_buffer` is zero-copy over `array`/`bytes`) | a copy: 65 ns per element through a proxy, or one `memcpy` from the interpreter's heap |
| toolchain | stable Rust, `wasm32-unknown-emscripten`, a staticlib; linked by the Docker build | stable Rust, `wasm32-unknown-unknown`, a `cdylib`; no Docker, no Emscripten |
| per app | **never**: one file per version, cached site-wide | **yes**: reached modules, cut to used exports |
| dev loop | `cargo build` (seconds) + the Docker link (a minute) | `cargo build` + reload |
| right for | the reactive graph, holes, `For`; sort/filter/group over rows of dicts | a columnar frame, FFT, decoders, anything DuckDB-shaped but small |

The one principle that falls out: **the interpreter is not a per-app artefact**. `FASTER.md`
§7 wants `micropython.wasm` at a stable URL shared by every app on a site, with V8's code
cache applying; a per-app link would throw that away for a few kilobytes, and would need
Emscripten on the author's machine, which `pip install frontage` does not have. So "analyse
which Rust code the app uses and build a minimal wasm" applies to the second home only, and
in the first home the rule is the opposite: only what every app is better off carrying.

## 2. Measured

All under node 26 on this laptop, `performance.now()` from JavaScript, best of 5–20.

**2.1 A Rust module of its own is small.** A `no_std` crate with `sort_f64`, `argsort_f64`,
`group_mean`, `filter_gt` and a bump allocator, `opt-level="z"`, `lto`, `panic="abort"`,
then `wasm-opt -Oz`:

| | raw | gzip | brotli | functions |
|---|---|---|---|---|
| without the allocator (sort, argsort, group mean) | 7,619 | 3,293 | 2,914 | 16 |
| with it (+ `alloc`, `filter_gt` returning a fresh buffer) | 8,176 | 3,621 | 3,210 | 20 |
| **the same module cut to `sort_f64` + `memory` by `wasm-metadce`** | **3,752** | | **1,688** | |

Two notes for the tooling: Rust 1.96 emits `memory.copy`, so every `wasm-opt`/`wasm-metadce`
call needs `--enable-bulk-memory`; and the cut is a JSON graph naming the exports to keep —
exactly the artefact an import walk can write.

**2.2 The boundary, by shape.** 10,000 floats from a Python list into a `Float64Array` — the
copy a module of its own always pays — and the Python work it would replace:

| | ms |
|---|---|
| list → JavaScript `for…of` over the proxy | 0.65 |
| list → `Float64Array.from(proxy)` | 0.80 |
| 80,000 `bytes` → JavaScript, byte by byte over the proxy | 4.23 |
| list → `json.dumps` + `JSON.parse` | 4.93 |
| list → `",".join(map(str))` + `split` | 3.95 |
| one crossing (an `echo`) | 0.001 |
| a `Uint32Array` of 10,000 back into a Python list | 0.15 |
| *Python: build the 10,000-float list* | 0.50 |
| *Python: `sorted` of them, shuffled* | 1.27 |
| *Python: `sorted` 10,000 dict rows by a key* | 5.23 |
| *Python: filter 10,000 dict rows* | 0.44 |
| *Python: one column of 10,000 dict rows into `array('d')`* | 0.36 |
| *Python: `json.loads` of 10,000 records* | 30.4 |

So the proxy is the way in (65 ns an element, eight times better than JSON) and reading a
typed array back is 15 ns an element. Every Python container crosses as an opaque proxy —
`bytes`, `bytearray`, `memoryview` and `array` included, none with a `.buffer` — so the
zero-copy path (a `_core.address(buf)` builtin and a `HEAPU8` view, one `memcpy`) does not
exist yet; it is the first thing §3.2 builds, expected under 20 µs for 80 KB.

**2.3 MicroPython's `sorted` is quadratic on ordered input, and unstable.** Found on the way,
and it matters more than any Rust question for `frontage.table`, which sorts by a column that
often arrives already ordered:

| `sorted(…)` of | ms |
|---|---|
| 10,000 floats, shuffled | 1.27 |
| 10,000 floats, ascending | **269** |
| 10,000 floats, descending | 265 |
| 10,000 ints, ascending | 105 |
| 1,000 / 2,000 floats, ascending | 2.6 / 10.4 (4× for 2×: quadratic) |
| **10,000 floats, ascending, `key=lambda x: x`** | **1,440** |

`py/objlist.c:mp_quicksort` pivots on the last element (`tail[0]`) and calls the key function
at every comparison rather than once per element; the file's own comment says "Python defines
sort to be stable but ours is not". A table sorted by one column and then another is wrong,
not just slow. This is the first job for `_core` (§3.1) and worth an upstream issue.

**2.4 Rust inside the interpreter links today, on stable.** `cargo 1.96.0`,
`rustup target add wasm32-unknown-emscripten`, a `staticlib` built on the host in seconds
(no `emcc` is needed to make the archive), then `python -m frontage runtime build
--c-modules DIR` linked it in the pinned `emsdk:6.0.9` on the first try. No nightly, no
`-Zbuild-std`, no ABI mismatch: `FASTER.md` §10's tax is for *side modules* (PIC, what Pyodide
needs to `dlopen` a wheel), and a static link is not one.

| interpreter | raw | brotli | Δ brotli |
|---|---|---|---|
| the committed lean variant | 265,584 | 107,984 | |
| + Rust with `std` (`Vec`, `BTreeMap`, the system allocator) | 309,864 | 125,286 | +17,302 |
| **+ Rust `no_std` + `alloc` over Emscripten's `malloc`** | **267,920** | **109,010** | **+1,026** |

`std` is 17 KB of brotli for nothing the core needs; the rule is `no_std`. What it does there:

| | |
|---|---|
| sum of 100,000 floats from an `array('d')`, per call | **51 µs** (Python `sum(array)`: 3,000 µs) — zero-copy through `mp_get_buffer` |
| a Python closure called from Rust, per call | **24 ns** (from C, `FASTER.md` §3: 15 ns; the C shim is one hop) |
| the same closure called from Python | 81 ns |
| a `ValueError` raised in a closure Rust is looping over | **propagates through the Rust frames to the Python caller; the interpreter runs on** |

That last row retires the main objection. MicroPython's `nlr_jump` is a `longjmp`, which on
this build is a wasm `throw`; Rust compiled with `panic="abort"` carries no unwinding tables,
so the throw passes through its frames as through any other. What it does *not* do is run
`Drop`, which becomes a rule (§3.1), not a blocker. Because nothing in the Rust emits an
exception instruction, the legacy-versus-`exnref` question of Rust's Emscripten target never
arose, and `panic="abort"` keeps it that way.

Two build facts for the task that does this: the module directory must be a *subdirectory* of
what `--c-modules` mounts (`cmods/frcore/micropython.mk`, the layout MicroPython's `py.mk`
globs), and the archive goes on `JSFLAGS`, not `LDFLAGS_USERMOD` — the port links
`emcc $(LDFLAGS) -o $@ $(OBJ) $(JSFLAGS)`, and an archive before the objects resolves nothing.

**2.5 What exists today weighs**, as `-O2` bytecode, brotli:

| | bytes | | bytes |
|---|---|---|---|
| `reactive.py` | 6,701 | `schema/__init__.py` | 5,905 |
| `view.py` | 6,932 | `table/__init__.py` | 2,281 |
| `flow.py` | 3,245 | `chart/plot.py` | 495 |
| `store.py` | 2,155 | `remote/client.py` | 2,566 |
| `dom.py` | 4,175 | `uplot.js` | 21,406 |
| `template.py` | 1,803 | `leaflet.js` | 37,238 |
| the whole `frontage.tar` | 36,986 | | |

The whole framework is 37 KB of brotli; a Rust core replaces the ~18 KB of `reactive`, the
hole and template half of `view`, `For` and `store`, and lands inside the interpreter at
Rust's `no_std` prices (§2.1: a sort, an argsort and a group-by are 3 KB). The schema package
is 6 KB as bytecode; a Rust validator would be larger, would need its input marshalled
(§2.2), and would win nothing — it stays Python.

## 3. The two homes

### 3.1 `frontage/_core`: Rust inside the interpreter

**Layout.**

```
rust/                         one cargo workspace, at the repository root
    core/                     crate `frontage-core`: no_std, staticlib, wasm32-unknown-emscripten
    frame/  dsp/  …           crates for §3.2: no_std, cdylib, wasm32-unknown-unknown
frontage/_core/               the C shim: type objects, the module table, qstrs, nlr; and
                              micropython.mk, which adds the shim and links libfrontage_core.a
```

`mk runtime.wasm` grows one step — `cargo build --release --target wasm32-unknown-emscripten`
on the host, then the existing Docker link with `--c-modules frontage/_core` — and CI adds the
target with `rustup`. The Rust toolchain is a build dependency of the *repository*, like
Docker and `mpy-cross`; a wheel carries the result, and `pip install frontage` stays the whole
install.

**The shim is C, and it is the only C.** MicroPython's object model is macros — `MP_ROM_QSTR`,
`MP_DEFINE_CONST_OBJ_TYPE`, `mp_obj_is_small_int`, `m_new_obj` — and its qstrs are an enum
generated by scanning C sources at build time. So the shim owns three things Rust cannot:
the type objects and their slot tables (the method bodies are `extern "C"` in Rust), the
`MP_QSTR_*` constants (the shim's source is what the scanner reads; it hands them to Rust as
plain `u16`s), and `nlr_push` (a `setjmp` macro; the shim offers `fr_try(fn, arg, &exc) ->
bool` for the few places Rust must *catch* a Python error rather than let it pass — a boundary
`Errored` sits on). Everything else is `extern "C"` declarations over `py/obj.h` and
`py/runtime.h`: `mp_call_function_n_kw`, `mp_obj_new_list`, `mp_obj_get_int`, `mp_get_buffer`,
`gc_alloc`. Expect three hundred lines of C, written once, and a hand-written `sys.rs` rather
than bindgen: the surface is small, stable across upstream releases, and bindgen would drag
`libclang` into every build for forty declarations.

**Four rules, from the probes and from LVGL's binding, which lived through the same GC:**

1. **`no_std`, `alloc` over the GC heap.** The global allocator is `gc_alloc` / `gc_free` /
   `gc_realloc`, so a `Vec<mp_obj_t>` a Rust value owns is scanned like any Python container
   and roots what it holds. (The probe used `malloc` — right for a buffer of floats, wrong
   for anything holding an object.) `std` is 17 KB of brotli and offers nothing the core
   uses; `core` + `alloc` is the budget, `panic = "abort"`.
2. **A Rust value that holds `mp_obj_t` lives on the GC heap or on the stack of one
   synchronous run**, never in a static, never in `malloc` memory. Types the app sees
   (`Signal`, `Memo`, `Effect`, `Owner`, a `For` row) are `#[repr(C)]` structs headed by
   `mp_obj_base_t`, allocated through the shim's `m_new_obj` equivalent. The stack is safe
   because this port collects only when control returns to JavaScript (`FASTER.md` §2), so
   nothing moves under a Rust local inside one run; and Rust never holds anything across an
   `await`, because it never awaits.
3. **A Python error passes through Rust without running `Drop`.** Rust must therefore hold no
   RAII resource across a call into Python — no `Box` it would free afterwards, no borrow it
   would release, no half-updated state. The pattern is: read what the call needs into
   locals, call, and only then mutate; where a partial update is unavoidable, `fr_try`.
   `FASTER.md` §12's "two weeks that are not writing features" — the audit of every
   `mp_obj_t` field and every path through `nlr` — are the same two weeks in Rust, with the
   difference that the compiler checks the first half.
4. **The Python implementation stays and stays tested.** `reactive.py` becomes
   `from ._core import Signal, …` in the browser and the Python graph on CPython, where
   pytest, the prerenderer and the language server run; `FRONTAGE_PURE=1` selects it in the
   browser (`FASTER.md` §12.3). Two implementations of `SPEC.md`'s C-lines, one suite: the
   Python one under pytest, the Rust one under node against the built interpreter, `gc.collect()`
   forced between phases. The pure parts of the core — the topological order, the LIS
   behind `_reconcile`, the hole walk over a template — are written against slices and
   indices and get `cargo test` on the host as well, with no interpreter in the room.

**What lives there.** `FASTER.md` §3's table, unchanged in content, in Rust: the reactive
graph (`Signal`, `Memo`, `Effect`, `RenderEffect`, `Owner`, `_mark`/`_flush`, `batch`,
cleanup, error routing), templates and holes (`Template` clone, `_mount_hole`, `_reconcile`
+ `_lis`, `_apply_attrs`, `_children`/`_build_nodes`/`_normalize`), `For` row ownership and
index signals, `Store` proxies, and the DOM op stream of §4. Plus one thing §3 did not list,
because it was not known to be needed: **row operations over Python objects** —

```python
from frontage._core import sort, filter, group   # stable; key called once per element
sort(rows, key=column.value, reverse=True)       # 10,000 ordered floats: 269 ms → ~2 ms
```

— a stable merge sort that decorates once, a filter that calls a predicate at 24 ns a row,
a group-by returning `(key, [rows])` pairs. `frontage.table` uses them in place of `sorted`
and a comprehension; they cost about a kilobyte of wasm and fix §2.3 for every app.

**Why Rust and not C, now.** `FASTER.md` §3 chose C because Rust looked like "a second FFI
around the first" on a nightly toolchain. The probes reduce the second FFI to the shim above,
on stable. What Rust buys in return is what it always buys in a codebase whose bugs are
pointer bugs: slices with bounds, `Option` where C has a null and a comment, enums for the
node states the two-phase graph has today as integers with names, `cargo test` for the
algorithms, and no undefined behaviour in the arithmetic. The one real cost is a second
language in the repository and in CI; the reason to pay it is that the core is the part of
frontage that will be read least and trusted most.

### 3.2 A module of its own: Rust behind `data-fr-js`

**Layout**, the component protocol as it stands (`COMPONENTS.md` §5) with one more file:

```
frontage/frame/
    __init__.py          the Python interface: Frame, from_csv, …; `import frame as _rs`
    _browser/index.js    the glue: instantiates ./frame.wasm, owns its memory, exports calls
    _browser/frame.wasm  built by `mk rust.build` from rust/frame/, committed like _runtime/
```

`build` already copies `_browser/` whole and merges the `data-fr-js` line; `serve` already
serves a `.wasm` beside its glue; `examples/wasm/mathlib.js` is the glue in its entirety. A
Rust component is the existing contract with a crate behind it, and nothing in the loader
changes.

**Handles, not data.** The module's memory is where the data lives; Python holds an integer
handle and asks coarse questions. `Frame.from_csv(text)` copies the text in once;
`frame.sort("temp")`, `frame.where("year", "in", years)`, `frame.group("month").mean("precip")`
are one crossing each and return handles or small results; `frame.series("day", "high")`
returns `Float64Array`s the chart draws with no copy and no Python in between — the path
`frontage.remote` already takes for a server's answer. `frame.window(offset, limit)` returns
one page of rows, so a `Frame` is a `table` source under the windowed protocol the grid
already speaks (`key()` + `window(…)`), local rather than remote. `examples/weather` — 1,461
dict rows, six aggregations in Python — is the app to port and the number to publish.

**Two costs, and what avoids them.** Data in: through the proxy at 65 ns an element (§2.2)
when it starts as a list, or as one `memcpy` when it starts as `bytes`/`array` — which needs a
`_core.address(buf)` builtin (a two-line `mp_get_buffer` in §3.1's shim, the `uctypes.addressof`
this build switched off) and `HEAPU8` from `boot.js`; to be measured, expected under 20 µs
for 80 KB against §2.2's 4.2 ms. Data across modules: two Rust modules have two memories, so a
frame and an FFT module trade through a typed array — cheap, and the reason the frame is one
crate rather than several. Emscripten's dynamic linking would put the modules in the
interpreter's memory instead; it is the nightly-Rust, PIC, `MAIN_MODULE` road Pyodide walks,
it costs the main module exports and glue, and nothing here needs it.

**What goes there.** The frame first (`COMPONENTS.md` §7's second bullet, and the local half
of what `frontage.remote` asks a server for); FFT and a spectrogram (`TODO.md`'s GW Quickview,
the concrete signal-processing case); CSV and Arrow IPC decoding. What does not: a chart, a
map, a grid's DOM, HTTP — the JavaScript library or the browser already does those, and a
Rust layer in front would lengthen the path (`COMPONENTS.md` §7, still right).

**Rules for the crates.** `no_std`, `panic = "abort"`, `opt-level = "z"`, `lto`,
`codegen-units = 1`; a bump or `free`-less allocator unless a crate frees (then a small real
one, ~1 KB); raw `extern "C"` exports over `(ptr, len)` rather than `wasm-bindgen`, whose glue
is bigger than these modules; every export documented in the glue's `KEEP` line (§4). Tests are
`cargo test` on the host over slices, plus one browser test per component through the real
`build`.

## 4. The interface, and what the build reads off it

The analysis the question asked for is the one `cli/graph.py` already does for Python,
extended one level into each component's JavaScript module:

1. **The import walk** (`FASTER.md` §6, `cli/graph.py`) reaches `frontage.frame`; a component
   whose module is reached ships its `_browser/` — the `.js`, the `.css`, the `.wasm` — and
   one that is not reached ships nothing. That is *module grain*, it needs no tool, and it is
   most of the answer: a page without a chart carries no uPlot, without a frame no engine.
2. **The export set.** The Python interface calls the module by static attribute —
   `_rs.argsort(…)`, `_rs.group_mean(…)` — and the walk collects `<module>.<name>` accesses in
   every reached module of the component, the same reading it gives `frontage.X` today. A
   `getattr(_rs, name)` or `_rs` passed along as a value means *every export*, printed, like
   the `frontage`-as-a-value rule in `graph.py`. The glue's own needs — `alloc`, `memory`,
   `__heap_base` — are one line in `index.js`, `export const KEEP = ["alloc", "memory"]`, read
   with a regex.
3. **The cut.** `frontage build --shrink` writes the set as a `wasm-metadce` graph and runs
   it, then `wasm-opt -Oz`, both with `--enable-bulk-memory`. Binaryen is not a dependency:
   `binaryen.py` is an 8 MB wheel, so it is an extra (`frontage[shrink]`) or the release
   binary fetched into `~/.cache/frontage` the way `tailwind` is; without it the whole module
   ships and the build says so, as `tools/site_css.py` does for a host that cannot run
   Tailwind. Function grain saves half of a small number (§2.1: 3.2 → 1.7 KB); it is a
   refinement to measure, not the mechanism.
4. **What prints**: per component, the modules reached, the exports kept, the bytes before and
   after — the numbers the gallery cards quote.
5. **Chunks** (`FASTER.md` §7): a component reached only from a lazy route rides in that
   route's chunk; its `.js` is the manifest's `imports`, its `.wasm` and `.css` its `assets`,
   fetched in parallel with the chunk, registered before the module's Python runs. `serve`
   synthesises nothing for a `.wasm` — it serves the committed file — and a Rust edit is
   `mk rust.build` and a reload; `dev.swap` is untouched, because the module objects the page
   holds are the interpreter's, not the crate's.

The interpreter is outside all of this by §1: `_core` is never analysed, never cut, and never
different between two apps of one version.

## 5. Each subpackage, and the verdict

| subpackage | today | Rust? | why |
|---|---|---|---|
| `reactive`, `view` (holes, templates), `flow.For`, `store` | Python, 18 KB of brotli | **`_core`** | `FASTER.md` §3, in Rust: the per-row calls become Rust calls; the app's Python is the only Python left per row |
| `table` | Python over `For`; `sorted`/comprehensions | **`_core.sort/filter/group`** for dict rows; a **`Frame`** as a windowed source for columns | §2.3: quadratic and unstable today; the grid's DOM stays exactly as it is |
| `chart` | 1.7 KB of Python over uPlot | no | the canvas is JavaScript's; the frame hands it `Float64Array`s, as `remote` does |
| `remote` | HTTP client; series decoded in JavaScript | the **frame** takes the bytes | the local half of the same API; nothing else changes |
| `schema` | 28 KB of Python, 5.9 KB of bytecode brotli | no | a Rust validator is larger and needs its input marshalled; split the `__init__` per type instead (`FASTER.md` §6) |
| `map`, `layout`, `supabase` | Leaflet, CSS, HTTP + websocket | no | not compute |
| **`frame`** (new) | — | **a module of its own** | `COMPONENTS.md` §7's second bullet; `weather` is the proof |
| **`dsp`** (new, when asked for) | — | a module of its own | the FFT case in `TODO.md` |

## 6. The plan, in `FASTER.md` §11's order

`FASTER.md` §11 step 1 (the interpreter) is done. This document changes step 2 and inserts
one step; the rest stand.

1. **`_core`, the skeleton, with the sort as its first tenant.** `rust/core/`,
   `frontage/_core/{shim.c,micropython.mk}`, `mk runtime.wasm` building the staticlib and
   linking it, CI adding the target; `_core.sort/filter/group`; `frontage.table` on them; a
   browser test that sorts an ordered column. Gate: the browser suite green; the interpreter
   ≤ 2 KB of brotli heavier; 10,000 ordered rows sorted by a key in under 5 ms (1,440 today).
   The upstream issue for §2.3 goes in the same week.
2. **The reactive core in Rust** — `FASTER.md` §11 step 2, retargeted: the graph first, then
   holes and templates, then `For` and `Store`, `reactive.py` re-exporting it in the browser,
   the SPEC tests under node against it, `cargo test` on the pure parts. Gates as written
   there: a 1,000-row create under 20 ms in `profile_rows` (71 on this interpreter, 139
   before it), swap and update no worse than 4.4 and 1.4 ms.
3. **The frame.** `rust/frame/`, `frontage/frame/` with its glue and the `KEEP` line,
   `_core.address` and the `HEAPU8` handoff measured, `Frame` as a `table` source,
   `examples/weather` ported and on the gallery with its numbers. Gate: weather's six
   aggregations under 1 ms total; the engine under 15 KB of brotli.
4. **The analysis** — inside `FASTER.md` §11 step 4 (the closure and the chunks): the export
   set in `graph.py`, `--shrink`, the report, a `.wasm` in a lazy chunk under test.
5. `dsp` and decoders when an app asks; `FASTER.md` steps 5–7 unchanged.

## 7. Risks, and the decisions to take

The risk is the one already named — GC roots and `nlr` paths in `_core` — and §3.1's rules 1–3
are the answer; the suite under node with forced collections is the guard, as before.

1. **Rust for the core, or C.** Recommendation: Rust, for §3.1's reasons; the probes removed
   the toolchain objection and the exception objection, and the shim is the same C either
   way. The cost is a second language in the repository, and it is real.
2. **How binaryen arrives** for `--shrink`: an extra (`frontage[shrink]`, an 8 MB wheel), a
   fetched release binary (`~/.cache/frontage`, the `tailwind` pattern), or a pure-Python
   cutter written later. Recommendation: the fetched binary, so the default install carries
   nothing; module grain is the mechanism and needs no tool at all.
3. **The frame's scope.** A small engine — filter, sort, group/aggregate, rolling, resample,
   CSV and Arrow in — against DuckDB-wasm's 3.2 MB for everything. Recommendation: the small
   one, measured on `weather` and the gallery; DuckDB stays the opt-in tier for SQL.
4. **`_core.sort` as a replacement for `sorted` framework-wide, or a name apps opt into.**
   Recommendation: the framework and the components use it; `sorted` is left alone for apps,
   with a line in the chapter and the upstream issue as the fix at the root.
