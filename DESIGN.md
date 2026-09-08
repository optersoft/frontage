# Frontage design

**Status: implemented through M12 (0.10.0, 2026-09-08: frontage's own Python runtime in Rust, with the framework core native inside it — `RUNTIME.md` is that design and its measurements, and supersedes what this document says about the interpreter; 0.9.0 replaced PyScript with a WebAssembly boot). Draft 4 of 2026-09-05 is the plan it followed; §6 and §12 carry what measurement changed since.** Draft 1 kept PuePy's shape. Draft 2 was written from Leptos.
Draft 3 added [Solid](https://github.com/solidjs/solid) (1.x, `dom-expressions`, the store,
`solid-router`, the 2.0 release candidate), the JavaScript origin of the model and the size
reference. This draft adds the three Python-first frameworks, [Streamlit](https://github.com/streamlit/streamlit),
[Shiny for Python](https://github.com/posit-dev/py-shiny) and [Reflex](https://github.com/reflex-dev/reflex),
with one question asked of each: what happens when it has to run in WebAssembly. Two of them
already do (stlite, Shinylive), and that evidence shapes section 2b. Decisions marked *open*
are for David.

## 1. The decision

Frontage is a **clean-room implementation**, Optersoft's own code, of a fine-grained
reactive web framework for Python in the browser. Reasons (ownership of copyright, license
and story) are in draft 1 and hold.

What carries over untouched: the name, the PyPI plan, `pyproject.toml`, the uv/ruff/ty
toolchain, `ci.yml` with the OIDC publisher, the Cloudflare Pages site, `Makefile.py`.

## 2. What the three references teach

| | PuePy | Leptos | Solid 1.x | Solid 2.0 RC |
|---|---|---|---|---|
| Update model | rebuild page, morph DOM | fine-grained signals | fine-grained signals | fine-grained, async in the graph |
| Size | 2.5k lines Python | ~80k lines Rust | ~2.4k reactive + ~0.7k DOM + ~1.1k store | 16k lines core alone |
| Lists | morph by id | keyed diff | keyed diff, DOM moves | same, one `For` with keying modes |
| Async | none | Resource, Suspense, Action | Resource, Suspense, transitions | async memos, Loading/Errored, actions, optimistic |
| Templates | Python builder | `view!` macro to typed tree | JSX compiled to `<template>` clones | same |
| Events | per-element listeners | delegation behind a flag | delegation by default | same |

**Solid 1.x is the size proof.** A complete fine-grained framework, with stores, routing
primitives and server rendering, is about five thousand lines of JavaScript. Frontage's core
budget of ~4,000 Python lines is realistic because Solid did it.

**Solid 2.0 is the direction, not the target.** Its core is seven times larger than 1.x to
put async, transitions and optimistic writes inside the graph. Frontage takes its *names and
shapes* (two-phase effects, `Loading` / `Errored`, one `For` with keying modes, draft-based
store writes, a `Renderer` interface) and leaves the machinery for a later major version.

**What transfers from all three** is in the sections below. What does not: Rust's typed
view tree and arena handles, JSX and the Babel compiler (Python 3.14 template strings do
that job at runtime), Solid's proxy-based store internals (Python has no `Proxy`; it has
dunder methods, which are enough), transitions and time slicing.

## 2b. The Python-first frameworks, and the WebAssembly test

| | Streamlit | Shiny for Python | Reflex |
|---|---|---|---|
| Model | the script re-runs top to bottom on every interaction; widgets return values | reactive `Value` / `calc` / `effect` graph on the server; UI functions return HTML; outputs bound by id | `State` classes with typed vars and handler methods on the server; the view compiles to React |
| Where Python runs | server (Tornado) | server (Starlette, asyncio) | server (FastAPI + websocket); the browser runs generated JavaScript |
| Size | runtime 23k + elements 46k lines | reactive 2.7k, render 6k, ui 17k, express 4k | 27k lines, plus Node and a React toolchain |
| Nesting syntax | `with st.sidebar:` | Express: `with ui.card():` | function calls |
| Partial updates | `@st.fragment` re-runs a subtree | per-output invalidation | state deltas over the websocket |
| In the browser | **stlite**: the whole runtime in Pyodide in a Web Worker, packages on demand from a 200 MB+ distribution | **Shinylive**: Pyodide plus a service worker, ~13 MB before app code, static export, code-in-URL sharing | none, and none possible: the architecture is Python-on-the-server by construction |

**What the WebAssembly test says.** Streamlit and Shiny run in the browser only by carrying
their *server* into it: a session, a message protocol, an emulated transport, and the full
Pyodide. They work, they are used, and they start in tens of seconds. Reflex cannot be
ported at all, and everything un-Pythonic in Reflex (`rx.cond` and `rx.foreach` instead of
`if` and `for`, `Var` objects that are expressions rather than values, `.to(dict)` casts) is
the price of Python *not* being present in the browser at runtime. That is the clearest
argument for Frontage's premise there is: a browser-first framework has no session, no
transport and no DSL, because the Python is right there.

**What transfers, and it is a lot:**

1. **`with` blocks for nesting.** Streamlit, Shiny Express and PuePy converged on the same
   syntax independently. The builder gets it (`with h.div(cls="card"): h.p(...)`), and it is
   the natural way to generate UI in a Python loop. The template string stays the primary
   syntax for static structure.
2. **Decorators are the Pythonic spelling of reactivity.** Shiny's `@reactive.calc` /
   `@reactive.effect` / `@render.text` on named functions read better than lambdas. Frontage's
   `Memo`, `Effect` and `RenderEffect` accept a function, so `@Memo` and `@Effect` work as
   decorators with no extra API, and a decorated `Memo` is an accessor a template hole can
   name. The tutorial teaches this form.
3. **"Not ready" as control flow.** Shiny's `req()` raises a silent exception that cancels
   the computation quietly; Solid 2.0's `NotReadyError` is the same idea from the other side.
   Frontage: `raise NotReady` (or `require(x)`) inside a compute ends it without error and
   registers with the nearest `Loading` boundary. This is how a hole reads a `Resource`
   without a `None` check.
4. **Timers as signals.** Shiny's `invalidate_later` and `reactive.poll`, Streamlit's
   `run_every`. Frontage: `interval(seconds)` returns an accessor that ticks; `poll(fn,
   seconds)` a `Resource` on a timer. Small, and every dashboard wants them.
5. **A widget catalogue.** Both data frameworks ship a fixed set of inputs (text, number,
   slider, select, checkbox, radio, date, file, button) as the beginner's vocabulary. Frontage
   0.2 ships `frontage.widgets`: plain HTML form controls bound to a signal (`text_input(sig,
   label=…)`), unstyled beyond a class hook, the thing the first tutorial chapter can use
   before templates are taught.
6. **Class-based state as sugar.** Reflex's `State` with typed fields and handler methods is
   a shape many Python developers reach for. Frontage 0.2 offers `State` as sugar over
   signals: `count = field(0)` descriptors (explicit, because MicroPython does not populate
   `__annotations__`), methods as handlers, `@computed` as memos. Optional; the primitives
   stay the foundation.
7. **Static export and a playground.** Shinylive's `export` command and code-in-URL sharing
   are how its docs and courses work. Frontage: `mk export` (or `frontage export`) writes a
   directory of app, wheel and `pyscript.json`; the site gets a playground page that runs the
   code in the URL fragment. For a company that teaches, the playground is the classroom.
8. **Fragments are a confession.** Streamlit added `@st.fragment` because re-running the
   whole script does not scale; Solid's `For` and Frontage's holes are the fine-grained
   answer to the same problem, taken from the start.

**What does not transfer.** The script-rerun model itself (its simplicity is real, and
`with` nesting plus module-level `mount()` give a first chapter that reads like a script
without paying its cost); server sessions and message protocols; Reflex's React component
wrapping (Frontage's component library is web components used as HTML, section 8.2, with
Shoelace as the documented example); anything that needs a thread or `time.sleep`, which
stlite lists as broken in the browser and Frontage's async model never wanted.

**Two consequences for the site.** Shinylive and stlite both note that several apps on one
page means several interpreters; the docs embed a dozen examples per chapter. The examples
site should load one interpreter per page and mount examples into it, or lazy-load each on
scroll. And the size story is Frontage's to tell: Shinylive is ~13 MB before the app; a
MicroPython Frontage app is under a megabyte. That number belongs on the landing page once
it is measured.

## 3. Goals

1. **Python only, in the browser.** Reactive UI, no JavaScript toolchain, deploy by serving files.
2. **Fine-grained.** A state change touches the DOM nodes that read it and nothing else.
3. **Few bridge calls.** Every DOM operation from Python crosses the Python-to-JavaScript
   bridge, which is the dominant cost in PyScript. The design counts crossings the way a
   database design counts round trips (section 8).
4. **One runtime, chosen by measurement.** MicroPython compiled to WebAssembly. Pyodide was first-class through 0.8 and left in 0.9.0 (§6): the same code ran on both, and carrying the second cost 13.8 MB, half the browser matrix, and a defensive shape in `dom.py` for a proxy-identity difference nobody was exercising.
5. **Small and teachable.** Core under ~4,000 lines; a reader can hold it in a day.
6. **Renderer-agnostic views**: DOM in the browser, HTML string on CPython; server rendering
   stays possible without a rewrite (section 8).
8. **Python is the control flow.** `if`, `for`, comprehensions and function calls work
   inside a view because the Python is in the browser. `Show` and `For` exist for
   fine-grained efficiency, never as a required DSL. No `cond`, no `foreach`, no `Var`.
7. **Honest testing**: the reactive core and the view layer test on CPython with no browser;
   the examples run in real browsers under both runtimes.

## 4. Non-goals for 0.x

A live rendering server (prerendering as a build step shipped in 0.4.0, and is the only server
rendering planned); a component library; PyScript, which 0.9.0 replaced with a direct
WebAssembly boot (§6).

## 5. Clean-room rules

- **Consult:** the documentation and examples of PuePy, Leptos and Solid; the reactive-graph
  algorithms as described in their books and READMEs (Reactively's article, Solid's
  "fine-grained reactivity" guide); PuePy's browser tests as an acceptance specification.
- **Do not copy:** source, tests, docstrings or prose from any of them. Code is written from
  `SPEC.md` (section 13) with no reference repository open.
- **Every PR states** it was written from the spec without reference source open.

## 6. Platform

| | |
|---|---|
| MicroPython | 1.28.0-6, the upstream `webassembly` build for the `pyscript` variant (template strings, `weakref`, `asyncio.Future`), vendored in `frontage/_runtime/` and pinned on one line in `cli/micropython.py` |
| PyScript | **left in 0.9.0** (M11). It was the delivery mechanism, never the bridge: `runtime.py`'s two imports were the whole coupling, and MicroPython's own `js`/`jsffi` answer them. `export` writes a PyScript page through 0.9.x for the academy's chapter repos, and goes at 1.0 |
| Pyodide | **unsupported from 0.9.0**: no CI, no examples, no docs. 13.8 MB against 0.64 was never the story this framework tells, and one interpreter halves the browser matrix. `runtime.py` keeps a three-line branch that still works, which is a cheaper way to leave the door open than deleting a name `frontage.platform` promises |
| Browsers | evergreen Chromium, Firefox, WebKit |
| Server | CPython ≥ 3.12 for tests, tooling, the string renderer |

The package is written in the MicroPython subset (string annotations, no runtime `typing`,
no dataclasses). The bridge is `pyscript.document` / `window` / `ffi` / `js_modules` /
`asyncio`, present on both interpreters; `pyscript.web` is not used. *Open:* MicroPython
first-class or best-effort. Proposal: first-class.

## 7. The reactive core (`frontage.reactive`)

The model is Solid's, which Leptos confirmed: signals (sources), memos (derived, cached,
lazy), effects (subscribers that touch the outside world), all with automatic, dynamic
dependency tracking under an owner tree.

```python
from frontage import Signal, Memo, Effect, batch, untrack

count = Signal(0)
double = Memo(lambda: count() * 2)  # accessors are callables
Effect(lambda: double(), lambda v, prev: print("double is", v))
count.set(2)
count.update(lambda n: n + 1)
```

**Accessors are callables.** A `Signal`, a `Memo`, a `Resource` and a plain `lambda` are
all read by calling them. This is Solid's rule and it is what makes the view layer simple:
*any callable in a child or attribute position is reactive*; anything else is static.

**Propagation** is Solid 1.x's, chosen over Solid 2.0's microtask batching because reads
after a write return the new value, which is what a beginner expects and what tests can
assert without an event loop. Three node states, Clean / Check / Dirty. A write marks
dependents; pure nodes (memos) recompute in topological order within the same batch;
effects run once at the end of the outermost `batch()`, every write being an implicit
batch. Memos compare with `==` by default and take `equal=`. `untrack()` reads without
subscribing. `on(deps, fn)` for explicit dependencies.

**Two-phase effects** (Solid 2.0). `Effect(compute, effect)`: `compute` runs tracked and
returns a value; `effect(value, prev)` runs untracked after the batch and may return a
cleanup. This makes the two classic mistakes impossible by construction: side effects
subscribing to signals they happened to read, and writes inside tracked code. A one-argument
`Effect(fn)` shorthand tracks `fn` and is documented as the rough tool. `RenderEffect` is the
same with the effect phase run before user effects; the view layer uses it.

**Ownership.** `Owner` tree; every effect and memo is created under the current owner; a
component body and every `For` row run under their own owner (Solid creates a root per row,
which is what lets one row dispose without touching the others). `owner.dispose()` runs
`on_cleanup` callbacks, cancels effects, disposes children, **destroys every JavaScript
proxy registered under it**, and releases delegated-event registrations. `Context`:
`provide(ctx, value)` / `use(ctx)` walk the owner tree.

**Utilities carried from Solid:** `selector(source)` for O(1) "is this row selected"
checks in a list; `on_mount(fn)`; `get_owner()` / `run_with_owner()`; `children(fn)` to
resolve a child accessor once. **From Shiny:** `NotReady` (section 2b), `interval(seconds)`
and `poll(fn, seconds)`. **Decorator form** for `Memo`, `Effect` and `RenderEffect`, which
falls out of them taking a function and is the form the tutorial teaches.

**Stores (`frontage.store`), in 0.1.** Python application state is dicts and lists, so
nested reactivity is not an optimisation, it is the default case. Solid's design transfers
without `Proxy`: a `Store` wraps a dict or list in an object whose `__getitem__` /
`__getattr__` / `__iter__` / `__len__` lazily create one signal node per key on a *tracked*
read (so untracked keys cost nothing), and re-wrap nested containers on the way out. Writes
go through a draft: `store.set(lambda s: s["todos"].append(...))`, applied inside a batch
with the wrapper's `__setitem__` notifying exactly the keys touched (Solid 2.0 made this the
only write form; 1.x's path syntax `set("user", "name", v)` is offered as `store.set_path`).
`reconcile(data, key="id")` merges fresh server data into an existing store preserving row
identity, so a `For` over it moves rows instead of recreating them. `snapshot(store)`
returns plain data.

The whole module is testable on CPython with no browser, and that suite is where the
framework's correctness lives.

## 8. Views (`frontage.view`)

### 8.1 Templates first, because of the bridge

Solid compiles JSX to a static HTML string per template, creates a `<template>` element
once, and instantiates it with a single `cloneNode(true)`; only the dynamic holes are then
touched. Leptos does the same. For PyScript this is not an optimisation to add later; it is
the difference between one bridge crossing per instance and one per element and attribute.

So Frontage's unit of rendering is the **`Template`**: a static HTML skeleton plus a list of
holes (a text position, an attribute, an event, a child slot), each with a path to its
node. Instantiation is: clone the skeleton in one call, locate the hole nodes, bind each
hole with a `RenderEffect` (or a static value). Both front ends below compile to it.

**The template string** (Python 3.14, both interpreters), parsed once per call site and
cached, is the primary syntax and what the tutorial teaches:

```python
def counter(initial=0):
    count = Signal(initial)
    return html(t"""
        <div class="counter">
            <button on:click={lambda e: count.update(lambda n: n - 1)}>-</button>
            <span>Value: {count}!</span>
            <button on:click={lambda e: count.update(lambda n: n + 1)}>+</button>
        </div>
    """)
```

**The builder** is the fallback and the escape hatch, and it produces the same `Template`
when its structure is static. It has a call form and a `with` form; the second is what
Streamlit, Shiny Express and PuePy all arrived at, and the natural one inside a loop:

```python
h.div(h.button("-", on_click=dec), h.span("Value: ", count, "!"), h.button("+", on_click=inc), cls="counter")

with h.ul(cls="menu"):
    for item in items:
        h.li(item.label, on_click=lambda e, i=item: select(i))
```

*Open:* if template strings prove immature on either interpreter, the builder ships alone
in 0.1 and the template follows. Proposal: builder in M1, template in M2, tutorial on the
template.

### 8.2 The insert rules

A child slot follows Solid's `insert` semantics exactly, because they are complete and
small: `str`/`int`/`float` → a text node updated in place; `None`/`bool` → nothing; a
callable → a `RenderEffect` around the same rules; a list → flattened, callables resolved,
then reconciled against the current nodes by identity (prefix, suffix, swap, then a map;
existing nodes are moved, not recreated); a view → mounted. A component's output is a view
or a list of nodes, never a wrapper element.

Attributes: a keyword or template attribute whose value is a callable is bound. Prefixes
name the DOM's real distinctions: `attr:` (default), `prop:` (a DOM property, the one form
inputs need for `value`), `class:name={bool}` and `class={dict}`, `style:prop`, `on:event`,
`bind:value` / `bind:checked` / `bind:group` (two-way), `ref={NodeRef()}`. Boolean
attributes are set and removed, never written as `"false"`.

