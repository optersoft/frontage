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
- [ ] E2 debug warnings (a signal read after `await`, a write inside a tracked compute).

## M3 (done 2026-09-05)

- [x] The router (SPEC U1–U10; scroll restoration best-effort) and floating holes, so a component
      may return control flow directly and the router renders no wrapper.
- [ ] Scroll restoration in a browser test; `use_is_routing` observable across async work.

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

## After 0.2.0 (the plan's "later", not scheduled)

- [ ] Server rendering through `HtmlRenderer` and hydration; async memos, `is_pending`,
      transactions and optimistic writes (Solid 2.0's model) — DESIGN §16 "later", for a 1.0.
- [ ] E2 debug warnings; the scroll-restoration browser test; `use_is_routing`.
- [ ] Docs: `.ca`/`.es` variants once a programme places the pages; a chapter on deploying
      (`mk export`, history mode needs the host to serve the page for every path).
- [ ] `mount` appends to its target: the examples clear `#app` themselves; decide whether mount
      should.

## Outward-facing, for David

- [ ] DNS: proxied CNAME `frontage -> frontage-a8x.pages.dev` in the optersoft.com zone; the Pages
      project has the domain attached and waits on it. Then connect the project to the GitHub
      repo and retire the hand deploy.
- [ ] Email PuePy's author about the fork and the rewrite (courtesy; nothing is owed).
- [ ] Check `frontage.dev`.
