# CLAUDE.md

Frontage: a fine-grained reactive UI framework for Python in the browser (PyScript; Pyodide
and MicroPython), published to PyPI as `frontage`, Apache 2.0, copyright Optersoft. Rewritten
clean-room from `SPEC.md` per `DESIGN.md`; `main` is past milestone **M6** (0.4.0: the plan, the command line, prerendering with hydration). `origin` is
`github.com/optersoft/frontage` (GitHub, because PyPI publishing needs Actions); the PuePy fork is
on branch `puepy-reference`.

## Read first

| | |
|---|---|
| `DESIGN.md` | the plan and its reasoning: what Leptos, Solid, Streamlit, Shiny and Reflex taught, the architecture, the milestones, the open decisions |
| `SPEC.md` | one line per behaviour, tagged with its milestone; every line is a test to write; code is written from this, never from a reference framework's source |
| `TODO.md` | what is next and what is blocked |

## Layout

| Path | What |
|---|---|
| `frontage/runtime.py` | which interpreter; the only module that imports `pyscript`; server stand-ins that raise a sentence |
| `frontage/reactive.py` | Signal, Memo, Effect/RenderEffect, Owner, context, batch, `spawn`, error routing, the two boundary contexts |
| `frontage/store.py` | `Store` over dicts and lists, `reconcile` |
| `frontage/renderer.py` | the `Renderer` seam, `HtmlRenderer` (nodes → HTML, parses templates on CPython), `RecordingRenderer` |
| `frontage/view.py` | `Element`/`Text`, the `h` builder, Template compile/clone, holes and the insert rules, floating holes, `mount` |
| `frontage/template.py` | `html(t"…")`: the template-string parser, cached per call site |
| `frontage/flow.py` | `Show`, `For`, `Switch`/`Match`, `Loading`, `Errored`, `Dynamic`, `Portal` |
| `frontage/aio.py` | `Resource`, `Action`, `interval`, `poll` |
| `frontage/router.py` | routes, matching, three modes, `A`, `Navigate`, `Redirect`, `query`, `ActionForm` |
| `frontage/state.py` (+ `.pyi`) | `State` with `field`/`computed`; the stub types fields as their values |
| `frontage/widgets.py` | form controls bound to signals |
| `frontage/dom.py` | the `Renderer` over the real DOM, delegated events, template cloning; `Hydration`, the cursor `mount(hydrate=True)` walks over prerendered HTML |
| `frontage/cli/` + `__main__.py` | `python -m frontage`: `export`, `prerender` (imports the app with `runtime.prerender.active`, renders each route with `HtmlRenderer(hydration_markers=True)`, awaits resources, injects HTML + JSON + the replay script), `tailwind` (standalone CLI fetched into `~/.cache/frontage`), `check` (lambda in a t-string, `html(f"…")`, HTML the parser rewrites), `pyscript` (the pinned bundle version lives here). CPython only; never listed in a `pyscript.json` |
| `frontage/errors.py` | `FrontageError`, `RenderError`, `NotReady`, `format_exception` |
| `tests/` | unit tests, CPython, no browser; `tests/browser/` is Playwright over `examples/` and starts its own server |
| `examples/` | one page per example; `pyscript.json` lists the package files by path so edits show live |
| `tools/serve.py`, `tools/fetch_pyscript.py`, `tools/bench.py` | dev server, offline PyScript fetch into `tools/pyscript/` (gitignored; the version is `frontage.cli.pyscript.VERSION`), the rows benchmark |
| `web/` | the landing page and `web/playground/` of frontage.optersoft.com; `mk site.build` assembles `www/` (with the bundle and the wheel) |
| `typings/` | ty stubs for the browser-only modules |
| branch `puepy-reference` | the PuePy fork, the acceptance test until 0.1.0; never merged |

## Rules that are not obvious from the code

- **Clean room.** Do not open PuePy, Solid or Leptos source while writing code here. Their docs
  and examples are fine. `SPEC.md` is the source. A PR states it was written that way.
- **MicroPython is a target.** No `typing` at runtime, no dataclasses, string annotations
  only, no stdlib module MicroPython lacks. Ruff's `UP` rules are off on purpose. The `mpy`
  browser smoke test is the guard: `mk test --browser`.
- **`runtime.py` re-exports the browser globals.** Its `__all__` is what stops ruff's
  unused-import autofix from deleting them; it happened once on the fork.
- **Count bridge crossings.** Every DOM call from Python crosses to JavaScript. The
  `RecordingRenderer` exists so tests assert how few operations an update costs. A change that
  adds operations to a hot path needs a number, not an argument.
- **PyScript is pinned** in `frontage/cli/pyscript.py` and served locally; examples load
  `/pyscript/core.js`. Bumping the version is one line there and a browser run.
- **`mk lint` runs `python -m frontage check`** over `examples`, `web` and the package, and the
  academy chapters get the same run by hand before a push: it found three lambdas the browser
  suite could not (they were in docs). Any new page directory on the site also needs a line
  in `web/_redirects` (PyScript resolves its interpreters relative to the page).
- **Pages that load Tailwind's browser build import `theme.css` + `utilities.css` only**: the
  full import brings preflight, which restyles the page around the app.
- **Hydration is fences, not ids.** Prerendered HTML wraps every hole's content in
  `<!--[-->` … `<!--h-->` and keeps `data-fr-h`; static template text keeps its `<!--h-->` too
  (the client adopts the text by it, then removes it). Each hole positions the cursor from its
  own fence, so effect order does not matter. An adopted element must use
  `Hydration.find_holes`, which skips fenced spans: `querySelectorAll` would also return the
  markers and `data-fr-h` of the templates built *inside* the hole's content, and every index
  shifts (that was the first hydration bug). Compare DOM nodes with `isSameNode`, never `is`:
  Pyodide hands out a new proxy per access.
- **Resources hydrate by creation order.** The prerenderer writes their values in the order
  they were created; the browser hands them back in the same order and skips the first load.
  Same code, same order; a Resource the server never created just fetches.
- **The version** is `frontage/version.py`; hatchling reads it; the browser reads it as code.
- **MicroPython differences met so far**, each now handled or documented: no writable
  `__name__`, no `co_argcount`, no `html.parser`, no `__getattribute__` hook, no `__mro__`, no
  writable instance `__dict__` (use `object.__setattr__`), `zip` has no `strict`, and **a
  `lambda` inside a template string's braces is a SyntaxError** (name the function). Pyodide
  returns a `JsNull` proxy, not `None`, for JavaScript null (`dom.is_node`).
- **Ruff's formatter follows the target version.** Under py314 it emits `except A, B:` (PEP
  758), which MicroPython cannot parse, so the package targets py312 and only the files with
  template strings are py314 (`per-file-target-version`). Its B009 autofix also rewrites a
  `getattr(x, "const")` guard back to attribute access; use a default argument.

## Toolchain

uv, ruff, ty, pytest; `uv run --frozen …` in anything a gate runs. `mk check` is the gate;
`mk test --browser` needs `mk pyscript.fetch` and `uv run playwright install chromium` once.
Release: bump `version.py`, commit, tag `vX.Y.Z`, push the tag; CI publishes over OIDC (the
publisher record PyPI needs is in the header of `.github/workflows/ci.yml`).
