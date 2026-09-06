# Frontage for VS Code

What an editor knows about `html(t"…")`.

Inside a template string every other tool is blind — to a type checker it is one opaque
`str` — so this is where the markup gets completed, documented and checked.

## What it does

- **Diagnostics.** The three things a browser interpreter enforces and a desktop Python does
  not: a `lambda` in a template string's braces (a SyntaxError on MicroPython), `html(f"…")`
  where a t-string was meant, and HTML the browser's parser rewrites — a block element inside
  `<p>`, a `<tr>` straight under `<table>`, an `<a>` inside an `<a>`. That last one is why a
  prerendered page fails to hydrate, and until now it was only ever discovered as a blank
  screen.
- **Completion.** Elements, attributes per element, and frontage's own prefixes first:
  `on:`, `oncapture:`, `prop:`, `class:`, `style:`, `bind:`, `attr:` and `ref`. Inside `on:`
  it lists events, inside `bind:` the three targets, inside `style:` CSS properties. `</`
  closes the innermost open element.
- **Hover** on an element, an attribute, a prefix, and on frontage's own names in the Python
  around the template.
- **Go to definition** on a component named inside `{…}` — the one position a Python
  language server cannot reach, because as far as it is concerned that name is a character
  in a string.
- **Highlighting**, twice over: a TextMate injection grammar so markup is coloured before the
  server starts, and semantic tokens from the server, which knows exactly where a hole ends.
- **Commands** for `check`, `serve`, `export`, `prerender` and `tailwind`.

It stays out of Python's territory: no syntax errors, no completions for your own variables,
nothing a type checker already says. Run it alongside Pylance or Pyright, not instead.

## Settings

| | |
|---|---|
| `frontage.enable` | Run the server at all. |
| `frontage.server.command` | How to start it. Empty means the workspace's `.venv` if it has frontage, else `uvx --python 3.14 frontage lsp`. |
| `frontage.python` | A Python 3.14 interpreter to run it with. |
| `frontage.trace.server` | Log the traffic, for when something is wrong. |

Python 3.14 matters: template strings do not parse below it, so two of the three checks
cannot fire. The server says so on connect rather than going quiet.

## Building it

```sh
npm install
npm run package    # frontage-<version>.vsix
```

The extension lives in the framework's own repository, at `editors/vscode/`, so the commit
that changes a template rule changes the editor's understanding of it in the same diff.
