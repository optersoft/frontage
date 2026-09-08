"""`python -m frontage check PATH...`: the rules a browser interpreter enforces but a desktop
Python does not, found before the page loads.

- A `lambda` inside a template string's braces: name the function (it reads better, and the
  rule predates the runtime, whose compiler accepts it).
- `html(f"…")` builds text, not a template: it wants a t-string.
- HTML the browser's parser rewrites (a block element inside `<p>`, `<tr>` straight under
  `<table>`, `<a>` inside `<a>`): the page then differs from the template, and a prerendered
  page cannot be hydrated.

Scans `.py` files and the ```py / ```python blocks of `.md` files; directories recurse.
Exit status 1 when anything was found. Needs Python 3.14 to parse template strings.

The rules themselves live in `frontage.lsp.rules`, because the language server reports the
same three while you type and a rule that existed twice would drift. This module is the
command line over them: it keeps its `(path, line, message)` tuples, which is what a shell
and its tests want, and drops the columns the editor needs.
"""

import argparse
import sys
from pathlib import Path

from frontage.lsp import rules

from . import PROG


def check_source(source, path="<string>", offset=0):
    """Findings for one piece of Python as `(path, line, message)`; `offset` shifts the lines."""
    return sorted({(f.path, f.line, f.message) for f in rules.findings(source, path, line_offset=offset)})


def check_markdown(text, path):
    return sorted({(f.path, f.line, f.message) for f in rules.findings_in_markdown(text, path)})


def check_path(path):
    path = Path(path)
    if path.is_dir():
        found = []
        for child in sorted(path.rglob("*")):
            if child.suffix in (".py", ".md") and "__pycache__" not in child.parts:
                found += check_path(child)
        return found
    text = path.read_text()
    if path.suffix == ".md":
        return check_markdown(text, str(path))
    return check_source(text, str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(prog=f"{PROG} check", description=__doc__)
    parser.add_argument("paths", nargs="+", help=".py or .md files, or directories")
    args = parser.parse_args(argv)
    if not rules.supported():
        print(
            f"warning: this Python cannot parse template strings; the t-string rules will not fire. "
            f"Run it on 3.14 (uvx --python 3.14 {PROG.split()[-1]} check …).",
            file=sys.stderr,
        )
    found = []
    for path in args.paths:
        found += check_path(path)
    for path, line, message in found:
        print(f"{path}:{line}: {message}")
    if found:
        print(f"{len(found)} finding{'s' if len(found) != 1 else ''}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
