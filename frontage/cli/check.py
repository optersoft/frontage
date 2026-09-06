"""`python -m frontage check PATH...`: the rules a browser interpreter enforces but a desktop
Python does not, found before the page loads.

- A `lambda` inside a template string's braces is a SyntaxError on MicroPython: name the function.
- `html(f"…")` builds text, not a template: it wants a t-string.
- HTML the browser's parser rewrites (a block element inside `<p>`, `<tr>` straight under
  `<table>`, `<a>` inside `<a>`): the page then differs from the template, and a prerendered
  page cannot be hydrated.

Scans `.py` files and the ```py / ```python blocks of `.md` files; directories recurse.
Exit status 1 when anything was found. Needs Python 3.14 to parse template strings."""

import argparse
import ast
import re
import sys
from pathlib import Path

_TemplateStr = getattr(ast, "TemplateStr", None)
_Interpolation = getattr(ast, "Interpolation", None)
_FENCE = re.compile(r"^```(?:py|python)\s*$")

# Elements a `<p>` cannot hold: the parser closes the paragraph first.
_BLOCK = {
    "address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "menu", "nav", "ol", "p", "pre", "section",
    "table", "ul",
}  # fmt: skip


def nesting_findings(markup):
    """`(message)` for each place the browser's parser would rewrite `markup`."""
    from html.parser import HTMLParser

    found = []

    class Walk(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self)
            self.stack = []

        def handle_starttag(self, tag, attrs):
            stack = self.stack
            if tag in _BLOCK and "p" in stack:
                found.append(f"<{tag}> inside <p>: the browser closes the paragraph first; use a <div> or <span>")
            if tag == "tr" and stack and stack[-1] == "table":
                found.append("<tr> straight under <table>: the browser inserts <tbody>; write it")
            if tag == "a" and "a" in stack:
                found.append("<a> inside <a>: the browser splits them")
            if tag not in (
                "area",
                "base",
                "br",
                "col",
                "embed",
                "hr",
                "img",
                "input",
                "link",
                "meta",
                "source",
                "track",
                "wbr",
            ):
                stack.append(tag)

        def handle_endtag(self, tag):
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass

    walker = Walk()
    walker.feed(markup)
    walker.close()
    return found


def check_source(source, path="<string>", offset=0):
    """Findings for one piece of Python as `(path, line, message)`; `offset` shifts the lines."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        line = (exc.lineno or 1) + offset
        return [(path, line, f"cannot parse: {exc.msg}")]
    found = []
    for node in ast.walk(tree):
        if _TemplateStr is not None and isinstance(node, _TemplateStr):
            markup = "".join(
                part.value if isinstance(part, ast.Constant) else "<!--h-->" for part in getattr(node, "values", ())
            )
            if "<" in markup:
                for message in nesting_findings(markup):
                    found.append((path, getattr(node, "lineno", 1) + offset, message))
            for part in getattr(node, "values", ()):
                if (
                    _Interpolation is not None
                    and isinstance(part, _Interpolation)
                    and any(isinstance(n, ast.Lambda) for n in ast.walk(part.value))
                ):
                    found.append(
                        (
                            path,
                            part.lineno + offset,
                            "lambda inside a template string's braces: MicroPython rejects it, name the function",
                        )
                    )
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.JoinedStr):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name == "html":
                found.append((path, node.lineno + offset, 'html(f"…") is text, not a template: use a t-string'))
    return sorted(set(found))


def check_markdown(text, path):
    found = []
    block, start = None, 0
    for number, line in enumerate(text.splitlines(), 1):
        if block is None:
            if _FENCE.match(line):
                block, start = [], number
        elif line.startswith("```"):
            found += check_source("\n".join(block), path, offset=start)
            block = None
        else:
            block.append(line)
    return found


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
    parser = argparse.ArgumentParser(prog="python -m frontage check", description=__doc__)
    parser.add_argument("paths", nargs="+", help=".py or .md files, or directories")
    args = parser.parse_args(argv)
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
