# Frontage design

**Status: draft, 2026-09-05.** Decisions marked *open* are for David to settle; everything
else is the proposal. This document is the plan for rewriting Frontage as Optersoft's own
code. It replaces nothing yet: the tree on `main` today is the PuePy fork and stays the
executable reference until the rewrite passes the same examples.

## 1. The decision

Frontage started on 2026-09-05 as a fork of PuePy 0.6.5. The fork works, but it can never be
fully Optersoft's: the copyright is the upstream authors', the license is fixed at Apache 2.0,
attribution travels with every distribution, and the story is "we adopted a dormant project".
For a public flagship of a studio that sells development, training and consulting, ownership
is the point. So Frontage is rewritten from scratch as a **clean-room implementation**:
same job, same shape where the shape is good, none of the code.

What carries over untouched: the name, the PyPI plan, `pyproject.toml` and the uv/ruff/ty
toolchain, `ci.yml` with the OIDC publisher, the Cloudflare Pages site and landing page,
`Makefile.py`, and the repo conventions. What is replaced: `frontage/`, `tests/`,
`examples/`, `docs/`.

## 2. Goals

1. **Python only, in the browser.** A developer who knows Python and HTML builds a reactive
   single-page app with no JavaScript, no Node and no bundler. Deployment is serving files.
2. **Small enough to read.** The core stays under ~3,000 lines. A user can read the whole
   framework in an afternoon, which is also what makes it teachable in a course.
3. **Two runtimes.** Pyodide for the full standard library and PyPI, MicroPython for a
   download an order of magnitude smaller. The same app runs on both.
4. **Current PyScript.** Target the 2026 line from day one (2026.7.3 at writing), through the
   `pyscript` module, not the raw `js` module, so the same import works on both interpreters.
5. **Honest testing.** Unit tests that run anywhere, plus the examples driven in a real
   browser under both runtimes, with PyScript served locally so CI does not depend on a CDN.

## 3. Non-goals

- Server-side rendering or hydration. Frontage renders in the browser, full stop. SEO-facing
  sites are not its audience; the docs say so.
- A component library or a CSS framework. Tailwind, Bootstrap and Shoelace work through
  plain classes and web components, as the examples show.
- Compatibility with PuePy at the import level. `from puepy import …` will not work. Porting
  a PuePy app should be a rename plus a handful of mechanical edits (section 6), no more.
- Supporting PyScript releases older than the one the examples pin.

## 4. Clean-room rules

These make "Optersoft's own code" true rather than a claim.

- **What may be consulted:** PuePy's documentation and examples for *behaviour* (what a
  feature does, what the tutorial teaches), its public API names, and the browser test
  suite as a specification of observable behaviour. Ideas and interfaces are not what
  copyright protects.
- **What may not be copied:** PuePy's source, its tests, its docstrings, and its prose.
  Not paraphrased line by line either. The rewrite is written from the spec in this
  document and the behaviour list in `SPEC.md` (to be written from the docs, section 10),
  not with the old source open in the next window.
- **Where the old tree lives:** branch `puepy-reference`, never merged, deleted once the
  rewrite passes the whole example suite and 0.1.0 ships. Its `tests/integration/` is the
  acceptance test until then, rewritten as ours as part of M1.
- **Credit stays.** README and the landing page keep one line: inspired by PuePy, which
  showed the shape. That is courtesy, not obligation, and it is the truth.
- **Every PR says so.** The template asks "written from the spec, without the reference
  source open?" A yes is the contributor's statement, and the maintainer's on merge.

## 5. Platform

| | |
|---|---|
| PyScript | ≥ 2026.7.3; the examples pin one exact release |
| Pyodide | 3.14 (what 2026.6.1+ ships); Python 3.14 semantics |
| MicroPython | the build PyScript ships; no `typing`, partial stdlib |
| Browsers | evergreen Chromium, Firefox, WebKit; the suite runs on all three |
| Server | CPython ≥ 3.11 for tests and tooling only |

**How to write for both interpreters.** The package is written in the MicroPython subset:
string annotations only, no runtime `typing` import, no dataclasses, no `functools` beyond
what MicroPython has, no f-string `=` specifier. Ruff's `UP` rules stay off; a CI job runs
the browser suite under `mpy` as well as `py`, and that job is the guard, not a style guide.
This is the same constraint PuePy accepted and it costs less than it sounds. *Open:* whether
MicroPython is first-class (a release blocks on it) or best-effort (a release notes what
broke). Proposal: first-class. The small-download story is half the pitch.

