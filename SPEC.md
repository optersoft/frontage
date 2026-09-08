# Frontage behaviour specification

One line per observable behaviour, grouped by chapter, written in our words from the
documentation of PuePy, Solid and Leptos and from the design in `DESIGN.md`. This is the
clean-room artefact: code is written from this file, not from any reference source. Each
line is a test to write. `[M1]` etc. marks the milestone that must satisfy it.

## 1. Runtime

- R1 `frontage.platform` is one of `pyodide`, `micropython`, `cpython`; `in_browser` is true for the first two. [M0]
- R2 On CPython, touching a browser global (`document`, `window`) raises `RuntimeError` naming the global; it is falsy. [M0]
- R3 The package imports without error under both browser interpreters and on CPython; no module imports `js` or `pyscript` except `runtime`. [M0]
- R4 Nothing in the package uses `typing`, dataclasses or any stdlib module MicroPython lacks. [M0, enforced by R3 under `mpy`]

## 2. Renderer seam

- S1 A `Renderer` provides: `create_element`, `create_text`, `replace_text`, `set_property`, `insert_node(parent, node, anchor=None)`, `remove_node`, `is_text`, `parent`, `first_child`, `next_sibling`. [M0]
- S2 `HtmlRenderer` produces nodes that serialise to HTML with text escaped, attribute values quoted and escaped, boolean attributes bare, `None`/`False` removing an attribute, void elements unclosed. [M0]
- S3 `insert_node` with an anchor places the node before it; without, appends; inserting an already-placed node moves it. [M0]
- S4 `RecordingRenderer` logs every operation so a test can assert an update's cost. [M0]
- S5 `DomRenderer` implements the same operations on the browser DOM; `set_property` distinguishes attributes from properties (`value`, `checked`, `selected` are properties). [M1]
- S6 `clone_template(html)` creates a `<template>` once per distinct HTML string and returns a fresh clone in one operation. [M1]

## 3. Static views (the `h` builder)

- V1 `h.tag(*children, **attrs)` builds an `Element`; a string, number or `Text` child becomes a text node; `None`, `True`, `False` render nothing; lists flatten. [M0]
- V2 `cls`/`class_` → `class`, `for_` → `for`, a trailing underscore is dropped, other underscores become hyphens (`data_id` → `data-id`, `aria_label`). [M0]
- V3 `h.sl_button` and `h("sl-button")` both build the custom element `sl-button`. [M0]
- V4 Inside `with h.tag(...):`, elements and `text()` calls append to the open element; the block leaves no state behind. [M0]
- V5 `render_to_string(view)` returns the HTML of a view with no browser. [M0]
- V6 `build(view, renderer)` issues exactly one `create_*` per node and one `insert_node` per child. [M0]

## 4. Reactive core

