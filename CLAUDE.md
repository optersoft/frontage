# CLAUDE.md

Frontage: a Python frontend framework for PyScript, published to PyPI as `frontage`. A
fork of PuePy 0.6.5 (Apache 2.0), maintained by Optersoft since 2026-09-05. The `upstream`
remote points at `kkinder/puepy`; `origin` is `github.com/optersoft/frontage` (GitHub, not
the forge, because PyPI publishing needs Actions).

## Layout

| Path | What |
|---|---|
| `frontage/` | the package: `core` (Tag/Component/Page), `reactivity`, `router`, `application`, `storage`, `runtime` (the Pyodide/MicroPython/CPython shim), `version` |
| `tests/unittests/` | run anywhere; `dom_test.py` fakes a DOM |
| `tests/integration/` | Playwright over the examples; needs `serve_examples.py` and a browser |
| `examples/` | the tutorial apps; every `pyscript*.json` lists the package files by path so edits show live |
| `docs/` | mkdocs-material, versioned with mike; `frontage_hooks.py` renders `<frontage src=…>` embeds |
| `Makefile.py` | the `mk` tasks; `mk check` is the gate |

## Rules that are not obvious from the code

- **The code runs under MicroPython too.** Anything in `frontage/` must stay within what
  MicroPython supports. That is why ruff's `UP` rules are off and why `runtime.py` branches
  on `sys.platform`. Test a change to the package in both runtimes (`mk serve`, switch the
  `<script type>` between `mpy` and `py`) before calling it done.
- **The PyScript pin lives in every example's `index.html`** (currently 2025.2.2, 36 places).
  Bump them together and re-run `mk test --integration`.
- **`frontage/version.py` is the version.** hatchling reads it at build time; the browser
  reads it as plain Python. Nothing else carries the number except `mkdocs.yml`'s
  `project_version`, which the docs use for download commands.
- **Docs tutorial embeds still point at the upstream author's hosted examples**
  (`kkinder.pyscriptapps.com`). They work but say `puepy`. Hosting our own is in TODO.md.
- **ruff's unused-import autofix has bitten this repo once already.** `runtime.py` exists
  to re-export the browser globals, and the tutorial's `main.py` imports `pages` and
  `components` for their side effects. Both were silently deleted by `ruff check --fix`
  on 2026-09-05, and only the browser suite noticed (the unit tests run server-side and
  never import `js`). `__all__` in `runtime.py` and `# noqa: F401` in the example are the
  guards; after any `--fix`, run `mk test --integration` before trusting the tree.
- **Attribution is a license obligation.** `NOTICE` and `ACKNOWLEDGEMENTS.md` name PuePy and
  its author; keep them when reorganising, and keep `LICENSE` verbatim.

## Toolchain

uv, ruff, ty, pytest. `uv run --frozen …` in anything a gate runs. Release: bump
`version.py`, commit, tag `vX.Y.Z`, push the tag; CI publishes over OIDC (see the header of
`.github/workflows/ci.yml` for the publisher record PyPI needs).
