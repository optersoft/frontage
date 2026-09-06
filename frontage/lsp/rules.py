"""The static rules, with ranges: what a browser interpreter enforces and a desktop Python
does not.

There is one implementation and two front ends. `frontage check` prints these findings a
line at a time; the language server publishes them as diagnostics while you type. Keeping
them here rather than in the CLI is the whole point — a rule that existed twice would drift,
and `SPEC.md` is meant to have exactly one reading.

Three rules today:

- A `lambda` inside a template string's braces is a SyntaxError on MicroPython: name the
  function. Fatal, and invisible until the page loads. Only the *parenthesised* form reaches
  this rule: CPython 3.14 rejects a bare `{lambda ev: None}` itself (the `:` opens a format
  spec), and that is reported as the parse error it is, which also names the lambda.
- `html(f"…")` builds a string, not a template: it wants a t-string.
- HTML the browser's parser rewrites (a block element inside `<p>`, `<tr>` straight under
  `<table>`, `<a>` inside `<a>`). The rendered page then differs from the template, and a
  prerendered page cannot be hydrated against it.

Template strings need Python 3.14 to parse. Below that the first two rules cannot fire at
all, which is why `supported()` exists: the CLI degrades quietly, but a server that goes
silent looks broken, so it says so once.
"""

import ast

_TemplateStr = getattr(ast, "TemplateStr", None)
_Interpolation = getattr(ast, "Interpolation", None)

ERROR = 1
WARNING = 2

# Elements a `<p>` cannot hold: the parser closes the paragraph first.
_BLOCK = {
    "address", "article", "aside", "blockquote", "details", "div", "dl", "fieldset", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "menu", "nav", "ol", "p", "pre", "section",
    "table", "ul",
}  # fmt: skip

_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr",
}  # fmt: skip


def supported():
    """Can this interpreter parse template strings at all? False below Python 3.14."""
    return _TemplateStr is not None


class Finding:
    """One diagnostic. Positions are 1-based lines and 0-based character columns, the
    convention `ast` uses, converted at the edges by whoever reports it."""

    __slots__ = ("path", "line", "col", "end_line", "end_col", "message", "code", "severity")

    def __init__(self, path, line, col, end_line, end_col, message, code, severity=ERROR):
        self.path = path
        self.line = line
        self.col = col
        self.end_line = end_line
        self.end_col = end_col
        self.message = message
        self.code = code
        self.severity = severity

    def key(self):
        return (self.line, self.col, self.code, self.message)

    def __repr__(self):
        return f"<Finding {self.path}:{self.line}:{self.col} {self.code}>"


class _Lines:
    """Offsets of each line start, so an `ast` position becomes a string offset and back.

    `col_offset` counts UTF-8 *bytes*; a Catalan `<p>Àlex</p>` past column zero is enough to
    shift every range after it if you forget that.
    """

    def __init__(self, text):
        self.text = text
        starts = [0]
        for index, char in enumerate(text):
            if char == "\n":
                starts.append(index + 1)
        self.starts = starts

    def offset(self, line, col):
        index = line - 1
        if index < 0:
            return 0
        if index >= len(self.starts):
            return len(self.text)
        start = self.starts[index]
        rest = self.text[start:]
        newline = rest.find("\n")
        if newline >= 0:
            rest = rest[:newline]
        if col <= 0:
            return start
        return start + len(rest.encode("utf-8")[:col].decode("utf-8", "ignore"))

    def position(self, offset):
        offset = max(0, min(offset, len(self.text)))
        low, high = 0, len(self.starts) - 1
        while low < high:
            mid = (low + high + 1) // 2
            if self.starts[mid] <= offset:
                low = mid
            else:
                high = mid - 1
        line_text = self.text[self.starts[low] : offset]
        return low + 1, len(line_text.encode("utf-8"))


def _markup_of(node, lines):
    """The template's static markup, plus a table mapping markup offsets back to the source.

    An interpolation becomes `<!--h-->` — a comment, so the HTML parser treats a hole the
    way the browser will. The table holds `(markup_start, markup_end, source_start)` for
    each literal run whose source span is character-for-character the same length as its
    value; a run with an escape in it is skipped, and positions inside it fall back to the
    whole template's range rather than lying about a column.
    """
    pieces = []
    spans = []
    cursor = 0
    for part in getattr(node, "values", ()):
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            value = part.value
            start = lines.offset(part.lineno, part.col_offset)
            end = lines.offset(part.end_lineno, part.end_col_offset)
            if end - start == len(value):
                spans.append((cursor, cursor + len(value), start))
            pieces.append(value)
            cursor += len(value)
        else:
            pieces.append("<!--h-->")
            cursor += 8
    return "".join(pieces), spans


