# TODO

Open work for `frontage`, most urgent first. `- [ ]` open, `- [x]` done where the reason is
worth keeping. The milestones themselves are in `DESIGN.md` §16; this file tracks the edges.

## Decisions taken by proposal on 2026-09-05 (say so if any should change)

All seven open decisions in `DESIGN.md` §17 were taken as proposed: MicroPython first-class;
template strings in M2 with the builder as fallback; pure Python first and a JS shim only
where the rows benchmark says so; Solid 1.x synchronous propagation; `Store` in 0.1;
accessors spelled `count()` with `.value` as alias; widgets as a subpackage.

## frontage-api — the HTTP server (`API.md`), 2026-09-10

Merged in from its own repo the same day; `rust/api/` is the crate, `frontage_api/` the
package, `API.md` the plan with the measurements.

- [x] §6.1 the spike, and its gate: **5.97× granian + FastAPI** on a body-echo route. Reading
      the body costs us 5% and costs Granian 48%, which is the one-crossing rule measured.
- [x] §4.3 the host future hook, thread-per-core, a coroutine driven in Rust rather than by an
      asyncio `Task`. It needed **no change to the VM** — the embedding surface was already
      enough for a server, which the spike could not assume.
- [x] §6.2 the surface: `App`, routing, binding, `frontage.schema` bodies, `HTTPError`,
      `Depends`, lifespan, CORS, `Stream` with SSE, static files. The gate is met:
      `frontage.chat`'s server half runs on it, streaming token by token.
- [x] Runtime changes it needed: **async generators** (`async for` refused an `async def` with
      a `yield`) and **`__annotations__`** (parsed and discarded, so no contract to read).
      Both are differential cases; both are in `rust/README.md`.
- [x] §6.2b the validator compiled once instead of walked per value: **21% off validation**,
      5.5% off a validated request, no wasm bytes, and the page gets it too.

### Next, and the order is not the plan's

⚠ **A handler could not reach anything, and that outranked OpenAPI.** `os` and `datetime`
landed on 2026-09-10, so a handler can now hold a key and date a row. What it still cannot do
is **talk to anything**: no `urllib`, no `socket`, no `_http`. `frontage.chat`'s whole purpose
— hold the key, forward to the model — is still impossible, which is why `_http` is next and
§6.4's *small* modules are not "the standard library, later".

- [x] `_env` and `_datetime` (and `time.strftime`): `os` (environ, getenv — there is no file
      system to wrap), `datetime` (date/time/datetime/timedelta/timezone, CPython byte for
      byte down to the `ValueError` messages), `time.gmtime`/`strftime`. Three differential
      cases; `/stamp` in the spike app is the gate — a handler reading a key out of the
      environment and dating a row. ⚠ Local time **is** UTC: no zone database (`rust/README.md`).
- [ ] The runtime's stdlib is embedded in the wasm, so **every page pays for `datetime`**:
      +13.3 KB brotli (214.8 → 228.1 KB), of which 7.2 KB is the module and 6.1 KB the
      calendar in Rust. Measured 2026-09-10. The fix is to ship such a module as a **chunk**
      the host compiles, the way every framework module already travels — `cli/graph.py`
      resolving `import datetime` to a stdlib source in the wheel. Until then it is embedded,
      because an `ImportError` in a page for a module the server has is worse than 7 KB.
- [ ] `_http` over `reqwest`: the smallest native module that matters, and the one
      `frontage.chat` needs to do the thing it exists to do. Streaming response bodies through
      the same `Chunks` shape `Stream` already uses.
- [ ] §6.3 OpenAPI and a docs page. Much cheaper now that annotations exist and
      `schema/jsonschema.py` already emits JSON Schema. Gate: §4.6's shared record produces a
      document that validates what the form accepts.
- [ ] §6.5 ship it. **Nothing outside this checkout can use any of this**: there is no
      `frontage_api` wheel (§7 decided two, and only one exists) and no binary. A wheel, a
      binary per platform on a tag, `hive-server` as the front door.
- [ ] The floor. Every route pays **8.44 µs** before any user code runs, against 5.55 µs for
      §6.1's hand-rolled dispatch — so the surface is ~2.9 µs of it. Profile it the way
      §6.2b profiled the validator, with `_frontage.profile_start()`, and fix what the
      numbers name rather than what the argument does.
- [ ] §6.4 `_polars`, and `frontage.remote` moving off FastAPI. Big, and its consumer is a
      component rather than the framework, so it can wait behind the four above.
- [ ] Multipart bodies. Not in `API.md` at all and a real gap: a form that uploads a file has
      nowhere to go.
- [ ] A native `_schema`: **not yet, and here is the number to revisit by.** Validation is
      3.31 µs of a 13.05 µs request, so making it free buys +34% on a validated route —
      against bytes in every page's download and a second implementation to keep in step.
      Revisit once the floor above is dealt with and validation is still the top line.

## M0 (in progress)

- [x] Fork tree removed from `main`.
- [x] Skeleton: `runtime`, `errors`, `renderer` (seam + `HtmlRenderer` + `RecordingRenderer`),
      `view` (`h` builder, call and `with` forms, `render_to_string`).
- [x] `SPEC.md` with milestone tags.
- [x] Local PyScript fixture: `tools/fetch_pyscript.py` unpacks the offline bundle (core +
      Pyodide + MicroPython, 18 MB, no CDN); `tools/serve.py` serves it at `/pyscript/`.
- [x] Browser smoke test green under `mpy` and `py` (`tests/browser/test_smoke.py`). PyScript's
      offline mode resolves interpreters as `./pyscript/<name>/…` relative to the *page*, so
      `tools/serve.py` answers `/pyscript/` under any path and the site has a `_redirects` rule.
- [x] CI: the browser job fetches the bundle and caches it by the fetcher's hash.
- [x] CI ran on GitHub 2026-09-05: test 10 s, browser 41 s (bundle fetch included), both green.

## M1 (next)

- [x] `frontage/reactive.py`: Signal, Memo, Effect (two-phase), RenderEffect, batch, untrack,
      on, Owner, context, selector. SPEC §4 C1–C15; 30 unit tests; runs under MicroPython
      (the browser smoke exercises it).
- [x] `frontage/store.py`: SPEC §5 T1–T5, T7; 17 unit tests; runs under MicroPython.
- [x] Reactive views: holes with the insert rules, bound attributes (`attr`/`prop_`/`class_`/
      `style_`/`bind_`/`ref`), `component`, `Show`, `For` (identity, key function, index
      mode), `mount`; `DomRenderer` with delegated events. SPEC S5, W1–W7, W13 (partly:
      `currentTarget` is not simulated yet). 26 view tests through the recording renderer.
- [x] Counter and todo examples with browser tests, green under MicroPython and Pyodide.
      Three MicroPython differences met on the way, all now handled: functions have no
      writable `__name__`, code objects have no `co_argcount`, and `Owner.run` needed kwargs.
- [x] The rows example and `tools/bench.py` (§12). Baseline, node-by-node path, medians of 3,
      2026-09-05, this laptop's Chromium:

      | operation | MicroPython | Pyodide | renderer ops |
      |---|---|---|---|
      | create 1,000 rows | 198 ms | 111 ms | 32,000 |
      | update every 10th | 3.4 ms | 0.9 ms | 100 |
      | swap two rows | 18 ms | 2.5 ms | 2 |
      | append 1,000 | 207 ms | 166 ms | 32,000 |
      | clear 1,000 | 44 ms | 9.5 ms | 1,000 |

      Two fixes fell out of the first run: dependency tracking was a linear scan (quadratic
      for a For over 1,000 rows: swap was 328 ms on MicroPython), and list iteration in a
      Store subscribed to a node per index. Lesson for §12: on MicroPython, Python-level work
      is the bottleneck as much as bridge crossings; the For and reconcile paths must stay lean.
- [x] The Template path (S6, W17): an Element compiles to one HTML skeleton with `<!--h-->`
      markers and `data-fr-h` elements; one `clone_template` per instance, holes bound after;
      a `For` keeps one Template per row function and reuses it when the row's shape matches
      (static attributes included). Text children are holes so like rows share a template.
      Renderer ops per row 31 → 11. Medians of 3, 2026-09-05:

      | operation | mpy templates | mpy node-by-node | py templates | py node-by-node |
      |---|---|---|---|---|
      | create 1,000 | 169 ms | 177 ms | 77 ms | 100 ms |
      | append 1,000 | 182 ms | 192 ms | 90 ms | 154 ms |
      | swap | 16 ms | 18 ms | 2.6 ms | 2.4 ms |
      | update every 10th | 3.3 ms | 3.4 ms | 0.8 ms | 0.7 ms |

      Templates are the default on both. On MicroPython the win is small because Python-level
      work (Element construction, effects, signals) dominates, not bridge crossings; the JS
      shim of DESIGN §8.6 would take ~7 of the 11 ops per row (hole finding) and is deferred to
      the M5 performance pass together with a MicroPython profiling session.
- [x] W13 leftovers (`currentTarget` via defineProperty in the delegated dispatcher,
      `oncapture_`), W15 custom events (`emit`).

## M2 (done 2026-09-05, except E2)

- [x] `Resource`, `Action`, `spawn`, `Loading`, `Errored`, `Switch`/`Match`, `Dynamic`, `Portal`,
      async handlers, `html(t"…")` on both interpreters, `mount(factory)` with a debug error page.
- [x] E2 debug warnings (0.5.0): a read after `await` inside a Resource fetcher or an async memo,
      a write inside a tracked compute, a `For` keyed by identity whose rows never survive.

## M3 (done 2026-09-05)

- [x] The router (SPEC U1–U10; scroll restoration best-effort) and floating holes, so a component
      may return control flow directly and the router renders no wrapper.
- [x] Scroll restoration in a browser test (0.5.0; `history.scrollRestoration = "manual"` in both
      browser modes, because with `auto` the browser moves the page before the event fires and
      the router remembers the wrong position; restore after the page is back on screen);
      `is_routing` stays up while the new route's Resources load.

## M4 (done 2026-09-05): 0.1.0 on PyPI

- [x] Docs on academy at `python/frontage` (Basic, Template, Flow, Async, Router, State), listed
      under Python > Web, `/tool/frontage` redirecting there. English only until a programme
      places the pages (then `.ca`/`.es` variants are owed).
- [x] Landing page with the measured download: 0.84 MB / 0.32 MB compressed on MicroPython,
      13.8 MB / 6.4 MB on Pyodide; Frontage itself 131 KB / 39 KB.
- [x] `mk export APP` (tools/export.py), verified on both interpreters from a plain static server.
      The wheel is served at `/dist/` so a `pyscript.json` can name it by URL.

## M5 (done 2026-09-06): 0.2.0 on PyPI

- [x] `frontage.widgets`, `State` (`field`/`computed`, MicroPython-compatible), `interval`/`poll`,
      `reconcile`, the playground (code in the URL fragment, four examples), a nightly CI job on
      Firefox and WebKit (both pass the full suite locally: 19 tests each).
- [x] Performance pass: the rows benchmark on the finished code is within noise of the M1
      numbers (create 1,000: 170 ms MicroPython, 87 ms Pyodide; 11 ops per row), so the added
      machinery (boundaries, floating holes, root Errored) costs nothing measurable. Decision:
      no JavaScript shim in 0.x; MicroPython is bound by Python execution, not the bridge.

