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
- [ ] `clone_template` and the Template path (S6, W17): one clone per instance, holes bound
      after. Then the rows example and the benchmark harness (§12) to compare against the
      node-by-node path this stage ships.
- [ ] W13 leftovers: simulate `currentTarget`, `oncapture:`; W15 custom events.

## Outward-facing, for David

- [ ] Email PuePy's author about the fork and the rewrite (courtesy; nothing is owed).
- [x] `github.com/optersoft/frontage` is live (main, `puepy-reference`, tag `v0.0.1`); the PyPI
      trusted publisher is registered and **`frontage 0.0.1` is on PyPI** (2026-09-05). A tag
      pushed seconds after the repo's first push did not trigger a run; re-pushing it did.
- [ ] DNS: proxied CNAME `frontage -> frontage-a8x.pages.dev` in the optersoft.com zone; the
      Pages project has the domain attached and waits on it. Then connect the project to the
      GitHub repo and retire the hand deploy.
- [ ] Check `frontage.dev`.

## Site and docs

- [ ] The landing page still shows the M2 template syntax as if it ran today; fine as a
      target, but say "target syntax" until M2 lands. The deployed site still serves the
      fork's examples; redeploy (`mk site.deploy`) once M1 has real examples to show.
- [ ] Docs on academy at `/tool/frontage`, chapter per concept in `DESIGN.md` order, each with
      its live example; one interpreter per page for the embeds (§2b).
- [ ] The measured size of a MicroPython Frontage app, on the landing page (§2b).
