# CLAUDE.md

Frontage: a fine-grained reactive UI framework for Python in the browser (PyScript; Pyodide
and MicroPython), published to PyPI as `frontage`, Apache 2.0, copyright Optersoft. Being
rewritten clean-room from `SPEC.md` per `DESIGN.md`; `main` is at milestone **M0**. `origin`
will be `github.com/optersoft/frontage` (GitHub, because PyPI publishing needs Actions).

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
| `frontage/renderer.py` | the `Renderer` seam (ten operations), `HtmlRenderer` (plain nodes → HTML), `RecordingRenderer` |
| `frontage/view.py` | `Element`/`Text`, the `h` builder (call form and `with` form), `build`, `render_to_string` |
| `frontage/errors.py` | `FrontageError`, `RenderError`, `NotReady` |
| `tests/` | unit tests, CPython, no browser; `tests/browser/` is Playwright over `examples/` and starts its own server |
| `examples/` | one page per example; `pyscript.json` lists the package files by path so edits show live |
| `tools/serve.py`, `tools/fetch_pyscript.py` | the dev server and the offline PyScript fetch; `tools/pyscript/` is gitignored |
| `web/` | the landing page of frontage.optersoft.com; `mk site.build` assembles `www/` |
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
- **PyScript is pinned** in `tools/fetch_pyscript.py` and served locally; examples load
  `/pyscript/core.js`. Bumping the version is one line there and a browser run.
- **The version** is `frontage/version.py`; hatchling reads it; the browser reads it as code.

## Toolchain

uv, ruff, ty, pytest; `uv run --frozen …` in anything a gate runs. `mk check` is the gate;
`mk test --browser` needs `mk pyscript.fetch` and `uv run playwright install chromium` once.
Release: bump `version.py`, commit, tag `vX.Y.Z`, push the tag; CI publishes over OIDC (the
publisher record PyPI needs is in the header of `.github/workflows/ci.yml`).
