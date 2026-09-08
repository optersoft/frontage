# CLAUDE.md

Frontage: a fine-grained reactive UI framework for Python in the browser, on its own Python
runtime compiled to WebAssembly (`rust/`), published to PyPI as `frontage`, Apache 2.0,
copyright Optersoft. Rewritten clean-room from `SPEC.md` per `DESIGN.md`; `main` is past
milestone **M11** (0.9.0: the WebAssembly boot, the framework as precompiled bytecode, a dev
server that swaps modules into the running page, C/Rust libraries as plain imports — after
M9's prerendering with hydration, transitions and async memos) and, unreleased, **M12/0.10**:
the runtime is frontage's own since 2026-09-08, and **MicroPython and PyScript are gone**
(the interpreter, `frontage.tar`, `mpy-cross`, `export`). `origin` is
`github.com/optersoft/frontage` (GitHub, because PyPI publishing needs Actions).

## Read first

| | |
|---|---|
| `DESIGN.md` | the plan and its reasoning: what Leptos, Solid, Streamlit, Shiny and Reflex taught, the architecture, the milestones, the open decisions |
| `SPEC.md` | one line per behaviour, tagged with its milestone; every line is a test to write; code is written from this, never from a reference framework's source |
| `TODO.md` | what is next and what is blocked |
| `FASTER.md` | M12's plan, one release: our own build of the interpreter, the framework core in C, one distribution, the closure and route chunks, state-preserving swap — with the measurements it rests on |
| `RUST.md` | where Rust goes (2026-09-08): the core inside the interpreter as a `no_std` staticlib behind a C shim — Rust, not C, on measurements that overturned `FASTER.md` §3/§10 — and bulk data in modules of their own, cut per app to the exports the Python interface calls; MicroPython's quadratic, unstable `sorted` is in there too |
| `RUNTIME.md` | the case for a Python runtime of our own in Rust instead of MicroPython (2026-09-08): values in a word, a precise collector, errors as `Result`, no parser in the page, the browser as the standard library, the reactive core as native VM types — and **§9, the spike run the same day**: `rust/` (see `rust/README.md`) passes 157 of the framework's tests on the wasm and boots the examples, at **parity** with MicroPython on `profile_rows` (not the 2× gate) and **179 KB brotli** (not the 120 KB gate). The decision it leaves is where the native core goes; `TODO.md` |

## Layout

| Path | What |
|---|---|
| `frontage/runtime.py` | which Python is running us (`FRONTAGE` in the browser, `CPYTHON` elsewhere); the only module that imports the browser's globals (`js`, `jsffi`); server stand-ins that raise a sentence |
| `frontage/reactive.py` | Signal, Memo (async when its function returns a coroutine; counts toward the Router's `is_routing` through `_navigation`, and prerenders/hydrates by ordinal), Effect/RenderEffect, Owner, context, batch, `spawn`, error routing, the two boundary contexts; `transition`/`Transition`/`use_transition`/`is_pending`/`Optimistic`; the `DEBUG` warnings |
| `frontage/debug.py` | import it in an app for the per-node hydration mismatch report (`last_hydration`, `hydration_report()`); nothing else imports it |
| `frontage/dev.py` | the module swap behind `frontage serve`: compile first, dispose every mount in `view._mounted` and let each renderer clean up the document, drop the app's modules, re-run the entry as `__main__`. Also what the playground uses to tear down between Runs |
| `frontage/store.py` | `Store` over dicts and lists, `reconcile` |
| `frontage/renderer.py` | the `Renderer` seam, `HtmlRenderer` (nodes → HTML, parses templates on CPython), `RecordingRenderer` |
| `frontage/view.py` | `Element`/`Text`, the `h` builder, Template compile/clone, holes and the insert rules, floating holes, `mount` |
| `frontage/template.py` | `html(t"…")`: the template-string parser, cached per call site |
| `frontage/flow.py` | `Show`, `For`, `Switch`/`Match`, `Loading`, `Errored`, `Dynamic`, `Portal` |
| `frontage/chunks.py` | code splitting: `load`/`prefetch`/`loaded` and the `component` behind `Route(lazy=…)`. A chunk is a module `frontage build` left out of the first payload; the page fetches it and its own imports through `window.frontage.loadChunk`, named by the manifest |
| `frontage/aio.py` | `Resource`, `Action`, `interval`, `poll` |
| `frontage/router.py` | routes, matching, three modes, `A`, `Navigate`, `Redirect`, `query`, `ActionForm` |
| `frontage/state.py` (+ `.pyi`) | `State` with `field`/`computed`; the stub types fields as their values |
| `frontage/widgets.py` | form controls bound to signals |
| `frontage/dom.py` | the `Renderer` over the real DOM, delegated events, template cloning; `Hydration`, the cursor `mount(hydrate=True)` walks over prerendered HTML |
| `frontage/_runtime/` | what the browser downloads, committed and shipped in the wheel, so `pip install frontage` is the whole install: `frontage.wasm` (the runtime), `frontage-compiler.wasm` (the same with the compiler, for the playground and the runner), `glue.js` (instantiates the wasm, holds the handle table, executes the DOM op stream, delegates events), `boot.js` (the loader). Built by `mk runtime.build` from `rust/` |
| `frontage/cli/` + `__main__.py` | `python -m frontage`: `build` (the entry's import closure as `.fbc` + a manifest + the runtime into a static directory), `prerender` (imports the app with `runtime.prerender.active`, renders each route with `HtmlRenderer(hydration_markers=True)`, awaits resources, injects HTML + JSON + the replay script), `serve` (a static server with live reload: the swap script is injected into HTML, an SSE stream at `/__frontage/reload`, a polling `Watcher`, each module compiled on request; `tools/serve.py` subclasses its handler so `mk serve` and the browser tests reload too), `tailwind` (standalone CLI fetched into `~/.cache/frontage`), `check` (lambda in a t-string, `html(f"…")`, HTML the parser rewrites), `runtime` (where the runtime's files and its compiler are), `lsp`. `frontage_rt.py` is the host side of the runtime: the compiler `fpy` (PATH, `FRONTAGE_FPY`, a checkout's `rust/target/`, or the release asset fetched once), `.fbc` per module cached by mtime, the import closure through `graph.py`. CPython only |
| `frontage/lsp/` | the language server behind `frontage lsp`: `protocol` (Content-Length framing over stdio, hand-written, no dependency), `documents` (open files, UTF-16 positions), `scanner` (the tolerant t-string lexer and the HTML state machine that answers *where is the cursor*), `rules` (the three static rules, with ranges — `cli/check.py` is the command line over these), `data` (elements, attributes, frontage's prefixes), `features` (completion, hover, definition, semantic tokens), `server`. CPython only, like `cli/`; never in a `pyscript.json` |
| `frontage/errors.py` | `FrontageError`, `RenderError`, `NotReady`, `format_exception` |
| `tests/` | unit tests, CPython, no browser; `tests/browser/` is Playwright over `examples/` and starts its own server |
| `examples/` | one page per example, the browser suite's and the benchmark's material (`tracker/` is the whole framework in one app: routes, a store kept by `reconcile`, memo-loaded details, a transactional toggle with `Optimistic`, a Portal modal, an `ActionForm`, boundaries; prerendered and hydrated in the tests too; `lazy/` is one route in a chunk of its own, the only example a dev server cannot show — a chunk exists only in a build; `wasm/` calls a 41-byte hand-assembled WebAssembly library through `data-fr-js`, which the docs quote byte for byte; `chart/` does the same on a real one, uPlot, and is the evidence behind `COMPONENTS.md`; `weather/` is Streamlit's Seattle Weather demo ported line for line — the 1,461-row dataset ships in `data.py`, two charts are uPlot and three are divs, and it is the app to point at when someone asks what frontage is *for*). Each page is one boot tag; the dev server answers `<dir>/_frontage/…` per directory and builds both archives from disk, so an edit to an example or to the framework shows on reload with nothing to rebuild. Not published: the academy chapters run their own apps in the page (the released wheel, through `frontage build` in each chapter's pipeline), so a chapter's code block is both what the reader reads and what runs |
| `web/` | frontage.optersoft.com as an Astro site on **`@optersoft/astro`** (the Optersoft chrome — layout, header with the light/gray/dark toggle, footer, brand, fonts — a `file:../../astro` path dependency on the sibling checkout; `mk site.build` clones it when absent): `src/pages/` is the landing page, the gallery index (rendered from `src/data/gallery.json`, which `tools/gallery.py` writes) and the 404; `public/` the playground and `runner.html` as static files. `mk site.dev` serves it; `mk site.build` builds it into `web/dist` and merges that into `www/` beside the built gallery apps, the runtime and the wheels. The Tailwind-CLI stylesheet (`site.css`, `tools/site_css.py`) is gone with it — Astro builds the CSS |
| `tools/serve.py`, `tools/bench.py`, `tools/profile/` + `tools/profile_rows.py` | dev server (live reload via `frontage.cli.serve`; it serves many apps at once, so a change reloads rather than swapping), the rows benchmark, the rows profile (phases + calibration, served at `/profile/`) |
| `editors/` | the editor clients. `editors/vscode/` is the VS Code one — a thin client plus the TextMate injection grammar and the snippets, plain JavaScript so there is no build step; `editors/README.md` is the config block for Zed, Neovim, Helix and Emacs, which need no code at all |
| `tools/gallery.py` | `mk gallery`: builds every app in its `APPS` list with the real `frontage build`, loads each cold in Chromium, and writes `www/gallery/` with the measured size and start time on every card. A broken app fails the build; a slower one changes the number on the page. `site.build` runs it and then preserves the result rather than rebuilding it. The page is styled with the site's Tailwind stylesheet, which it copies in beside itself (see `tools/site_css.py`) |
| `web/` | what frontage.optersoft.com serves: `index.html` (the landing page; the documentation itself is the academy's Frontage section, linked from it), `404.html` + `_redirects` (one line, `/* /404.html 404`, because the project answers an unknown path with the landing page and a 200 — a soft 404), `site.tailwind.css` + the committed `site.css` (see `tools/site_css.py`), `_headers` (CORS + `Cross-Origin-Resource-Policy` on `/dist/` and both runtime copies), `web/playground/`, the **gallery** (generated, see `tools/gallery.py`), and **`runner.html`** — the page an embedded live-code frame points at, with the program in the URL fragment. `mk site.build` assembles `www/` with the playground, the runtime twice (once under the playground, once at the root for the runner) and every released wheel |
| `typings/` | ty stubs for the browser-only modules |
| `rust/` | **frontage's own Python runtime, the default since 0.10 (decided 2026-09-08, `TODO.md`)**: `vm/` (the VM: `core.rs` is the reactive graph as VM types, `dom.rs` the DOM op stream, `view.rs` the native template path, `fbc.rs` the bytecode format, `lib/` the Python standard modules including `re` over `RegExp`), `compile/` (source → bytecode over ruff's parser), `py/` (`fpy`, the compiler and native runner, and the differential tests against CPython; `--stress` collects at every safe point), `web/` (the wasm crate, `glue.js` with the op executor and event delegation, `boot.js`, `run.mjs` for node). `mk runtime.rs` vendors the three browser files into `frontage/_runtime/rs/`; `cli/frontage_rt.py` is the host side (`.fbc` per module through `fpy`, the import closure through `cli/graph.py`). `rust/README.md` has the build and test lines; `RUNTIME.md` §9 the numbers. `frontage/runtime.py` reports it as `FRONTAGE`; `reactive.py`, `dom.py` and `view.py` switch to `_core`, `_dom` and `_view` when the modules exist and keep their Python for CPython |

## Rules that are not obvious from the code

- **On the Rust runtime, three Python modules have a native half, and the Python half is
  the specification.** `reactive.py` rebinds `Signal`/`Memo`/`Effect`/`RenderEffect`/`Owner`
  and the scheduling to `_core` (`rust/vm/src/core.rs`), `dom.py`'s `DomRenderer` is the
  `StreamRenderer` over `_dom` (`dom.rs`: nodes are integer ids, a negative id is "the parent
  of node -id", operations are bytes flushed in one crossing), and `view.py`'s template branch
  tries `_view.build_template` (`view.rs`) first, which answers None — and the Python path
  runs — for the first row of a shape, hydration, prerender and any other renderer. So a
  behaviour is written in Python first, tested on CPython, and then ported; the 157 tests run
  on both (`rust/README.md`). What is rare stays in Python and reaches in through the node's
  attributes (`_state`, `_observers`, `_urgent`, …) and the hooks `_core.setup` installs. The
  module state moved into the VM: read it through `_current_owner()`, `_current_listener()`,
  `_current_transition()`, `set_debug()`, never the old globals. A sampling profiler is
  `_frontage.profile_start()/profile_stop()` — the core was built by it, and a change to a hot
  path should come with its numbers.
- **Clean room.** Do not open PuePy, Solid or Leptos source while writing code here. Their docs
  and examples are fine. `SPEC.md` is the source. A PR states it was written that way.
- **The runtime is a target, and it is a subset.** No `typing` at runtime, no dataclasses,
  string annotations only, no stdlib module the runtime lacks (`rust/vm/src/lib/` and
  `modules.rs` are the list; `rust/README.md` says what is not written yet: `match`,
  metaclasses, generator finalisation). Ruff's `UP` rules are off on purpose. The browser
  suite is the guard: `mk test --browser`; `tests/components/test_schema_runtime.py` runs a
  component's Python on the wasm under node with no browser in the way.
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
- **Count DOM operations, and count Python calls.** The `RecordingRenderer` exists so tests
  assert how few operations an update costs; the op stream makes a batch one crossing, but
  every operation is still work in the document. A change that adds operations to a hot path
  needs a number, not an argument. The hot paths (`_children`, `_build_nodes`, `_normalize`,
  a hole's compute, `Store._is_container`) use `type(x) is T` rather than `isinstance` with a
  tuple; keep it that way. `tools/profile_rows.py` (the page in `tools/profile/`) gives the
  phase-by-phase numbers and a per-primitive calibration; `_frontage.profile_start()` the
  per-function ones.
- **The browser boots frontage's own runtime; there is no other.** A page loads
  `_frontage/boot.js`, which loads the wasm and the `.fbc` modules `manifest.json` names — the
  entry's import closure, compiled on the host by `fpy`, no parser in the page — and runs the
  entry as `__main__`; the counter boots in 26 ms. A built app's files are content-hashed
  (`frontage.reactive.1a2b3c4d.fbc`, `frontage.<hash>.wasm`, the manifest maps them) with a
  `_headers` that caches them forever and preload hints in the page; the dev server serves
  them by plain name. The
  compiler is found on PATH, in `FRONTAGE_FPY`, in a checkout's `rust/target/`, or fetched
  from the release's assets into `~/.cache/frontage` on first use (`cli/frontage_rt.py`; CI
  builds one per platform on a tag). `mk runtime.build` rebuilds and vendors the runtime
  after a change under `rust/` — both wasms and the two scripts — and the four files are
  committed, ~2.5 MB, shipped in the wheel. Needs Safari 15 / Chrome 90 / Firefox 88 (the
  `d` flag on `RegExp`, bulk memory).
- **A page that runs a program someone types boots `frontage-compiler.wasm`**: the same
  runtime with the compiler in it (the `compiler` feature of `frontage-web`: `exec`,
  `compile`, `run_source`), 1.8 MB raw against 660, so a built app never gets it. The
  playground's boot tag says `data-fr-compiler`; the runner calls `startRuntime()`.
- **An embedded frame runs a program through `web/runner.html`**, not through a boot tag.
  `boot.js` exports `startRuntime()` — the compiler build of the runtime, no application —
  because a runner holds its program in a URL fragment and has nothing to fetch; the program
  runs through `rt.runSource(...)`.
  Importing `boot.js` without a boot tag warns rather than throwing, precisely so this works.
  The frame is sandboxed without `allow-same-origin`, so it sits in an **opaque origin** and
  even its own-origin fetches leave as `Origin: null`: that is why `/_frontage/*` answers CORS,
  and why `frontage serve` sends the same headers — otherwise a frame works on Pages and not
  locally, which is the worst way round.
- **A dev page needs `frontage.dev`, and the manifest is the only way it can get one.** The
  page is *handed* its modules; it cannot fetch one it turns out to need, and no app imports
  the module that performs a swap. `cli/serve.py` appends it to the manifest it synthesises.
  Every swap failed on `ModuleNotFoundError` before that, silently falling back to a reload.
- **`window.frontage` is the runtime object, and the boot assigns it.** Anything a dev script
  hangs on that name is gone the moment the runtime is ready — which is how the error
  overlay's hooks disappeared. The overlay uses `window.frontageDevError` instead.
- **A lazy route's component reads its memo inside a hole, never at component-call time.**
  The router calls a route's component under `untrack` (`router._level`), so a memo read
  *there* is a dependency of nothing and the page sits on the old route forever after the
  chunk lands. `chunks.component` therefore returns a `Dynamic` over the memo and starts the
  memo itself in the component call, which is inside the router's navigation window — that
  start is what makes a chunk in flight count toward `is_routing`.
- **A closure carries the packages its modules live in.** `import pages.map` needs `pages`,
  and a `pages/__init__.py` that imports nothing is reached by no edge in `cli/graph.py`, so
  a chunk rooted in a package shipped without it and the import in the page failed with
  nothing on the console. `Graph.closure` adds every ancestor package; `cli/serve.py` resolves
  a dotted name back to a directory's `__init__.py` for the same reason.
- **A C or Rust library reaches an app through `data-fr-js`** (0.9.0): `name=./lib.js` pairs on
  the boot tag, imported and awaited before the entry runs, then `registerJsModule`d so it is a
  plain `import name`. Specifiers resolve from `../` of `boot.js` -- the app's own directory in
  every layout -- so a prerendered page at any depth needs no rewriting. A crossing is 1.00 us,
  a few Python method calls; the limit is *volume*, because the two wasm modules have
  separate memories and anything but a number is copied through JavaScript. `examples/wasm/`
  and the academy's Wasm libraries chapter.
- **A component is a Python package that also ships browser assets** (0.9.0). It declares a
  `frontage.components` entry point and lays out `_browser/index.js` (+ optional `index.css`);
  `build` copies the assets to `_frontage/components/<name>/`, merges a `data-fr-js` entry into
  the boot tag, and packs the component's Python under its package path so `import <package>`
  resolves in the page. `--component NAME=PATH` develops one before publishing. **A module whose name starts with an
  underscore stays on CPython** (`_server.py`, `_compile.py`): the page could not import it and
  it is dead weight there. **Discovery
  must never import a component**: its Python targets the browser, and `find_spec` locates it
  without running it. ⚠ **In `serve`, a real file under `_frontage/` wins over the synthesised
  archive** — serving a built directory must serve what `build` produced, or a component's
  Python silently never reaches the page.
- **`frontage serve` swaps modules, it does not reload the page.** The server compiles the
  changed app modules (`/__frontage/module/<name>.fbc`), the page's script hands them to the
  runtime (`rt.addModule`) and calls `rt.swap`, and `frontage/dev.py` disposes every mount in
  `view._mounted`, calls the renderer's `teardown` (the delegated dispatchers on `document`
  are shared and owned by nobody), drops the modules from `sys.modules` and re-runs the entry
  as `__main__` from the new bytecode. **A change under `frontage/` reloads the page
  instead**: the framework's own module objects are what the live page holds. In dev
  **nothing is built** — the manifest and every `.fbc` are made per request off disk, so a
  framework edit is live on the next reload. ⚠ **A failed swap must not reload.** The server
  answers 500 for a module that does not compile and the script leaves the page alone, so a
  half-typed file keeps the last working page on screen.
- **The academy chapters are part of a release.** The docs live in
  `~/optersoft/academy-pages/python/frontage/` (served at academy.optersoft.com), not here.
  Every change that a user can see — a new or renamed API, a new flag, a moved command, a
  wheel version bump — is not done until the chapter that covers it says so and the pushed
  pages match the version on PyPI. Before a version commit: grep the chapters for the old
  spelling, update the wheel name in Basic, and run `python -m frontage check` over
  `python/frontage/*.md` (it found three lambdas the browser suite could not, and it is not
  in `mk lint` because the pages are another repo). Each chapter app boots from wasm: one
  `data-fr-boot` tag and a pipeline running `frontage build`. Verify a deploy with
  `curl -sL https://optersoft.gitlab.io/python/frontage-<c>/ | grep -c data-fr-boot` — the old
  check read `frontage/version.py`, which no longer exists as a file.
  **Each chapter's app is a repository** at `gitlab.com/optersoft/python/frontage-<chapter>`
  (checkout `~/xtec/python-frontage-<chapter>`), exported to GitLab Pages by its pipeline with
  the `frontage` on PyPI; the page's code blocks must match its `app/app.py`, and a wheel bump
  is a commit in nine repos too (the two pipeline files pin `pip install frontage==X.Y.Z`;
  Ship's copies of them say the same). ⚠ The chapters still describe MicroPython (0.9.x); the
  0.10 release rewrites what they say about the runtime.
- **Pages that load Tailwind's browser build import `theme.css` + `utilities.css` only**: the
  full import brings preflight, which restyles the page around the app.
- **Hydration is fences, not ids.** Prerendered HTML wraps every hole's content in
  `<!--[-->` … `<!--h-->` and keeps `data-fr-h`; static template text keeps its `<!--h-->` too
  (the client adopts the text by it, then removes it). Each hole positions the cursor from its
  own fence, so effect order does not matter. An adopted element must use
  `Hydration.find_holes`, which skips fenced spans: `querySelectorAll` would also return the
  markers and `data-fr-h` of the templates built *inside* the hole's content, and every index
  shifts (that was the first hydration bug). Compare DOM nodes with `isSameNode`, never `is`:
  a proxy is not the node. On the streaming renderer hydration's cursor stays on proxies and
  every proxy read flushes the op stream first, so the document it reads is current.
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
- **Rules that came from MicroPython and still hold, for other reasons.** A `lambda` inside a
  template string's braces: name the function (the compiler accepts it now; a named function
  reads better in a hole). **Any API where the order of a mapping is visible takes pairs**,
  not a dict — `tabs([("Trend", view), …])`: the runtime's dicts keep insertion order, but the
  rule keeps components honest about what they promise. Before relying on a corner of Python
  (`zip(strict=)`, `__getattribute__`, a metaclass) check `rust/README.md`, and add a
  differential case (`rust/py/tests/cases/`) when a corner turns out to matter.
- **Ruff's formatter follows the target version.** Under py314 it emits `except A, B:` (PEP
  758), which reads oddly to anyone on an older Python, so the package targets py312 and only
  the files with template strings are py314 (`per-file-target-version`). Its B009 autofix also rewrites a
  `getattr(x, "const")` guard back to attribute access; use a default argument.

## Toolchain

uv, ruff, ty, pytest; `uv run --frozen …` in anything a gate runs. `mk check` is the gate;
`mk test --browser` needs the runtime's compiler (`cargo build --profile native -p fpy` in
`rust/`, or a release's binary) and `uv run playwright install chromium` once; the 28 tests
take 20 s. `cargo test --profile native` in `rust/` is the runtime's own gate (the
differential cases against CPython, one of them on the wasm under node). `mk runtime.build`
rebuilds and vendors the runtime after a change under `rust/`; commit `frontage/_runtime/`.
`ruff` excludes `rust/` (its Python is test input and the runtime's standard modules).
Release: bump `version.py`, commit, tag `vX.Y.Z`, push the tag; CI publishes over OIDC (the
publisher record PyPI needs is in the header of `.github/workflows/ci.yml`).

The VS Code client releases separately: bump `version` in `editors/vscode/package.json`, tag
`editor-vX.Y.Z`, push it; `.github/workflows/vscode.yml` publishes to the Visual Studio
Marketplace and Open VSX. Neither speaks OIDC, so unlike PyPI this one needs two stored
secrets (`VSCE_PAT`, `OVSX_PAT`) — the first in this repository's release path. `mk
vscode.package` builds the `.vsix` locally, `mk vscode.install` puts it in the local VS Code,
and `mk lsp.probe FILE` prints what the server would say about a file with no editor in the way.
