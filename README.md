# Frontage

[documentation](https://academy.optersoft.com/python/frontage) · [PyPI](https://pypi.org/project/frontage/)

**A fine-grained reactive UI framework for Python in the browser.** Signals, memos and
effects; templates that clone once and bind only their holes; a keyed `For`; a nested
router; running on its own Python runtime compiled to WebAssembly, with the framework delivered as
precompiled bytecode. No JavaScript, no Node, no bundler: you write Python and the browser
runs it.

> **Status: 0.13.0, alpha.** The rewrite planned in [DESIGN.md](DESIGN.md) is complete
> through M12. Reactive core, store, templates (`h` and `html(t"…")`), control flow and
> boundaries, `Resource`/`Action`, a nested router, widgets, `State`, timers, the playground
> (0.2–0.3); **prerendering with hydration** (0.4), pages that show before Python loads;
> **transitions**, async memos and the debug warnings (0.5–0.7); `frontage serve` (0.8);
> **the WebAssembly boot that replaced PyScript** (0.9). **0.10.0 replaces the interpreter
> itself**: frontage's own Python runtime, written in Rust ([RUNTIME.md](RUNTIME.md)), with
> the reactive graph, the DOM operations and the template path native inside it. A thousand
> rows are built in 24.8 ms where MicroPython took 71.1, the counter paints in 23 ms, and
> `frontage build` ships only the modules your entry imports, compiled to bytecode and
> content-hashed. **0.11 makes the runtime optional**: `mount(view, "#app", when="never")` is
> a static page — prerendered, no boot tag, 142 bytes over the wire and not one request for
> the runtime — and `island(view, when="visible")` is the exception it makes, a component
> hydrated when its trigger fires ([ISLAND.md](ISLAND.md)). **0.12 gives such a page
> something to say**: `frontage.content` reads a directory of Markdown whose front matter a
> `frontage.schema` record checks, renders it on CPython at build time, and turns a
> `::: island` container in the prose into one. **0.13 makes it a site**: `frontage site` is
> `pages/` as the site map, one page per entry, layouts and endpoints, and every page static
> unless it says otherwise. The API is young and will move;
> the [browser suite](tests/browser/) runs every example on Chromium each push and on Firefox
> and WebKit nightly.

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
it read changes; a component body runs once. Name the functions you put in holes: a `lambda`
inside a template's braces is hard to read and `frontage check` will tell you so.

**Try it** at [frontage.optersoft.com/playground](https://frontage.optersoft.com/playground/),
which runs your code in the browser and keeps it in the link. **Learn it** at
[academy.optersoft.com/python/frontage](https://academy.optersoft.com/python/frontage), ten
chapters with exercises, nine of them with an app published on GitLab Pages. **Install it** with pip,
and `frontage build` writes a directory that runs anywhere:

```sh
uvx frontage build myapp        # index.html, your .py, and _frontage/ beside them
```

| The counter, cold cache | 0.10.0 | 0.9.1 (MicroPython) | 0.8.3 (PyScript) |
|---|---|---|---|
| requests | 17 | 6 | 29 |
| transferred | 0.78 MB | 0.46 MB | 0.91 MB |
| compressed | 0.32 MB | 0.19 MB | 0.33 MB |
| to first paint | 23 ms | 59 ms | 88 ms |

Most of that is the runtime, 261 KB of gzip; the rest is one file per module of bytecode,
each named by its content so a host can cache it forever, and none of it is parsed in the
browser. It is a bigger download than MicroPython's and a much faster page: the runtime
starts in a few milliseconds and builds a thousand rows in 24.8 ms against 71.1
([RUNTIME.md](RUNTIME.md) §9). Medians of five, this laptop's Chromium; DESIGN.md §12 has
the method.

The same package is a small command line on your machine, stdlib only:

```sh
uvx frontage serve              # a dev server that swaps a changed module into the live page
uvx frontage check app.py       # the rules the browser enforces and CPython does not
uvx frontage tailwind           # Tailwind CSS: the standalone CLI, fetched once, no Node
uvx frontage prerender . --out build --crawl   # every route the pages link to, as finished HTML
```

(`uvx` runs the `frontage` script straight from PyPI; `pip install frontage` puts the same
`frontage` command on PATH, and `python -m frontage` is the same thing.)

`prerender` runs the app on your machine, waits for its resources and async memos, and writes each route as
finished HTML with the values embedded. In the browser `mount` hydrates: it adopts the HTML
already on screen instead of building it, skips the fetches the page already holds, and
replays the clicks made before Python was ready. Static hosting only, no server: Leptos's
async rendering mode as a build step.

A page with nothing to run should download nothing to run it. `mount(view, "#app",
when="never")` says so: `prerender` writes the HTML and no boot tag, so a content page is its
own bytes and stops there. What is interactive on it is an **island** —

```python
from frontage import h, island, mount


def page():
    return h.main(
        h.article(...),  # static: rendered once, at build
        island(theme_toggle, when="idle"),  # alive when the browser is free
        island("charts:sparkline", when="visible"),  # its own chunk, fetched when seen
    )


mount(page, "#app", when="never")
```

— and the first trigger to fire boots the runtime once, shared by every island on the page.
`examples/islands` is the whole of it in forty lines.

What such a page says comes from a **collection**: a directory of Markdown whose front matter
is checked by the same `frontage.schema` record that checks a form, rendered once, on your
machine, and shipped as HTML.

```python
from frontage.content import collection
from frontage.schema import iso_date, record, text

Post = record(("title", text(min=1)), ("date", iso_date()), ("summary", text(), None))
posts = collection("posts", Post)  # content/posts/*.md, newest first

for post in posts.entries():
    post.slug, post.data["title"], post.view()
```

A file whose front matter does not match fails the build, naming the file and the field, and
a `::: island widgets:reactions when="visible"` container in a post is an island where it
stands. `pip install "frontage[content]"`; `examples/blog` is a blog in one page.

A whole site is a directory, and the directory is the site map:

```
site/
  pages/index.py          → /
  pages/about.py          → /about/
  pages/blog/index.py     → /blog/
  pages/blog/[slug].py    → /blog/<slug>/, one per static_paths()
  pages/sitemap.xml.py    → /sitemap.xml, a module with a get()
  layouts/site.py         a component taking children; no new concept
  content/posts/*.md      the collection above
  public/                 copied as it is
```

`frontage site` renders every page on your machine and writes it where its path says. A page
with nothing interactive on it carries **no script at all**; the runtime is written once,
beside the pages, only if some page has an island. `frontage serve --prerender` is the same
build with a file watcher in front of it. `examples/site` is seven pages, six of which fetch
nothing.

Tailwind with no build at all: the playground loads Tailwind's browser build, so utility
classes work as you type. The [Style](https://academy.optersoft.com/python/frontage/style),
[Ship](https://academy.optersoft.com/python/frontage/ship) and
[Prerender](https://academy.optersoft.com/python/frontage/prerender) chapters cover all of it.

## Why

Python in the browser exists — CPython and MicroPython both compile to WebAssembly — and the
frameworks that use it either carry a server into the browser (Streamlit's stlite, Shiny's
Shinylive: tens of seconds to start) or rebuild and diff the page on every change. Frontage
is browser-first: no session, no transport, no DSL, and a state change touches only the DOM
nodes that read it. Its runtime is its own, because the framework's hot paths are inside it:
[RUNTIME.md](RUNTIME.md) is why, with the measurements that decided it. The whole reasoning, with the frameworks it learned from, is in [DESIGN.md](DESIGN.md);
the behaviours it must have, one line each, are in [SPEC.md](SPEC.md).

## Develop

The repo uses [uv](https://docs.astral.sh/uv/) and [mkrun](https://github.com/optersoft/make) (`mk`).

```sh
mk sync                 # .venv with every dependency group
mk check                # lint, types, unit tests: the gate
mk runtime.build        # build the runtime from rust/ into frontage/_runtime/ (cargo, wasm-opt)
mk serve                # examples and playground at http://127.0.0.1:8000/, package read live, reload on save
mk test --browser       # every example in Chromium, on the runtime in WebAssembly
mk build examples/todo  # a static directory that boots from WebAssembly
cargo test --profile native   # in rust/: the runtime's own tests, against CPython
mk site.deploy          # publish frontage.optersoft.com by hand (Cloudflare Pages): landing page, gallery, playground, wheels
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
