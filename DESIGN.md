# Frontage design

**Status: draft 2, 2026-09-05.** Supersedes draft 1, which was written to keep PuePy's shape.
This draft is written from a study of [Leptos](https://github.com/leptos-rs/leptos) (Rust,
MIT), whose architecture is a better model for what a Python browser framework should be.
Decisions marked *open* are for David to settle; everything else is the proposal.

## 1. The decision

Frontage is a **clean-room implementation**, Optersoft's own code, of a reactive web framework
for Python in the browser. It replaces the PuePy fork on `main` today, which moves to the
branch `puepy-reference` and serves as an acceptance test until the rewrite passes the same
examples. The reasons are in draft 1 and still hold: ownership of copyright, license and
story. What changed is the model. PuePy rebuilds a whole page on every state change and
diffs it against the DOM. Leptos shows the other way, and it is the right one.

What carries over untouched: the name, PyPI plan, `pyproject.toml`, the uv/ruff/ty
toolchain, `ci.yml` with the OIDC publisher, the Cloudflare Pages site, `Makefile.py`.

## 2. What Leptos teaches, and what transfers

Leptos is ~80,000 lines of Rust across a dozen crates. Its ideas, not its code, are what
matter here. Five transfer directly to Python; two do not.

**Transfer:**

1. **Fine-grained reactivity instead of re-render and diff.** Signals, memos and effects
   form a graph. A signal read inside a view position creates an effect that updates that
   one text node or attribute. There is no virtual DOM and no morphing. `reactive_graph`'s
   README states the assumption: effects (DOM writes) are expensive, propagation is cheap.
   In PyScript that assumption is stronger still, because every DOM call crosses the
   Python-to-JavaScript bridge. The model that minimises DOM writes is the model for us.
2. **Ownership and cleanup.** Every effect and computation belongs to an `Owner`; when a
   view is removed its owner is disposed, which cancels effects, runs `on_cleanup`
   callbacks and drops what it held. In PyScript this is not a nicety: every Python
   callback handed to the DOM is a `create_proxy` that leaks unless destroyed. Frontage
   needs an owner tree from day one to have any story about memory at all.
3. **Control flow as components, keyed lists.** `Show`, `For` with a key function, `Either`,
   `Suspense`, `ErrorBoundary`. `For` diffs keys, not nodes, and moves existing DOM
   elements; a row whose key is unchanged is never touched, which is what keeps focus and
   input state, the "refs problem" PuePy needed a chapter for.
4. **URL drives state; nested routes.** The router matches a URL against a tree, renders
   each level into its parent's `Outlet`, exposes params and query as reactive values, and
   upgrades real `<a>` and `<form>` elements rather than replacing them.
5. **Async as reactive values.** A `Resource` is an async function that re-runs when the
   signals it read change and exposes its result as a signal; `Suspense` shows a fallback
   while resources under it load; `Action` is the same for mutations, with `pending` and
   `value` as signals. This is the whole story for "fetch some data", and PuePy had none.

**Do not transfer:**

- The statically typed view tree (`tachys`). It exists so Rust can monomorphise views;
  Python gets nothing from it. Our view tree is a plain object tree.
- `Copy` arena handles for signals. Rust needs them for closures; Python references suffice.
- Compile-time feature flags for `csr` / `ssr` / `hydrate`. Frontage detects its runtime.
- Server functions (`#[server]`). Frontage has no server half in 0.x. Section 8 keeps the
  door open.

## 3. Goals

1. **Python only, in the browser.** Reactive UI with no JavaScript, Node or bundler.
2. **Fine-grained.** A state change touches the DOM nodes that read it, nothing else.
3. **Two runtimes.** Pyodide and MicroPython, one codebase, the browser suite run on both.
4. **Small.** Core under ~4,000 lines, readable in an afternoon. This is what makes it
   teachable, and teaching is half of what Optersoft does.
5. **Renderer-agnostic views**, so the same view tree can render to a DOM or to an HTML
   string. This is what makes server rendering possible later without a rewrite.
6. **Honest testing.** The reactive graph and the string renderer test on plain CPython with
   no DOM at all; the examples run in a real browser under both runtimes in CI.

## 4. Non-goals for 0.x

- Server-side rendering and hydration as shipped features. The design allows them
  (section 8); 0.x does not deliver them.
- A component library or CSS framework.
- Import compatibility with PuePy. Porting an app is a rewrite of its views, mechanical
  but real. The shape below is different on purpose.
- PyScript releases older than the one the examples pin.