**The bridge to the browser** is `pyscript.document`, `pyscript.window`,
`pyscript.ffi.create_proxy` / `to_js` and `pyscript.js_modules`. They exist on both
interpreters, which removes the platform branching PuePy needed. `pyscript.web` (its own
Element wrapper) is not used: Frontage owns its element model, and two abstractions over
the same node is one too many.

## 6. Public API

Keep PuePy's shape where it is good, because it is good and because it is what the tutorial
audience already understands. Names below are the proposal; the module layout in section 7
is where they live.

```python
from frontage import Application, Component, Page, Prop, t

app = Application()


@app.page("/", name="home")
class Home(Page):
    def initial(self):
        return {"count": 0}

    def populate(self):
        with t.section(classes="counter"):
            t.h1(f"Count: {self.state['count']}")
            t.button("+", on_click=self.increment)
            t.input(placeholder="Your name", bind="name")

    def increment(self, event):
        self.state["count"] += 1


app.mount("#app")
```

**Kept from PuePy:** `Application`, `Page`, `Component`, `Prop`, the `t` builder with
`with` nesting, `initial()` / `populate()`, `state` as a reactive mapping, `bind=` on form
elements, `on_<event>=` handlers, `ref=` and `self.refs`, slots and `insert_slot()`, props
declared on the class, `on_ready` / `on_redraw` lifecycle hooks, the router with hash and
history modes, `Redirect` / `NotFound` / `Forbidden` / `Unauthorized` as exceptions raised
from `populate()`, `page_title()`, `add_event_listener`, `trigger_event` for custom events
bubbling to a parent.

**Changed:**

- Routes are declared on the decorator: `@app.page("/pets/<id>")`. Route names default to
  the snake-cased class name. `Application.install_router()` goes; the router exists as
  soon as a route does, in hash mode unless `Application(link_mode="history")`.
- State has one shape: a `State` mapping with `watch(key, callback)` and a `mutate()`
  context manager for in-place changes to nested objects. No second `ReactiveDict` name.
- Handlers may be `async def`. Awaiting `fetch` from a click handler is the most common
  thing a beginner wants to do and it must not need a wrapper.
- Redraw scheduling is explicit and documented: one microtask after a state change,
  coalesced, morphing only the tags that read the changed keys. `redraw()` remains for the
  manual case.
- Errors from `populate()` render an error page that names the component and the key, in
  development mode. Production mode (`Application(debug=False)`) renders the configured
  error page only.
- Everything in `frontage/__init__.py` is in `__all__`, and nothing else is public.

**Dropped:** `CssClass` (generate real CSS files or use classes), `Builder`/`html` string
injection as a public API (an `unsafe_html()` escape hatch remains, named for what it is),
`BrowserStorage` as a core module (it becomes `frontage.storage`, optional, documented as a
thin dict view over `localStorage`), and the runtime-detection constants as public names.

*Open:* keep the name `t` for the builder, or spell it `html`? `t` is short and PuePy users
know it; `html` reads better in a course. Proposal: `t`, with `html` as an alias in the
docs' first chapter only if teaching shows it is needed.

## 7. Architecture

```
frontage/
  __init__.py     public names, __all__, __version__
  runtime.py      which interpreter, the pyscript bridge, next_tick(); nothing else imports js
  state.py        State (reactive mapping), watchers, mutate(), the notification queue
  dom.py          the Tag tree: t builder, attributes, classes, children, refs, event wiring
  render.py       Tag tree -> DOM; the morph step (section 8); redraw scheduling
  component.py    Component, Prop, slots, props validation, parent/child, trigger_event
  page.py         Page, Application, mount(), error pages, debug mode
  router.py       Route matching, reverse(), hash/history modes, navigation guards
  storage.py      optional: dict view over localStorage / sessionStorage
  errors.py       Redirect, NotFound, Forbidden, Unauthorized, FrontageError
```

Dependency direction is top to bottom: `errors` and `runtime` import nothing of ours;
`state` imports `runtime`; `dom` imports `state`; and so on. `router` and `storage` are
leaves the application wires in. A module never reaches around this order, and a test can
import `state` or `router` without a browser.

**Server-side stand-ins.** On CPython the browser globals are objects that raise a sentence
naming the global when touched, never `None`. This is what lets the unit tests import the
whole package and what gives a clear error to anyone who runs an app outside a browser.

## 8. Rendering

The Tag tree is rebuilt by `populate()` on each redraw and reconciled into the live DOM.
Reconciliation is **morphdom** (BSD-style license, ~1,000 lines of JavaScript, the same
choice PuePy made and the right one: writing a DOM differ in Python that runs on
MicroPython is a project of its own). It is loaded through `pyscript.js_modules` from the
app's config. If it is absent, the fallback is whole-subtree replacement, which is correct
and slow, and a console warning says so once.

