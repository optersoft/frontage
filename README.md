# Frontage

[frontage.optersoft.com](https://frontage.optersoft.com) · [documentation](https://academy.optersoft.com/tool/frontage) · [PyPI](https://pypi.org/project/frontage/)

**A fine-grained reactive UI framework for Python in the browser.** Signals, memos and
effects; templates that clone once and bind only their holes; a keyed `For`; a nested
router; running on [PyScript](https://pyscript.net) over WebAssembly, on Pyodide or
MicroPython. No JavaScript, no Node, no bundler: you write Python and the browser runs it.

> **Status: pre-alpha, being rewritten.** `main` holds milestone M0 of the plan in
> [DESIGN.md](DESIGN.md): the runtime bridge, the renderer seam and a static view builder.
> Reactivity, the DOM renderer and templates follow. The previous code, a fork of PuePy,
> lives on the `puepy-reference` branch and still works if you need something today.

```python
from frontage import Signal, html

def counter(initial=0):
    count = Signal(initial)
    return html(t"""
        <div class="counter">
            <button on:click={lambda e: count.update(lambda n: n - 1)}>-</button>
            <span>Value: {count}!</span>
            <button on:click={lambda e: count.update(lambda n: n + 1)}>+</button>
        </div>
    """)
```

That is the target syntax (M2). What runs today:

```python
from frontage import h, render_to_string

with h.ul(cls="menu") as menu:
    for label in ("Home", "About"):
        h.li(label)

print(render_to_string(menu))  # <ul class="menu"><li>Home</li><li>About</li></ul>
```

## Why

Python in the browser exists (PyScript, Pyodide, MicroPython) and the frameworks that use it
either carry a server into the browser (Streamlit's stlite, Shiny's Shinylive: tens of
seconds to start) or rebuild and diff the page on every change. Frontage is browser-first:
no session, no transport, no DSL, and a state change touches only the DOM nodes that read
it. The whole reasoning, with the frameworks it learned from, is in [DESIGN.md](DESIGN.md);
the behaviours it must have, one line each, are in [SPEC.md](SPEC.md).

## Develop

The repo uses [uv](https://docs.astral.sh/uv/) and [mkrun](https://github.com/optersoft/make) (`mk`).

```sh
mk sync                 # .venv with every dependency group
mk check                # lint, types, unit tests: the gate
mk pyscript.fetch       # PyScript's offline bundle (core + both interpreters) into tools/pyscript/
mk serve                # the examples at http://127.0.0.1:8000/examples/, package read live
mk test --browser       # the examples in Chromium, under MicroPython and Pyodide
mk site.deploy          # publish frontage.optersoft.com (Cloudflare Pages)
```

Without `mk`: `uv sync --all-groups`, `uv run pytest`, `uv run ruff check`, `uv run ty check`.

## Contributing

Contributions are welcome and are accepted under the Apache License 2.0, the same terms the
project is published under. By opening a pull request you agree that your contribution may be
distributed under that license, including its patent grant (section 3). There is no separate
contributor agreement. The rewrite is clean-room: code is written from `SPEC.md`, not from
any reference framework's source, and a pull request says so.

## License

Apache License 2.0, copyright Optersoft, S.L. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

**Frontage** and the Frontage logo are trademarks of Optersoft, S.L. The license grants no
rights to the name or the logo (Apache License section 6). You may say that your work uses or
is built with Frontage; a fork or a derivative must ship under another name.

Frontage's reactive model follows [Solid](https://www.solidjs.com/) and
[Leptos](https://leptos.dev/); the project began as a fork of [PuePy](https://github.com/kkinder/puepy).
