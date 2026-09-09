"""Content as data: a directory of Markdown, JSON or YAML, checked by a schema.

A **collection** is a directory of files whose front matter is a `frontage.schema` record.
Everything here runs on CPython at build time and **none of it ships**: a page that lists
posts is a plain function over `entries()`, rendered once.

    from frontage.content import collection
    from frontage.schema import iso_date, record, text

    Post = record(("title", text(min=1)), ("date", iso_date()), ("summary", text(), None))
    posts = collection("posts", Post)              # content/posts/*.md

    for post in posts.entries():                   # newest first when the schema has a date
        post.slug, post.data["title"], post.html()

A `.md` file is front matter between `---` fences and a Markdown body; a `.json` or `.yaml`
file is data with no body. The slug is the file name, so `content/posts/hello-world.md` is
`hello-world`. Front matter that does not match the schema **fails the build**, naming the
file and the field:

    content/posts/draft.md: date: not an ISO date; title: too short

Markdown is rendered here, once, by markdown-it-py, and a `:::` container becomes a `<div>`
of that class — with one exception, which is the point of doing this in Python at all:

    ::: island comments when="visible" post="hello"
    :::

That is an `island` (`frontage.island`), placed in the prose where it stands. `Entry.view()`
is the entry as a view with its islands in it; `Entry.html()` is the HTML with the islands
left as they were written, for a page that only wants a string.

This module needs `markdown-it-py`, `mdit-py-plugins` and `PyYAML`, which are the `content`
extra: `pip install "frontage[content]"`, or `uvx --from "frontage[content]" frontage site`.
A Markdown renderer is not a thing to vendor, and no page ever downloads one.
"""

import json
import re
from pathlib import Path

from ..runtime import prerender

__all__ = ["Collection", "ContentError", "Entry", "collection", "jsonable", "markdown", "split_front_matter", "view_of"]

#: What a `.md` file's front matter is fenced by, and what a body is separated from it by.
FENCE = "---"

#: The extensions a collection reads, and whether the file is all data or data plus a body.
SUFFIXES = (".md", ".markdown", ".json", ".yaml", ".yml")


class ContentError(Exception):
    """A file that cannot be read as content: bad front matter, a schema that says no."""


def _missing(package, extra="content"):
    return ImportError(
        f"frontage.content needs {package}, which is the `{extra}` extra: "
        f'pip install "frontage[{extra}]" (or uvx --from "frontage[{extra}]" frontage …)'
    )


def _yaml():
    try:
        import yaml
    except ImportError:
        raise _missing("PyYAML") from None
    return yaml


# --- reading a file -------------------------------------------------------------------------


def split_front_matter(text):
    """`(data_text, body)` for a `---`-fenced document; `("", text)` when there is no fence.

    The opening fence has to be the first line: a horizontal rule further down a document is
    three dashes too, and a reader who wrote one should not have half their post eaten.
    """
    if not text.startswith(FENCE):
        return "", text
    lines = text.split("\n")
    if lines[0].strip() != FENCE:
        return "", text
    for i in range(1, len(lines)):
        if lines[i].strip() == FENCE:
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :]).lstrip("\n")
    raise ContentError("the front matter opens with --- and is never closed")


