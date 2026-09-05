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
- C16 Raising `NotReady` inside a compute ends it quietly; the nearest `Loading` boundary shows its fallback; no `Errored` boundary sees it. [M2]
- C17 Any other exception inside a compute propagates to the nearest `Errored` boundary, else to the mount root. [M2]
- C18 `interval(seconds)` is an accessor that changes every `seconds`; `poll(fn, seconds)` is a `Resource` re-run on that interval; both stop when their owner is disposed. [M5]

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
- U10 `use_before_leave()` can cancel a navigation; scroll position is restored on back. [M3]

## 9. Errors and development mode

- E1 In debug mode an uncaught error renders a page naming the component and the traceback; in production the configured fallback renders and the error is logged. [M2]
- E2 Debug warnings: a read after `await` (A3), a write inside a tracked compute, a `For` whose keys are not unique. [M2]