Keys: a `key=` attribute on a tag inside a loop is passed to morphdom as the node id it
matches on, which is what keeps focus and input state across a redraw. This is the "refs
problem" from the tutorial, solved by naming the mechanism instead of an example.

Redraw scope: a tag records which state keys `populate()` read while building it. A change
to a key redraws the smallest enclosing component that read it. *Open:* whether that
tracking is worth its complexity in 0.1, or whether 0.1 redraws the whole page (simpler,
what PuePy does) and scoping is 0.2. Proposal: whole page in 0.1, measured, then decide.

## 9. Testing

- **Unit tests** on CPython with a small DOM stand-in of ours (attributes, children,
  events; enough for `dom`, `render`, `state`, `router`, `component`). No browser.
- **Browser suite**: the examples driven by Playwright, under `py` and `mpy`, on Chromium in
  every CI run and on Firefox and WebKit nightly. The server fixture is `autouse`, so any
  test runs alone. PyScript is served from a local copy (`tools/pyscript/<version>/`,
  fetched by `mk pyscript.fetch`, gitignored), so CI never waits on a CDN and a release is
  reproducible.
- **The examples are the acceptance suite.** Each tutorial chapter has an example, and each
  example has a browser test. A feature without an example is not done.
- **Gate:** `mk check` runs ruff, ty and the unit tests; the browser suite is `mk test
  --integration` and a required CI job.

## 10. Documentation

Documentation lives in `academy-pages` and is served at `academy.optersoft.com/tool/frontage`,
by the fleet's convention. The tutorial is rewritten for the new API, chapter by chapter,
each chapter pointing at its live example on `frontage.optersoft.com/examples/…`. The
reference is generated from docstrings.

Before code: `SPEC.md`, a behaviour list written from PuePy's docs and its browser tests in
our words, one line per observable behaviour, grouped by the tutorial's chapters. It is the
clean-room artefact, the thing the code is written from, and the checklist M1 to M3 tick.

## 11. Distribution

- **PyPI** `frontage`, a pure-Python wheel, published by `ci.yml` on a tag.
- **The wheel on the site**, at `frontage.optersoft.com/dist/frontage-<version>-py3-none-any.whl`,
  so a `pyscript.json` can name it by URL with no PyPI hop. `mk site.build` copies it.
- **A minimal `pyscript.json`** documented in chapter one: the wheel in `packages`,
  morphdom in `js_modules`. That file is the whole install.

## 12. License and ownership

- **MIT OR Apache-2.0**, at the user's choice, the pair every other Optersoft repo ships
  under and the same reasoning: MIT is the shortest read, Apache adds the patent grant and
  the trademark reservation. Copyright Optersoft, S.L. `LICENSE-MIT` and `LICENSE-APACHE`.
- **Inbound = outbound.** Contributions are accepted under the same dual license, stated in
  the README, no separate agreement.
- **Frontage is a trademark of Optersoft.** Stated in README and NOTICE, as today.
- The switch from Apache-only happens when the first line of rewritten code lands on
  `main`, and not one commit earlier: the fork tree is Apache and stays Apache on its
  branch.

## 13. Milestones

| | Deliverable | Done when |
|---|---|---|
| M0 | `SPEC.md`; `puepy-reference` branch; empty package skeleton with `runtime`, `errors`; unit-test DOM stand-in; local PyScript fixture | `mk check` green on an empty package; browser suite runs hello-world under `py` and `mpy` |
| M1 | `state`, `dom`, `render`, `component`, `page`; tutorial examples 1 to 6 rewritten | their browser tests pass on both runtimes |
| M2 | `router`, error pages, `storage`; examples 7 to 10 | full example suite green on Chromium, both runtimes |
| M3 | tutorial and reference on academy; landing page updated; wheel on the site | `0.1.0` tagged and on PyPI |
| M4 | Firefox and WebKit in CI; redraw scoping decision; the `refs` chapter rewritten around `key=` | `0.2.0` |

M0 to M2 are code and can run in parallel with the docs port once `SPEC.md` exists. The
estimate is weeks, not days; the fork on the reference branch is what ships if something
needs to be shown before M3.

## 14. Open decisions

1. MicroPython first-class or best-effort (section 5). Proposal: first-class.
2. Builder name `t` or `html` (section 6). Proposal: `t`.
3. Redraw scoping in 0.1 or 0.2 (section 8). Proposal: 0.2.
4. Route declaration on the decorator, retiring `install_router()` (section 6). Proposal: yes.
5. Whether `storage` ships in 0.1 at all, or waits for someone to ask.