## 0.3.0 (2026-09-06) — the command line, and what React still had to teach

- [x] `mount` empties its target (`clear=False` appends).
- [x] `python -m frontage`: `export` (moved out of tools/, fetches the bundle into a cache),
      `tailwind` (Tailwind's standalone CLI, downloaded once, `tailwind.css` created if missing —
      what `dx` does), `check` (lambda in a t-string, `html(f"…")`; `.py` and the `py` blocks
      of `.md`; in `mk lint`), `pyscript`.
- [x] The playground loads Tailwind's browser build (utilities only) and has a `tailwind`
      example; docs chapters Style and Export.
- [x] `Loading(keep=True)`: a refetch keeps the content on screen (React's transition, the
      part that fits a synchronous reactive graph).
- [x] `is_routing` is true while a navigation's preloads run, not for one batch.
- [x] `unique_id()`; widgets give their control an id and the label a `for`.
- [x] `tree(handle)`: the owner tree as text; `component` names its owner.
- [x] `For(key="id")`.
- [x] `transition()` (0.5.0): render effects the writes dirty are parked until the refetches
      settle, then applied at once; `is_pending`, `use_transition`, `Optimistic`. Not concurrent
      rendering: what the new state would create is built at the commit.

## M6 — prerender and hydrate (0.4.0, 2026-09-06)

Decided from the Preact + Leptos analysis of 2026-09-06. The estimate recorded then: **rough
size under a thousand lines with tests; islands, streaming and server functions stay off the
plan.** Actual: 967 net lines (744 in the package, 223 of tests), one day. Built as a static build step, never a server (the WASM-only
constraint holds).

- [x] `python -m frontage prerender APP [--route …]`: export, import the app on CPython with
      `runtime.prerender.active` (`mount` registers, the router starts at the route, `Portal`
      renders nothing), render with `HtmlRenderer(hydration_markers=True)`, await every
      `Resource`, embed the values as JSON, one `index.html` per route with `../` paths.
- [x] `mount` hydrates a `data-fr-hydrate` target: `Hydration` cursor in `dom.py`, fences
      `<!--[-->`…`<!--h-->` per hole, adoption of elements and text in document order, a
      mismatch rebuilds that piece and sweeps the server's nodes with one console warning.
- [x] Hydrated resources skip their first load; `is_routing`, `Loading` unaffected.
- [x] The replay script: clicks and input made before Python boots are replayed on mount.
- [x] `check` flags HTML the parser rewrites (`<div>` in `<p>`, `<tr>` under `<table>`, `<a>`
      in `<a>`), the hydration-mismatch class Leptos documents.
- [x] Browser tests: counter (adoption proven by a tagged node, early click replayed) and
      fetch (no refetch, data block consumed).
- Off the plan, on purpose (a decision, not a task): islands (Python has no tree shaking, so
      an `@island` saves boot work, not download), streaming modes and server functions (need
      a server).
