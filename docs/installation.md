# Installation

## Client-side installation

Although Frontage is [available on pypi](https://pypi.org/project/frontage/), because Frontage is intended primarily as a client-side framework,
"installation" is best achieved by downloading the wheel file and including it in your pyscript `packages` configuration.

A simple first project (with no web server) would be:

- `index.html` (index.html file)
- `pyscript.json` (pyscript config file)
- `hello.py` (Hello World code)
- `frontage-{{project_version}}-py3-none-any.whl` (Frontage wheel file)

### Downloading client runtime

Every release's wheel is on PyPI, under the *Download files* tab of
[pypi.org/project/frontage](https://pypi.org/project/frontage/#files), or in one command:

```Bash
pip download frontage=={{project_version}} --no-deps --dest .
```

### Setting up your first project

Continue to the [tutorial](tutorial/00-using-this-tutorial.md) to see how to set up your first project.