## 5. Clean-room rules

- **Consult:** PuePy's and Leptos's documentation and examples for behaviour and API design;
  the reactive-graph algorithm as described in Leptos's book appendix and the Reactively
  article it cites; PuePy's browser tests as an acceptance specification.
- **Do not copy:** source code, tests, docstrings or prose from either project. The code is
  written from `SPEC.md` (section 12) with neither repository open.
- **Where the old tree lives:** branch `puepy-reference`, never merged, deleted after 0.1.0.
- **Credit.** README: "Frontage's reactive model follows Leptos; the project began as a
  fork of PuePy." Courtesy, both true, neither an obligation.
- **Every PR states** it was written from the spec without reference source open.

## 6. Platform

| | |
|---|---|
| PyScript | ≥ 2026.7.3; examples pin one exact release, served locally in CI |
| Pyodide | 3.14 (2026.6.1+); Python 3.14 semantics, including template strings |
| MicroPython | the build PyScript ships (template strings, `weakref`, `asyncio.Future` since 2026.3.1) |
| Browsers | evergreen Chromium, Firefox, WebKit |
| Server | CPython ≥ 3.12 for tests, tooling and the string renderer |

**Both interpreters.** The package is written in the MicroPython subset: string annotations,
no runtime `typing`, no dataclasses, no `functools` beyond MicroPython's. Ruff's `UP` rules
stay off; the `mpy` browser job is the guard. *Open:* MicroPython first-class or
best-effort. Proposal: first-class; the small download is half the pitch, and Pyodide's 10 MB
is the number every PyScript sceptic quotes.

**The bridge** is `pyscript.document`, `pyscript.window`, `pyscript.ffi.create_proxy` /
`to_js`, `pyscript.js_modules` and `asyncio`, all present on both interpreters. Not
`pyscript.web`, which is a second element model we do not need.

## 7. The reactive core (`frontage.reactive`)

A direct port of the *idea* of `reactive_graph`, sized for Python.

```python
from frontage import Signal, Memo, Effect

count = Signal(0)
double = Memo(lambda: count.get() * 2)
Effect(lambda: print("double is", double.get()))   # runs once, then on change
count.set(2)
count.update(lambda n: n + 1)
```

- **Nodes**: `Signal` (source), `Memo` (source and subscriber), `Effect` (subscriber),
  `RenderEffect` (an `Effect` that runs synchronously on creation, for DOM binding).
- **Automatic, dynamic dependency tracking.** A global "current observer" stack; a `get()`
  while an observer runs records the edge; each run re-records from scratch, so a branch
  that stops reading a signal stops subscribing to it.
- **Three node states**, Clean / Check / Dirty, exactly as Leptos and Reactively describe:
  setting a signal marks it Dirty and its transitive subscribers Check; a Check node asks
  its sources to update first and recomputes only if one actually changed. Memos compare
  with `==` by default and accept an `equal=` function. Effects therefore run once per
  batch, never for an upstream change that netted out to no change.
- **Scheduling.** Setting a signal updates its value immediately; effects run on the next
  microtask (`queueMicrotask` in the browser, `asyncio.get_running_loop().call_soon` or
  synchronously under CPython tests). `batch()` defers until its block ends. `untrack()`
  reads without subscribing.
- **Ownership.** `Owner` is a tree. Every effect and memo is created under the current
  owner; a component's view runs under an owner of its own. `owner.dispose()` runs
  `on_cleanup` callbacks, cancels effects, disposes children, and **destroys every
  `create_proxy` registered under it**. `provide_context(value)` / `use_context(Type)` walk
  the owner tree; this is how a page shares state with deep descendants, and how the
  router hands params to a route.
- **Stores** (`frontage.store`, 0.2): nested reactivity over plain dicts and lists, one
  node per path, so `store["user"]["name"]` is readable as a signal and writing it does not
  notify `store["user"]["email"]`. Leptos's `reactive_stores`, in the shape Python data has.

The whole module is testable on CPython with no browser, and that test suite is where the
correctness of the framework lives.

## 8. Views (`frontage.view`)

**The view tree is plain objects**, built two ways that produce the same thing.

**The builder**, always available and what the template compiles to (Leptos's
`counter_without_macros`):

```python
from frontage import html as h

def counter(initial=0):
    count = Signal(initial)
    return h.div(
        h.button("-", on_click=lambda ev: count.update(lambda n: n - 1)),
        h.span("Value: ", count, "!"),
        h.button("+", on_click=lambda ev: count.update(lambda n: n + 1)),
        cls="counter",
    )
```

