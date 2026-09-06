# Editors

The server is the product; a client is a config block.

`frontage lsp` speaks the Language Server Protocol on stdin and stdout, so any editor that
speaks it gets the same completion, hover, go-to-definition, diagnostics and semantic tokens
inside `html(t"…")`. Only VS Code needs code, and only because it also ships the TextMate
grammar and the snippets.

```sh
uvx --python 3.14 frontage lsp
```

The pin is not decoration: template strings do not parse below Python 3.14, so two of the
three checks cannot fire there. The server says so once, on connect, rather than going quiet.

## VS Code

`editors/vscode/`. Build it with `npm install && npm run package`, then install the `.vsix`.
It finds the server itself — the workspace's `.venv` if frontage is in it, otherwise `uvx`.

## Zed

`~/.config/zed/settings.json`:

```json
{
  "lsp": {
    "frontage": { "binary": { "path": "uvx", "arguments": ["--python", "3.14", "frontage", "lsp"] } }
  },
  "languages": { "Python": { "language_servers": ["pyright", "frontage"] } }
}
```

## Neovim

With `nvim-lspconfig`, as a custom server:

```lua
vim.lsp.config.frontage = {
  cmd = { "uvx", "--python", "3.14", "frontage", "lsp" },
  filetypes = { "python", "markdown" },
  root_markers = { "pyproject.toml", ".git" },
}
vim.lsp.enable("frontage")
```

## Helix

`languages.toml`:

```toml
[language-server.frontage]
command = "uvx"
args = ["--python", "3.14", "frontage", "lsp"]

[[language]]
name = "python"
language-servers = ["pylsp", "frontage"]
```

## Emacs

With `eglot`:

```elisp
(add-to-list 'eglot-server-programs
             '(python-mode . ("uvx" "--python" "3.14" "frontage" "lsp")))
```
