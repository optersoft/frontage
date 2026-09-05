# Frontage

[frontage.optersoft.com](https://frontage.optersoft.com) · [documentation](https://academy.optersoft.com/tool/frontage) · [PyPI](https://pypi.org/project/frontage/)

**A Python frontend framework for the browser.** Reactive components, an SPA router and
two-way data binding, running on [PyScript](https://pyscript.net) over WebAssembly. No
JavaScript, no Node, no bundler: you write Python, and the browser runs it.

```python
from frontage import Application, Page, t

app = Application()


@app.page()
class Hello(Page):
    def initial(self):
        return dict(name="")

    def populate(self):
        with t.div(classes=["container", "mx-auto", "p-4"]):
            t.h1("Welcome to Frontage", classes=["text-xl", "pb-4"])
            if self.state["name"]:
                t.p(f"Hello there, {self.state['name']}")
            else:
                t.p("Why don't you tell me your name?")
            t.input(placeholder="Enter your name", bind="name")
            t.button("Continue", classes="btn btn-lg", on_click=self.on_button_click)

    def on_button_click(self, event):
        print("Button clicked")  # logs to the browser console


app.mount("#app")
```

## What you get

- **Reactivity.** Change a component's state and the DOM updates; redraws are diffed with morphdom.
- **Components.** Props, slots and events in the style of Vue, each component a single Python class.
- **Routing.** A hash or history router for single-page apps, with navigation guards.
- **Your choice of runtime.** Full CPython via [Pyodide](https://pyodide.org), or
  [MicroPython](https://micropython.org/) when a small download matters more than the standard library.
- **No build step.** Serve the files. That is the whole deployment.

## Install

Frontage is a client-side library, so "installing" it means telling PyScript where the wheel is.
The short version is a `pyscript.json` with the wheel in `packages`; the
[installation guide](https://academy.optersoft.com/tool/frontage) and the tutorial walk through a
complete first project.

```sh
pip download frontage --no-deps --dest .
```

## Develop

The repo uses [uv](https://docs.astral.sh/uv/) and [mkrun](https://github.com/optersoft/make) (`mk`).

```sh
mk sync                 # .venv with every dependency group
mk check                # lint, types, unit tests: the gate
mk serve                # the examples at http://localhost:8000
mk test --integration   # the examples driven in a real browser (Playwright)
mk site.deploy          # publish frontage.optersoft.com (Cloudflare Pages)
```

Without `mk`: `uv sync --all-groups`, then `uv run pytest`, `uv run ruff check`, `uv run ty check`.

## Provenance

Frontage is a fork of [PuePy](https://github.com/kkinder/puepy) by Ken Kinder, taken from
version 0.6.5 (February 2025) after the project went quiet. The design and most of the code
are his; see [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) and [NOTICE](NOTICE). Frontage
carries the work forward under the same Apache 2.0 license, maintained by
[Optersoft](https://optersoft.com).

## License

Apache License 2.0. See [LICENSE](LICENSE).