- [x] 0.5.0: `prerender --crawl` (links filtered to the mounted Router's routes); `import
      frontage.debug` lists each hydration mismatch; `unique_id` counts per mount, named after
      the target (`fr-app-1`), so two mounts or two interpreters never collide.

## Docs (2026-09-06, after 0.4.0)

- [x] Nine chapters in the order things are needed: Basic, **Ship**, Template, Style, Flow, Async,
      Router, State, **Prerender**. Ship is the first half of the old Export chapter plus GitLab
      Pages and GitHub Pages walk-throughs; Prerender is the second half. Every project ends
      "ship it". `/python/frontage/export` redirects to `/ship`.
- [x] One repository per chapter at `gitlab.com/optersoft/python/frontage-<chapter>` (flat, the
      academy's convention; checkout `~/xtec/python-frontage-<chapter>`): `app/` with the
      chapter's code, `.gitlab-ci.yml` and `.github/workflows/pages.yml` exporting it to Pages.
      All nine pipelines green and the sites smoke-tested in Chromium. ⚠ A new project's Pages
      defaults to members-only even when public: `PUT /projects/:id pages_access_level=enabled`
      (`public` is refused for a public project).
- [x] 0.4.1 (2026-09-06): `export` drops the wheel from `packages` and rewrites the CDN links when
      bundling; the chapter repos and Basic name the 0.4.1 wheel; `site.build` keeps every released
      wheel at its URL. ⚠ `git push origin main --tags` created no run for the tag on GitHub (the
      same-commit branch push won); pushing the tag on its own did.

## After 0.4.0 (the plan's "later", not scheduled)

- [x] Async memos (`Memo` returning a coroutine), `is_pending`, `transition()` and `Optimistic`
      (0.5.0, Solid 2.0's model on a synchronous graph). A live server rendering mode is not planned.
- [x] The `frontage` console script (0.5.0); docs say `uvx frontage …`.
- [ ] Docs: `.ca`/`.es` variants once a programme places the pages.
- [x] 0.6.0: a transition builds the new state off screen (render effects compute at once; only
      the effect phase of what is on screen waits; `renderer.is_connected` decides), and
      `Router(transition=True)` / `navigate(…, transition=True)` change the page when the new
      route's data is in, with no fallback.
- [x] 0.7.0: async memos as the router's data primitive (M9 below). DESIGN §16 has no dated
      milestone left; 1.0 is an API freeze once 0.x has users.

## M9 — async memos as the router's data primitive (0.7.0, 2026-09-06)

- [x] `Memo(lambda: get_contact(params()["id"]))` counts toward `is_routing` like a Resource
      (SPEC U13; `reactive._navigation`, the Router's `_track_load`/`_load_done`); the contacts
      example and the Router chapter use it, `Resource(source=…)` stays the declared spelling.
- [x] `prerender` waits for async memos and writes them by ordinal (SPEC L9; the data block is a
      dict, a list still hydrates); a hydrated memo settles without running. Fetch example +
      browser test cover it on both interpreters.
- [x] Docs polish after the three same-day releases: the audit found no version drift and a
      clean `frontage check`; fixed `use_router`/`use_is_routing` imports, the `missing` route
      matching its repo, "accessor" and "boundary" defined where first used, the lambda rule
      explained once (Basic), stale metas, `number_input` import, the `_index` helper.
- [x] The git-connected Pages build had failed on every push since this morning (no PyScript
      bundle on the builder; found through the API build log), so the site sat at 0.4.0 while the
      chapters named 0.5.0–0.7.0 wheels. `site.build` now fetches the bundle; the d510d1d build
      deployed itself. `mk site.deploy` remains the hand fallback.
- [x] The academy serves the chapters whole to anonymous readers (verified 2026-09-08:
      `router`, `basic`, `async` and `ship` all show their exercises).

## M10 — the language server (in progress, 2026-09-06)

Decided this session: it lives in **this** repo, and it is **Python**. One repo because the
extension's whole value derives from `SPEC.md` and the CLI, so the commit that changes a rule
changes the editor's understanding of it in the same diff; Python because `frontage/lsp/`
imports the package and shares `rules.py` with `frontage check`, and a Rust server would be a
second implementation of the spec. Rust was weighed for speed and declined on a measurement:
`ast.parse` + a full `ast.walk` — the entire diagnostics pass — is 3.4 ms on `reactive.py`,
the largest file here, and 0.7 ms on `examples/rows`. `git subtree split` on `editors/vscode/`
is the exit if it ever outgrows this.

- [x] L0 foundations: `frontage lsp`; hand-written JSON-RPC over stdio (`protocol.py`, no
      dependency, so the package's `dependencies = []` and `uvx frontage lsp` both survive);
      `documents.py` with the UTF-16 arithmetic; `scanner.py`, the tolerant t-string lexer and
      the HTML state machine, which is what every feature is a lookup on top of.
- [x] L1 diagnostics: `rules.py` with real ranges — the old `check_source` reported one line
      number, and `nesting_findings` reported the *enclosing template's* line for every finding.
      `cli/check.py` is now the command line over it and its tests pass unchanged.
- [x] L2 completion: elements, per-element and global attributes, and frontage's prefixes first;
      events inside `on:`, the three targets inside `bind:`, CSS inside `style:`, enums inside a
      value, `</` closing the innermost open element.
- [x] L3 hover and go-to-definition, including a component named inside `{…}` — the position a
      Python language server cannot reach, because to it that name is a character in a string.
- [x] L4 semantic tokens, with the TextMate grammar kept as the fallback that works before the
      server starts.
- [x] L5 clients: `editors/vscode/` (thin, plain JavaScript, no build step) and `editors/README.md`
      for Zed, Neovim, Helix and Emacs. `.github/workflows/vscode.yml` releases on `editor-v*`.
- [x] 62 tests in `tests/test_lsp.py`, including one full session over a pipe. `mk lsp.probe FILE`
      prints what an editor would show.
- [ ] `[human]` Register the `optersoft` publisher on the Visual Studio Marketplace and Open VSX,
      then put `VSCE_PAT` and `OVSX_PAT` in the repo's `vscode` environment. Neither marketplace
      speaks OIDC, so these are the first stored secrets in this repo's release path — PyPI needs
      none. Nothing ships until they exist.
- [x] Docs: the Ship chapter has an "In your editor" section (`frontage lsp`, what it gives that
      a Python server cannot, the 3.14 pin, `editors/` for each editor).
- [x] Tried in a real VS Code: activates on `onLanguage:python`, resolves the server through
      uvx, publishes `html-nesting` at the right range. `mk vscode.test` (13 tests, in CI)
      covers the grammar through Oniguruma, the snippets, the manifest and server discovery.
- [x] The lambda rule fires only for the parenthesised form; the bare one is a CPython parse
      error. Two tests now, one per path, and the rule and Basic say which is which.

## 0.8.0 (2026-09-06) — the dev server, the router repo, the profiling session

- [x] `frontage serve [DIR]`: live reload (SPEC L10); `tools/serve.py` and `mk serve` reload too.
- [x] The router chapter repo carries the data loading (`Memo` over a `query`), so the live site
      demonstrates the memo form; the nine pipelines pin `pip install frontage==X.Y.Z`.
- [x] MicroPython profiling session on the rows benchmark: `tools/profile/` + `tools/profile_rows.py`
      (phase by phase, three renderers, a per-primitive calibration). Findings in DESIGN §12;
      tuple `isinstance` gone from the hot paths, calls trimmed (−5%). Bench after, medians of 3:
      create 1,000 = 188 ms MicroPython / 89 ms Pyodide, clear = 44 / 8.4, swap = 17 / 2.5.
- [x] 0.8.3 structural pass (DESIGN §12, third measurement). Unsubscribing was O(observers):
      1,000 effects over one signal took 78 ms to dispose, now 3.3 ms. Create 1,000 rows
      188 → 171 ms (mpy), 89 → 85 (py). The "For, null renderer under 100 ms" target was NOT
      met (≈108 ms): what is left is element construction, spread thin. Two negative results
      are in DESIGN §12 so nobody repeats them (class-attribute defaults on `Owner` are 2×
      slower; a scan instead of the dependency set measures the same).

## 0.8.1 (2026-09-06) — the examples move to the academy

- [x] The chapters run their apps in the page (`::: pyscript` frames on MicroPython, the wheel by
      URL): Basic, Template, Style, Flow, Async, Router, State. frontage.optersoft.com is a 301 to
      academy.optersoft.com/python/frontage (`/examples/<name>` to its chapter) except `/dist/`
      (wheels, CORS) and `/playground/`. Hash mode ignores a fragment that is not a path.
      `examples/` stays the browser suite's material; a separate Examples page was tried and
      withdrawn the same evening.
- [x] Call-count pass on the core: 332 → 266 Python calls per row; a 1,000-row create on
      MicroPython 124 → 108 ms (null renderer), 163 → 151 ms (DOM, templates).
- [x] 0.8.2: the demo app, `examples/tracker/` (routes + query string, a store kept by `reconcile`,
      memo-loaded details over a preloaded `query`, a transactional done toggle with `Optimistic`
      inside a `transition`, a Portal modal, `ActionForm` + `State` + widgets, boundaries, an
      interval), driven end to end by `tests/browser/test_tracker.py` on both interpreters,
      prerendered in `test_prerender.py` and hydrated in `test_hydrate.py`. It found five
      framework bugs, all fixed: a memo whose compute hit `NotReady` read as None (C16), a
      preload failure took the app down (U14), `query` hid the real error from waiters, the
      prerenderer ignored async memos started during a render and waited on disposed resources,
      and on MicroPython a task that disposed its own owner cancelled itself (C24).

## M11 — boot from WebAssembly, drop PyScript (0.9.0, planned 2026-09-07)

The delivery model Dioxus and Leptos have: the browser loads a compiled artifact instead of
fetching sixteen `.py` files and compiling 5,700 lines on every page view. MicroPython only;
the framework is cross-compiled to bytecode at release and vendored in the wheel; the app
ships as source and costs about two milliseconds to compile in the VM. Plan in
`~/.claude/plans/fizzy-stirring-simon.md`.

- [x] Phase 0, the spike (2026-09-07), green and measured — numbers in DESIGN §12. Boot
      **88 → 52 ms** and **29 → 6 requests**; counter and the t-string template example both
      run, reactivity and all. Size is the small part: the framework is 53 KB gzipped as
      source against 40 KB as bytecode, so what the compile buys is the parse, not the
      download. `build/spike/` has the whole thing (gitignored).
      - `runtime.py`'s two imports really are the entire PyScript coupling: point them at `js`
        and `jsffi` and nothing else in the package moves.
      - `romfs` exists in this build but is **not** worth its image builder; the 30-line JS
        untar wins. Overrides the plan's preference.
      - Two MicroPython findings for Phase 1: `type(sys)('__main__')` raises, so the app is
        exec'd against `runPython`'s globals, which are already `__main__`; and mpy-cross
        rejects adjacent f-strings (`f"a" f"b"`), which happens once, at `reactive.py:182`.
- [x] Phase 1 (2026-09-07): the runtime seam, the vendored runtime, `frontage build`. **The
      framework changed by 21 lines** — `runtime.py`'s two imports, and one adjacent-f-string
      merge. Everything else is toolchain: `frontage/_runtime/` (committed, 628 KB, in the
      wheel, which goes 100 KB → 394 KB), `frontage runtime fetch|image`, `frontage build`,
      `mk runtime.fetch`/`mk runtime.build`/`mk build`, `typings/jsffi/`, 15 tests. mpy-cross
      is dev-group only, so `dependencies = []` is untouched.
- [x] Phase 2 (2026-09-07): prerender and hydration on the new boot. `find_entry` reads
      `data-fr-entry` instead of hunting `src="./app.py"` through inline JavaScript with a
      regex; `prerender --boot pyscript` keeps the old page for 0.9.x. Verified in Chromium on
      the prerendered counter and fetch examples: HTML on screen before Python, an early click
      replayed, the tagged node adopted rather than rebuilt, fences and `data-fr-h` consumed,
      the data block consumed and removed, no refetch, no hydration warnings.
      - `relocate` needed **no change**: the loader takes every runtime path from
        `import.meta.url`, so a nested route rewrites exactly one string, the boot tag's `src`
        (`./` → `../` → `../../`, verified at depth 2 through `--crawl`).
      - `build` strips PyScript's `core.js`/`core.css` from a page it is migrating, so a
        converted app does not ship two 404s.
      - ⚠ Pre-existing, not caused by this work: `prerender examples/tracker --crawl` fails on
        the tracker's deliberately cursed issue 13. The PyScript boot fails identically.
- [x] Phase 3 (2026-09-07): the module-swap hot reload. Save a file and the page rebuilds in
      **under 180 ms without reloading**: the interpreter stays up, the wasm is not fetched
      again, the scroll position stays. `frontage/dev.py` (compile, dispose, drop from
      `sys.modules`, re-run the entry as `__main__`), `view._mounted`, `DomRenderer.teardown`,
      and a `serve.py` that reports *which* paths changed and streams JSON. Nothing is built in
      dev: both archives are synthesised per request off disk, so a framework edit is live too.
      Verified in Chromium: no reload, state rebuilt, still reactive, no leaked listeners, a
      syntax error leaves the last good page up and interactive, and a later good save recovers.
      - **The `Router` teardown was not needed and the risk was misdiagnosed.** `Router.__init__`
        registers nothing; `popstate`, `hashchange` and the document click listener are all
        registered in `__call__`, under the mount's owner, so disposing the mount removes them.
        A module-level `Router` is fine.
      - **The real leak was `DomRenderer`'s delegated dispatchers** — one per event type on
        `document`, shared by every element, owned by nobody. Invisible while a page mounted
        once and ended; twenty-four per swap otherwise.
      - Fixed on the way: `web/playground/playground.py` disposed `handle[0]`, which was always
        None, so every Run leaked a root owner and those listeners. It now calls
        `dev.teardown()`, and the dead `handle` is gone.
      - ⚠ **Do not reload the page when a swap fails.** The usual failure is a half-typed file,
        and `dev.swap` compiles before it tears anything down, so what is on screen is still the
        last version that worked. Reloading replaces it with the broken source and a blank page.
        This was written the wrong way round first and the browser test caught it.
      - MicroPython in this build **has `compile()`** and it rejects bad syntax, so the
        compile-before-teardown guarantee is real. Verified in the VM, not assumed.
- [x] Phase 4 (2026-09-07): examples, the dev server, the browser suite and the playground all
      boot from wasm. **The browser suite is 16 tests in 14.5 s**, against ~44 cases and over a
      minute when every one ran twice. No `?type=`, no PyScript anywhere in `examples/`.
      - `<dir>/_frontage/…` resolves **per directory**, so one server carries every example with
        the same relative boot tag a built app uses, and `tools/serve.py` lost the `/pyscript/`
        rewrite (and `web/_redirects` its mirror of it). `mk site.build` is 23 files and 1 MB.
      - `MISMATCH_PAGE` is **gone**: that fixture writes no `index.html`, so `build` supplies the
        boot shape and the test cannot drift from what the command emits.
      - Two tests were asserting things that were only true because the old boot was slow. The
        fetch hydration test read the data block from the live DOM, which Python now consumes
        first; it reads what the server sent instead. Pyodide's 60–90 s boot budgets are 30 s.
      - The export tests now build their own PyScript-shaped app. Exporting an example to
        PyScript stopped being a real combination, so it was asserting nothing.
      - ⚠ **A rejected promise is nobody's problem now.** `playground.share` wrapped
        `clipboard.writeText` in `try/except`, which catches only the synchronous half; PyScript
        used to swallow the rejection and a denied clipboard is ordinary. It surfaced as an
        uncaught page error the moment PyScript left. Handled on the promise now. Anything else
        that ignores a returned promise has the same hole.
- [x] Phase 5 (2026-09-07), the parts that live in this repo: Pyodide and PyScript out of
      `DESIGN.md` §3/§6, `CLAUDE.md`, `README.md`, `pyproject.toml` and the academy's
      `index.md`; `web/_headers` gains `Cross-Origin-Resource-Policy` beside the CORS it
      already had, and the same pair on `/playground/_frontage/*`; CI drops both PyScript cache
      blocks and **the `publish` job now asserts the vendored runtime is in the wheel** —
      `import frontage` passed without it, so a packaging mistake would have shipped a release
      that installs cleanly and boots nothing. That assertion was run against a real wheel, not
      merely written.
      - `version.py` is **deliberately still 0.8.3**. Bumping it is a release, and a release is
        a commit in nine chapter repos too (the rule is in `CLAUDE.md`). The docs describe
        0.9.0 because that is what this work ships as; the tag is a separate, deliberate act.
- [x] Phase 6 (2026-09-07): **foreign wasm libraries (C, Rust) are a declared contract.**
      `data-fr-js="mathlib=./mathlib.js"` on the boot tag; `boot.js` imports each one, awaits
      it, and `registerJsModule`s the named ones, so an app writes `import mathlib` and
      `from mathlib import add`. Specifiers resolve from `../` of `boot.js`, which is the app's
      own directory in every layout, so a prerendered page at any depth is correct with nothing
      for `relocate` to rewrite. `build` and the dev server needed **no change**: the `.js` and
      `.wasm` are copied and served already.
      - `examples/wasm/`: a **41-byte** hand-assembled module whose every byte is in the docs,
        so a reader can see there is no magic in it. Browser test asserts the import, 2,000
        correct crossings and reactivity. Verified served *and* built.
      - Measured: **1.00 µs per crossing**, about four MicroPython method calls (§12). The
        limit is volume, not frequency — separate linear memories, so anything but a number is
        copied through JavaScript. That is what decides a coarse boundary API.
      - Chapter written and shipped: `wasm.md` + `.meta.md`, in `index.md` under "Going
        further", with a repository of its own like the other nine. Its `::: pyscript` frames
        work unchanged — 0.9.0 runs under PyScript, because it talks to MicroPython's own
        `js`/`jsffi`, which PyScript never removed. The `::: frontage` frame is a nicety now,
        not a blocker.

## M11 — what is left before 0.9.0 ships

- [x] The frontage half of the `::: frontage` frame (2026-09-07). `boot.js` exports
      `startRuntime()`, and **`web/runner.html`** is the page a frame points at: the program
      arrives as percent-encoded JSON in the URL fragment (`{"code":…, "markup":…}`), the
      markup fence becomes the body, and a raising program shows `format_exception` output
      rather than a blank frame. Proven in a **sandboxed, opaque-origin frame**, which is how
      the academy embeds one. Two browser tests.
      - Importing `boot.js` with no boot tag now **warns instead of throwing**: a runner
        legitimately has no app to boot. A real app missing its tag still says so.
      - `frontage serve` now sends the CORS and `Cross-Origin-Resource-Policy` headers that
        `web/_headers` sends in production, or a frame would work on Pages and not locally.
      - `mk site.build` publishes the runtime **twice**: under the playground and at the site
        root for the runner. One copy cannot serve both, because `boot.js` finds `app.tar`
        beside itself and the runner has no app.
- [x] The nightly matrix, run for real (2026-09-07). **Chromium, Firefox and WebKit are all
      19/19** on the wasm boot. WebKit was 18/19 and it was **not** M11's doing — the same
      test failed on `main` at `76c80d1`, twice, once per interpreter.
      - The cause: **WebKit resets `history.scrollRestoration` to `auto` on every hash
        navigation.** Chromium and Firefox keep `manual`, so setting it once in
        `HashMode.__init__` was enough there and quietly useless on WebKit from the first
        `location.hash =` onwards. After that the browser restores scroll itself before
        `hashchange` fires, so the position the router records for the page being left is
        already the next page's — precisely what `_manual_scroll_restoration` exists to
        prevent (U10), and what DESIGN §10 describes.
      - Fixed by re-asserting it after every navigation `HashMode` causes or observes.
      - Worth remembering: this had been failing on the nightly job since some point after
        M5, where the entry claims both browsers passed. Nobody was reading it.
- [x] **The academy's `::: frontage` frame shipped (2026-09-08).** `academy-content`'s
      dispatch gained the branch beside `"pyscript"`, and `academy_preview::pyscript` grew a
      second runtime — `frontage.optersoft.com/runner.html`, a `{"code", "markup"}` fragment,
      no packages and no terminal — with three tests. Seven cards across the chapters were
      opened in Chromium against production and run.
- [x] The nine chapter repos moved to `frontage build` (2026-09-07). One boot tag instead of
      PyScript CDN links, `pyscript.json` deleted, both pipelines on `frontage==0.9.0` and
      `frontage build`. All nine built and opened in Chromium before pushing, all nine
      pipelines fired, and all nine deployed sites verified live with the boot tag present.
      They did **not** need to wait for the academy's frame: 0.9.0 talks to MicroPython's own
      `js`/`jsffi`, which PyScript never removed.
      - [x] The tenth repo exists: `gitlab.com/optersoft/python/frontage-wasm`, built from the
        chapter's own code, live and verified. Its `pages_access_level` was set explicitly —
        a new GitLab project serves Pages to members only even when the project is public.
      - [x] The nine READMEs caught up too: they still described PyScript, a `pyscript.json`
        the repos no longer have, and a pipeline running `export`.
- [x] Release: bump `version.py`, check the chapters name the new wheel, tag `v0.9.0` (0.9.0 and 0.9.1 shipped).
## M12 — faster than React, in one release: 0.10.0 (planned 2026-09-08)

The plan is `FASTER.md`; §1–§4 there are measured, on the examples, on the pinned
interpreter, and on seven custom builds of the MicroPython wasm port made for it. What it
decides, all in 0.10.0:

- [x] ~~**Our own build of the interpreter.**~~ Superseded 2026-09-08: MicroPython is gone from
      `main`; the runtime is frontage's own (`rust/`). Kept for the record: an out-of-tree variant for `ports/webassembly`
      (three files, `VARIANT_DIR=`, upstream tag untouched): **`SUPPORT_LONGJMP=wasm`** (the
      upstream build routes every Python exception through JavaScript longjmp trampolines),
      an optimised link (upstream never runs Binaryen), the frozen micropython-lib cut from
      27 packages to `asyncio`, unused C modules off. Measured: 446 → 266 KB raw, 196 →
      125 KB gzip, 170 → 108 KB brotli; a Python call 0.248 → 0.052 µs (4.8×); on the real
      page, **create 1,000 rows 139 → 71 ms, swap 12 → 4.4, update 3.3 → 1.4**, with the
      framework unchanged. The browser suite (21 tests) passes on it. Safari ≥ 15.2.
      Bump to upstream `1.29.0-6` on the way.
- [x] ~~**The framework core in Rust, inside the interpreter**~~ Superseded 2026-09-08 by the
      native core in frontage's own runtime (below). Kept for the record (`frontage/_core`: a `no_std`
      staticlib behind a ~300-line C shim, linked by `runtime build --c-modules`) — **was
      "in C"; `RUST.md` (2026-09-08) is the design and the reason.** Probed the same day, on
      stable Rust 1.96 and the pinned emsdk: it links first time, `no_std` costs 1 KB of
      brotli (`std` would cost 17), a Python closure called from Rust is 24 ns, and a Python
      exception passes through Rust frames with the interpreter intact. What moves is
      unchanged: the reactive graph, template holes, `For`/LIS, `Store`, then the DOM op
      stream with integer node ids. Gate: create-1,000 under 20 ms in `profile_rows`, swap
      and update no worse. API unchanged; the Python implementation stays for CPython and
      behind a flag. **One decision for the user first: Rust or C** (`RUST.md` §7.1).
- [x] **The spike of a Python runtime of our own ran (2026-09-08, `RUNTIME.md` §9, code in
      `rust/`, uncommitted).** A NaN-boxed Rust bytecode VM with a precise collector, a
      compiler over ruff's parser, a JavaScript bridge and a wasm build: 157 of the framework's
      unit tests pass on it under node, `counter`/`todo`/`profile` boot in Chromium.
      **Gates: correctness met; speed at parity with MicroPython (70.1 vs 71.1 ms create),
      not 2×; size 179 KB brotli against ≤ 120, and the wasm is 80% interpreter with nothing
      removable at that scale.**
- [x] **Decided 2026-09-08: the native reactive core is built in the Rust runtime**
      (`RUNTIME.md` §3.8), not in MicroPython through the C shim of `RUST.md` §3.1. The
      spike's numbers (§9) said the interpreter alone is parity and the 2× is the core; the
      user chose the runtime that can hold the core as VM types. `main` ships MicroPython
      until the runtime reaches parity with the browser suite; `rust/` is the release path
      from here. Done the same day: the build packs the import closure (`cli/graph.py`),
      `re` over `RegExp` (`rust/vm/src/lib/re.py`, a web case in the differential suite).
- [x] **The native core in the runtime** (`RUNTIME.md` §3.8, `FASTER.md` step 2 landing
      here). Gate: `profile_rows` create ≤ 35 ms (2× MicroPython's 71), the 157 tests
      unchanged — **met, 24.8 ms.** Measured in Chromium, create of 1,000 rows with DOM templates, each step
      committed the same day (2026-09-08):
      - [x] the reactive graph as VM types (`rust/vm/src/core.rs`: Signal/Memo/Effect/Owner,
            tracking with O(1) unsubscribe, marking, the flush, batch; `reactive.py` keeps the
            Python implementation for CPython and switches to `_core`): **74.9 → 58.8 ms**.
      - [x] the DOM op stream (`rust/vm/src/dom.rs`, `glue.js`, `dom.py`'s `StreamRenderer`:
            nodes are integers, operations are bytes executed in one crossing, delegated
            events walked in JavaScript): **58.8 → 46.9 ms**; the counter boots in 29 ms
            (62 before, MicroPython 52).
      - [x] the view's template path in Rust (`rust/vm/src/view.rs`: `Template.extract`,
            the clone and its holes, the two hole effects — a child position with the insert
            rules and reconcile, a bound attribute — `_listen` with an unlisten record among
            the owner's cleanups; taken for the streaming renderer without hydration and a
            cached Template, `view.py` for everything else): **46.9 → 24.8 ms. Gate met**
            (2.9× MicroPython's 71.1). Every phase of `tools/profile` on the runtime, Chromium,
            MicroPython in brackets: For DOM templates 26.8 (71.1), swap two rows 2.9 (4.4),
            update every 10th 0.6 (1.4), effects create+dispose 1,000 0.4 (4.8), 1,000 text
            holes 2.1 (6.6). The Python left per row is the author's `h` calls (`_children`,
            7 ms of a 32 ms profiled run) and the Store's reads (9 ms): the next tenants, if
            wanted — the gate no longer asks for them.
- [x] **The browser suite passes on the runtime, 28 of 28 (2026-09-08, the same evening).**
      `frontage build --runtime frontage` and `frontage serve --runtime frontage` (or
      `FRONTAGE_RUNTIME=frontage`, which the suite reads: `FRONTAGE_RUNTIME=frontage mk test
      --browser`) pack the entry's import closure as `.fbc` with a manifest, through
      `cli/frontage_rt.py` and the `fpy` binary from `rust/target/`; the playground and the
      runner stay on MicroPython, which has the parser. Found on the way, each now a test: an
      async method called with keywords bound its receiver twice; a JavaScript constructor
      read off an object (`window.FormData`) had no `.new`; hydration's cursor must stay on
      proxies and every proxy read flushes the op stream first; a floating hole's parent is
      a question, not `-marker`. Prerender + hydration work unchanged.
- [x] **`main` ships the runtime, and only the runtime (2026-09-08, the user's call).**
      MicroPython is gone — its interpreter, `frontage.tar`, `mpy-cross`, the variant, the
      PyScript `export` — and `frontage/_runtime/` holds `frontage.wasm`, `frontage-compiler.wasm`
      (the same with the compiler: the playground and the runner `exec` a program in the page),
      `glue.js` and `boot.js`, vendored by `mk runtime.build` and shipped in the wheel. The
      compiler `fpy` is fetched from the release's assets on first use (CI builds five, one per
      platform, on a tag), like the Tailwind CLI. `frontage serve` swaps modules over `.fbc`.
- [x] Runtime gaps the suite did not reach, closed 2026-09-08 with a differential case each:
      `match` statements (PEP 634, every pattern kind, over four hidden builtins), metaclasses
      and class keywords (`type.__new__`, a class typed by its metaclass, `__init_subclass__`
      with keywords), a generator's `finally` when it is collected unreachable (the collector
      keeps it one cycle and the VM closes it), `__slots__` (accepted; not enforced), and a
      size budget test (`test_the_runtime_stays_within_its_size_budget`: 300 KB gzip, 261
      today).
- [x] **0.10.0 and 0.10.1 are on PyPI (2026-09-08)**, with the five `fpy` binaries on each
      GitHub release; a clean `uvx frontage build` fetches the one for its platform and works.
      0.10.1 adds `binascii`, which `examples/uber` needs and 0.10.0 lacked — the gallery
      caught it after the tag. The ten chapter repositories are pinned to 0.10.1, rebuilt and
      verified live. The academy chapters are rewritten and committed.
- [x] **The release is live end to end (2026-09-08).** frontage.optersoft.com deploys from a
      push now (Cloudflare Pages builds `mk site.build` itself), and three things had to be
      fixed for that build to pass: an app with a t-string could not be read by a build host
      older than 3.14 (0.10.2), the compiler asset was fetched by exact version while the
      release was still uploading (a fallback to the latest release), and `@optersoft/astro`
      kept Vite's module runner open past its config hook. The academy's ten chapters, their
      seven `::: frontage` cards, the playground, the gallery and the runner were all opened
      in Chromium against production and run.
- [x] **Every gallery card on the site was a 404** (found and fixed 2026-09-08). `site.build`
      moves the measured gallery aside, lets Astro write `www/`, and moves it back — and
      `shutil.move` of a directory onto an existing one puts it *inside*, so the apps landed in
      `www/gallery/_gallery-keep/` while the index that lists them looked perfectly well. It
      merges entry by entry now. Nothing tests `mk site.build`, which is why this shipped;
      the cheapest guard would be a line in the task itself that fails when
      `www/gallery/<first app>/index.html` is missing.
- [x] **The site deploy raced its own release, twice** (2026-09-08). `frontage build` fetches
      the `fpy` binary from the release matching its version; the deploy that Cloudflare starts
      on the version-bump push runs while that release's assets are still uploading. The
      0.10.2 fix — fall back to `releases/latest` — does not help, because a release exists
      from the moment its tag is pushed: during a release, `latest` **is** the incomplete one,
      so the build asked twice and got the same 404. It now walks the releases list and takes
      the first one that actually carries the asset.
- [ ] `[human]` The academy still describes 0.9 in `python/frontage/polars.md`'s measurements
      and in any `.ca`/`.es` variant of these pages, if one is ever cut. Re-measure the polars
      binary-vs-JSON numbers on this runtime when that page next changes.
- [x] **`_core.sort/filter/group` as the core's first tenant.** Moot with the runtime: its
      `sorted` is a stable merge sort in Rust that calls `key` once per element — **10,000
      ordered floats sort in 2.0 ms on the wasm, 2.5 with a key** (MicroPython: 269 and
      1,440). The gate was under 5 ms. `frontage.table` sorts with `sorted` and needs nothing
      else.
- [x] **0.11.0: islands and static pages — `ISLAND.md` steps A, B and C (2026-09-09).**
      `mount(view, "#app", when="never")` is a static page: `frontage prerender` writes the
      HTML and no boot tag, and a built content page makes **no request under `_frontage/`**
      — 142 bytes over the wire against the 264,658 a prerendered app still waits for.
      `island(view, when="load"|"idle"|"visible"|"media:…"|"only"|"never", **props)` renders
      at build time into an `<fr-island>` wrapper; `_runtime/island.js` (1,341 bytes brotli,
      the only script such a page carries) watches the triggers, boots the runtime **once**
      for every island on the page, and `frontage.island` — which the boot runs as
      `__main__`, there being no app entry to run — mounts each wrapper over its own markup,
      in its own `unique_id` scope, with its own settled values. `island("mod:name")` is a
      chunk root like `Route(lazy=…)`. `examples/islands`, `tests/test_island.py`,
      `tests/browser/test_island.py`, `SPEC.md` §10.
      Three things the plan did not know: the wrapper is `display: contents` and generates no
      box, so the observer has to watch the island's **children**; `frontage.island` needs
      absolute imports because a relative one under `__main__` resolves against `__main__`;
      and an island needs a hydration data block of its own rather than the page's.
- [x] **The academy covers islands, and is current on 0.11.2 (2026-09-09).** A seventeenth
      chapter, `python/frontage/islands.md`, with its repository
      `gitlab.com/optersoft/python/frontage-islands` — a theme toggle on `idle` and a chart on
      `visible` named as a string, so its module and its data are a chunk. Every labelled code
      block in the page is that repository's file byte for byte. Around it: all eleven
      pipelines moved 0.10.1 → 0.11.2 and the prerender job lost `--no-pyscript` (a flag that
      went with PyScript and now fails the build); `prerender.md` lost "before `core.js` has
      arrived" and "exactly as `export` does" and gained the hand-off to islands; `style.md`
      no longer builds its CSS "before the export"; `index.md` counts seventeen. All eleven
      chapters rebuilt and `frontage check`ed against the published wheel, all eleven
      pipelines green, all eleven pages live. The claim in `CLAUDE.md` that the chapters
      "still describe MicroPython (0.9.x)" was itself two releases stale.
- [x] **0.12.0: content collections — `ISLAND.md` step D (2026-09-09).** `frontage.content`:
      `collection(name, schema)` over `content/<name>/`, front matter through
      `frontage.schema`, Markdown by markdown-it-py, and `::: island posts:comments
      when="visible"` in prose as a real island. A bad front matter fails the build naming the
      file and every field, which was the gate. `Entry.view()` is the prose as *elements*, not
      a blob of HTML, so the prerenderer fences it and an island in it is a node in the tree.
      `examples/blog`, `tests/test_content.py`, `tests/browser/test_content.py`, `SPEC.md`
      §11. The `content` extra (markdown-it-py, mdit-py-plugins, PyYAML) — build-time only,
      and no page ever downloads a Markdown renderer.
      Three things the plan did not know: the render must run **before** the build finishes,
      because an island named in prose is invisible to the import walk (the page 404'd on
      `frontage.island.fbc`); on a static page only the *islands* may decide which components
      ship, or a page that uses `frontage.schema` at build time links the schema component's
      stylesheet; and YAML hands back a `datetime.date` where `iso_date()` wants a string, so
      content data is normalised to JSON on the way in.
      Also `frontage serve --prerender`: a content page cannot run in the browser at all, so
      its dev loop is the build, re-run when a file changes.
- [x] **The academy covers content too (2026-09-09).** An eighteenth chapter,
      `python/frontage/content.md`, with `gitlab.com/optersoft/python/frontage-content` — the
      twelfth chapter repository, and the first whose pipeline installs an extra
      (`"frontage[content]==0.12.0"`). All twelve pipelines on 0.12.0, all twelve apps
      rebuilt and `frontage check`ed against the published wheel, all twelve pages live.
- [x] **0.13.0: `frontage site` — `ISLAND.md` step E (2026-09-09).** A directory of pages as
      a directory of files. `pages/` is the site map (`index.py` → `/`, `blog/[slug].py` →
      one page per `static_paths()`, `docs/[...path].py` → the rest of the path), a layout is
      an ordinary component taking `children`, an endpoint is a module with a `get()` written
      at its own name (`sitemap.xml.py`), `public/` is copied, `_redirects` comes from
      `site.py`. A page or endpoint whose signature names `site` is handed every URL the build
      made — which is how the sitemap knows them. Every page is static: the example's six
      ordinary pages fetch nothing under `_frontage/`, and the runtime is written once,
      beside them, only because the seventh has an island. `frontage serve --prerender` builds
      and serves a site with live rebuild. `examples/site`, `tests/test_site.py`,
      `tests/browser/test_site.py`, `SPEC.md` §12.
      Four things the plan did not know: a page must be **called inside its mount** or an
      `::: island` in the Markdown it renders comes out inline; a collection must resolve its
      directory on first use, because a site imports every page before it renders one; a dev
      rebuild must drop the site's modules from `sys.modules` or the pages come out fresh and
      their content does not; and `[...path]` has a dot in it, so `Path.suffix` called the
      rest route an endpoint named `path]`.
      ⚠ E's gate in the plan was "`web/` rebuilt from frontage" — that is F+G's, since `web/`
      is on `@optersoft/astro`. E's own gate is the one above.
- [x] **0.13.1: locales — `ISLAND.md` step F (2026-09-09).** A parameter can be a directory,
      so `pages/[lang]/blog/[slug].py` has two and `static_paths()` returns both;
      `static_paths(site)` gets the site, so a locale tree is `return site.paths()`.
      `LOCALES` in `site.py` is a list whose first entry is the default and contributes **no
      URL segment**, so English is at `/` and Spanish at `/es/`. `frontage.i18n` writes the
      `hreflang` alternates (with `x-default`) and the switcher; `collection().locale(lang)`
      is `content/<name>/<lang>/`; the build writes `<html lang>`, which no layout can reach.
      `examples/locales` is twelve pages in three languages, `tests/test_locales.py`,
      `tests/browser/test_locales.py`, `SPEC.md` §13.
      ⚠ **The switcher is not an island, and the plan expected one.** The build made every
      page, so `site.translate(path, "es")` is an answer and the switcher is two `<a>` and a
      `<span>` — a reader changing language waits for a document, not for a runtime. The
      example fetches nothing under `_frontage/` at all.
- [x] **The a11y focus test was flaky, about one full-suite run in three.** `editable` starts
      `frontage serve` and the test then writes `counter.py`; the watcher had not seen the
      write yet, so it swapped the module a moment *after* the page loaded, which re-ran the
      entry and took the focus the test is about with it. It waits for the watcher to absorb
      the change before loading the page now, which makes the test about focus rather than
      about timing. Four full runs green since.
- [x] **The academy covers sites and locales (2026-09-09).** A nineteenth chapter,
      `python/frontage/sites.md`, with `gitlab.com/optersoft/python/frontage-sites` — the
      thirteenth chapter repository: eight pages in two languages, 388 bytes for the home
      page, no `<script>` in the output at all. All thirteen pipelines on 0.13.1, all
      thirteen apps rebuilt and `frontage check`ed against the published wheel, all thirteen
      pages live.
- [ ] **A site's links are absolute, so it needs a root.** `/blog/` is what the build knows,
      so a site served under a path — a GitHub Pages *project* site is `user.github.io/repo/`
      — follows its own links out of the deployment. GitLab Pages gives every project its own
      domain, which is why the chapter's site works, and Cloudflare Pages and Netlify serve a
      directory at `/`. The general fix is a `BASE_PATH` in `site.py` that the build prefixes
      onto every root-absolute `href` and `src` in the output — one pass over the written
      HTML, not a helper every page has to call (Astro's `base`). Written down in the chapter
      and the repo README meanwhile.
- [ ] An island whose component lives in an **installed package** is not packed.
      `build.required` reads imports to decide which component packages to ship, and an
      island's own module has no reason to import its package by name — only the spec says
      it (`optersoft_brand.theme:toggle` needs `optersoft_brand`). Ten lines in
      `site.write_runtime` fix it, and they were written and then reverted, because the
      chrome that motivated them turned out to need no island at all. Do it when something
      real asks: it fails as a module the page cannot import, which is a confusing way to
      find out.
- [x] **0.13.2: what step G needed from the framework (2026-09-09).** `STATIC` in `site.py`
      — a list of directories copied into the output, `(path, where)` to place them — so a
      site can take a stylesheet, four fonts and a favicon from a **package** without any of
      them living in the site's repository. And `<script>`/`<style>` as **raw text**: their
      content is no longer escaped on the way out, and the template compiler no longer turns
      it into a `<!--h-->` hole. An inline theme script with `&&` in it came out as
      `&amp;&amp;`, and the marker inside it was a line of JavaScript rather than a marker,
      so the template found one fewer than it had written and raised on the next row.
- [x] **0.13.3: `web/` is a frontage site — `ISLAND.md` step G, half of it (2026-09-09).**
      frontage.optersoft.com is built by frontage, on `optersoft/brand` (the chrome, ported
      from `@optersoft/astro` and pushed to github.com/optersoft/brand). `pages/` is the
      landing page, the gallery index and `pages/404.py` — whose `PATH = "/404.html"` is the
      new bit: `frontage site` writes `<url>/index.html`, and a host looking for `404.html`
      would never find `/404/`. `layouts/site.py` is the chrome with this site's brand;
      `tailwind.css` imports the chrome's `chrome.css` and `--tailwind` compiles one file.
      `mk site.build` writes it straight into `www/`; `mk site.dev` is `frontage serve
      --prerender`. **Astro, `@optersoft/astro`, `node_modules`, `package.json` and
      `web/src/` are deleted**, and every page of the site makes four requests and carries no
      `<script src>`.
      Two sharp edges found by deploying it and looking: `relocate` rewrote the gallery's own
      `./counter/` links to `../counter/`, so every card pointed one directory too high and
      the page looked fine — a site is served at a root and is not relocated at all now; and
      the island loader's `./_frontage/island.js` asked two directories too deep from a post.
      The template *is* normalised, because it sits one file behind pages at every depth.
      ⚠ The chrome ships **no island**, which G's gate expected: the theme has to be applied
      before first paint, so twelve lines are inline in the head, and the toggle's clicks
      belong with them. Three islands the plan named, three better without one.
- [x] **0.13.5 + the corpus: `site/`'s copy is content collections (2026-09-09).** The first
      half of G's other half. `src/content/` was three 490-line `Content` objects and a
      373-line `types.ts`, a shape Astro needed because TypeScript was the only thing that
      could say "a field added to one locale must be added to the other two". A
      `frontage.schema` record says it on the data and names the file and the field. The
      three legal documents were 954 lines of typed blocks — `p`, `ul`, `table`, `note` —
      which is a hand-rolled Markdown AST; they are Markdown now, and `note` is the `:::`
      container. A case study is a document, an app is a thing, a person is a person: 66
      files where there were six, in `~/optersoft/site/content/`, with `corpus.py` over them.
      **Converted, not retyped** (`site/tools/convert_*.py` read the real TS through Node):
      all 1,518 strings present verbatim, every legal block accounted for. The framework
      needed `PATH` as a *function* of the params, because the paths are translated slugs.
      ⚠ The port surfaced **stale marketing copy**: the frontage case study still says
      "PyScript", "MicroPython · Pyodide" and "a nine-chapter course". It is live on
      optersoft.com today and has been wrong since 0.10.
- [ ] **G's other half, the rest: `site/`'s pages and components on frontage.** 27 pages, three
      locales, the theme toggle and the language switcher — both of which are now plain HTML
      rather than islands. It is a separate repository (`~/optersoft/site`), it is live, and
      its content is 27 pages of TypeScript modules that become YAML collections. When it
      lands, `astro/` is retired for both sites and `ISLAND.md` is finished. The Optersoft chrome as a frontage
      component package in `optersoft/brand` (see the entry below). Acceptance, and the gate
      for E and F as well: `web/` and then `site/` rebuilt from frontage, `astro/` retired for
      them — 27 pages, three locales, the theme toggle as an island.
- [ ] The gallery cannot show a *site*. `tools/gallery.py` builds one app per card with
      `frontage build` or `frontage prerender`; `frontage site` is a third command and a card
      would be a whole tree rather than a page. Either teach it a `SITE` set whose card
      measures the site's entry page, or accept that the blog card is the one that carries
      the number and say so on the page.
- [ ] **The chrome is a project of its own — `optersoft/brand` (decided 2026-09-09, David).**
      Not a `frontage` subpackage and not `astro/` renamed: `frontage` is Apache-2.0 and
      shipped to strangers, and the chrome is one company's logo, fonts, palette and footer.
      **`brand`, not `chrome`**: this fleet is full of browser automation, so "the chrome
      broke" is ambiguous exactly where it would be said, and `import chrome` is a bad name
      to claim — while `brand.css` and `theme.css` are what the repository actually owns.
      ⚠ It should be the **source of truth for the brand**, not a third copy of it:
      `astro/src/styles/brand.css` is 3,834 bytes against `dioxus-chrome/assets/brand.css`'s
      4,429, and `theme.css` exists in only one of them — the parent `CLAUDE.md`'s "keep both
      equal" is already broken, and a third copy makes it worse. `web/`'s CI builds off this
      laptop, so the chrome has to be fetchable there, which is why `astro/` is public on
      GitHub and is the same answer here. `ISLAND.md` §6 has the reasoning.
- [ ] A content build ships the Markdown it rendered. `build` copies the app directory, and
      `content/` goes with it like the `.py` sources do — harmless for a public blog, wrong
      for a site with drafts in the tree. The fix is not to special-case the name: it is for
      the build to copy what the page *references*, which is step E's question anyway.
- [x] **0.11.1: the islands feature finished (2026-09-09).** Four things, and the third is the
      one that mattered:
      - **The gallery shows the release's own number.** `tools/gallery.py` grew `PRERENDERED`:
        such a card is built with `frontage prerender` and measured with everything under
        `_frontage/` **denied** but the loader, so its `ready` selector is proof the page needs
        none of it and the figure cannot quietly include 660 KB of runtime. **Islands: 10 KB,
        65 ms, "no runtime"**, beside 771–1,199 KB for the fourteen app cards.
      - **The early-click replay is per island.** `__frontage_replay(root)` dispatches only
        what happened inside `root` and keeps capturing until no `<fr-island>` is left
        waiting; without an argument it is the old whole-page behaviour. `end_hydration`
        leaves an island's replay to `frontage.island`, which fires it after marking the
        wrapper mounted.
      - ⚠ **Two islands hydrating in the same frame broke the first one.** Delegated events
        reach Python through *one* dispatcher registered with the runtime
        (`_dom.set_dispatcher`), so each island's own `DomRenderer` replaced the last and
        every island that mounted before it stopped hearing its clicks — silently, with the
        DOM looking perfectly hydrated. `island._shared_renderer` is one renderer for the
        page. The 0.11.0 tests never caught it because no page in them had two islands
        hydrate at once.
      - **`only` is no longer rendered at build**, which is what it says: an empty wrapper the
        browser fills, for a component with no server-side meaning.
      Also `frontage prerender --quiet`, which the gallery needed, and which `build` and
      `serve` already had; the command's summary line now names the islands and says when a
      page is static.
- [x] **0.11.2: a static page in a live-code frame (2026-09-09).** `mount(…, when="never")`
      asked whether the page had a boot tag to decide whether the island loader was driving —
      and the runner and the playground have no boot tag either, so a static page typed into
      one **rendered nothing**, silently. It now asks for `window.__frontageIslands`, which
      `island.js` and nothing else creates. Found while writing the academy's islands chapter,
      whose every `::: frontage` block would have been a blank frame; `tests/browser/`
      exercises `web/public/runner.html` now, which had no browser test at all.
- [ ] **`frontage.frame`: a columnar engine as a Rust module of its own** (`data-fr-js`,
      `wasm32-unknown-unknown`, `no_std`): filter, sort, group/aggregate, rolling, resample,
      CSV and Arrow in; handles in Python, `Float64Array`s to the chart, a windowed `table`
      source. A probe with sort, argsort, group-mean and filter is 3.2 KB of brotli, and
      `wasm-metadce` cuts it to what an app's Python calls (1.7 KB for one export) — the
      "minimal wasm per app" of `RUST.md` §4, module grain by the import walk and export
      grain with binaryen when present. `examples/weather` is the port and the number. Needs
      `_core.address(buf)` + a `HEAPU8` handoff for the zero-copy way in (every Python
      container crosses as an opaque proxy today: 65 ns an element).
- [x] **No more `frontage-*` projects on PyPI.** Subpackages of `frontage`, extras for
      server halves, assets in the wheel, the component repo merged in (M12 step 3, 38c2d60).
      No shim releases for the five published names and no 0.9-page compatibility in
      `boot.js` (decided 2026-09-08).
- [x] **`frontage build` packs the closure of what the entry imports**, walked with `ast`
      (`cli/graph.py`), as bytecode, app included, one `.fbc` per module and a manifest;
      `__init__.py` lazy through PEP 562; `serve` and `swap` follow (2026-09-08).
- [x] Content-hashed files (`name.<8 hex>.fbc`, `frontage.<8 hex>.wasm`, named in the
      manifest), a `_headers` that caches them forever, `modulepreload`/`preload` hints in the
      page; a rebuild moves only the URL of what changed (2026-09-08). Brotli beside them is
      not written: the hosts in use compress on the fly.
- [x] **`Route("/map", lazy="pages.map")` is a chunk** (2026-09-08): `graph.lazy_roots` finds
      the roots, `split` gives each what only it reaches, the manifest names the modules of
      each, and `frontage.chunks` fetches them the first time the route is visited. The wait
      is the framework's own — the nearest `Loading`, `is_routing`, a transition, `Errored` —
      and `A` prefetches on hover. `examples/lazy` is the example and the browser test.
      Two things the plan got wrong: a shared module needs no size rule, because `split`
      writes one file that both chunks name and the second fetch skips what the interpreter
      already has; and the lazy component must read its memo **inside a hole**, since the
      router calls a route's component under `untrack` and a memo read there is a dependency
      of nothing.
- [ ] `examples/uber` is not a route split: it has no router, and its 133 KB of data is what
      the one page draws. What it wants instead is `frontage.frame` below (the data as a
      binary the columnar engine reads), so it is filed there rather than here.
- [x] **An error overlay** (2026-09-08): a file that does not compile shows the compiler's
      message with the working page still running underneath, and an entry that raises while
      the page rebuilds shows its traceback; the next good save clears it. `tests/browser/
      test_dev_loop.py` is the first coverage the dev loop has ever had, and it found that
      **the swap had been broken in the browser** since the runtime switch: the page is handed
      its modules and no app imports `frontage.dev`, so every swap died on `ModuleNotFoundError`
      and fell back to a reload. The dev manifest names that module now.
- [x] **Module-level state survives a swap** (2026-09-08), by qualified name — Vue's rule,
      not React's guess. A `Signal`, `Store` or `State` at module level is read before the
      modules are dropped and written back after the rebuild, in one batch; renaming it or
      moving it to another module starts it fresh, and an edit to its initial value does not
      win over the live one (reload for that). ⚠ `frontage.store` is imported *defensively*
      there: a page holds only the modules its app imports, so an app with no Store has no
      `frontage.store` to import, and an unguarded import broke every swap.
- [x] **A devtools panel** (2026-09-08): Ctrl+Shift+D in any `frontage serve` page, listing
      every mount and the ownership tree under it. `frontage/devtools.py` is compiled by the
      dev server and run in the page; it uses the document directly, so it stays out of the
      tree it shows, and its imports are absolute because the runtime runs it as a script.
      ⚠ It needed a runtime change: `rt.run` makes the code it runs `__main__`, which
      displaced the app's own entry and quietly broke the state-preserving swap. The new
      `run_detached` (`vm.run_detached`, exported through glue as `rt.runDetached`) runs a
      script in a module of its own — the general answer for anything the page runs beside
      the app.
- [ ] **Development, still**: a template-only edit patches templates in place.
- [x] **Head management** (2026-09-08): `frontage/head.py` — `Title`, `Meta`, and
      `Route(title=)`. A stack per slot, so leaving a route puts the outer title back; the
      prerenderer takes its snapshot *before* the mount is disposed, because the entries go
      with their owner exactly as they must in a browser. `tools/exports.py` was written on
      the way (the `mk exports` the export table's comment had promised for months) and
      `mk check` now checks the stub is in step.
- [x] **View transitions and accessibility basics** (2026-09-08).
      `Router(view_transition=True)` hands the commit to `document.startViewTransition` — the
      commit is already the one place every parked effect reaches the page, which is exactly
      the snapshot boundary that API wants, so it is a `wrapper` on `Transition` and nothing
      else moved. `Router(announce=True)` (the default) writes the new title into a polite live
      region, `Router(focus="main")` moves focus into the new content, and the language server
      has a fourth rule: an `<img>` with no `alt`. ⚠ The announcer reads `document.title`
      rather than importing `frontage.head`, for the same reason `dev` guards its Store
      import: a page holds only the modules its app imports.
- [x] **Form validation in core** (2026-09-08): `ActionForm(schema=, errors=)` and
      `Resource(schema=)`. Both are seams onto `frontage.schema`, which already had the
      checker and `Form`; neither imports it, so an app that names no schema carries none of
      it. The form's check is `coerce=True` and dispatches the parsed value, because a form
      holds strings whatever the schema says.
- [x] **Tailwind for apps** (2026-09-08): `frontage build --tailwind` generates the stylesheet
      and links it, so shipping a Tailwind app is one command. The scanning needed nothing —
      Tailwind v4 reads every non-ignored text file, and a class in a t-string is a class in a
      `.py` file.
- [ ] Still open from that line: **class completion in the language server** (a class list is
      version-dependent and large; the honest source is the CLI's own output, not a table
      copied into this repo), and the "from React" and "from Streamlit" chapters.
- [x] Open, now closed by the runtime: there is no interpreter to trim and no second core to
      keep behind a flag; `-O2` has no meaning for `.fbc` (docstrings are dropped at compile).
- Measured and rejected, with the number, in `FASTER.md` §10: Pyodide, Python→JS,
      SPy/mypyc/Codon for apps, pocketpy, Rust in the same wasm, `wasm-opt` on the upstream
      binary (53 KB raw, 4 KB gzip — the size is data), a Worker, symbol-level shaking.

## Beating Streamlit — the component strategy (planned 2026-09-07)

`COMPONENTS.md` is the argument and the order of work. The short version: frontage already
wins on boot, size and interaction, and loses on *surface* — Streamlit ships ~115 public
`st.*` commands, frontage ships nine form controls, so an app that shows data has nothing to
show it with.

**The number that right-sizes the job: ~52 of those 115 are plain HTML with no dependency, and
~12 more are one small library each. About 56% of Streamlit's surface is reachable for well
under 400 KB.** The remaining 44% is not a backlog — ~6 want the scientific stack and ~14 want
a server, and both are constraints we chose.

- [x] `examples/chart/`, measured and committed: a dashboard with two sliders and a live uPlot
      chart, wired through `data-fr-js`. **946 KB over 10 requests, 96 ms cold to a drawn
      chart**, redraw 6/22/38/68 ms at 2k/5k/10k/20k points per series. stlite's playground
      downloads ~50 MB and starts in tens of seconds. The component is 40 lines of JavaScript
      and 20 of Python; `plot.py` is the pattern any library follows.
      - It lives in `examples/`, **not a sibling repo**, on purpose. `examples/` is the browser
        suite's material, so it is tested on every push and cannot rot; a sibling repo would be
        untested, and this project already carries nine chapter repos whose sync is a standing
        cost. Vendoring uPlot's minified ESM build costs 80 KB against the 446 KB interpreter
        already committed. When the component protocol lands, the chart moves out to its own
        package and this example becomes a consumer of it.
- [x] The `frontage-component` protocol (2026-09-07). A component is a Python package that also
      ships browser assets: it declares itself with a `frontage.components` entry point and lays
      out `_browser/index.js` (+ optional `index.css`) by convention. `build` discovers them,
      copies the assets beside the runtime, merges a `data-fr-js` declaration into the boot tag
      (an author's own entry wins), links the stylesheet, and packs the component's Python under
      its package path so `import frontage_chart` resolves in the page. `--component NAME=PATH`
      uses one before it is published. Discovery never *imports* a component — its Python is
      written for the browser. 6 unit tests, plus a browser test that builds against a
      package shaped exactly like a published one. An afternoon, because the three pieces it
      needed already shipped.
      - ⚠ Two dev-server bugs found on the way, both one mistake: when serving a **built**
        directory, `frontage serve` synthesised `app.tar` and intercepted `_frontage/`
        sub-paths, so it served a different app than `build` produced — the component's Python
        never reached the page and its assets 404'd. **Disk now wins over synthesis**;
        synthesis is what happens when nothing is built, which is the dev loop.
- [x] `frontage-chart` and `frontage-layout` (2026-09-07), in a new sibling repo
      **`~/optersoft/frontage-component`** — one repo, a package each, the way `hive/` and
      `turso/` hold several crates. 38 tests, lint clean, `frontage check` clean.
      - `frontage-layout`: columns, tabs, expander, container, metric, progress, spinner,
        divider. **Pure Python and 2.5 KB of CSS**, no JavaScript, no dependency — about a third
        of the ~52 commands that need nothing but markup.
      - `frontage-chart`: line/area/bar/scatter on uPlot, 41 KB gzipped, vendored so a build
        needs no network. Both take an **accessor**, not data.
      - Measured together as a dashboard: **78 ms to drawn, 730 KB over 12 requests**, and a
        region change updates a metric, a progress bar and the chart and nothing else.
      - Proven through **real entry-point discovery**, not `--component`: installed, found,
        assets copied, Python packed, `from frontage_chart import line_chart` resolving in the
        page.
      - ⚠ `--with` caches a built wheel, so editing a component's source and rebuilding runs the
        *old* code in the browser. Use `--with-editable`; the symptom is a traceback from a line
        number that does not match the file.
- [x] **An app gallery on the site** (2026-09-07): `mk gallery` builds every app in its list
      with the real `frontage build`, loads each cold in Chromium, and writes `www/gallery/`
      with measured size and start time on every card. Numbers are generated, never typed — a
      broken app fails the build, a slower one changes the page. **51–160 ms cold, 638–828 KB
      each**, of which 627 KB is the interpreter, loader and framework.
      - ⚠ Each app carries its own copy of that 627 KB, so the site is 8 MB and a visitor
        browsing three apps downloads it three times. That follows from the rule that keeps
        nested routes correct — `boot.js` resolves `app.tar` beside itself — and sharing one
        runtime would need a second base for `app.tar`. Left as designed; revisit only if the
        gallery grows.
- [ ] Three *Streamlit* gallery apps rebuilt, with download size and cold start published beside
      each. **One of the three is done** (2026-09-07): **Seattle Weather**, ported line for line
      as `examples/weather/` — the same eight metrics, year pills, five charts and raw table, at
      **828 KB and 160 ms cold**, dataset included, no server. Two of its charts are uPlot and
      three are divs, which is the case for when a canvas earns its bridge crossings. The two
      remaining targets: **Uber NYC Pickups** (needs the map; its 180 MB CSV becomes a sliced
      Parquet) and **GW Quickview** once a DSP module exists.
      - The comparison the page still owes a reader is a *side-by-side*: Streamlit's own hosted
        demo next to this one, both cold, both measured. Today the gallery publishes only our
        half of it.
- [x] **`frontage.dsp`, the DSP/FFT module** (2026-09-09): a radix-2 FFT, Hann windows,
      Welch's PSD, a spectrogram in decibels, a brick-wall bandpass and an RMS — **12 KB** of
      `no_std` Rust in `rust/components/dsp/`, tested against a naive DFT and against `std`'s
      own `cos`/`ln`/`sqrt` (the crate computes those itself). `examples/spectrum` is a chirp
      under noise with a live spectrogram, spectrum and filter, and it is what GW Quickview
      needs. `draw` rasterises the spectrogram onto a canvas without the values ever reaching
      Python — a few hundred frames of a hundred bins is a few hundred thousand crossings.
      ⚠ Two things it cost, both worth keeping: the dev server **did not declare components at
      all**, so any app importing `frontage.chart` (or any other) ran when built and not when
      served; and `bandpass` filtered one transform's worth while everything else measured the
      whole signal, so a filter over a long signal looked like it did nothing. The filtered
      count is now the signal's length.
- [x] `frontage-table` (2026-09-07): a virtualised, sortable grid in **pure Python — no
      JavaScript at all**, which is the surprise. A grid is where libraries reach for 200 KB,
      but the expensive part is *not* drawing the rows nobody is looking at, and a fine-grained
      framework already does that. Measured on a 50,000-row dashboard: **235 ms cold to drawn,
      623 KB, and 21 row elements in the DOM** — still 21 after scrolling to row 40,000.
      - Sorting compares the **raw value**, never the formatted text: correct (`"1,200"` sorts
        before `"70"` as a string) and **111 ms against 914 ms** for 50,000 rows on MicroPython.
        Mixed types fall back to the text form.
      - ⚠ Found on the way, and it is a `serve` bug not a table one: **`extensions_map` in
        modern Python holds only compression extensions** (`.Z`, `.bz2`, `.gz`, `.xz`), not MIME
        types. `_send_runtime` used `extensions_map.get()`, so every component stylesheet went
        out as `application/octet-stream` and the browser refused all three — silently, because
        a rejected stylesheet is not an error, just a page with no rules. `guess_type()` is the
        API. Production was unaffected; only the dev server lied.
- [x] The components are on GitHub at **`optersoft/frontage-component`** (public, Apache-2.0,
      CI green) and release **per package on a tag**: `frontage-chart-v0.1.0` publishes only
      that one, because a shared version would force a pointless release of the other two. CI
      checks the tag against the package's own version, and asserts the wheel actually carries
      `_browser/index.js` — the failure that installs and imports perfectly and then does
      nothing in a page, which no test run from the source tree can catch.
- [x] ~~Register three PyPI trusted publishers for `frontage-layout`, `frontage-chart` and
      `frontage-table`.~~ Moot since 0.10: the components are subpackages of `frontage` and
      there are no `frontage-*` projects to publish (M12 step 3). `pip install frontage` is
      the whole install, and `COMPONENTS.md` says so.
- [ ] `frontage-postgrest`. **Correction to an earlier claim**: database dashboards are *not*
      out of reach. Browsers have no raw sockets, but PostgREST generates an HTTP API from a
      Postgres schema and enforces **row-level security**, so the policy lives next to the data
      and applies to every client. That is better than Streamlit, which holds a connection
      string in a process and expects you to write the access control in Python. §2b survives:
      nothing of *ours* listens. The academy already teaches it — module 0486 *Accés a dades*,
      chapter `data/postgres/postgrest`, plus Supabase — so the teaching material exists before
      the users do.
- [ ] `frontage-turso` — **the database in the page**, and the strategically interesting one.
      `@tursodatabase/database-wasm` is SQLite in wasm with OPFS persistence, `sync-wasm` adds
      push/pull against Turso Cloud. Measured from the published package: `turso.wasm32-wasi.wasm`
      is **11.07 MB raw, 3.61 MB gzipped** — npm reports 41 MB because it counts every variant.
      Opt-in, same bracket as DuckDB-wasm. It buys **offline-first data apps**: no network, the
      app still works, remembers between visits, syncs later. Streamlit cannot enter that
      category — it is a websocket to a process. And **we already run this engine**: the browser
      package is 0.7.2 against `optersoft/turso`'s `>=0.7.0, <0.8` pin, so the `turso` skill's
      gotchas (immature planner, rowid reuse, FKs off) apply unchanged. ⚠ Our own README says
      *"alpha-grade engine"* and the browser package is BETA — fine behind an opt-in dependency,
      not fine as a default.
- **Decided, because we already own both halves**: **Supabase** for hosted data, **Turso Cloud**
      for offline-first. Not a procurement question.
      - Supabase's data API *is* PostgREST, so one component serves both — point it at a
        self-hosted PostgREST or a Supabase project and only the URL changes. What Supabase adds
        is what a browser-only app actually lacks: the service that issues the JWT, and
        **Realtime**. Realtime answers Streamlit's live-dashboard case outright — the database
        pushes, one signal takes it, one chart redraws, where Streamlit re-runs the script on a
        timer. Client is 0.64 MB unpacked, and **Supabase appears in 48 academy files** with its
        own `cloud/` and `kotlin/` sections; `data/postgres/row-level-security` is already a
        chapter.
      - **Neon: no.** Technically fine, but it solves what Supabase solves, adds a third vendor,
        and still needs a separate auth provider to issue the JWT that Supabase issues itself.
        Revisit only for Postgres branching or scale-to-zero.
      - ⚠ One failure mode common to all of them, and it is silent: the connection role must not
        hold `BYPASSRLS`. Supabase's **service key bypasses RLS by design and must never reach a
        browser** — the anonymous key is the one that ships.
- [x] **`frontage-polars`** (2026-09-07), in `~/optersoft/frontage-component`: **polars on the
      server, small answers in the page.** The case §7b did not cover: a dataset too big to ship
      and a transform that is Python, not SQL. An author registers ordinary functions returning
      a polars frame (`@src.query`) behind a FastAPI router; the browser asks for them by name
      with parameters from signals, and gets column-oriented JSON for a chart or one window of
      rows for the grid. Nothing from the browser is evaluated — no expression, no SQL — and a
      frame past `max_rows` answers 413 rather than shipping the dataset. HTTP for the queries,
      **Server-Sent Events for push** (`src.changed(name)` bumps one version signal per query
      name in every open page and only the readers refetch), **no WebSocket**: each interaction
      is one query and one answer, and a session per client is Streamlit's model, the thing
      the static-files property exists to avoid. Measured on the `examples/trips` dashboard,
      500,000 synthetic rows, four queries and a grid over all of them: **94 ms cold to drawn,
      780 KB for the page, and ~10 KB of answers** (204 B, 274 B, 5.9 KB, 4.1 KB) for a frame
      that is 30 MB in memory; a borough change is four requests and **15 ms** to the updated
      metric. What it needed elsewhere: **`frontage-table` takes a windowed
      source** (`key()` + `async window(...)`, so PostgREST could be one too), fetches the
      block it is scrolled to in `For`'s index mode, and leaves sorting and search to the
      server; and `Sources.frame` caches the collected result so scrolling never re-runs a
      query. 22 server tests through FastAPI's client, 11 client tests with the transport
      faked, 5 remote-grid tests, and **3 browser tests against a real uvicorn** — the first in
      the component repo, because a MicroPython awaiting a `fetch` and an event stream
      reaching a page are the things CPython cannot stand in for. Both worked first time:
      MicroPython's `await` on a JS promise, and cancellation aborting the request.
      - ⚠ **This revises the "no server" rule, and the revision is narrow.** The *framework*
        ships none and knows of none; a *component* may ship an opt-in server half
        (`pip install "frontage-polars[server]"`), the way `frontage-turso` would ship a
        database. `COMPONENTS.md` §7b and §8 say so now. The property that mattered survives:
        `frontage build` still writes a directory of static files, and it is the app that
        points at a server, not the page that needs one.
      - ⚠ Two MicroPython facts met on the way: **`"{:,.0f}".format(x)` ignores the comma on a
        float** (an int formats fine), and **Chromium serialises a large inline
        `translateY` as `1.27996e+07px`**, which is the browser, not Python — a test must parse
        the value rather than match it.
      - ✅ The four follow-ups, same day (2026-09-07 evening):
        **the binary column path** — `GET /series/{name}?columns=a,b` answers float64 columns
        behind an 8-byte header, the JavaScript half makes `Float64Array` views over the
        response buffer, `Remote.series(...)` is a Resource of a `Series` whose `.data` the
        chart draws as it is (frontage-chart 0.1.1 passes typed arrays through). Measured in
        the MicroPython build for the trips example's 8,784-point series: the JSON path is
        **11 ms per redraw** (6 parse + 5 lists-and-crossing) and 152 KB, the binary path
        0.007 ms and 140 KB — smaller than the "~400 KB" guess above, because JSON parsing in
        this build is fast; the win is the crossing and the bytes, and it grows with the
        series. frontage-polars 0.2.0.
        **`frontage serve --proxy PREFIX=URL`** (0.9.1): forwards a prefix to another port,
        any method, status and headers relayed, an event stream copied line by line, a dead
        upstream a 502 that names it. Four tests with a stand-in upstream that holds its
        stream open until the first event is read.
        **A fleet path for a Python process**: hive already had `runtime = "uv"` (coded,
        unit-tested, never used — every row was a Rust binary). `examples/trips` is now a
        deployable project (`pyproject.toml` with a `trips` script, `uv.lock`, `/healthz`,
        `TRIPS_ADDR`), `[apps.trips]` is in `hive-deploy/fleet.toml` (nbg-3, :8008,
        `activation = "restart"`, `avoid = ["broker"]`) and `hive fleet bootstrap --host
        trips --dry-run` renders the unit as expected. ⚠ **Not rolled out**: bootstrap on the
        VM, the DNS record for `trips.frontage.optersoft.com` and the gateway tenant are
        operator steps, listed in `examples/trips/DEPLOY.md`. Two hive caveats from the
        research: `packaged = true` + `uv` has no agent-side `uv sync`, so it is the rsync
        path; and the README's `### runtime = "uv"` section it points at does not exist.
        **The academy chapter**: `python/frontage/polars.md` (+ card), listed in the index
        between Components and Wasm, no live frame (the first chapter whose app needs a
        server, and it says so), code blocks matching `examples/trips`.
- [ ] The one thing a browser truly cannot do is hold an API key. For LLM apps that is ~20
      lines of Cloudflare Worker in front, and the site already deploys to Pages. We do not
      write a server into the framework; both answers are off-the-shelf things an app points
      at (and `frontage-polars` is the opt-in exception a component may make, above).
- [x] **`frontage-schema`** (2026-09-07, `frontage-component`): schemas as pairs, `validate` →
      `(value, [(path, message)])`, `coerce` for strings, `sample` for big arrays, `Form` with a
      signal and a message per field, `from_json_schema`/`json_schema()`, and the
      `frontage-schema` command that compiles Pydantic models on CPython. 121 tests + a
      MicroPython smoke under node + 3 Chromium tests over `examples/signup/`.
      Left: `Resource(load, schema=)` and `use_query(schema=)` in core; the academy chapter;
      the fifth PyPI trusted publisher (environment `frontage-schema`) before the first tag.
      ⚠ Met on the way: MicroPython has no `str.isalnum`, `json.dumps` takes no `indent`, and
      `re` has no counted repeats (`\d{4}` → None), so formats are string code.
- [ ] `[auto]` The underscore rule in `build` (4701d08) says "private" when it means "not for
      the browser": frontage-polars had to keep a 779-byte `server.py` shim re-exporting
      `_server.py` because `from frontage_polars.server import Sources` is published. When a
      second package needs the same shim, add a declared list instead — a key in the
      component's `pyproject.toml`, read at discovery without importing — and keep the name rule.
      Done: `build.Component.modules()` skips a listed module; the shim can go.
- [x] **The template for calling your own Rust** (2026-09-08): `examples/rustlib/` — a crate,
      the glue, the boot-tag line, a README that is the fifteen minutes, and a page that
      measures the thing that decides the design. **No wasm-pack and no wasm-bindgen**: a
      `no_std` cdylib of `extern "C"` functions over numbers is 1,036 bytes and thirty lines of
      glue, and a generator would hide exactly what a reader needs to see.
      ⚠ The first version had the API shaped `mean(values)` and was **slower than Python** —
      2.5× slower — because a list does not cross, it is copied element by element, and 20,000
      crossings cost 1.5 ms against 0.16 ms to compute. Shaped as `load(values)` once and then
      questions, it is 13× faster than the same statistics in Python. The example now measures
      and states both numbers, because that ratio is the whole rule for a wasm boundary.
- Not doing, deliberately: pandas/scikit-learn/matplotlib (that is stlite, at 13.8 MB before
      app code), copying `st.*` names onto reactive semantics, or a server *in the framework*
      (a component's opt-in server half, `frontage-polars`, is the one exception, and it is
      named as such in `COMPONENTS.md` §8).
- The research found an argument we had not thought to make (`COMPONENTS.md` §2b), and it may
      be the strongest one: **a frontage app has nothing to leave open.** Streamlit had no
      authentication until `st.login` in February 2025, asked for on the 2019 launch thread; a
      security vendor's December 2025 scan found 14,995 IPs running it and *"well over ten
      thousand"* apps publicly accessible, Verizon data among them. It also collects usage
      statistics by default (`browser.gatherUsageStats = True`) to this day. A directory of
      static files has no process, no session and nothing listening. **Consequence for us: a
      frontage component may never phone home.** That property is given away by one library
      that does.
- Also worth knowing: Hugging Face Spaces shipped a custom Streamlit frontend for two years,
      then **deprecated the Streamlit SDK on 2025-04-30**. And the re-run is not a wart to wait
      out — Streamlit's issue #5827 answers it with *"This touches on the fundamental of
      Streamlit… No guarantees that we'll do this anytime soon!"*, open since 2022.

- [x] At 1.0: delete `frontage/cli/pyscript.py`, `tools/fetch_pyscript.py`, `mk pyscript.fetch`,
      the `export` command with its tests, and the ~18 MB `tools/pyscript/` fixture — done
      early, 2026-09-08, with MicroPython.

## Do not "fix" these

- Do not wrap `justrach/dhi` (the Zig validator, 28 KB wasm) for forms — evaluated 2026-09-07.
  Its Python package is a CPython C extension over `typing.Annotated`/metaclasses and cannot
  run on MicroPython; the wasm's 66 exports are `(ptr,len)->bool`, and through the JS bridge a
  call is 0.55–0.75 µs against 0.25–3.35 µs in plain MicroPython (node, 20k iterations) — a
  form validates five fields per keystroke, so neither number matters. Its rules are also
  loose: `a@@b.c` and `2026-02-30` pass, `http://localhost:8000` and `o'neil@x.com` fail.
- A push to a chapter repo may create **no** GitLab pipeline (router, 0.8.2): the commit is on
  `main` and no pipeline exists, so the site keeps serving the old wheel. Not a CI failure and
  not a bad `.gitlab-ci.yml`. `glab api -X POST "projects/optersoft%2Fpython%2Ffrontage-<c>/pipeline?ref=main"`.
  ⚠ **The old check no longer works.** `curl .../frontage-<c>/frontage/version.py` read the
  framework as loose `.py` files, and since 0.9.0 it is bytecode inside `_frontage/frontage.tar`.
  Check the boot tag instead:
  `curl -sL https://optersoft.gitlab.io/python/frontage-<c>/ | grep -c data-fr-boot` is 1.

## Outward-facing, for David

- [x] DNS: frontage.optersoft.com is live (2026-09-06).
- [x] Connect the Pages project to the GitHub repo (2026-09-06; `mk site.deploy` stays as the
      fallback).
- [x] Check `frontage.dev`.
