"""Completion, hover, go-to-definition and semantic tokens.

Every one of these starts from `scanner.context_at` and is then a lookup in `data.py`. The
rule they all follow: stay out of Python's territory. Inside `html(t"…")` no other tool
knows anything — the string is opaque to a type checker — so the server answers fully. In
the Python around it, it answers only for frontage's own names, and leaves the rest to
whatever language server the editor already runs.
"""

import ast

from . import data
from .scanner import context_at, emit_tokens, scan_templates

# LSP `CompletionItemKind`.
KIND_TEXT = 1
KIND_METHOD = 2
KIND_FUNCTION = 3
KIND_FIELD = 5
KIND_VALUE = 12
KIND_ENUM = 13
KIND_KEYWORD = 14
KIND_SNIPPET = 15
KIND_PROPERTY = 10
KIND_EVENT = 23
KIND_CLASS = 7

PLAIN, SNIPPET = 1, 2

# The semantic-token legend, declared at initialize and indexed into by number afterwards.
TOKEN_TYPES = ["type", "property", "decorator", "string", "comment", "operator"]
_TOKEN_TYPE_OF = {"tag": 0, "attr": 1, "prefixed": 2, "value": 3, "comment": 4, "punct": 5}

# A handful of CSS properties, enough that `style:` is not a blank prompt.
_CSS = [
    "color", "background", "background_color", "display", "position", "top", "right", "bottom", "left",
    "width", "height", "min_width", "max_width", "min_height", "max_height", "margin", "margin_top",
    "margin_bottom", "padding", "border", "border_radius", "font_size", "font_weight", "font_family",
    "line_height", "text_align", "opacity", "overflow", "flex", "flex_direction", "align_items",
    "justify_content", "gap", "grid_template_columns", "z_index", "cursor", "transform", "transition",
]  # fmt: skip

_ENUMS = {
    ("input", "type"): ["text", "number", "checkbox", "radio", "email", "password", "search", "url", "tel",
                        "date", "time", "datetime-local", "month", "week", "color", "range", "file",
                        "hidden", "submit", "reset", "button"],
    ("button", "type"): ["button", "submit", "reset"],
    ("form", "method"): ["get", "post", "dialog"],
    ("a", "target"): ["_self", "_blank", "_parent", "_top"],
    ("a", "rel"): ["noopener", "noreferrer", "nofollow", "external", "help", "license"],
    ("img", "loading"): ["lazy", "eager"],
    ("iframe", "loading"): ["lazy", "eager"],
    ("img", "decoding"): ["sync", "async", "auto"],
    ("th", "scope"): ["row", "col", "rowgroup", "colgroup"],
    ("link", "rel"): ["stylesheet", "icon", "preload", "manifest", "canonical", "alternate"],
}  # fmt: skip
_ANY_TAG_ENUMS = {"dir": ["ltr", "rtl", "auto"], "spellcheck": ["true", "false"], "draggable": ["true", "false"]}


def _item(label, kind, doc="", insert=None, sort="5", form=PLAIN, detail=""):
    item = {"label": label, "kind": kind, "sortText": sort + label}
    if doc:
        item["documentation"] = {"kind": "markdown", "value": doc}
    if detail:
        item["detail"] = detail
    if insert is not None:
        item["insertText"] = insert
    if form == SNIPPET:
        item["insertTextFormat"] = SNIPPET
    return item


# --- completion ---------------------------------------------------------------------------------


def complete(document, offset):
    """Completion items for a position, or `[]` when the position is not ours to answer."""
    context = context_at(document.text, offset)
    if context is None:
        return []
    if context.kind == "tag":
        return _complete_tag()
    if context.kind == "endtag":
        return _complete_endtag(context)
    if context.kind == "attr":
        return _complete_attribute(context)
    if context.kind == "value":
        return _complete_value(context)
    if context.kind == "interp":
        return _complete_interpolation()
    return []


def _complete_tag():
    found = []
    for tag, doc in data.TAGS.items():
        if tag in data.VOID:
            insert, form = tag, PLAIN
        else:
            # The `<` is already typed; finish the element and put the cursor in the middle.
            insert, form = f"{tag}>$0</{tag}>", SNIPPET
        found.append(_item(tag, KIND_CLASS, doc, insert, sort="3", form=form, detail="element"))
    return found


