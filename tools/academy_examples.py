"""Write the academy's Examples page from examples/: `mk docs.examples`.

Each example becomes one `::: pyscript` block, the academy directive that runs a Python
fence for real: MicroPython in a frame, the markup from an `html` fence, and `packages=`
naming the released wheel of this version by URL. The repository stays the one copy of
every example (the academy's rule): this page is generated, never edited by hand, and its
`.meta.md` card says so. The academy renders `<page:…>` links and `:::` directives; nothing
else here is academy-specific."""

import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WHEEL = "https://frontage.optersoft.com/dist/frontage-{version}-py3-none-any.whl"

# name, title, frame height (px): the order of the chapters that use them.
EXAMPLES = [
    ("hello", "Hello", 180),
    ("counter", "Counter", 160),
    ("template", "Template", 160),
    ("todo", "Todo", 340),
    ("forms", "Forms", 380),
    ("fetch", "Fetch", 240),
    ("contacts", "Contacts", 440),
    ("rows", "Rows", 520),
]

INTRO = """Every example below runs in the page, on MicroPython, from the `frontage` wheel of
this version: what you see is the program under it, and the program is one Python file
with the HTML it mounts into. The chapters build on them (<page:python/frontage/basic>
starts with the counter); the source of each is `examples/<name>/` in the
[repository](https://github.com/optersoft/frontage), where the browser suite runs them under
both interpreters on every push. `?type=py` there switches an example to Pyodide; here they
all run on MicroPython, the interpreter that loads in under a megabyte."""


def split_docstring(code):
    """(first paragraph of the module docstring as prose, the code without the docstring)."""
    match = re.match(r'\s*"""(.*?)"""\s*\n', code, re.S)
    if match is None:
        return "", code
    doc = match.group(1).strip()
    prose = re.split(r"\n\s*\n", doc)[0].replace("\n", " ")
    return prose, code[match.end() :]


def body_of(index_html):
    """The markup between `<body>` and the page's loader script: what the app mounts into."""
    match = re.search(r"<body>(.*?)<script>", index_html, re.S)
    return match.group(1).strip() if match else '<div id="app"></div>'


def block(name, title, height, version):
    folder = ROOT / "examples" / name
    prose, code = split_docstring((folder / f"{name}.py").read_text())
    markup = body_of((folder / "index.html").read_text())
    wheel = WHEEL.format(version=version)
    lines = [f"## {title}", ""]
    if prose:
        lines += [prose, ""]
    lines += [
        f'::: pyscript title="examples/{name}/{name}.py" height="{height}" packages="{wheel}"',
        "```html",
        markup,
        "```",
        "```py",
        code.rstrip(),
        "```",
        ":::",
        "",
    ]
    return "\n".join(lines)


def render(version, today=None):
    today = today or datetime.date.today().isoformat()
    head = f"""---
title: Examples
updated: {today}
description: The eight examples the Frontage chapters build on, running live on MicroPython from the released wheel.
---

{INTRO}

"""
    return head + "\n".join(block(name, title, height, version) for name, title, height in EXAMPLES)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", default=str(ROOT.parent / "academy-pages"), help="the academy-pages checkout")
    parser.add_argument("--stdout", action="store_true", help="print the page instead of writing it")
    args = parser.parse_args(argv)
    from frontage.version import __version__

    page = render(__version__)
    if args.stdout:
        print(page)
        return 0
    target = Path(args.pages) / "python" / "frontage" / "examples.md"
    if not target.parent.is_dir():
        print(f"error: {target.parent} is not there; pass --pages", file=sys.stderr)
        return 2
    target.write_text(page)
    print(f"wrote {target} ({len(EXAMPLES)} examples, wheel {__version__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
