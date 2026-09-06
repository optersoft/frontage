# Frontage

[documentation](https://academy.optersoft.com/python/frontage) · [PyPI](https://pypi.org/project/frontage/)

**A fine-grained reactive UI framework for Python in the browser.** Signals, memos and
effects; templates that clone once and bind only their holes; a keyed `For`; a nested
router; running on [PyScript](https://pyscript.net) over WebAssembly, on Pyodide or
MicroPython. No JavaScript, no Node, no bundler: you write Python and the browser runs it.

> **Status: 0.8.2, alpha.** The rewrite planned in [DESIGN.md](DESIGN.md) is complete through
> its M5 milestone: reactive core, store, templates (`h` and `html(t"…")`), control flow and
> boundaries, `Resource`/`Action`, a nested router, widgets, `State`, timers, the playground;
> 0.3.0 added the command line (`export`, `tailwind`, `check`); 0.4.0 added **prerendering
> with hydration** (M6): pages that show before Python loads; 0.5.0 adds **transitions**
> (`transition`, `is_pending`, `Optimistic`), async memos, the debug warnings, the `frontage`
> console script and `prerender --crawl` (M7); 0.6.0 builds the new state off screen during a
> transition and lets the router navigate inside one (M8); 0.7.0 makes async memos the router's
> data primitive: they count toward `is_routing`, and `prerender` settles and hydrates them (M9); 0.8.0 adds
> `frontage serve`, a dev server that reloads the page on save. The API is young and will move; the [browser suite](tests/browser/) runs every example under
> MicroPython and Pyodide on Chromium each push and on Firefox and WebKit nightly.

```python
from frontage import Signal, component, html, mount


@component
def counter(initial=0):
    count = Signal(initial)

    def inc(ev):
        count.update(lambda n: n + 1)

    def dec(ev):
        count.update(lambda n: n - 1)

    return html(t"""
        <div class="counter">
            <button on:click={dec}>-</button>
            <span>Value: {count}</span>
            <button on:click={inc}>+</button>
        </div>
    """)


mount(lambda: counter(initial=0), "#app")
```

Signals hold state; anything callable in a template is a hole that updates in place when what
it read changes; a component body runs once. Name the functions you put in holes: MicroPython
does not accept a `lambda` inside a template's braces.

**Try it** at [frontage.optersoft.com/playground](https://frontage.optersoft.com/playground/),
which runs your code on MicroPython and keeps it in the link. **Learn it** at
[academy.optersoft.com/python/frontage](https://academy.optersoft.com/python/frontage), nine
chapters with exercises, each with its app published on GitLab Pages. **Install it** with a `pyscript.json`:

```json
{ "packages": ["https://frontage.optersoft.com/dist/frontage-0.8.2-py3-none-any.whl"] }
```

| The counter above, as downloaded | MicroPython | Pyodide |
|---|---|---|
| transferred | 0.84 MB | 13.8 MB |
| compressed | 0.32 MB | 6.4 MB |

Frontage itself is 131 KB (39 KB compressed); the rest is the interpreter.

The same package is a small command line on your machine, stdlib only:

```sh
uvx frontage serve              # a dev server that reloads the page whenever a file changes
uvx frontage check app.py       # the rules MicroPython enforces and CPython does not
uvx frontage tailwind           # Tailwind CSS: the standalone CLI, fetched once, no Node
uvx frontage export . --out build              # a self-contained static folder
uvx frontage prerender . --out build --crawl   # every route the pages link to, as finished HTML
```

(`uvx` runs the `frontage` script straight from PyPI; `pip install frontage` puts the same
`frontage` command on PATH, and `python -m frontage` is the same thing.)

`prerender` runs the app on your machine, waits for its resources and async memos, and writes each route as
finished HTML with the values embedded. In the browser `mount` hydrates: it adopts the HTML
already on screen instead of building it, skips the fetches the page already holds, and
replays the clicks made before Python was ready. Static hosting only, no server: Leptos's
async rendering mode as a build step.

Tailwind with no build at all: the playground loads Tailwind's browser build, so utility
classes work as you type. The [Style](https://academy.optersoft.com/python/frontage/style),
[Ship](https://academy.optersoft.com/python/frontage/ship) and
[Prerender](https://academy.optersoft.com/python/frontage/prerender) chapters cover all of it.

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
mk serve                # examples and playground at http://127.0.0.1:8000/, package read live, reload on save
mk test --browser       # every example in Chromium, under MicroPython and Pyodide
mk export examples/todo # python -m frontage export, with the local PyScript bundle
mk site.deploy          # publish frontage.optersoft.com (Cloudflare Pages): wheels, playground, redirects
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
[Leptos](https://leptos.dev/).