**The template**, a Python 3.14 template string (PEP 750), available on both interpreters,
parsed once per call site and cached; Frontage's answer to `view!`:

```python
def counter(initial=0):
    count = Signal(initial)
    return html(t"""
        <div class="counter">
            <button on:click={lambda ev: count.update(lambda n: n - 1)}>-</button>
            <span>Value: {count}!</span>
            <button on:click={lambda ev: count.update(lambda n: n + 1)}>+</button>
        </div>
    """)
```

*Open:* template strings are new in 3.14 and in MicroPython 2026.3; if either implementation
proves incomplete, the template layer waits and the builder ships alone. Proposal: build the
builder first (M1), the template on top (M2), and let the tutorial teach the template.

**Children** may be: `str` (a text node), a `Signal` or `Memo` (a text node bound by a
`RenderEffect`), a zero-argument callable (same, tracked), another view, `None` (nothing),
or a list. **Attributes** are keyword arguments; a `Signal` or callable value becomes a
bound attribute. Prefixes follow Leptos because they name real DOM distinctions the
beginner will otherwise hit as bugs: `attr` (default), `prop_value` (a DOM property, the
one that works for form inputs), `class_active=signal` (toggle one class), `style_color`,
`on_click` (event), `bind_value=signal` (two-way, on `input`), `bind_checked`,
`bind_group`, `ref=NodeRef()`.

**Components are functions.** A component is a function that takes keyword props, runs
once under its own `Owner`, and returns a view. Props that are signals stay reactive
inside; plain values are plain. `children` is a callable returning a view; named slots are
callables passed as props. No base class, no `populate()`, no magic attribute lookup.

**Control flow**, as components:

| | |
|---|---|
| `Show(when=signal, fallback=..., children)` | mounts one branch, toggles without rebuilding |
| `For(each=signal_of_list, key=fn, children=fn(item))` | keyed; adds, removes and moves rows, never rebuilds one whose key survived |
| `Either(cond, a, b)` / `Match(signal, {case: view})` | branch by value |
| `Suspense(fallback, children)` | fallback while any `Resource` read beneath is loading |
| `Transition` | `Suspense` that keeps the old view while reloading |
| `ErrorBoundary(fallback=fn(errors), children)` | catches exceptions raised in effects beneath; renders the fallback |
| `Portal(target, children)` | render into another DOM node |

**Renderers.** The view tree does not touch `document` directly. It talks to a `Renderer`
with a dozen methods (`create_element`, `create_text`, `set_attribute`, `set_property`,
`insert_before`, `remove`, `add_listener`, …). Two implementations: `DomRenderer` in the
browser, `HtmlRenderer` on CPython, which writes an HTML string. The second is what makes
the view layer unit-testable without a browser, and it is the seam server rendering would
later plug into: a Python web server rendering the first paint, PyScript hydrating it.
Hydration is not in 0.x; the marker comments it would need are designed in now and cost
nothing.

**Events are delegated.** One listener per event type on the mount root, dispatching by
element identity to the Python handler. In PyScript this replaces one `create_proxy` per
handler with one per event type, and a removed element's handler is simply dropped from a
dict. Leptos does this behind a feature flag; here it is the only mode. Handlers may be
`async def`. `Event(name)` creates a custom event a child can `emit()` to a parent.

## 9. Async (`frontage.async_`)

- `Resource(fetcher)`: runs `fetcher` (an `async def`) under tracking, re-runs when a signal
  it read changes, exposes `.get()` (value or `None`), `.loading`, `.error` as signals.
  `Suspense` finds the resources read under it through the owner tree.
- `Action(fn)`: `.dispatch(input)` runs `fn(input)` once; `.pending`, `.value`, `.input`
  are signals. What a form submits to.
- Tasks are spawned with `asyncio.create_task` on both interpreters; every task is owned,
  so a disposed owner cancels its in-flight fetches.

## 10. Router (`frontage.router`)

Leptos's principles, verbatim: URL drives state; nested routing; progressive enhancement.

```python
app = Router(
    Route("/", Home),
    Route("/contacts", ContactList, children=[
        Route(":id", Contact, children=[
            Route("", ContactInfo),
            Route("conversations", Conversations),
        ]),
        Route("", SelectAContact),
    ]),
    fallback=NotFound,
)
mount("#app", app)
```

- **Nested routes** render into the parent's `Outlet()`. Navigating between siblings
  re-renders only the level that changed; the parent's state and effects survive.
