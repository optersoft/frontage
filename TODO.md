# TODO

Open work for `frontage`, most urgent first. `- [ ]` open, `- [x]` done where the reason
is worth keeping.

## Before the first release (0.1.0)

- [ ] Email PuePy's author: tell them about the fork, offer co-maintainership, ask whether
      they would rather hand PuePy itself over. Two weeks for a reply before announcing.
- [ ] Register the `frontage` name on PyPI and create `github.com/optersoft/frontage`,
      then the trusted publisher (owner `optersoft`, repo `frontage`, workflow `ci.yml`,
      environment `pypi`) and the `pypi` environment on the repo.
- [ ] Enable GitHub Pages on the `gh-pages` branch so `docs.yml` has somewhere to publish.
- [ ] Check `frontage.dev` is free (the RDAP lookup hung on 2026-09-05); otherwise the
      docs stay at `optersoft.github.io/frontage`.
- [ ] **Absorb PyScript drift.** Examples pin 2025.2.2; PyScript is at 2026.7.3
      (2026-07-29). Bump the 36 pins, run the browser suite under both `mpy` and `py`,
      fix what broke. This is the real first milestone.
- [ ] Merge or decline the four upstream PRs left open (two from 2025-10: `trigger_redraw`
      and lifecycle docs; a jinja2 bump; Playwright on WebKit/Firefox).
- [ ] Run `mk test --integration` locally once and record the browser it needs.

## Docs

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