- C1 `Signal(v)` is an accessor: `s()` reads, `s.set(v)` writes, `s.update(fn)` writes `fn(old)`; `s.value` mirrors `s()`. [M1]
- C2 A write with an equal value (`==`, or the signal's `equal=` function) notifies nobody. [M1]
- C3 Reading an accessor inside a running computation records a dependency; a computation re-records its dependencies on every run, so a branch that stops reading a signal stops depending on it. [M1]
- C4 `Memo(fn)` caches `fn()`, recomputes lazily when a dependency changed, and notifies its own dependents only when its value changed. [M1]
- C5 Propagation is synchronous: after `s.set(v)` returns, every memo that reads `s` returns its new value. [M1]
- C6 Effects run once at the end of the outermost `batch()`; a plain write is an implicit batch; an effect runs at most once per batch however many of its dependencies changed. [M1]
- C7 `Effect(compute, effect)`: `compute` runs tracked and returns a value; `effect(value, prev)` runs untracked afterwards and may return a cleanup that runs before the next `effect` call and on disposal. `Effect(fn)` is shorthand for a tracked `fn`. [M1]
- C8 `RenderEffect` is an `Effect` whose effect phase runs before user effects in the same batch. [M1]
- C9 A diamond (`a` → `b`, `a` → `c`, `b` and `c` → `d`) recomputes `d` once per change of `a`, never with a stale input. [M1]
- C10 `untrack(fn)` runs `fn` without recording dependencies; `on(deps, fn)` runs `fn` with exactly `deps` as dependencies. [M1]
- C11 `Memo`, `Effect` and `RenderEffect` work as decorators (`@Memo` on a function yields the accessor). [M1]
- C12 Every computation is created under the current `Owner`; `Owner.dispose()` disposes children first, runs `on_cleanup` callbacks in reverse order of registration, cancels the owner's effects, destroys its JavaScript proxies and drops its delegated-event registrations. [M1]
- C13 A computation that re-runs disposes what it owned during its previous run before running again. [M1]
- C14 `provide(ctx, value)` / `use(ctx)` resolve through the owner tree; `use` outside any provider returns the context's default. [M1]
- C15 `selector(source)` returns `is_selected(key)` such that only the rows whose key equals the old or new value are notified when `source` changes. [M1]
- C16 Raising `NotReady` inside a compute ends it quietly; the nearest `Loading` boundary shows its fallback; no `Errored` boundary sees it. A `Memo` whose compute ended so raises `NotReady` to its readers and registers with the reader's `Loading` boundary (the memo may live above it), so a hole never sees `None` in its place. [M2; the memo half 0.8.2]
- C17 Any other exception inside a compute propagates to the nearest `Errored` boundary, else to the mount root. [M2]
- C18 `interval(seconds)` is an accessor that changes every `seconds`; `poll(fn, seconds)` is a `Resource` re-run on that interval; both stop when their owner is disposed. [M5]
- C19 A `Memo` whose function returns a coroutine is an async memo: the reads made while calling the function (before the coroutine runs) are its dependencies; the coroutine runs as a task owned by the memo; reading it raises `NotReady` until the first value and returns the previous value while a later run is in flight; `loading()` says which; an exception in the coroutine is raised to readers; a re-run cancels the coroutine in flight. [M7]
- C20 `transition(fn)`: the render effects the writes in `fn` dirty compute at once, so the new state is built off screen (a branch or component the writes create is built under its own owners and its resources start loading), but their effect phase, which would put it on the page, waits until every `Resource` load and async memo run the transition started has settled; then they apply in one batch, recomputing whatever changed meanwhile. No `Loading` fallback appears on the page. `is_pending()` is true meanwhile; the returned `Transition` has `pending`, `wait()` and `on_commit`; a transition with no async work commits at once. An effect whose target is already off screen applies at once. [M7, off-screen build M8]
- C21 `Optimistic` is a `Signal` whose write inside a transition renders at once (the effects downstream of it run despite the transition) and is undone when the transition commits. [M7]
- C24 A task disposed by its own owner (`spawn`; an action that navigates away disposes the component that owns it) is not cancelled from inside itself: it runs to its end (MicroPython refuses a self-cancel). A `transition()` whose function raises still closes, so nothing it parked is lost. [0.8.2]
- C22 `is_pending(x)` for a `Resource`, an async `Memo`, an `Action` or a `Transition`; `use_transition()` returns `(pending, start)` where `pending()` covers the transitions started with `start`. [M7]

## 5. Stores

- T1 `Store(data)` wraps a dict or list; `store["k"]`, `store.k`, `len`, iteration and `in` work; nested containers come back wrapped. [M1]
- T2 A tracked read of `store["k"]` creates a node for that key on first read; untracked keys create nothing. [M1]
- T3 `store.set(lambda d: ...)` applies mutations through a draft inside a batch, notifying exactly the keys written and, for lists, `length` and the shifted indices. [M1]
- T4 Writing a key to its current value notifies nobody; deleting a key notifies it and `in`-checks on it. [M1]
- T5 `store.set_path("user", "name", v)` is the path form of T3. [M1]
- T6 `reconcile(data, key="id")` updates a store from fresh data preserving the identity of rows whose key survives, so a `For` over it moves rather than recreates. [M5]
- T7 `snapshot(store)` returns plain, unwrapped data. [M1]

## 6. Reactive views

- W1 Any callable in a child position is a hole bound by a `RenderEffect`; a `Signal`/`Memo` is a callable. [M1]
- W2 A hole whose value is a string or number updates its text node in place; `None`/`bool` renders nothing; a view mounts; a list is reconciled by node identity, moving existing nodes rather than recreating them. [M1]
- W3 A change to one signal touches exactly the holes that read it: `RecordingRenderer` shows no operation on any other node. [M1]
- W4 A callable attribute value is bound; `attr:` (default) sets attributes, `prop:` sets properties, `class:name={bool}` toggles one class, `class={dict}` toggles many, `style:prop` sets one style, `bind:value` / `bind:checked` / `bind:group` are two-way with an `input` listener. [M1]
- W5 A component is a function of keyword props run once under its own owner; its return is a view, a list, or control flow (`Show(…)` directly); no wrapper element is added. [M1, control flow M3]
- W6 `Show(when, fallback, children)` mounts one branch and toggles without rebuilding the mounted one; `keyed=True` rebuilds when the value changes; `children` may be a function of the value. [M1]
- W7 `For(each, children, key=…)`: identity keys by default, `key=fn` extracts one, `key=False` is index mode where the item is an accessor; unchanged keys keep their nodes and their focus; rows dispose individually. [M1]
- W8 `Switch`/`Match` mount the first matching branch. [M2]
- W9 `Loading(fallback, children)` shows `fallback` while any `Resource` read beneath it is loading; nested boundaries are independent. [M2]
- W10 `Errored(fallback, children)`: `fallback(error, reset)`; `reset()` re-runs the failed subtree. [M2]
- W11 `Dynamic(component, **props)` and `Portal(mount, children)`. [M2]
- W12 `NodeRef()` passed as `ref=` holds the element after mount and `None` before. [M2]
- W13 Events are delegated: bubbling events get one document listener per type; the handler dispatched is the registered ancestor's, `currentTarget` is that ancestor, `disabled` elements are skipped, `stop_propagation()` ends the walk; non-bubbling events attach directly; `on:` forces direct, `oncapture:` the capture phase. [M1]
- W14 A handler may be `async def`; its exceptions reach the nearest `Errored`. [M2]
- W15 `Event(name)` creates a custom event a child can `emit(detail)` to a parent listening with `on:name`. [M2]
- W16 A template string `html(t"…")` parses once per call site, producing the same tree the builder would; holes in text, attribute and event positions bind as W1 and W4. [M2]
- W17 Instantiating a template clones its skeleton in one renderer operation and then binds only its holes. [M1 builder, M2 template]
- W18 `unique_id()` counts per mount and names the mount's target (`fr-app-1`), so two mounts on a page, or two interpreters, never hand out the same id, and a prerendered mount and its hydration count alike (`mount(scope=…)` names it explicitly; outside any mount the counter is global). [M7]

## 7. Async

- A1 `Resource(fetcher, source=None)` runs `fetcher` (async) once, and again whenever `source` changes; it is an accessor of the latest value: while the first load is pending it raises `NotReady` (so a hole reads it without a `None` check and the nearest `Loading` shows its fallback); while a reload is pending it returns the previous value. [M2]
- A2 `.loading`, `.error`, `.state` are accessors; `.refetch()` re-runs; `.mutate(v)` sets the value without fetching. [M2]
- A3 Reactive inputs read after the first `await` are not tracked; in debug mode a read after `await` warns. [M2]
- A4 `Action(fn)`: `.dispatch(x)` runs `fn(x)`; `.pending`, `.value`, `.input` are accessors. [M2]
- A5 A task spawned by a resource or action is cancelled when its owner is disposed. [M2]

## 8. Router

- U1 `Router(*routes, mode="history"|"hash"|"memory")` matches the current URL against a route tree; the deepest match renders inside its parents' `children`. [M3]
- U2 `:param` segments and `*rest` wildcards; `use_params()`, `use_query()`, `use_location()` are accessors. [M3]
- U3 Navigating between sibling routes re-renders only the changed level; parent state survives. [M3]
- U4 A same-origin `<a>` click is intercepted and navigates without a page load; `A(href)` also resolves relative paths and sets the active class. [M3]
- U5 `navigate(path)`, `Navigate(to)`, `Redirect(path)` raised from a component body. [M3]
- U6 A route's `preload(params)` runs before render and on link hover. [M3]
- U7 `query(fn)` de-duplicates concurrent calls with equal keys and caches results until `revalidate()`. [M3]
- U8 `action(fn)` with `use_submission()`; `redirect()` raised inside an action navigates. [M3]
- U9 Memory mode drives the router with no browser; the whole router suite runs on CPython. [M3]
- U10 `use_before_leave()` can cancel a navigation; scroll position is restored on back, once the page navigated back to is on screen (the router sets `history.scrollRestoration` to manual). [M3, browser test M7]
- U11 `is_routing` stays true from a navigation until the preloads it started *and* the first loads of the `Resource`s the new route created have settled. [M7]
- U12 `Router(transition=True)`, or `navigate(path, transition=True)` for one call, runs the navigation as a transition (C20): the new route is built off screen, its resources load, and the page changes when they are ready; the scroll to the top (or the restored position on back) happens at the commit. [M8]
- U14 A route's `preload` that fails is a warning, never an error page: the component's own load surfaces the error in its boundary. `query` re-raises the failure to callers that waited on the same key. [0.8.2]
- U13 An async `Memo` created while a route renders counts toward `is_routing` like a `Resource` (U11), so `Memo(lambda: get_contact(params()["id"]))` is a route's data primitive: the id is tracked, a `preload` warms the same `query`, and the route's transition (U12) and the prerenderer (L9) wait for it as for a Resource. [M9]
- U15 `Route(path, lazy="pages.map:page")` names a module instead of a component. `frontage build` leaves that module, and whatever only it imports, out of the first payload and writes it beside the page as a *chunk*; the page fetches it the first time it goes to that route. While the chunk is in flight the route is not ready: the nearest `Loading` shows its fallback (W9), `is_routing` stays true (U11), a transition holds the old page (U12), and a failed fetch reaches the nearest `Errored` (W10). An `A` to such a route prefetches its chunk on hover. Off the browser — the tests, the language server, the prerenderer — the module is simply imported, so a lazy route renders like any other. [0.10.3]

## 9. Errors and development mode

- E1 In debug mode an uncaught error renders a page naming the component and the traceback; in production the configured fallback renders and the error is logged. [M2]
- E2 Debug warnings, once each, in the console (or stderr): a signal read inside a `Resource` fetcher or an async memo's coroutine after tracking ended (A3), naming the resource; a write to a signal inside a tracked computation, naming it; a `For` keyed by identity whose rows all failed to survive an update. Duplicate `For` keys stay an error. `mount(debug=False)` silences them. [M7]
- E4 Under `frontage serve` a save that cannot work shows an overlay over the page rather than a blank page or a console line: a file that does not compile shows the compiler's message and nothing is torn down, so the last working page keeps running underneath with its state; an entry that raises while the page is rebuilding shows the traceback. The next save that works takes the overlay away. A built page has no overlay. [0.10.3]
- E3 `import frontage.debug` makes a hydration that rebuilt nodes list each mismatch (`expected <b>, found <i>`, `dropped <i>: …`) and keeps the last `Hydration` in `frontage.debug.last_hydration`. [M7]

## 10. The layer above (M5)

- L1 `State` subclasses declare fields with `field(default)`; each instance gets a signal per field; reading the attribute tracks, assigning writes; `@computed` is a memo per instance; methods are handlers; `signal(name)` returns the Signal. Works on MicroPython (no `__getattribute__`, no `__mro__`). [M5]
- L2 `frontage.widgets`: `text_input`, `textarea`, `number_input`, `slider`, `checkbox`, `select`, `radio_group`, `button`, each bound to a Signal, with an optional label and a class hook. [M5]
- L3 `interval(seconds)` is an accessor that increments on a schedule and stops with its owner; `poll(fetcher, seconds)` is a Resource re-run on it. [M5]
- L4 `reconcile(store_list, data, key)` updates a list Store to equal `data` while keeping the identity of rows whose key survives, so a `For` moves nodes and only changed fields notify. [M5]
- L5 `mk export APP` produces a static directory that runs the app with no repo, PyPI or CDN. [M4]
- L6 The playground runs code from the URL fragment against the site's package under MicroPython. [M5]
- L7 `frontage prerender --crawl` also renders every route the rendered pages link to (an `A`, a plain `<a href>`), filtered to the mounted `Router`'s routes. [M7]
- L8 `pip install frontage` puts a `frontage` console script on PATH with the same commands as `python -m frontage`; usage lines name whichever was invoked. [M7]
- L10 `frontage serve [DIR]` serves a directory uncached, injects a reload script into every HTML page it sends, polls the files under it (and `--watch` directories) and reloads every open page when one changes: Vite's loop for a page that has to boot its interpreter again. [M9]
- L9 `frontage prerender` waits for every async `Memo` a mount created, as it does for resources, and writes their values into the page by the memo's ordinal among the mount's memos; a hydrating mount hands each value back and the memo settles with it, its coroutine never run. Pages written before 0.7.0 (a list of resource values) still hydrate. [M9]