- **Params and query** are memos: `use_params()["id"]` is reactive, so a `Resource` that
  reads it reloads on navigation.
- **Plain `<a>` works.** The router intercepts same-origin clicks at the document level (one
  delegated listener) and calls `history.pushState`. `A(href)` additionally resolves
  relative paths within nested routes and sets `aria-current`. `Form` does the same for
  `GET` forms. Nothing here needs a component to be a link.
- History and hash modes; hash for the no-server tutorial case.
- `navigate(path)`, `Redirect(path)` raised from a component body.

## 11. Errors and development mode

Exceptions in a component body or an effect are routed to the nearest `ErrorBoundary`; with
none, to the mount root, which in `debug=True` renders the traceback with the component and
signal named, and in production renders a configured fallback and logs. Both interpreters
give tracebacks; the debug page makes them readable in a `<pre>`.

## 12. Testing

- `SPEC.md` first: behaviours, one line each, grouped by chapter, written in our words
  from both projects' docs. The clean-room artefact and the checklist.
- **Reactive core**: exhaustive unit tests on CPython, including the diamond and
  branching graphs the Leptos appendix draws, cleanup ordering, and batch semantics.
- **Views**: unit tests through `HtmlRenderer` (structure) and through a small recording
  fake renderer (which DOM operations a state change caused, and how few).
- **Keyed diff**: property-based tests against a brute-force reference: random key
  sequences, assert the DOM order equals the target and count operations.
- **Browser suite**: the examples under Playwright, `py` and `mpy`, Chromium every run,
  Firefox and WebKit nightly; PyScript served from a local copy; the server fixture is
  `autouse`.

## 13. Documentation and distribution

Docs on `academy.optersoft.com/tool/frontage`, chapter per concept in the order above,
each chapter with its live example on `frontage.optersoft.com/examples/…`. Distribution is
the wheel on PyPI and mirrored on the site, plus a three-line `pyscript.json` that is the
whole install. Reference generated from docstrings.

## 14. License and ownership

**Apache License 2.0**, copyright Optersoft, S.L. Not the MIT OR Apache pair the Python CLIs
use: for a company the value of Apache is section 3 (patent grant both ways), section 5
(contributions arrive under the same terms, no CLA), and section 6 (no trademark rights). A
dual license lets the user pick MIT and take none of those obligations, which is the Rust
ecosystem's convention and a loss here. PyScript itself is Apache 2.0. Frontage is a
trademark of Optersoft, stated in README and NOTICE. The fork on `puepy-reference` stays
under its own Apache 2.0 notice; the rewrite carries Optersoft's from the first commit.

## 15. Milestones

| | Deliverable | Done when |
|---|---|---|
| M0 | `SPEC.md`; `puepy-reference` branch; skeleton; local PyScript fixture; `Renderer` protocol with `HtmlRenderer` and a fake | `mk check` green; hello-world renders to a string |
| M1 | `reactive` (signals, memos, effects, owner, context, batch); `view` builder; `DomRenderer`; delegated events; `Show`, `For`; `bind_*`; counter and todo examples | unit suite green; browser suite green for those examples on both runtimes |
| M2 | `t"…"` templates; `Resource`, `Action`, `Suspense`, `Transition`; `ErrorBoundary`; `NodeRef`; fetch and forms examples | same |
| M3 | `router` (nested, params, `A`, `Form`, hash + history); contacts example; debug error page | full example suite green on Chromium, both runtimes |
| M4 | docs on academy; landing page; wheel on the site | **0.1.0** on PyPI |
| M5 | `store`; Firefox + WebKit in CI; `Portal`; performance pass with the js-framework-benchmark rows example | **0.2.0** |
| later | `HtmlRenderer` exposed as server rendering; hydration; islands | when someone needs it |

## 16. Open decisions

1. MicroPython first-class or best-effort (section 6). Proposal: first-class.
2. Template strings in M2, or builder only until t-strings prove solid on both runtimes
   (section 8). Proposal: M2, with the builder as the fallback the tutorial can switch to.
3. Attribute prefix spelling: `on_click` / `class_active` / `prop_value` as keyword
   arguments, or a single `attrs={}` dict with `"on:click"` keys. Proposal: keywords; they
   read as Python and the template syntax uses the colon form.
4. Whether `Store` ships in 0.1 or 0.2. Proposal: 0.2.
5. Whether to design the hydration markers now (cheap) or leave server rendering out of the
   view layer entirely (simpler). Proposal: design the seam, ship nothing.
