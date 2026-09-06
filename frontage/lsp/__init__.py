"""The frontage language server: what an editor knows about `html(t"…")`.

Inside a template string every other tool is blind — to a type checker it is one opaque
`str` — so this is where tag and attribute completion, hover, and the checks that only a
browser interpreter enforces have to come from. Outside it, the server stays quiet and
leaves Python to whatever language server the editor already runs.

    uvx --python 3.14 frontage lsp

Stdlib only, like the rest of the developer-side code, and CPython only: none of this is
ever loaded in the browser. `editors/vscode/` is a thin client over it, and any editor that
speaks LSP can spawn the same command — the server is the product, a client is a config
block.

Modules, in the order a request passes through them:

| `protocol` | `Content-Length` framing over stdio, and the dispatch loop |
| `documents` | open files, and the UTF-16 position arithmetic the protocol wants |
| `scanner` | where the cursor is: the t-string lexer and the HTML state machine |
| `rules` | the three static rules, with ranges; `frontage check` prints the same ones |
| `data` | the tables: HTML elements and attributes, and frontage's own prefixes |
| `features` | completion, hover, definition, semantic tokens |
| `server` | the handlers, and `frontage lsp` |
"""

from .server import Server, main

__all__ = ["Server", "main"]
