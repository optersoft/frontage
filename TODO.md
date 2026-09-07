# TODO

Open work for `frontage`, most urgent first. `- [ ]` open, `- [x]` done where the reason is
worth keeping. The milestones themselves are in `DESIGN.md` §16; this file tracks the edges.

## Decisions taken by proposal on 2026-09-05 (say so if any should change)

All seven open decisions in `DESIGN.md` §17 were taken as proposed: MicroPython first-class;
template strings in M2 with the builder as fallback; pure Python first and a JS shim only
where the rows benchmark says so; Solid 1.x synchronous propagation; `Store` in 0.1;
accessors spelled `count()` with `.value` as alias; widgets as a subpackage.

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
- [ ] `[human]` The academy still cuts the chapters for anonymous readers (the Router page stops
      after Links, 2026-09-06 15:00). `index.md` has `public: true`; the academy commit that
      honours it (4e1b5042) is not deployed, and the academy tree has uncommitted work.
      Do: deploy academy. Done: `curl -s academy.optersoft.com/python/frontage/router | grep -c Exercises` is 1.
      **Still open, re-checked 2026-09-07**: `router`, `basic` and `async` all return 0. The
      commit is in `~/optersoft/academy` with `adfb5bdc` on top of it, so the fix exists and
      has simply never shipped. A day old now, and it hides every exercise on the site.

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
      - Chapter written: `~/optersoft/academy-pages/python/frontage/wasm.md` + `.meta.md`, in
        `index.md` under a new "Going further" section. ⚠ Its code blocks are **not** runnable
        frames yet: `::: pyscript` cannot boot a wasm page, so the chapter waits on Phase 5's
        `::: frontage` frame. It also has no GitLab repo yet, unlike the other nine.

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
- [ ] `[human]` **The academy's half is a small Rust change now.** `academy-content`'s frame
      dispatch gains a `frame.kind == "frontage"` branch beside the `"pyscript"` one at
      `content.rs:4611`, reusing `academy_preview::pyscript`'s machinery with
      `RUNNER_URL = "https://frontage.optersoft.com/runner.html"` — the fragment payload is
      already the same shape. No new runner file is needed on that side: this repo hosts it.
      Until that lands, the Wasm libraries chapter has code blocks rather than a running app,
      and the other nine chapters keep their PyScript frames, which still work. Nothing on the
      live site is broken in the meantime.
- [ ] The nine chapter repos (`gitlab.com/optersoft/python/frontage-<chapter>`) move to
      `frontage build` once the frame lands; the new chapter gets a tenth.
- [ ] Release: bump `version.py`, check the chapters name the new wheel, tag `v0.9.0`.
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
- [ ] The `frontage-component` protocol in `build`: discover installed components by entry
      point, copy their `_browser/` assets, extend `data-fr-js`, and pack their Python into
      `app.tar`. Everything it needs exists — this is discovery and packing, not new machinery.
- [ ] `frontage-chart` (uPlot, +41 KB) and `frontage-layout` (columns, tabs, metric — pure
      Python, no dependency): the smallest pair that makes a credible dashboard.
- [ ] Three Streamlit gallery apps rebuilt, with download size and cold start published beside
      each. The gallery is the marketing and the test suite at once, and the research named the
      honest targets: **Uber NYC Pickups** (needs the map; its 180 MB CSV becomes a sliced
      Parquet), a **filter-and-chart dashboard** (`examples/chart/` almost is one), and **GW
      Quickview** once a DSP module exists.
- [ ] A DSP/FFT wasm module — the concrete first case for Rust, not a hypothetical one. GW
      Quickview is blocked *only* by `scipy.signal` and `gwpy`: the FFT and filtering are the
      app, one buffer in and a spectrogram out, exactly the coarse boundary the 1.00 µs
      crossing rewards. It is also the most impressive thing on the list to run with no server.
- [ ] `frontage-table`: a virtualised grid. Second thing every data app reaches for, and
      virtualisation is the whole trick.
- [ ] `frontage-postgrest`. **Correction to an earlier claim**: database dashboards are *not*
      out of reach. Browsers have no raw sockets, but PostgREST generates an HTTP API from a
      Postgres schema and enforces **row-level security**, so the policy lives next to the data
      and applies to every client. That is better than Streamlit, which holds a connection
      string in a process and expects you to write the access control in Python. §2b survives:
      nothing of *ours* listens. The academy already teaches it — module 0486 *Accés a dades*,
      chapter `data/postgres/postgrest`, plus Supabase — so the teaching material exists before
      the users do.
- [ ] The one thing a browser truly cannot do is hold an API key. For LLM apps that is ~20
      lines of Cloudflare Worker in front, and the site already deploys to Pages. We do not
      write a server or make frontage aware of one; both answers are off-the-shelf things an
      app points at.
- [ ] A `frontage-wasm` template (wasm-pack, glue, Python wrapper, the `data-fr-js` line) so
      calling your own Rust is a fifteen-minute exercise. Streamlit has no answer to this: its
      Python is on a server, where the wasm cannot go.
- Not doing, deliberately: pandas/scikit-learn/matplotlib (that is stlite, at 13.8 MB before
      app code), copying `st.*` names onto reactive semantics, or a server.
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

- [ ] At 1.0: delete `frontage/cli/pyscript.py`, `tools/fetch_pyscript.py`, `mk pyscript.fetch`,
      the `export` command with its tests, and the ~18 MB `tools/pyscript/` fixture.

## Do not "fix" these

- A push to a chapter repo may create **no** GitLab pipeline (router, 0.8.2): the commit is on
  `main` and no pipeline exists, so the site keeps serving the old wheel. Not a CI failure and
  not a bad `.gitlab-ci.yml`. `glab api -X POST "projects/optersoft%2Fpython%2Ffrontage-<c>/pipeline?ref=main"`.
  Check after a wheel bump: `curl -sL https://optersoft.gitlab.io/python/frontage-<c>/frontage/version.py`.

## Outward-facing, for David

- [x] DNS: frontage.optersoft.com is live (2026-09-06).
- [x] Connect the Pages project to the GitHub repo (2026-09-06; `mk site.deploy` stays as the
      fallback).
- [x] Check `frontage.dev`.