def read(path):
    """`(data, body)` for one content file, before any schema has looked at it."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            return json.loads(text), ""
        if suffix in (".yaml", ".yml"):
            return jsonable(_yaml().safe_load(text) or {}), ""
        front, body = split_front_matter(text)
        data = _yaml().safe_load(front) if front.strip() else {}
        return jsonable(data or {}), body
    except ContentError:
        raise
    except Exception as exc:
        raise ContentError(f"{path}: {exc}") from None


def jsonable(value, where=""):
    """`value` with YAML's dates and times as ISO strings, and anything else JSON rejects
    reported by the field it sits in.

    Content data is JSON everywhere it goes — through a schema, into an island's props, out
    of an endpoint — and YAML is the one format that quietly hands back something else:
    `date: 2026-09-02` is a `datetime.date`, and a schema written as `iso_date()` (a string,
    because the browser has no `date`) then says "expected a string" about a line that looks
    exactly right.
    """
    import datetime

    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): jsonable(v, f"{where}.{k}" if where else str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v, f"{where}[{i}]") for i, v in enumerate(value)]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ContentError(f"{where or 'the value'}: {type(value).__name__} is not JSON, and content data has to be")


# --- entries and collections -----------------------------------------------------------------


class Entry:
    """One file in a collection: its slug, its checked data, and its body."""

    def __init__(self, path, data, body, collection=None):
        self.path = Path(path)
        self.slug = self.path.stem
        self.data = data
        self.body = body
        self.collection = collection

    def __repr__(self):
        return f"<Entry {self.slug!r} from {self.path}>"

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, default=None):
        return self.data.get(key, default)

    def html(self):
        """The body as HTML, rendered once, here. Islands are left as they were written."""
        return markdown(self.body)

    def view(self):
        """The body as a view — its HTML as elements, with `::: island` blocks as islands.

        A view rather than a string, because an island has to be a node in the tree the
        prerenderer walks: that is what makes a container in prose into a mount with a
        trigger, and what makes it hydrate over its own markup in the browser.
        """
        return view_of(*_render(self.body))


class Collection:
    """A directory of content files, checked by one schema."""

    def __init__(self, name, schema=None, root=None, suffixes=SUFFIXES):
        self.name = name
        self.schema = schema
        self.root = Path(root) if root is not None else content_root() / name
        self.suffixes = tuple(suffixes)
        self._entries = None

    def __repr__(self):
        return f"<Collection {self.name!r} at {self.root}>"

    def __iter__(self):
        return iter(self.entries())

    def __len__(self):
        return len(self.entries())

    def files(self):
        if not self.root.is_dir():
            raise ContentError(f"collection {self.name!r}: {self.root} is not a directory")
        return sorted(p for p in self.root.rglob("*") if p.is_file() and p.suffix.lower() in self.suffixes)

    def entries(self, order=None, reverse=None):
        """Every entry, read and checked once.

        The default order is the one a reader expects and neither is a surprise: newest first
        when every entry has a `date`, and by slug otherwise. `order` is a field name or a
        callable; `reverse` overrides the direction that choice implies.
        """
        if self._entries is None:
            self._entries = [self._entry(path) for path in self.files()]
        found = list(self._entries)
        by_date = order is None and bool(found) and all(e.data.get("date") is not None for e in found)
        if order is None:
            order = "date" if by_date else (lambda entry: entry.slug)
        key = order if callable(order) else (lambda entry: entry.data.get(order))
        if reverse is None:
            reverse = by_date  # newest first, which is what a list of posts means
        return sorted(found, key=key, reverse=reverse)

    def get(self, slug):
        """One entry by slug, with a message that lists the alternatives when it is not there."""
        for entry in self.entries():
            if entry.slug == slug:
                return entry
        known = ", ".join(sorted(e.slug for e in self.entries())) or "nothing"
        raise ContentError(f"collection {self.name!r} has no entry {slug!r} (it has: {known})")

    def _entry(self, path):
        data, body = read(path)
        if self.schema is not None:
            data = self._checked(path, data)
        return Entry(path, data, body, self)

    def _checked(self, path, data):
        """`data` through the schema, or a build error naming the file and every bad field."""
        from ..schema import SchemaError

        schema = self.schema
        if schema is None:
            return data
        try:
            return schema.parse(data)
        except SchemaError as exc:
            problems = "; ".join(f"{path_.lstrip('$.')}: {message}" for path_, message in exc.errors)
            raise ContentError(f"{_relative(path)}: {problems}") from None


def collection(name, schema=None, root=None, suffixes=SUFFIXES):
    """The collection `name`: `content/<name>/` unless `root` says otherwise."""
    return Collection(name, schema, root, suffixes)


def content_root():
    """Where `content/` is: beside the app being rendered, or under the working directory.

    `frontage prerender` records the app's directory, so a page module can say
    `collection("posts")` and mean the app's own content wherever the command was run from.
    """
    app = getattr(prerender, "app", None)
    return (Path(app) if app else Path.cwd()) / "content"


def _relative(path):
    try:
        return Path(path).relative_to(Path.cwd())
    except ValueError:
        return Path(path)


# --- Markdown -------------------------------------------------------------------------------

#: `::: island posts:comments when="visible" post="hello"` → the spec and the keywords. The
#: spec cannot contain `=`, so `::: island when="visible"` is a container with no component
#: rather than one whose component is called `when`.
_ISLAND = re.compile(r"^island\b[ \t]*(?P<spec>[\w.]+(?::[\w.]+)?(?![\w.:=]))?[ \t]*(?P<args>.*)$", re.S)
_KWARG = re.compile(r"""(\w+)\s*=\s*("[^"]*"|'[^']*'|[^\s]+)""")
_PLACEHOLDER = "fr-island:"