### 8.3 Components and control flow

A component is a function of keyword props that runs once under its own owner and returns a
view. Reactive props are accessors; static props are values; `children` is a callable. No
base class. Control flow is components:

| | |
|---|---|
| `Show(when, fallback, children)` | one branch mounted; `children` may be a function of the narrowed value (`keyed=True` re-creates on value change, Solid's rule) |
| `For(each, children, key=…)` | keyed by identity by default; `key=fn` for an extracted key; `key=False` for index mode where the item is an accessor and rows are reused positionally (Solid 2.0 folded `Index` into `For` this way) |
| `Switch` / `Match` | first matching branch |
| `Loading(fallback, children)` | Solid 2.0's name for Suspense: fallback while any `Resource` read beneath is loading; nested boundaries |
| `Errored(fallback, children)` | Solid 2.0's name for ErrorBoundary: `fallback(error, reset)` |
| `Dynamic(component, **props)` | component chosen at runtime |
| `Portal(mount, children)` | render elsewhere in the DOM |

### 8.4 The renderer seam

The view layer talks to a `Renderer` with Solid's universal-renderer surface, ten methods:
`create_element`, `create_text`, `replace_text`, `set_property`, `insert_node`,
`remove_node`, `is_text`, `parent`, `first_child`, `next_sibling`, plus `clone_template`
and the event hooks. Solid's `universal` package is the proof that a whole framework can
sit on this seam. Two implementations: `DomRenderer` in the browser and `HtmlRenderer` on
CPython, which is how views are unit-tested without a browser and the seam server rendering
would plug into later. Hydration markers are designed now and shipped never, in 0.x.

### 8.5 Events

Delegated, as in Solid: one listener per event type on the document for the bubbling
events (click, input, keydown, pointer and touch events, focusin/out, …); the handler walks
from the target up to the mount root and dispatches to the Python handler registered for
that element, simulating `currentTarget`, honouring `disabled` and `stopPropagation`.
Non-bubbling events attach directly. `on:` on the template forces a direct listener;
`oncapture:` for the capture phase. Handlers may be `async def`. In PyScript this turns one
`create_proxy` per handler into one per event type, and a disposed owner drops its
registrations from a dict.

### 8.6 A small JavaScript shim, measured

*Open, and the one place this design proposes shipping JavaScript.* Two hot paths cross the
bridge many times per operation when written in Python: locating a clone's hole nodes
(one call per `firstChild` / `nextSibling` step) and the delegated event walk (one call per
ancestor). A ~100-line `frontage.js`, loaded through `js_modules` like morphdom was, can do
each in a single call: `holes(root)` returns the hole nodes of a clone, `dispatch(event)`
walks to the registered ancestor and calls Python once. The user never sees it. Proposal:
build pure Python first, measure with the js-framework-benchmark rows example on both
runtimes, and add the shim only where the numbers say so.

## 9. Async (`frontage.reactive`, continued)

`Resource(fetcher, source=None)`: `fetcher` is an `async def`; it re-runs when `source`
changes; the resource is an accessor returning the latest value (or `None`) with
`.loading`, `.error`, `.state` as accessors and `.refetch()` / `.mutate()` for imperative
control. Reading it under a `Loading` boundary registers with that boundary's counter
(Solid's increment/decrement design). `Action(fn)`: `.dispatch(input)`, with `.pending`,
`.value`, `.input` accessors; what a form submits to. Tasks are spawned with
`asyncio.create_task` on both interpreters and owned, so a disposed owner cancels them.

One rule, documented and enforced with a dev-mode warning because Python makes it easy to
get wrong: **read every reactive input before the first `await`.** After an `await` the
tracking context is gone. Solid 2.0 states the same rule for its async memos.

Solid 2.0's async-in-the-graph (memos returning awaitables, `is_pending`, `latest`,
`refresh`, generator-based transactional actions, optimistic values) is the model Frontage
1.0 should grow toward once 0.x has users. It is written down here so 0.x does not paint
over it: `Resource` is designed to be replaceable by an async `Memo` without changing the
`Loading` / `Errored` boundaries.

## 10. Router (`frontage.router`)

Solid-router's shape, which is Leptos's with data loading co-located:

```python
router = Router(
    Route("/", Home),
    Route(
        "/users",
        Users,
        children=[
            Route("/", UserList),
            Route("/:id", User, preload=preload_user),
        ],
    ),
    Route("/*any", NotFound),
    mode="history",  # or "hash" for the no-server tutorial case, or "memory" for tests
)
mount("#app", router)
```

- **Nested routes**; a parent route component receives the matched child as `children`.
- **Params, query, location** as accessors: `use_params()["id"]` is reactive.
- **`preload`** per route: called when a route is about to render and, eagerly, when a link
  is hovered; returns nothing, warms `query` caches. Solid's render-as-you-fetch.
- **`query(fn)`**: a keyed async cache with de-duplication and `revalidate()`; a `Resource`
  reading it gets the cached value first.
- **`action(fn)`** and **`use_submission()`** for mutations bound to forms, with
  `redirect()` raised from inside.
- **Plain `<a>` works** (document-level interception); `A(href)` adds relative resolution
  and the active class. `Navigate(to)`, `navigate()`, `use_before_leave()`, scroll
  restoration. **Memory mode** is what makes the router unit-testable.

## 11. Errors and development mode

Exceptions in a component body or effect route to the nearest `Errored`; with none, to the
mount root, which in debug mode renders the traceback with the component named and in
production renders a configured fallback and logs. Dev-mode warnings for the three mistakes
the design cannot prevent: a signal read after `await`, a write inside a tracked compute,
and a `For` over unstable keys.

## 12. The three questions the measurements answer

Before M2 the rows example from js-framework-benchmark runs under both runtimes with a
harness that counts bridge crossings and wall time for create 1,000 rows, update every
tenth row, swap two rows, remove a row, clear. It decides: whether the JavaScript shim of
8.6 is needed and where; whether MicroPython is first-class or best-effort; and whether
the builder without templates is acceptable in 0.1. Numbers, not opinions.

**First measurement (2026-09-05, M1, this laptop's Chromium).** Create 1,000 rows: 169 ms on
MicroPython, 77 ms on Pyodide, 11 renderer operations per row with templates against 31
without. Templates ship as the default on both interpreters. On MicroPython the template
gain was small (177 → 169 ms), because the cost there is Python execution rather than the
bridge; the two fixes the benchmark forced (O(1) dependency tracking, one version node per
list) mattered far more (swap 328 → 16 ms). The JavaScript shim question stays open until
M5, with the numbers in `TODO.md`.

**Second measurement (2026-09-06, 0.8.0, `tools/profile_rows.py`).** The Python side is
three quarters of a 1,000-row create on MicroPython (124 ms of 160 with a renderer that
does nothing, against 27 of 140 on Pyodide, where the bridge is the cost and templates the
cure). Per row it is ~330 Python calls: element trees 19 ms per thousand, the `For` row and
its static build 55, the two holes 43 (a `RenderEffect` with its owner, state and closures
each), handlers 5, `Store` proxies 17. A method call costs 0.24 µs on MicroPython, an object
0.5 µs, a closure 0.15 µs, and **an `isinstance` against a tuple that misses 2.7 µs**, fifteen
times a single-class test; the hot paths use `type(x) is T` now. Trimming allocations did
nothing measurable; trimming calls (the builder caches its tag factories, static attributes
skip three calls, child insertion is inlined) gained 5%. The lever left is structural, fewer
calls per hole and per row, and it is an open item in `TODO.md`. Templates stay the default
on both: equal on MicroPython, a third faster on Pyodide.

**Third measurement (2026-09-06, 0.8.3).** The structural pass the second one asked for.
The one algorithmic find: **unsubscribing was O(observers)**, a scan of the source's list per
source, so disposing many computations that share a node was quadratic — 1,000 effects over
one signal took 78 ms to dispose against 10 ms to create. Both sides now record where the
other keeps them and a removal is a swap with the last entry: **78 ms → 3.3 ms**. The rows
benchmark does not show it (its rows share nothing), but any list whose rows read one signal
did. Trimming the rest gave create 1,000 rows **188 → 171 ms** on MicroPython and 89 → 85 on
Pyodide: a flatter `Effect` constructor, a hole's state as class attributes, cleanup
registration inlined, no normalising pass for a childless element. Two negative results worth
not repeating: **moving an owner's defaults to class attributes made it twice as slow**
(MicroPython walks the class chain for an attribute the instance does not have, and `_state`,
`_queued` and `_disposed` are read on every mark and flush), and a linear scan instead of the
dependency set measured no better. `clear` stays at 45 ms, and a 1,000-row create is bound by
element construction rather than by any one thing worth cutting.

**Fourth measurement (2026-09-07, the M11 spike).** Not the rows benchmark: *boot*, which no
earlier measurement had ever timed. The question was whether dropping PyScript for a direct
MicroPython-wasm load is worth the migration, and the answer had to be a number. The spike
loads the stock upstream `micropython.{mjs,wasm}` 1.28.0-6 — byte-identical to the build
PyScript already ships — plus the sixteen framework modules cross-compiled to `.mpy` and
packed in one tar, with a 2.2 KB loader. `examples/counter`, cold cache, median of five,
this laptop's Chromium, navigation until the app's first element is on screen:

| boot | ms | requests | bytes | gzipped |
|---|---|---|---|---|
| wasm, framework precompiled | **52** | **6** | 640,031 | 268,511 |
| PyScript, MicroPython | 88 | 29 | 905,330 | ~328,802 |
| PyScript, Pyodide | 844 | 33 | 1,531,941 | — |

So 41% off the boot and 29 requests down to 6. **Size is the least of it**: the framework as
sixteen `.py` files is 198,645 bytes raw and 53,126 gzipped, against 81,920 and 40,478 as
bytecode, a saving of 13 KB over the wire. What the compile buys is the *parse*, which
MicroPython was repeating on all 5,700 lines on every page view.

Three things the spike settled that no amount of reading would have. **`runtime.py`'s two
imports are the entire PyScript coupling**: patch them to `js` and `jsffi` and the framework
runs untouched, `.new()`, `create_proxy` and `to_js` included, because those are upstream
MicroPython rather than PyScript additions. **MicroPython cannot instantiate a module object**
(`type(sys)('__main__')` raises), so the app is exec'd against `runPython`'s own globals, which
are already `__main__`. And **`mpy-cross` from PyPI rejects two adjacent f-strings** —
`f"a" f"b"` fails where `f"a" "b"` compiles — which occurs exactly once in the package, at
`reactive.py:182`. That build is from 2025-08-10 and also predates PEP 750, so it cannot
compile a t-string at all; the framework is unaffected because its own source has none, and
app code keeps compiling in the VM, where a t-string example boots in 55 ms.

`romfs` was to be preferred over the tar and is genuinely available (`mp_js_register_romfs` is
an export of this build). It is not worth it: writing sixteen files into the in-memory
filesystem is lost in the noise of a 52 ms boot, and the image needs a builder the tar does
not. Thirty lines of JavaScript beat a new toolchain dependency.

**Fifth measurement (2026-09-08, M12, `FASTER.md` §2).** The interpreter itself, which no
earlier measurement had questioned. Upstream's `webassembly` port links with
`SUPPORT_LONGJMP=emscripten` — MicroPython's `nlr` is `setjmp`/`longjmp`, so every call out of
the bytecode loop goes through a JavaScript trampoline — never optimises at link time, and
freezes 27 library packages no page imports. Frontage's own variant (`tools/micropython/variant/`,
built by `mk runtime.wasm`) switches to wasm exception handling, links at `-Oz`, freezes
`asyncio` alone and drops the unused C modules. Same page, same framework, Chromium:

| `tools/profile_rows.py` | upstream | frontage's build |
|---|---|---|
| method call, per 10,000 | 2.3 ms | 0.8 ms |
| `For` of 1,000, null renderer | 102 ms | 43 ms |
| **create 1,000 rows, DOM, templates** | **139 ms** | **70 ms** |
| swap two rows | 12.1 ms | 4.3 ms |
| update every tenth row | 3.3 ms | 1.4 ms |
| `micropython.wasm`, brotli | 170 KB | 108 KB |

Every gallery card lost 188 KB on disk and none booted slower (`uber` went 328 → 93 ms, its
133 KB of data now parsed three times faster). What the faster interpreter exposes is the
next target: the null-renderer create is 43 ms and the DOM one 70, so the DOM side — a
`jsffi` proxy per node, 11,000 of them — is now 27 ms of the 70. That, and the 43 ms of
framework Python, is what the C core in `FASTER.md` §3–§4 is for.

## 13. Testing

- `SPEC.md` first: behaviours, one line each, grouped by chapter, in our words.
- **Reactive core**: exhaustive on CPython: the diamond and branching graphs, dynamic
  dependency changes, cleanup order, batch semantics, store node laziness.
- **Views** through `HtmlRenderer` (structure) and a recording fake renderer (which
  operations a change caused, and how few).
- **List reconciliation**: property-based against a brute-force reference: random
  sequences of keys, the DOM order equals the target, operation counts bounded.
- **Browser suite**: the examples under Playwright, `py` and `mpy`, Chromium every run,
  Firefox and WebKit nightly, PyScript served locally, `autouse` server fixture.
- **The rows benchmark** of section 12, run in CI for regressions.

## 14. Documentation and distribution

Docs on `academy.optersoft.com/tool/frontage`, one chapter per concept, in the order things
are needed rather than the order of this document: shipping comes second (Basic, Ship,
Template, Style, Flow, Async, Router, State, Prerender), so every project after the first
ends on a public URL. Each chapter has a repository at
`gitlab.com/optersoft/python/frontage-<chapter>` published on GitLab Pages by its own
pipeline, and runs that app in the page itself (the academy's `::: pyscript` frame, on
MicroPython from the released wheel; `frontage.optersoft.com` redirects to the academy and
keeps only the wheels and the playground). Distribution:
the wheel on PyPI and mirrored on the site; a `pyscript.json` of a few lines is the whole
install. Reference generated from docstrings.

## 15. License and ownership

**Apache License 2.0**, copyright Optersoft, S.L. Section 3 grants patents both ways,
section 5 makes contributions arrive under the same terms with no CLA, section 6 reserves the
Frontage trademark. Not the MIT OR Apache pair: a user choosing MIT would take none of those
obligations. PyScript is Apache 2.0; Solid and Leptos are MIT, which is why their ideas may
be studied freely and their code is not copied regardless. The fork in this repository's
history
keeps its own notice; the rewrite carries Optersoft's from the first commit.

## 16. Milestones

| | Deliverable | Done when |
|---|---|---|
| M0 ✅ | `SPEC.md`; the fork tree off `main`; skeleton; `Renderer` protocol with `HtmlRenderer` and a recording fake; local PyScript fixture | `mk check` green; hello-world renders to a string |
| M1 ✅ | reactive core (signals, memos, two-phase effects, owner, context, batch, `on`, `selector`); `Store` with draft writes; builder → `Template`; `DomRenderer`; delegated events; insert rules; `Show`, `For` (all keying modes); `bind:`; counter, todo and rows examples | unit suite green; browser suite green for those examples on both runtimes; the rows benchmark runs |
| M2 ✅ | `t"…"` templates; `Resource`, `Action`, `Loading`, `Errored`; `NodeRef`; `Dynamic`, `Portal`; fetch and forms examples; the shim decision of 8.6 | same; section 12 decided |
| M3 ✅ | router (nested, params, `preload`, `query`, `action`, `A`, three modes); contacts example; debug error page | full example suite green on Chromium, both runtimes |
| M4 ✅ | docs on academy (`python/frontage`, six chapters); landing page with the measured size; wheel on the site; `mk export` | **0.1.0** on PyPI, 2026-09-05 |
| M5 ✅ | `frontage.widgets`; `State` sugar; `interval` / `poll`; `reconcile`; the playground page; Firefox + WebKit nightly in CI; performance pass (numbers in TODO.md; no JS shim: MicroPython is bound by Python execution, not the bridge) | **0.2.0**, 2026-09-06 |
| M6 ✅ | prerendering through `HtmlRenderer` + hydration, as a static build step (`python -m frontage prerender`) | **0.4.0**, 2026-09-06 |
| M7 ✅ | the E2 debug warnings; `is_routing` across a route's resources and the scroll-restoration browser test; the `frontage` console script; `prerender --crawl`, `frontage.debug` with per-node hydration mismatches, ids per mount; async memos, `transition()` with `is_pending`, `use_transition` and `Optimistic` (Solid 2.0's model, on a synchronous graph: deferred render effects rather than concurrent rendering) | **0.5.0**, 2026-09-06 |
| M8 ✅ | concurrent rendering the way a synchronous graph can have it: during a transition every render effect computes at once, so the new state is built off screen and its resources start, and only the effect phase of what is on screen waits for the commit; `Router(transition=True)` / `navigate(…, transition=True)` | **0.6.0**, 2026-09-06 |
| M9 ✅ | async memos as the router's data primitive: `Memo(lambda: get_contact(params()["id"]))` counts toward `is_routing`, the route's transition and the prerenderer like a `Resource`, and hydrates by ordinal; `Resource` stays as the declared-source spelling | **0.7.0**, 2026-09-06 |
| 1.0 | freeze the API after 0.x has users; nothing scheduled | — |

## 17. Open decisions

1. MicroPython first-class or best-effort. Proposal: first-class, confirmed by section 12.
2. Template strings in M2 with the builder as fallback. Proposal: yes.
3. The JavaScript shim of 8.6. Proposal: pure Python first, shim only where measured.
4. Solid 1.x synchronous propagation versus Solid 2.0 microtask batching. Proposal: 1.x.
5. Whether `Store` is in 0.1 (this draft says yes, because Python state is dicts) or 0.2.
6. Accessor spelling: `count()` (Solid) or `count.get()` (Leptos). Proposal: `count()`, so
   the rule "a callable is reactive" has no exceptions; `.value` as a read-only property
   alias for people who find bare calls odd.
7. Whether `frontage.widgets` (the Streamlit/Shiny input catalogue) belongs in the core
   package or in a second package. Proposal: a subpackage of the core, so `pip download
   frontage` is still the whole install.
