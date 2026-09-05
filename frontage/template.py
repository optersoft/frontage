"""`html(t"…")`: a view from a Python 3.14 template string.

The static parts of a template string are parsed once per call site (the tuple of literal
strings is the cache key) into a plan; each call then builds an `Element` tree from the
plan and the interpolated values, so the parser never runs twice for the same template.

What the syntax means, position by position:

- `<tag attr="x" {…}>` : attributes as in HTML; `attr={value}` passes `value` as is, so a
  Signal or lambda there is a bound attribute and a plain value a static one. The prefixes
  are the builder's, spelled with a colon: `on:click`, `prop:value`, `class:active`,
  `style:color`, `bind:value`, `ref`, `oncapture:click`.
- `{value}` between tags: a child. A callable is a hole; a view mounts; a list flattens;
  a string or number is text (with `!r`, `!s` and a format spec honoured).
- Text between tags is kept, except whitespace-only text containing a newline, which is
  indentation.
- Elements close as in HTML; void elements and `<tag/>` need no close tag.

Both interpreters ship `string.templatelib`, so this runs on MicroPython too. The parser is
hand-written: no `re`, which MicroPython only partly has.
"""

from .view import Element, Text, _children

__all__ = ["html"]

_plans = {}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_MARK = "\x00"


class _Hole:
    __slots__ = ("index",)

    def __init__(self, index):
        self.index = index


class _PElement:
    def __init__(self, tag):
        self.tag = tag
        self.attrs = []  # (raw name, value | _Hole | list of str-or-_Hole)
        self.children = []  # _PElement | str | _Hole


def html(template):
    strings = tuple(template.strings)
    plan = _plans.get(strings)
    if plan is None:
        plan = _parse(strings)
        _plans[strings] = plan
    interpolations = template.interpolations
    values = []
    for i in range(len(interpolations)):
        values.append(_convert(interpolations[i]))
    roots = [_build(node, values) for node in plan]
    return roots[0] if len(roots) == 1 else roots


def _convert(interpolation):
    value = interpolation.value
    if callable(value) or isinstance(value, (Element, Text, list, tuple)) or value is None or isinstance(value, bool):
        return value
    conversion = interpolation.conversion
    if conversion == "r":
        value = repr(value)
    elif conversion == "s":
        value = str(value)
    elif conversion == "a":
        value = ascii(value)
    spec = interpolation.format_spec
    if spec:
        value = format(value, spec)
    return value


def _build(node, values):
    if isinstance(node, _PElement):
        attrs = {}
        for raw, value in node.attrs:
            if isinstance(value, _Hole):
                attrs[raw] = values[value.index]
            elif isinstance(value, list):
                attrs[raw] = _joined(value, values)
            else:
                attrs[raw] = value
        children = []
        for child in node.children:
            if isinstance(child, _PElement):
                children.append(_build(child, values))
            elif isinstance(child, _Hole):
                children.append(values[child.index])
            else:
                children.append(Text(child))
        return Element(node.tag, attrs, _children(children))
    if isinstance(node, _Hole):
        return values[node.index]
    return Text(node)


def _joined(parts, values):
    """A quoted attribute with interpolations inside: static if every value is plain, else a
    function that re-joins them (so a signal in `class="a {cls}"` keeps it live)."""
    resolved = [values[p.index] if isinstance(p, _Hole) else p for p in parts]
    if any(callable(v) for v in resolved):

        def joined():
            return "".join(str(v() if callable(v) else v) for v in resolved)

        return joined
    return "".join(str(v) for v in resolved)


# --- parsing ------------------------------------------------------------------------------------


def _parse(strings):
    source = _MARK.join(strings)  # a marker where each interpolation sits; the n-th marker is value n
    roots = []
    stack = []
    i = 0
    n = len(source)
    hole = [0]

    def add(node):
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)

    def add_text(chunk):
        if not chunk:
            return
        if "\n" in chunk and chunk.strip() == "":
            return
        parts = chunk.split(_MARK)
        for k in range(len(parts)):
            if k:
                add(_Hole(hole[0]))
                hole[0] += 1
            if parts[k]:
                add(parts[k])

    while i < n:
        lt = source.find("<", i)
        if lt < 0:
            add_text(source[i:])
            break
        add_text(source[i:lt])
        if source.startswith("<!--", lt):
            end = source.find("-->", lt)
            i = n if end < 0 else end + 3
            continue
        if source.startswith("</", lt):
            gt = source.find(">", lt)
            tag = source[lt + 2 : gt].strip()
            if stack and stack[-1].tag == tag:
                stack.pop()
            else:
                raise ValueError(f"html(): unexpected </{tag}>")
            i = gt + 1
            continue
        i, element, closed = _parse_tag(source, lt, hole)
        add(element)
        if not closed and element.tag not in _VOID:
            stack.append(element)
    if stack:
        raise ValueError(f"html(): <{stack[-1].tag}> is never closed")
    return roots


def _parse_tag(source, i, hole):
    """Parse `<tag attrs…>` at `i`; returns (index after '>', element, self_closed)."""
    n = len(source)
    i += 1
    start = i
    while i < n and source[i] not in " \t\n/>":
        i += 1
    element = _PElement(source[start:i])
    closed = False
    while i < n:
        c = source[i]
        if c in " \t\n":
            i += 1
        elif c == "/":
            closed = True
            i += 1
        elif c == ">":
            return i + 1, element, closed
        else:
            start = i
            while i < n and source[i] not in " \t\n=/>":
                i += 1
            name = source[start:i]
            value = True
            if i < n and source[i] == "=":
                i += 1
                if i < n and source[i] in "\"'":
                    quote = source[i]
                    end = source.find(quote, i + 1)
                    raw = source[i + 1 : end]
                    i = end + 1
                    if _MARK in raw:
                        parts = []
                        pieces = raw.split(_MARK)
                        for k in range(len(pieces)):
                            if k:
                                parts.append(_Hole(hole[0]))
                                hole[0] += 1
                            if pieces[k]:
                                parts.append(pieces[k])
                        value = parts[0] if len(parts) == 1 and isinstance(parts[0], _Hole) else parts
                    else:
                        value = raw
                elif i < n and source[i] == _MARK:
                    value = _Hole(hole[0])
                    hole[0] += 1
                    i += 1
                else:
                    start = i
                    while i < n and source[i] not in " \t\n>":
                        i += 1
                    value = source[start:i]
            element.attrs.append((name, value))
    raise ValueError(f"html(): <{element.tag}> is never closed")
