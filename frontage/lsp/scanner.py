"""Where is the cursor? — the module every other feature is a table lookup on top of.

While someone types, a file is syntactically broken most of the time, so nothing here goes
through `ast`: a tolerant hand lexer finds the template strings, and a small HTML state
machine replays the one the cursor is in. `rules.py` is the opposite bargain — it needs a
real parse and gets one only when the file happens to be valid.

Two passes:

`scan_templates(text)` finds every t-string literal, tolerating unterminated ones (the file
is mid-edit; the last template usually has no closing quote yet) and splitting each body
into literal chunks and interpolation spans. It marks the ones written as `html(t"…")`,
which are the templates; a bare t-string elsewhere is somebody's SQL and is left alone.

`context_at(text, offset)` replays the markup up to the cursor and says what the position
is: a tag name, an attribute name, an attribute value, text between tags, or inside a
`{…}`. Completion, hover and semantic tokens all start from that answer.
"""

# Every Python string prefix that includes `t`. `u` cannot combine, `b` cannot pair with `t`.
_T_PREFIXES = {"t", "tr", "rt"}
_ALL_PREFIXES = {"", "r", "u", "b", "rb", "br", "f", "rf", "fr", "t", "tr", "rt"}
_NAME_START = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
_NAME = _NAME_START + "0123456789"
_SPACE = " \t\r\n\\"

# Tags that need no closing tag; the state machine must not push them on the stack.
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class Template:
    """One `t"…"` literal in the document."""

    __slots__ = ("start", "body_start", "body_end", "end", "quote", "is_raw", "is_html", "parts")

    def __init__(self, start, body_start, body_end, end, quote, is_raw, is_html, parts):
        self.start = start  # offset of the prefix letter
        self.body_start = body_start  # first character of the body
        self.body_end = body_end  # one past the last character of the body
        self.end = end  # one past the closing quote, or len(text) if unterminated
        self.quote = quote
        self.is_raw = is_raw
        self.is_html = is_html
        self.parts = parts  # ("text" | "hole", start, end), in order, covering the body

    def contains(self, offset):
        """A cursor exactly at `body_end` is still inside: that is where typing continues."""
        return self.body_start <= offset <= self.body_end

    def __repr__(self):
        return f"<Template {self.start}:{self.end} html={self.is_html} parts={len(self.parts)}>"


def _skip_string_body(text, i, quote, is_raw, interpolated, parts):
    """Consume a string body starting at `i` (just past the opening quote).

    Returns the offset of the closing quote, or `len(text)` when the string is unterminated.
    When `interpolated`, records `("text", …)` / `("hole", …)` spans into `parts`.
    """
    n = len(text)
    size = len(quote)
    chunk_start = i
    while i < n:
        char = text[i]
        if char == "\\" and not is_raw and i + 1 < n:
            i += 2
            continue
        if char == "\\" and is_raw and i + 1 < n:
            # A raw string keeps the backslash, but the quote after it still does not close it.
            i += 2
            continue
        if size == 1 and char == "\n":
            # An unterminated single-quoted string ends at the newline; the file is mid-edit.
            if interpolated and i > chunk_start:
                parts.append(("text", chunk_start, i))
            return i
        if text.startswith(quote, i):
            if interpolated and i > chunk_start:
                parts.append(("text", chunk_start, i))
            return i
        if interpolated and char == "{":
            if text.startswith("{{", i):  # an escaped brace is literal text
                i += 2
                continue
            if i > chunk_start:
                parts.append(("text", chunk_start, i))
            hole_start = i
            i = _skip_interpolation(text, i, quote)
            parts.append(("hole", hole_start, min(i, n)))
            chunk_start = i
            continue
        if interpolated and text.startswith("}}", i):
            i += 2
            continue
        i += 1
    if interpolated and n > chunk_start:
        parts.append(("text", chunk_start, n))
    return n