def _complete_endtag(context):
    found = []
    for depth, tag in enumerate(reversed(context.stack)):
        found.append(_item(tag, KIND_CLASS, data.TAGS.get(tag, ""), f"{tag}>", sort=str(depth), detail="close"))
    return found


def _complete_attribute(context):
    word = context.word
    # Inside a prefix, the useful list is the prefix's own: events, bind targets, CSS.
    for prefix in ("on:", "on_", "oncapture:", "oncapture_"):
        if word.startswith(prefix):
            return [
                _item(prefix + name, KIND_EVENT, f"The `{name}` event, delegated at the mount root.", sort="0")
                for name in data.EVENTS
            ]
    for prefix in ("bind:", "bind_"):
        if word.startswith(prefix):
            return [_item(prefix + name, KIND_FIELD, doc, sort="0") for name, doc in data.BIND_TARGETS.items()]
    for prefix in ("style:", "style_"):
        if word.startswith(prefix):
            sep = prefix[-1]
            return [
                _item(prefix + name.replace("_", "-" if sep == ":" else "_"), KIND_PROPERTY, sort="0") for name in _CSS
            ]

    found = []
    for prefix, kind, doc in data.PREFIXES:
        # A prefix is not a complete attribute; leave the cursor after the colon.
        found.append(_item(prefix, KIND_KEYWORD, doc, f"{prefix}$0", sort="0", form=SNIPPET, detail=kind))
    for name, doc in data.BARE:
        found.append(_item(name, KIND_PROPERTY, doc, sort="1", detail="frontage"))
    specific = data.TAG_ATTRS.get(context.tag, {})
    for name, doc in specific.items():
        found.append(_item(name, KIND_PROPERTY, doc, f'{name}="$0"', sort="2", form=SNIPPET, detail=context.tag))
    for name, doc in data.GLOBAL_ATTRS.items():
        if name in specific:
            continue
        found.append(_item(name, KIND_PROPERTY, doc, f'{name}="$0"', sort="4", form=SNIPPET, detail="global"))
    return found


def _complete_value(context):
    values = _ENUMS.get((context.tag, context.attr)) or _ANY_TAG_ENUMS.get(context.attr)
    if not values:
        return []
    return [_item(value, KIND_ENUM, sort="0") for value in values]


def _complete_interpolation():
    """Frontage's own names, sorted last so a Python language server's completions win.

    This is the one place the two overlap, and the editor merges both lists. Being wrong
    here is worse than being absent, so it offers the flow components — which are what
    someone reaches for inside a template — and nothing that looks like a local variable.
    """
    found = []
    for name, snippet in data.FLOW_SNIPPETS.items():
        found.append(
            _item(name, KIND_SNIPPET, data.API.get(name, ""), snippet, sort="9", form=SNIPPET, detail="frontage")
        )
    for name, doc in data.API.items():
        if name in data.FLOW_SNIPPETS:
            continue
        found.append(_item(name, KIND_FUNCTION, doc, sort="9", detail="frontage"))
    return found


# --- hover --------------------------------------------------------------------------------------


def _markdown(value):
    return {"contents": {"kind": "markdown", "value": value}}


def hover(document, offset):
    context = context_at(document.text, offset)
    if context is None:
        return _hover_python(document, offset)
    if context.kind in ("tag", "endtag"):
        # The word under the cursor, not `context.tag`: that one stops at the cursor, so
        # hovering the middle of `<div>` would look up "d".
        tag = _word_at(document.text, offset, extra="-") or context.tag
        doc = data.TAGS.get(tag)
        if doc:
            void = " Void: it takes no closing tag." if tag in data.VOID else ""
            return _markdown(f"**`<{tag}>`** — {doc}{void}")
        return None
    if context.kind == "value":
        # Inside a value, the useful documentation is the attribute's, not the word's.
        return _hover_attribute(context.attr, context.tag)
    if context.kind == "attr":
        return _hover_attribute(_word_at(document.text, offset, extra=":-_") or context.attr, context.tag)
    return None


def _hover_attribute(name, tag):
    for prefix, kind, doc in data.PREFIXES:
        if name.startswith(prefix) or name.startswith(prefix.replace(":", "_")):
            rest = name[len(prefix) :]
            title = f"**`{name}`** — frontage {kind}"
            if rest:
                title += f" `{rest}`"
            return _markdown(f"{title}\n\n{doc}")
    for bare, doc in data.BARE:
        if name == bare:
            return _markdown(f"**`{name}`** — {doc}")
    doc = data.attributes_for(tag).get(name)
    if doc:
        return _markdown(f"**`{name}`** — {doc}")
    return None


