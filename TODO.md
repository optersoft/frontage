# TODO

Open work for `frontage`, most urgent first. `- [ ]` open, `- [x]` done where the reason
is worth keeping.

## Decide first

- [ ] Settle the five open decisions at the end of `DESIGN.md`; the rewrite starts with
      `SPEC.md` (M0) once they are.

## Before the first release (0.1.0)

- [ ] Email PuePy's author: tell them about the fork, offer co-maintainership, ask whether
      they would rather hand PuePy itself over. Two weeks for a reply before announcing.
- [ ] Register the `frontage` name on PyPI and create `github.com/optersoft/frontage`,
      then the trusted publisher (owner `optersoft`, repo `frontage`, workflow `ci.yml`,
      environment `pypi`) and the `pypi` environment on the repo.
- [ ] **DNS for frontage.optersoft.com.** The Pages project `frontage` has the custom
      domain attached (status pending, "CNAME record not set") and needs a proxied CNAME
      `frontage -> frontage-a8x.pages.dev` in the optersoft.com zone. The wrangler login
      on this machine has zone read only, so add it in the dashboard or re-login with DNS
      write. The site already answers at https://frontage-a8x.pages.dev.
- [ ] Connect the Pages project to `github.com/optersoft/frontage` once the repo exists
      (build command `mk site.build` or a shell equivalent, output `www`), then drop the
      hand deploy from `Makefile.py`.
- [ ] **Absorb PyScript drift.** Examples pin 2025.2.2; PyScript is at 2026.7.3
      (2026-07-29). Bump the 36 pins, run the browser suite under both `mpy` and `py`,
      fix what broke. This is the real first milestone.
- [ ] Merge or decline the four upstream PRs left open (two from 2025-10: `trigger_redraw`
      and lifecycle docs; a jinja2 bump; Playwright on WebKit/Firefox).
- [x] `mk test --integration` runs locally (Chromium via `uv run playwright install
      chromium`, ~6 min because every example pulls PyScript from the CDN). It caught the
      import-stripping regression the unit tests cannot see; keep it in the release
      checklist even though it is slow.

## Known failing

- [ ] `tests/integration/test_examples.py::test_refs_problem` fails on the pristine upstream
      tree too (3/3 runs each, Chromium, 2026-09-05), on the second assertion: after
      `fill("F")` the input is expected to have lost focus and has not. Either the redraw
      is now fast enough to keep focus or Playwright's `fill` behaves differently than in
      2025; the "problem" the example demonstrates may simply no longer reproduce. Decide
      after the PyScript bump; until then CI's `examples` job is red on this one test.
- [ ] Most integration tests do not request the `http_server` fixture, so they only pass
      when an earlier test started the server. Make it `autouse` (session scope).

## Docs (moving to academy.optersoft.com)

- [ ] Port the mkdocs tree under `docs/` into `academy-pages` and add the `/tool/frontage`
      redirect there; every URL in this repo already points at that path, which is a 404
      until then. The `<frontage src=…>` embeds become links to
      `https://frontage.optersoft.com/examples/…` in the port.

- [ ] Host our own tutorial examples (the `<frontage src=…>` embeds still load
      `kkinder.pyscriptapps.com/puepy-tutorial`, whose code says `puepy`). Serving
      `examples/` from the docs site is the obvious route.
- [ ] `docs/installation.md` now points at PyPI's files tab; check the wording once a
      release exists.
- [ ] `docs/faq.md` and the tutorial still read as PuePy's voice in places; a pass for
      "we/our" and for the project name in prose.

## Later

- [ ] A changelog (`CHANGELOG.md`) starting at 0.1.0 = PuePy 0.6.5 renamed.
- [ ] Decide whether MicroPython support stays first-class; it constrains the whole package
      (see CLAUDE.md) and the tests only cover CPython.