def _skip_interpolation(text, i, quote):
    """Consume `{…}` starting at the brace; returns the offset just past the closing brace.

    Nested braces, and strings inside the expression (PEP 701 lets them reuse the outer
    quote), are what stop this from being `text.find("}")`.
    """
    n = len(text)
    depth = 0
    while i < n:
        char = text[i]
        if char in "{[(":
            depth += 1
            i += 1
            continue
        if char in "]),":
            if char != ",":
                depth -= 1
            i += 1
            continue
        if char == "}":
            depth -= 1
            i += 1
            if depth <= 0:
                return i
            continue
        if char in "\"'":
            inner = text[i : i + 3] if text.startswith(char * 3, i) else char
            i = _skip_string_body(text, i + len(inner), inner, False, False, None)
            i += len(inner)
            continue
        if char == "\n" and len(quote) == 1:
            return i  # an unterminated interpolation in a single-quoted string
        i += 1
    return n


def _preceded_by_html(text, start):
    """Is this literal the argument of a call to `html`? Looks back over whitespace for `(`
    and then for the name; `frontage.html(t"…")` counts, `sql(t"…")` does not."""
    i = start - 1
    while i >= 0 and text[i] in _SPACE:
        i -= 1
    if i < 0 or text[i] != "(":
        return False
    i -= 1
    while i >= 0 and text[i] in _SPACE:
        i -= 1
    end = i + 1
    while i >= 0 and text[i] in _NAME:
        i -= 1
    return text[i + 1 : end] == "html"


def scan_templates(text):
    """Every t-string literal in `text`, in order."""
    found = []
    i = 0
    n = len(text)
    while i < n:
        char = text[i]
        if char == "#":
            newline = text.find("\n", i)
            i = n if newline < 0 else newline + 1
            continue
        if char in _NAME_START:
            start = i
            while i < n and text[i] in _NAME:
                i += 1
            word = text[start:i]
            if i < n and text[i] in "\"'" and word.lower() in _ALL_PREFIXES:
                i = _consume_literal(text, start, i, word, found)
            continue
        if char in "\"'":
            i = _consume_literal(text, i, i, "", found)
            continue
        i += 1
    return found


def _consume_literal(text, start, quote_at, prefix, found):
    """Consume one string literal; append it to `found` when it is a t-string. Returns the
    offset just past it."""
    n = len(text)
    char = text[quote_at]
    quote = char * 3 if text.startswith(char * 3, quote_at) else char
    body_start = quote_at + len(quote)
    lowered = prefix.lower()
    is_t = lowered in _T_PREFIXES
    is_raw = "r" in lowered
    interpolated = is_t or "f" in lowered
    parts = [] if interpolated else None  # an f-string needs them too, only nobody reads them
    body_end = _skip_string_body(text, body_start, quote, is_raw, interpolated, parts)
    end = min(body_end + len(quote), n) if body_end < n else n
    if is_t:
        found.append(
            Template(start, body_start, body_end, end, quote, is_raw, _preceded_by_html(text, start), parts or [])
        )
    return end


def template_at(text, offset, templates=None):
    """The template the cursor is in, or `None`."""
    for template in templates if templates is not None else scan_templates(text):
        if template.contains(offset):
            return template
    return None


class Context:
    """What the cursor is sitting on inside a template."""

    __slots__ = ("kind", "tag", "attr", "word", "word_start", "quote", "stack", "template")

    def __init__(self, kind, template, tag="", attr="", word="", word_start=0, quote="", stack=None):
        self.kind = kind  # text | tag | endtag | attr | value | interp | comment
        self.template = template
        self.tag = tag  # the element being written, or the innermost open one
        self.attr = attr  # the attribute whose value we are in
        self.word = word  # what has been typed of the current token
        self.word_start = word_start  # where that token starts, in document offsets
        self.quote = quote  # the quote around an attribute value, "" when bare
        self.stack = stack or []  # open elements, outermost first

    def __repr__(self):
        return f"<Context {self.kind} tag={self.tag!r} attr={self.attr!r} word={self.word!r}>"