def _hover_python(document, offset):
    """Only frontage's own names, and only in a file that mentions frontage at all."""
    if "frontage" not in document.text:
        return None
    word = _word_at(document.text, offset)
    doc = data.API.get(word)
    if not doc:
        return None
    return _markdown(f"**`{word}`** — {doc}")


_NAME = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"


def _word_at(text, offset, extra=""):
    """The identifier under the cursor, `extra` widening what counts as part of it."""
    alphabet = _NAME + extra
    start = offset
    while start > 0 and text[start - 1] in alphabet:
        start -= 1
    end = offset
    while end < len(text) and text[end] in alphabet:
        end += 1
    return text[start:end]


# --- go to definition ---------------------------------------------------------------------------


def definition(document, offset, read_file=None):
    """Where the name under the cursor is defined.

    The point of this one is the position a Python language server cannot reach: a component
    named inside `{…}`, which as far as any type checker is concerned is a character in a
    string. Same file first, then the module a top-level import names, resolved as a sibling
    file — enough for how an app is laid out, and it declines rather than guessing when the
    import comes from a package it would have to search for.
    """
    context = context_at(document.text, offset)
    if context is None or context.kind != "interp":
        return None
    name = _word_at(document.text, offset)
    if not name:
        return None
    here = _definition_in(document.text, name)
    if here is not None:
        return {"uri": document.uri, "range": document.range_at(*here)}
    return _definition_in_import(document, name, read_file)


def _definition_in(source, name):
    """`(start, end)` offsets of a top-level definition of `name`, or `None`."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    from .rules import _Lines

    lines = _Lines(source)
    for node in tree.body:
        target = None
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            target = node
        elif isinstance(node, ast.Assign):
            for element in node.targets:
                if isinstance(element, ast.Name) and element.id == name:
                    target = element
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            target = node.target
        if target is None:
            continue
        # Point at the name, not the whole body: an editor scrolls to the range it is given.
        line, col = target.lineno, target.col_offset
        if isinstance(target, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = lines.offset(line, col) + (source[lines.offset(line, col) :].find(name))
            return start, start + len(name)
        start = lines.offset(line, col)
        return start, start + len(name)
    return None


def _definition_in_import(document, name, read_file):
    """Follow `from x import name` to a sibling module, when there is one to read."""
    if read_file is None:
        return None
    try:
        tree = ast.parse(document.text)
    except SyntaxError:
        return None
    module = None
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.level in (0, 1):
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    module = node.module
    if not module or module.split(".")[0] == "frontage":
        return None
    for candidate in (module.replace(".", "/") + ".py", module.replace(".", "/") + "/__init__.py"):
        found = read_file(document.uri, candidate)
        if found is None:
            continue
        uri, text = found
        from .documents import Document

        other = Document(uri, text)
        where = _definition_in(text, name)
        if where is not None:
            return {"uri": uri, "range": other.range_at(*where)}
    return None


# --- semantic tokens ----------------------------------------------------------------------------


def semantic_tokens(document):
    """The whole document's markup tokens, in the protocol's delta encoding.

    The TextMate grammar in the VS Code client colours templates before the server starts,
    and keeps working for anyone who never installs it; these refine it, because the server
    knows where a hole ends and a grammar with nested quotes and braces can only guess.
    """
    spans = []
    for template in scan_templates(document.text):
        for kind, start, end in emit_tokens(document.text, template):
            if kind == "hole":  # the braces hold Python; let the editor's own grammar have them
                continue
            spans.append((start, end, _TOKEN_TYPE_OF[kind]))
    spans.sort()
    result = []
    last_line = 0
    last_char = 0
    for start, end, token_type in spans:
        position = document.position_at(start)
        line, char = position["line"], position["character"]
        if line != last_line:
            last_char = 0
        length = (
            document.position_at(end)["character"] - char if line == document.position_at(end)["line"] else end - start
        )
        result += [line - last_line, char - last_char, max(1, length), token_type, 0]
        last_line, last_char = line, char
    return {"data": result}
