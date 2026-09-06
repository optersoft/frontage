# TODO

Open work for `frontage`, most urgent first. `- [ ]` open, `- [x]` done where the reason is
worth keeping. The milestones themselves are in `DESIGN.md` §16; this file tracks the edges.

## Decisions taken by proposal on 2026-09-05 (say so if any should change)

All seven open decisions in `DESIGN.md` §17 were taken as proposed: MicroPython first-class;
template strings in M2 with the builder as fallback; pure Python first and a JS shim only
where the rows benchmark says so; Solid 1.x synchronous propagation; `Store` in 0.1;
accessors spelled `count()` with `.value` as alias; widgets as a subpackage.

## M0 (in progress)

- [x] `puepy-reference` branch; fork tree removed from `main`.
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
      fetch (no refetch, data block consumed), both interpreters.
- [ ] Off the plan, on purpose: islands (Python has no tree shaking, so an `@island` saves
      boot work, not download), streaming modes and server functions (need a server).
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
- [ ] Docs: the extension is user-visible, so a section in the tooling chapter on
      academy.optersoft.com before `editor-v0.1.0` is tagged. It is tooling, not an app, so it
      needs no `frontage-<chapter>` repo of its own.
- [ ] Try the extension in a real VS Code (`mk vscode.install`) before tagging. Everything so far
      is verified through the protocol, which is the server's whole surface — but the grammar, the
      snippets and the client's server discovery have only been checked as valid JSON and
      `node --check`.
- [ ] The lambda rule fires only for a *parenthesised* lambda. CPython 3.14 rejects
      `{lambda ev: None}` in a t-string outright (the `:` is a format spec), so
      `test_check_flags_a_lambda_in_a_template_string` has been passing on the syntax-error
      branch, not the rule — its assertion is `"lambda" in message`, and the parse error says
      "lambda expressions are not allowed without parentheses". The rule is still right for
      `{(lambda: 1)}`, which parses here and fails on MicroPython. Worth deciding whether the
      docs' advice ("name the function") needs to mention the parenthesised form at all.

## 0.8.0 (2026-09-06) — the dev server, the router repo, the profiling session

- [x] `frontage serve [DIR]`: live reload (SPEC L10); `tools/serve.py` and `mk serve` reload too.
- [x] The router chapter repo carries the data loading (`Memo` over a `query`), so the live site
      demonstrates the memo form; the nine pipelines pin `pip install frontage==X.Y.Z`.
- [x] MicroPython profiling session on the rows benchmark: `tools/profile/` + `tools/profile_rows.py`
      (phase by phase, three renderers, a per-primitive calibration). Findings in DESIGN §12;
      tuple `isinstance` gone from the hot paths, calls trimmed (−5%). Bench after, medians of 3:
      create 1,000 = 188 ms MicroPython / 89 ms Pyodide, clear = 44 / 8.4, swap = 17 / 2.5.
- [ ] `[auto]` A hole costs ~21 µs on MicroPython (≈80 calls: `RenderEffect` + `Owner` + `_HoleState`
      + three closures + marker + reconcile) and a `For` row ~55 µs before its holes; `clear`
      (disposal) is 44 µs per row. Structural, not trimming: a lighter text-hole path (no owner
      when the accessor creates nothing), cheaper `Owner`/`_Computation` construction, a
      disposal that skips empty lists.
      Do: `uv run python tools/profile_rows.py --interpreters mpy` before and after.
      Done: "For, null renderer" under 100 ms; the browser suite green on both interpreters.

## 0.8.1 (2026-09-06) — the examples move to the academy

- [x] The eight examples run on the academy's Examples page (`::: pyscript` frames, MicroPython,
      the wheel by URL), generated by `mk docs.examples` from `examples/`; the chapters link there.
      frontage.optersoft.com is a 301 to academy.optersoft.com/python/frontage except `/dist/`
      (wheels, CORS) and `/playground/`. Hash mode ignores a fragment that is not a path.
- [x] Call-count pass on the core: 332 → 266 Python calls per row; a 1,000-row create on
      MicroPython 124 → 108 ms (null renderer), 163 → 151 ms (DOM, templates).
- [ ] `[auto]` The demo app (an issue tracker exercising router + memo data + transitions +
      Optimistic + Store/For + widgets/State + Portal + prerender) was started and set aside
      for the move. Do: `examples/tracker/` + `tests/browser/test_tracker.py` + a prerender test;
      then `mk docs.examples`. Done: browser suite green on both interpreters with it.

## Outward-facing, for David

- [x] DNS: frontage.optersoft.com is live (2026-09-06).
- [x] Connect the Pages project to the GitHub repo (2026-09-06; `mk site.deploy` stays as the
      fallback).
- [x] Email PuePy's author about the fork and the rewrite (courtesy; nothing is owed).
- [x] Check `frontage.dev`.