def _markup_prefix(text, template, offset):
    """The template's markup up to `offset`, plus the document offset of each character.

    An interpolation collapses to one `\\x00`, the same trick `template.py` uses, so the
    state machine sees a hole as a single opaque character wherever it appears.
    """
    markup = []
    offsets = []
    for kind, start, end in template.parts:
        if start >= offset:
            break
        if kind == "hole":
            if offset < end:  # the cursor is inside the braces
                return None, None
            markup.append("\x00")
            offsets.append(start)
            continue
        stop = min(end, offset)
        for index in range(start, stop):
            markup.append(text[index])
            offsets.append(index)
    offsets.append(offset)  # so the machine can address the position itself
    return "".join(markup), offsets


def context_at(text, offset, templates=None):
    """What is at `offset`, or `None` when it is not inside an `html(t"…")`."""
    template = template_at(text, offset, templates)
    if template is None or not template.is_html:
        return None
    markup, offsets = _markup_prefix(text, template, offset)
    if markup is None:
        return Context("interp", template)
    state = "text"
    stack = []
    tag = ""
    attr = ""
    quote = ""
    token_start = len(markup)  # where the token under the cursor began
    i = 0
    n = len(markup)
    while i < n:
        char = markup[i]
        if state == "text":
            if markup.startswith("<!--", i):
                state = "comment"
                i += 4
                continue
            if markup.startswith("</", i):
                state = "endtag"
                i += 2
                token_start = i
                tag = ""
                continue
            if char == "<":
                state = "tag"
                i += 1
                token_start = i
                tag = ""
                continue
            i += 1
            continue
        if state == "comment":
            if markup.startswith("-->", i):
                state = "text"
                i += 3
                continue
            i += 1
            continue
        if state == "tag":
            if char in " \t\r\n":
                tag = markup[token_start:i]
                state = "in_tag"
                i += 1
                continue
            if char == ">":
                tag = markup[token_start:i]
                if tag and tag not in VOID:
                    stack.append(tag)
                state = "text"
                i += 1
                continue
            if char == "/":
                tag = markup[token_start:i]
                state = "in_tag"
                i += 1
                continue
            i += 1
            continue
        if state == "endtag":
            if char == ">":
                name = markup[token_start:i].strip()
                while stack:
                    if stack.pop() == name:
                        break
                state = "text"
                i += 1
                continue
            i += 1
            continue
        if state == "in_tag":
            if char in " \t\r\n/":
                i += 1
                continue
            if char == ">":
                if tag and tag not in VOID and not markup[:i].rstrip().endswith("/"):
                    stack.append(tag)
                state = "text"
                i += 1
                continue
            state = "attr"
            token_start = i
            continue
        if state == "attr":
            if char == "=":
                attr = markup[token_start:i]
                state = "value_start"
                i += 1
                continue
            if char in " \t\r\n":
                state = "in_tag"
                i += 1
                continue
            if char in ">/":
                state = "in_tag"
                continue
            i += 1
            continue
        if state == "value_start":
            if char in "\"'":
                quote = char
                state = "value"
                i += 1
                token_start = i
                continue
            if char in " \t\r\n":
                state = "in_tag"
                i += 1
                continue
            quote = ""
            state = "value"
            token_start = i
            continue
        if state == "value":
            if quote and char == quote:
                state = "in_tag"
                quote = ""
                i += 1
                continue
            if not quote and char in " \t\r\n":
                state = "in_tag"
                i += 1
                continue
            if not quote and char == ">":
                state = "in_tag"
                continue
            i += 1
            continue
    kind = {
        "text": "text",
        "comment": "comment",
        "tag": "tag",
        "endtag": "endtag",
        "in_tag": "attr",
        "attr": "attr",
        "value_start": "value",
        "value": "value",
    }[state]
    if kind in ("tag", "endtag", "attr", "value"):
        word = markup[token_start:] if token_start <= n else ""
    else:
        word = ""
    if state == "in_tag":  # a fresh attribute starts here
        token_start = n
        word = ""
    if state == "value_start":
        token_start = n
        word = ""
        quote = ""
    if state == "tag":
        tag = word
    if kind == "endtag" and stack:
        tag = stack[-1]  # what a `</` most likely wants to close
    if kind != "value":
        attr = ""  # the last attribute seen is noise anywhere else
    start_offset = offsets[token_start] if token_start < len(offsets) else offset
    return Context(kind, template, tag=tag, attr=attr, word=word, word_start=start_offset, quote=quote, stack=stack)


