# CLAUDE.md

Frontage: a fine-grained reactive UI framework for Python in the browser (PyScript; Pyodide
and MicroPython), published to PyPI as `frontage`, Apache 2.0, copyright Optersoft. Rewritten
clean-room from `SPEC.md` per `DESIGN.md`; `main` is past milestone **M9** (0.7.0: the plan, the command line, prerendering with hydration, transitions that build the new state off screen, async memos as the router's data primitive). `origin` is
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
| `frontage/reactive.py` | Signal, Memo (async when its function returns a coroutine; counts toward the Router's `is_routing` through `_navigation`, and prerenders/hydrates by ordinal), Effect/RenderEffect, Owner, context, batch, `spawn`, error routing, the two boundary contexts; `transition`/`Transition`/`use_transition`/`is_pending`/`Optimistic`; the `DEBUG` warnings |
| `frontage/debug.py` | import it in an app for the per-node hydration mismatch report (`last_hydration`, `hydration_report()`); nothing else imports it |
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
| `frontage/cli/` + `__main__.py` | `python -m frontage`: `export`, `prerender` (imports the app with `runtime.prerender.active`, renders each route with `HtmlRenderer(hydration_markers=True)`, awaits resources, injects HTML + JSON + the replay script), `tailwind` (standalone CLI fetched into `~/.cache/frontage`), `check` (lambda in a t-string, `html(f"…")`, HTML the parser rewrites), `pyscript` (the pinned bundle version lives here), `serve` (a static server with live reload: the reload script is injected into HTML, an SSE stream at `/__frontage/reload`, a polling `Watcher`; `tools/serve.py` subclasses its handler so `mk serve` and the browser tests reload too). CPython only; never listed in a `pyscript.json` |
| `frontage/lsp/` | the language server behind `frontage lsp`: `protocol` (Content-Length framing over stdio, hand-written, no dependency), `documents` (open files, UTF-16 positions), `scanner` (the tolerant t-string lexer and the HTML state machine that answers *where is the cursor*), `rules` (the three static rules, with ranges — `cli/check.py` is the command line over these), `data` (elements, attributes, frontage's prefixes), `features` (completion, hover, definition, semantic tokens), `server`. CPython only, like `cli/`; never in a `pyscript.json` |
| `frontage/errors.py` | `FrontageError`, `RenderError`, `NotReady`, `format_exception` |
| `tests/` | unit tests, CPython, no browser; `tests/browser/` is Playwright over `examples/` and starts its own server |
| `examples/` | one page per example; `pyscript.json` lists the package files by path so edits show live. **The examples are published on the academy**, at `python/frontage/examples`, a page `mk docs.examples` (`tools/academy_examples.py`) generates from this directory: one `::: pyscript` frame per example, MicroPython, the released wheel by URL. Regenerate it after a release; never edit it there |
| `tools/serve.py`, `tools/fetch_pyscript.py`, `tools/bench.py`, `tools/profile/` + `tools/profile_rows.py` | dev server (live reload via `frontage.cli.serve`), offline PyScript fetch into `tools/pyscript/` (gitignored; the version is `frontage.cli.pyscript.VERSION`), the rows benchmark, the rows profile (phases + calibration, served at `/profile/`) |
| `editors/` | the editor clients. `editors/vscode/` is the VS Code one — a thin client plus the TextMate injection grammar and the snippets, plain JavaScript so there is no build step; `editors/README.md` is the config block for Zed, Neovim, Helix and Emacs, which need no code at all |
| `web/` | what frontage.optersoft.com still serves since 2026-09-06: `_redirects` (everything else goes to academy.optersoft.com/python/frontage), `_headers` (CORS on `/dist/`) and `web/playground/`; `mk site.build` assembles `www/` with the package, the bundle and every released wheel |
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
- **The package's own signals write with `_write`, not `set`.** `Signal.set` warns (E2) when a
  tracked computation is running, and a Loading scope's count or a For row's index legitimately
  changes during a tracked read. User-facing writes keep `set`. Tasks that should have read
  their inputs before their first await are spawned with `spawn(…, name=…)`; that name is
  what the read-after-await warning prints.
- **A transition parks the effect phase of on-screen render effects, nothing else.** While a
  `Transition` is open, `Effect._run` still computes (that is what builds the new state: a
  `Show` branch, a route level, a `For` row, under their own owners, off screen) and then, if
  the effect's `_target` says its output is on the page, keeps the result in `_parked` and
  lists itself in the transition; `_queued` stays set so a mark meanwhile only makes it
  DIRTY. An effect whose target is off screen (inside the new branch) applies at once, so the
  branch assembles itself and its `Loading` boundaries resolve there. `Resource._load` and an
  async `Memo._start` register with the transition and `_release`/`_settle` count them down;
  the commit calls `_commit_parked` on each parked effect: apply the parked result, or
  recompute if it was marked meanwhile. Effects downstream of an `Optimistic` write are
  `_urgent` and never park. "On screen" is `renderer.is_connected(node)`: `isConnected` in
  the DOM, a `_root` flag `mount` sets (`mark_root`) on the HtmlRenderer's target and a
  parent walk otherwise. The view layer passes `target=` to every `RenderEffect` it creates;
  a user `RenderEffect` without one is assumed on screen and parks.
- **Count bridge crossings, and on MicroPython count calls.** Every DOM call from Python
  crosses to JavaScript. The `RecordingRenderer` exists so tests assert how few operations an
  update costs. A change that adds operations to a hot path needs a number, not an argument.
  On MicroPython the Python side is three quarters of a 1,000-row create (DESIGN §12):
  a method call is 0.24 µs, and **`isinstance(x, (A, B))` that misses is 2.7 µs**, so the hot
  paths (`_children`, `_build_nodes`, `_normalize`, a hole's compute, `Store._is_container`)
  use `type(x) is T`; keep it that way. `tools/profile_rows.py` (the page in `tools/profile/`)
  gives the phase-by-phase numbers and a per-primitive calibration on both interpreters.
- **PyScript is pinned** in `frontage/cli/pyscript.py` and served locally; examples load
  `/pyscript/core.js`. Bumping the version is one line there and a browser run.
- **The academy chapters are part of a release.** The docs live in
  `~/optersoft/academy-pages/python/frontage/` (served at academy.optersoft.com), not here.
  Every change that a user can see — a new or renamed API, a new flag, a moved command, a
  wheel version bump — is not done until the chapter that covers it says so and the pushed
  pages match the version on PyPI. Before a version commit: grep the chapters for the old
  spelling, update the wheel name in Basic, and run `python -m frontage check` over
  `python/frontage/*.md` (it found three lambdas the browser suite could not, and it is not
  in `mk lint` because the pages are another repo). After the release, `mk docs.examples`
  regenerates the academy's Examples page so its frames name the new wheel. Any new page directory on the site also
  needs a line in `web/_redirects` (PyScript resolves its interpreters relative to the page).
  **Each chapter's app is a repository** at `gitlab.com/optersoft/python/frontage-<chapter>`
  (checkout `~/xtec/python-frontage-<chapter>`), exported to GitLab Pages by its pipeline with
  the `frontage` on PyPI; the page's code blocks must match its `app/app.py`, and a wheel bump
  is a commit in nine repos too (`app/pyscript.json` names the wheel by URL, and since 0.8.0 the
  two pipeline files pin `pip install frontage==X.Y.Z`; Ship's copies of them say the same).
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
- **Resources hydrate by creation order; async memos by ordinal.** The prerenderer writes the
  resources' values in the order they were created; the browser hands them back in the same
  order and skips the first load. Every `Memo` created during a prerendered mount gets an
  ordinal (`reactive._memo_registry` / `_memo_hydration`), and the async ones are written as
  `[ordinal, value]` pairs, so a plain memo between them costs nothing and a memo the server
  never started just runs. Same code, same order; a Resource the server never created just
  fetches. The data block is a dict since 0.7.0; a list (an older page) still hydrates.
- **The language server is Python because the rules are.** `frontage/lsp/` imports the package
  and shares `rules.py` with `frontage check`, so the server's reading of a template is the
  runtime's by construction rather than a second implementation of `SPEC.md` in another
  language. That is also the answer to "shouldn't it be Rust, like ruff": ruff analyses whole
  repositories, this analyses one open buffer, and the whole diagnostics pass measures 3.4 ms
  on the largest file here — parse *and* walk. A rewrite would buy 3 ms nobody was waiting
  for and cost per-platform wheels, a second parser for PEP 750, and the drift. If a profile
  ever says otherwise the answer is a PyO3 module behind `rules.py`, not a second server.
- **The server stays out of Python's territory.** Inside `html(t"…")` no other tool knows
  anything, so it answers fully; outside, it answers only for frontage's own names. It never
  reports a syntax error — Pylance says it better, and while someone types most keystrokes
  leave the file briefly unparseable, so `server.publish` keeps the last good diagnostics
  instead of flashing a parse error that moves around.
- **`scanner.py` reads the same grammar twice, on purpose.** `context_at` cuts at a cursor
  and needs the state at a boundary in half-written text; `emit_tokens` walks forwards and
  needs every span. A test asserts they agree. Both collapse an interpolation to one
  character before running — the trick `template.py` and `rules.py` also use — because
  otherwise an attribute after a hole in the same tag is invisible.
- **`editor-v*` is the extension's tag prefix, and the `v` matters.** `ci.yml` triggers on
  `v*.*.*`, which a glob happily matches against `vscode-v0.1.0`: the leading `v` of "vscode"
  *is* the `v`. A VS Code release under that name would run the PyPI publish job.
- **The version** is `frontage/version.py`; hatchling reads it; the browser reads it as code.
- **`frontage` on PATH and `python -m frontage` are the same `cli.main`**; `cli.PROG` says which
  was invoked and every sub-parser's `prog` reads it, so `--help` names the right one. Docs say
  `uvx frontage …` (the script, from PyPI, nothing installed) since 0.5.0.
- **`unique_id` counts per mount** (`_ID_SCOPE`, an internal context the root owner provides,
  named after the target's id). The prerenderer passes the selector as `scope=` so the server
  and the browser hand out the same ids; a test that mounts into a node gets an ordinal.
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

The VS Code client releases separately: bump `version` in `editors/vscode/package.json`, tag
`editor-vX.Y.Z`, push it; `.github/workflows/vscode.yml` publishes to the Visual Studio
Marketplace and Open VSX. Neither speaks OIDC, so unlike PyPI this one needs two stored
secrets (`VSCE_PAT`, `OVSX_PAT`) — the first in this repository's release path. `mk
vscode.package` builds the `.vsix` locally, `mk vscode.install` puts it in the local VS Code,
and `mk lsp.probe FILE` prints what the server would say about a file with no editor in the way.