def _parser():
    try:
        from markdown_it import MarkdownIt
        from mdit_py_plugins.container import container_plugin
    except ImportError as exc:
        raise _missing(exc.name or "markdown-it-py") from None

    md = MarkdownIt("commonmark", {"html": True, "linkify": False, "typographer": False})
    md.enable("table")
    md.enable("strikethrough")
    # One registration for every container name: `validate` is what decides, and it says yes
    # to anything, so `::: aside`, `:::: task` and `::: island` are all the same rule.
    container_plugin(md, "fr", validate=lambda params, *rest: bool(params.strip()), render=_render_container)
    return md


def _render_container(self, tokens, index, options, env):
    token = tokens[index]
    info = token.info.strip()
    if token.nesting != 1:
        return "</div>\n"
    if info.startswith("island"):
        return ""  # replaced by the island itself; `_render` records where
    name = info.split()[0]
    rest = info[len(name) :].strip()
    label = f' data-args="{_escape(rest)}"' if rest else ""
    return f'<div class="{_escape(name)}"{label}>\n'


def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")


def markdown(text):
    """`text` as HTML. `:::` containers become `<div class="name">`; islands are left out."""
    html, _ = _render(text)
    return html


def _render(text):
    """`(html, islands)`: the body, with `<!--fr-island:N-->` where each island belongs."""
    md = _parser()
    tokens = md.parse(text)
    islands = []
    kept = []
    depth = None
    for token in tokens:
        if token.type == "container_fr_open" and token.info.strip().startswith("island"):
            # The body of an island container is the island's, not the document's: drop it.
            depth = 0
            token.content = ""
            islands.append(_island_spec(token.info.strip()))
            kept.append(_comment(md, f"{_PLACEHOLDER}{len(islands) - 1}"))
            continue
        if depth is not None:
            if token.type == "container_fr_open":
                depth += 1
            elif token.type == "container_fr_close":
                if depth == 0:
                    depth = None
                    continue
                depth -= 1
            continue
        kept.append(token)
    return md.renderer.render(kept, md.options, {}), islands


def _comment(md, text):
    from markdown_it.token import Token

    token = Token("html_block", "", 0)
    token.content = f"<!--{text}-->\n"
    return token


def _island_spec(info):
    """`island posts:comments when="visible" post="hello"` → `(spec, when, props)`."""
    match = _ISLAND.match(info)
    spec = (match.group("spec") if match else None) or ""
    if match is None or not spec:
        raise ContentError(f"::: {info}: an island container names its component, `::: island posts:comments`")
    when, props = "load", {}
    for key, raw in _KWARG.findall(match.group("args") or ""):
        value = raw[1:-1] if raw[:1] in "\"'" else raw
        if raw[:1] not in "\"'":
            try:
                value = json.loads(raw)
            except ValueError:
                pass
        if key == "when":
            when = value
        else:
            props[key] = value
    return spec, when, props


# --- HTML back into a view --------------------------------------------------------------------


def view_of(html, islands=()):
    """Rendered HTML as view nodes, with each `<!--fr-island:N-->` replaced by its island.

    The Markdown becomes a real view tree rather than a blob of HTML, which is what lets an
    island in prose be a mount with a trigger, lets the prerenderer fence it for hydration,
    and lets `frontage check`'s rules apply to it like anything else.
    """
    from html.parser import HTMLParser

    from ..island import island as make_island
    from ..renderer import _VOID
    from ..view import Element, Text

    out = []
    stack = []

    def add(node):
        (stack[-1].children if stack else out).append(node)

    class Builder(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self, convert_charrefs=True)

        def handle_starttag(self, tag, attrs):
            element = Element(tag, {name: (True if value is None else value) for name, value in attrs}, [])
            add(element)
            if tag not in _VOID:
                stack.append(element)

        def handle_startendtag(self, tag, attrs):
            add(Element(tag, {name: (True if value is None else value) for name, value in attrs}, []))

        def handle_endtag(self, tag):
            for i in range(len(stack) - 1, -1, -1):
                if stack[i].tag == tag:
                    del stack[i:]
                    return

        def handle_data(self, data):
            if data:
                add(Text(data))

        def handle_comment(self, data):
            text = data.strip()
            if text.startswith(_PLACEHOLDER):
                spec, when, props = islands[int(text[len(_PLACEHOLDER) :])]
                add(make_island(spec, when=when, **props))

    builder = Builder()
    builder.feed(html)
    builder.close()
    return out