# Token kinds `emit_tokens` produces, in the order the semantic-token legend declares them.
TOKEN_KINDS = ("tag", "attr", "prefixed", "value", "comment", "punct", "hole")


def emit_tokens(text, template):
    """Every markup span in one template, as `(kind, start, end)` in document offsets.

    This is the same grammar `context_at` replays, read forwards instead of cut at a cursor.
    They are kept apart on purpose: one answers "what is everything here", which a token
    emitter can do in a single pass, and the other "what is at this one position while the
    text around it is still half-written", which needs the state at a boundary rather than
    the spans either side of it. `tests/test_lsp.py` asserts they agree.

    Interpolations collapse to one character before tokenising, so an attribute that follows
    a hole inside the same tag is still seen; the spans are mapped back afterwards, and a
    token that runs across a hole — `class="row {cls} wide"` — comes back split around it.
    """
    if not template.is_html:
        return []
    markup = []
    offsets = []
    holes = []
    for kind, start, end in template.parts:
        if kind == "hole":
            markup.append("\x00")
            offsets.append((start, end))
            holes.append(True)
            continue
        for index in range(start, end):
            markup.append(text[index])
            offsets.append((index, index + 1))
            holes.append(False)
    return _map_back(_tokens_in_chunk("".join(markup)), offsets, holes)


def _map_back(spans, offsets, holes):
    """Markup spans as document spans, splitting any that run across an interpolation."""
    found = []
    for kind, start, end in spans:
        run_start = None
        for index in range(start, min(end, len(offsets))):
            if holes[index]:
                if run_start is not None:
                    found.append((kind, offsets[run_start][0], offsets[index - 1][1]))
                    run_start = None
                found.append(("hole", offsets[index][0], offsets[index][1]))
                continue
            if run_start is None:
                run_start = index
        if run_start is not None:
            found.append((kind, offsets[run_start][0], offsets[min(end, len(offsets)) - 1][1]))
    return found


def _tokens_in_chunk(text):
    """Markup spans over a whole reconstructed template body."""
    found = []
    i = 0
    end = len(text)
    while i < end:
        lt = text.find("<", i, end)
        if lt < 0:
            break
        if text.startswith("<!--", lt):
            close = text.find("-->", lt, end)
            stop = end if close < 0 else close + 3
            found.append(("comment", lt, stop))
            i = stop
            continue
        i = lt + 1
        closing = i < end and text[i] == "/"
        if closing:
            i += 1
        found.append(("punct", lt, i))
        name_start = i
        while i < end and text[i] not in " \t\r\n/>":
            i += 1
        if i > name_start:
            found.append(("tag", name_start, i))
        while i < end:
            char = text[i]
            if char == ">":
                found.append(("punct", i, i + 1))
                i += 1
                break
            if char == "/":
                found.append(("punct", i, i + 1))
                i += 1
                continue
            if char in " \t\r\n":
                i += 1
                continue
            attr_start = i
            while i < end and text[i] not in " \t\r\n=/>":
                i += 1
            name = text[attr_start:i]
            found.append(("prefixed" if _is_prefixed(name) else "attr", attr_start, i))
            if i < end and text[i] == "=":
                found.append(("punct", i, i + 1))
                i += 1
                if i < end and text[i] in "\"'":
                    quote = text[i]
                    close = text.find(quote, i + 1, end)
                    stop = end if close < 0 else close + 1
                    found.append(("value", i, stop))
                    i = stop
                else:
                    value_start = i
                    while i < end and text[i] not in " \t\r\n>":
                        i += 1
                    if i > value_start:
                        found.append(("value", value_start, i))
    return found


_PREFIX_SPELLINGS = (
    "on:", "on_", "oncapture:", "oncapture_", "prop:", "prop_", "class:", "class_",
    "style:", "style_", "bind:", "bind_", "attr:",
)  # fmt: skip


def _is_prefixed(name):
    """Is this one of frontage's own attribute spellings rather than plain HTML?"""
    if name == "ref":
        return True
    for prefix in _PREFIX_SPELLINGS:
        if name.startswith(prefix) and len(name) > len(prefix):
            return True
    return False