def _source_offset(markup_offset, spans):
    """A markup offset as a source offset, or `None` when it is inside a hole or an escape."""
    for start, end, source_start in spans:
        if start <= markup_offset < end:
            return source_start + (markup_offset - start)
    return None


def _nesting(markup):
    """`(markup_offset, tag, message)` for each place the browser's parser would rewrite."""
    from html.parser import HTMLParser

    starts = [0]
    for index, char in enumerate(markup):
        if char == "\n":
            starts.append(index + 1)

    found = []

    class Walk(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self)
            self.stack = []

        def at(self):
            line, col = self.getpos()
            index = line - 1
            if index < 0 or index >= len(starts):
                return 0
            return starts[index] + col

        def handle_starttag(self, tag, attrs):
            stack = self.stack
            if tag in _BLOCK and "p" in stack:
                found.append(
                    (
                        self.at(),
                        tag,
                        f"<{tag}> inside <p>: the browser closes the paragraph first; use a <div> or <span>",
                    )
                )
            if tag == "tr" and stack and stack[-1] == "table":
                found.append((self.at(), tag, "<tr> straight under <table>: the browser inserts <tbody>; write it"))
            if tag == "a" and "a" in stack:
                found.append((self.at(), tag, "<a> inside <a>: the browser splits them"))
            if tag not in _VOID:
                stack.append(tag)

        def handle_startendtag(self, tag, attrs):
            self.handle_starttag(tag, attrs)
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()

        def handle_endtag(self, tag):
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass

    walker = Walk()
    walker.feed(markup)
    walker.close()
    return found


def findings(source, path="<string>", line_offset=0):
    """Every finding in one piece of Python. `line_offset` shifts the lines, for a fenced
    block lifted out of a Markdown file."""
    lines = _Lines(source)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        line = (exc.lineno or 1) + line_offset
        col = max(0, (exc.offset or 1) - 1)
        return [Finding(path, line, col, line, col + 1, f"cannot parse: {exc.msg}", "syntax", ERROR)]

    found = []

    def add(node, message, code, severity=ERROR, start=None, end=None):
        if start is None:
            start_line, start_col = node.lineno, node.col_offset
            end_line, end_col = (
                getattr(node, "end_lineno", node.lineno),
                getattr(node, "end_col_offset", node.col_offset + 1),
            )
        else:
            start_line, start_col = lines.position(start)
            end_line, end_col = lines.position(end)
        found.append(
            Finding(path, start_line + line_offset, start_col, end_line + line_offset, end_col, message, code, severity)
        )

    for node in ast.walk(tree):
        if _TemplateStr is not None and isinstance(node, _TemplateStr):
            markup, spans = _markup_of(node, lines)
            if "<" in markup:
                for markup_offset, tag, message in _nesting(markup):
                    start = _source_offset(markup_offset, spans)
                    if start is None:
                        add(node, message, "html-nesting", WARNING)
                    else:
                        add(node, message, "html-nesting", WARNING, start, start + len(tag) + 1)
            for part in getattr(node, "values", ()):
                if (
                    _Interpolation is not None
                    and isinstance(part, _Interpolation)
                    and any(isinstance(inner, ast.Lambda) for inner in ast.walk(part.value))
                ):
                    add(
                        part,
                        "lambda inside a template string's braces: MicroPython rejects it, name the function",
                        "lambda-in-template",
                    )
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.JoinedStr):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name == "html":
                add(node, 'html(f"…") is text, not a template: use a t-string', "f-string-template")

    seen = {}
    for finding in found:
        seen.setdefault(finding.key(), finding)
    return sorted(seen.values(), key=lambda f: (f.line, f.col, f.code))


_FENCE_OPEN = ("```py", "```python")


def findings_in_markdown(text, path="<string>"):
    """Findings in the ```py / ```python blocks of a Markdown file."""
    found = []
    block, start = None, 0
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.rstrip()
        if block is None:
            if stripped in _FENCE_OPEN:
                block, start = [], number
        elif stripped.startswith("```"):
            found += findings("\n".join(block), path, line_offset=start)
            block = None
        else:
            block.append(line)
    return found
