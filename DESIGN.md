# Frontage design

**Status: implemented through M5 (0.2.0, 2026-09-06); draft 4 of 2026-09-05 is the plan it followed.** Draft 1 kept PuePy's shape. Draft 2 was written from Leptos.
Draft 3 added [Solid](https://github.com/solidjs/solid) (1.x, `dom-expressions`, the store,
`solid-router`, the 2.0 release candidate), the JavaScript origin of the model and the size
reference. This draft adds the three Python-first frameworks, [Streamlit](https://github.com/streamlit/streamlit),
[Shiny for Python](https://github.com/posit-dev/py-shiny) and [Reflex](https://github.com/reflex-dev/reflex),
with one question asked of each: what happens when it has to run in WebAssembly. Two of them
already do (stlite, Shinylive), and that evidence shapes section 2b. Decisions marked *open*
are for David.

## 1. The decision

Frontage is a **clean-room implementation**, Optersoft's own code, of a fine-grained
reactive web framework for Python in the browser. The PuePy fork on `main` moves to the
branch `puepy-reference` and serves as an acceptance test until the rewrite passes its
examples. Reasons (ownership of copyright, license and story) are in draft 1 and hold.

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
4. **Two runtimes.** Pyodide and MicroPython, one codebase, both in CI.
5. **Small and teachable.** Core under ~4,000 lines; a reader can hold it in a day.
6. **Renderer-agnostic views**: DOM in the browser, HTML string on CPython; server rendering
   stays possible without a rewrite (section 8).
8. **Python is the control flow.** `if`, `for`, comprehensions and function calls work
   inside a view because the Python is in the browser. `Show` and `For` exist for
   fine-grained efficiency, never as a required DSL. No `cond`, no `foreach`, no `Var`.
7. **Honest testing**: the reactive core and the view layer test on CPython with no browser;
   the examples run in real browsers under both runtimes.

## 4. Non-goals for 0.x

Server rendering and hydration as shipped features; transitions and optimistic updates; a
component library; PuePy import compatibility; PyScript releases older than the pinned one.

## 5. Clean-room rules

- **Consult:** the documentation and examples of PuePy, Leptos and Solid; the reactive-graph
  algorithms as described in their books and READMEs (Reactively's article, Solid's
  "fine-grained reactivity" guide); PuePy's browser tests as an acceptance specification.
- **Do not copy:** source, tests, docstrings or prose from any of them. Code is written from
  `SPEC.md` (section 13) with no reference repository open.
- **Old tree:** branch `puepy-reference`, never merged, deleted after 0.1.0.
- **Credit** in README: "Frontage's reactive model follows Solid and Leptos; the project began
  as a fork of PuePy." True, courteous, not required.
- **Every PR states** it was written from the spec without reference source open.

## 6. Platform

| | |
|---|---|
| PyScript | ≥ 2026.7.3; the examples pin one exact release, served locally in CI |
| Pyodide | 3.14; Python 3.14 semantics incl. template strings (PEP 750) |
| MicroPython | the build PyScript ships (template strings, `weakref`, `asyncio.Future` since 2026.3.1) |
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

Docs on `academy.optersoft.com/tool/frontage`, one chapter per concept in the order of this
document, each with its live example on `frontage.optersoft.com/examples/…`. Distribution:
the wheel on PyPI and mirrored on the site; a `pyscript.json` of a few lines is the whole
install. Reference generated from docstrings.

## 15. License and ownership

**Apache License 2.0**, copyright Optersoft, S.L. Section 3 grants patents both ways,
section 5 makes contributions arrive under the same terms with no CLA, section 6 reserves the
Frontage trademark. Not the MIT OR Apache pair: a user choosing MIT would take none of those
obligations. PyScript is Apache 2.0; Solid and Leptos are MIT, which is why their ideas may
be studied freely and their code is not copied regardless. The fork on `puepy-reference`
keeps its own notice; the rewrite carries Optersoft's from the first commit.

## 16. Milestones

| | Deliverable | Done when |
|---|---|---|
| M0 ✅ | `SPEC.md`; `puepy-reference` branch; skeleton; `Renderer` protocol with `HtmlRenderer` and a recording fake; local PyScript fixture | `mk check` green; hello-world renders to a string |
| M1 ✅ | reactive core (signals, memos, two-phase effects, owner, context, batch, `on`, `selector`); `Store` with draft writes; builder → `Template`; `DomRenderer`; delegated events; insert rules; `Show`, `For` (all keying modes); `bind:`; counter, todo and rows examples | unit suite green; browser suite green for those examples on both runtimes; the rows benchmark runs |
| M2 ✅ | `t"…"` templates; `Resource`, `Action`, `Loading`, `Errored`; `NodeRef`; `Dynamic`, `Portal`; fetch and forms examples; the shim decision of 8.6 | same; section 12 decided |
| M3 ✅ | router (nested, params, `preload`, `query`, `action`, `A`, three modes); contacts example; debug error page | full example suite green on Chromium, both runtimes |
| M4 ✅ | docs on academy (`python/frontage`, six chapters); landing page with the measured size; wheel on the site; `mk export` | **0.1.0** on PyPI, 2026-09-05 |
| M5 ✅ | `frontage.widgets`; `State` sugar; `interval` / `poll`; `reconcile`; the playground page; Firefox + WebKit nightly in CI; performance pass (numbers in TODO.md; no JS shim: MicroPython is bound by Python execution, not the bridge) | **0.2.0**, 2026-09-06 |
| later | server rendering through `HtmlRenderer`; hydration; async memos, `is_pending`, transactions and optimistic writes (Solid 2.0's model) | 1.0 |

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
