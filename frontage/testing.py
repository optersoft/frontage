"""Run an app without a browser: mount it, click it, and read what it drew.

A frontage app is ordinary Python, and `HtmlRenderer` is a document made of plain objects,
so a test does not need a browser to answer *did this button change that number*. `App`
mounts a view on one, hands back the nodes it built, and delivers events to the handlers
that are really bound to them:

    from frontage.testing import App

    def test_counter():
        app = App(counter)
        assert app.find(".count").text == "0"
        app.click("button.inc")
        assert app.find(".count").text == "1"

What this does **not** test is the browser: layout, CSS, focus, a component's JavaScript
half, and anything `data-fr-js` loads are all absent here, and a `_browser/index.js` is
never run. That is the price of the speed — these tests are milliseconds — and the reason
`tests/browser/` exists next door. Test the logic here and the page there.

The other boundary worth stating: this renders on **CPython**, and the browser runs
frontage's own runtime, which is a subset (no `typing` at runtime, string annotations, a
smaller standard library). A test that passes here can still fail in the page for a reason
`frontage check` and the browser suite catch, not this one.
"""

import asyncio

from . import aio, reactive
from .renderer import HtmlRenderer
from .view import mount

__all__ = ["App", "Node", "NotFound"]

DEFAULT_TIMEOUT = 3.0


class NotFound(AssertionError):
    """No node matched. An `AssertionError`, because in a test that is what it is."""


class App:
    """A mounted app, and the operations a test performs on one.

    `view` is what `mount` takes: a component, or a `lambda:` that builds the page. It is
    mounted inside a running event loop, so a `Resource` created at the top of the app can
    start its work — and every method below runs on that same loop, which is what lets a
    fetch begun by a click finish during the next call.

    Actions **settle** by default: after a click, the app waits for every `Resource` and
    async `Memo` to stop loading, so the assertion after it sees the finished page. Pass
    `settle=False` to look at the page mid-flight, which is how a `Loading` fallback is
    tested at all.
    """

    def __init__(self, view, timeout=DEFAULT_TIMEOUT, debug=True, fallback=None):
        self.timeout = timeout
        self.renderer = HtmlRenderer()
        self.root = self.renderer.create_element("div")
        self._loop = asyncio.new_event_loop()
        self._disposed = False
        # Append-only registries of what the app created, the same two the prerenderer reads
        # to know when a page has finished loading. `settle` asks them the same question.
        self._resources = aio._begin_prerender()
        self._memos = reactive._begin_prerender()
        self._handle = None
        try:
            self._handle = self._run(lambda: mount(view, self.root, self.renderer, debug=debug, fallback=fallback))
            self.settle()
        except BaseException:
            # A first load that fails or times out must still take the app down, or the
            # tasks it started outlive the test and pytest reports "Task was destroyed"
            # from a later one instead of this one.
            self.dispose()
            raise

    @classmethod
    def from_module(cls, name, selector=None, **options):
        """The app your `frontage build` entry builds — imported, its `mount` caught.

            app = App.from_module("app")

        An entry module ends in `mount(view, "#app")`, and on CPython that call has nowhere
        to draw: it raises rather than guess. So the import happens with the same switch the
        prerenderer uses, which makes `mount` *register* its view instead, and this mounts it
        here. Nothing in the app has to know it is under test — no `if in_browser`, no second
        entry point, no view exported only for the tests.

        `selector` picks one when a page holds several mounts. The module is imported fresh
        every time, so two tests never share the module-level signals of an app.
        """
        import importlib
        import sys

        from .runtime import prerender

        was_active, prerender.active = prerender.active, True
        mounts = prerender.mounts
        prerender.mounts = []
        try:
            sys.modules.pop(name, None)
            importlib.import_module(name)
            found = prerender.mounts
        finally:
            prerender.active = was_active
            prerender.mounts = mounts
        if not found:
            raise AssertionError(f"{name!r} mounted nothing: an entry module ends in mount(view, '#app')")
        if selector is not None:
            found = [m for m in found if m[0] == selector]
            if not found:
                raise AssertionError(f"{name!r} has no mount on {selector!r}")
        elif len(found) > 1:
            targets = ", ".join(repr(m[0]) for m in found)
            raise AssertionError(f"{name!r} has {len(found)} mounts ({targets}): name one with selector=")
        target, view, debug, fallback = found[0]
        options.setdefault("debug", debug)
        options.setdefault("fallback", fallback)
        return cls(view, **options)

    # -- lifetime ---------------------------------------------------------------------------

    def dispose(self):
        """Take the app down: its owner is disposed, so effects stop and tasks are cancelled.

        A test that does not call it leaks a loop and, worse, leaves the module-level
        registries pointing at a dead app; use the `app` fixture in the docs, or a
        `try/finally`.
        """
        if self._disposed:
            return
        try:
            if self._handle is not None:
                self._run(self._handle.dispose)
        finally:
            self._teardown()

    def _teardown(self):
        self._disposed = True
        aio._end_prerender()
        reactive._end_prerender()
        try:
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
        finally:
            self._loop.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.dispose()
        return False

    # -- the loop ---------------------------------------------------------------------------

    def run(self, fn, settle=True):
        """Call `fn()` with the app's loop running, and settle. What a click does, for code
        the page calls itself: `app.run(lambda: chat.ask("hi"))`. Without it a `spawn` has no
        loop to put its task on."""
        value = self._run(fn)
        if settle:
            self.settle()
        return value

    def _run(self, fn):
        """Call `fn` with the loop running, so `spawn` has somewhere to put a task."""

        async def go():
            return fn()

        return self._loop.run_until_complete(go())

    def settle(self, timeout=None):
        """Wait until nothing is loading. Returns the app, so calls chain."""
        self._loop.run_until_complete(self._settle(self.timeout if timeout is None else timeout))
        return self

    async def _settle(self, timeout):
        deadline = self._loop.time() + timeout
        while self._pending():
            if self._loop.time() > deadline:
                names = ", ".join(sorted(self._pending()))
                raise TimeoutError(f"still loading after {timeout}s: {names}")
            await asyncio.sleep(0.001)
        await asyncio.sleep(0)  # let a task that finished on the last poll run its callbacks

    def _pending(self):
        pending = set()
        for i, resource in enumerate(self._resources):
            owner = getattr(resource, "_owner", None)
            if getattr(owner, "_disposed", False):
                continue  # a branch that went away never settles
            if resource.state() in ("pending", "refreshing"):
                pending.add(f"resource #{i}")
        for i, memo in enumerate(self._memos):
            if memo.loading():
                pending.add(f"async memo #{i}")
        for memo in reactive._memo_started or []:
            if memo.loading():
                pending.add("async memo")
        return pending

    # -- reading ----------------------------------------------------------------------------

    @property
    def html(self):
        """Everything the app drew, as HTML."""
        return "".join(child.to_html() for child in self.root.children)

    @property
    def text(self):
        """The app's visible text, whitespace collapsed — what a reader would read."""
        return _text(self.root)

    @property
    def node(self):
        """The app's root as a `Node`. Its children are what the view built."""
        return Node(self, self.root)

    def find(self, selector):
        """The one node matching `selector`, or `NotFound`."""
        return self.node.find(selector)

    def find_all(self, selector):
        return self.node.find_all(selector)

    def query(self, selector):
        """The first match, or None. `find` is what a test usually wants."""
        return self.node.query(selector)

    def get_by_text(self, text, selector=None):
        return self.node.get_by_text(text, selector)

    def get_by_label(self, label):
        """The control a `<label>` names — the one that survives a redesign.

        `frontage.widgets` wraps every control in its label, so this is how a test says
        *the Name field* without knowing it is the third input on the page. A position is
        not an identity: someone adds a field above it and every index moves.
        """
        return self.node.get_by_label(label)

    # -- driving ----------------------------------------------------------------------------

    def click(self, selector, settle=True, **fields):
        return self.find(selector).click(settle=settle, **fields)

    def type(self, selector, text, settle=True):
        return self.find(selector).type(text, settle=settle)

    def check(self, selector, on=True, settle=True):
        return self.find(selector).check(on, settle=settle)

    def select(self, selector, value, settle=True):
        return self.find(selector).select(value, settle=settle)

    def submit(self, selector="form", settle=True):
        return self.find(selector).submit(settle=settle)

    def _fire(self, node, event, settle, **fields):
        if self._disposed:
            raise RuntimeError("the app was disposed")
        self._run(lambda: node.fire(event, **fields))
        if settle:
            self.settle()
        return self


class Node:
    """One element of the rendered app, and what a test does with it."""

    def __init__(self, app, node):
        self._app = app
        self._node = node

    def __repr__(self):
        return f"<Node {self.html[:60]}>"

    # -- reading ----------------------------------------------------------------------------

    @property
    def tag(self):
        return self._node.tag

    @property
    def text(self):
        return _text(self._node)

    @property
    def html(self):
        return self._node.to_html()

    @property
    def attrs(self):
        return dict(self._node.attrs)

    @property
    def classes(self):
        return [c for c in str(self._node.attrs.get("class", "")).split() if c]

    @property
    def value(self):
        """What the control holds. A DOM property, not the attribute — the same distinction
        the browser makes, and the reason a bound input reads back what was typed."""
        return self._node.props.get("value", self._node.attrs.get("value"))

    @property
    def checked(self):
        return bool(self._node.props.get("checked", False))

    @property
    def disabled(self):
        return bool(self._node.props.get("disabled", self._node.attrs.get("disabled", False)))

    def find(self, selector):
        found = self.query(selector)
        if found is None:
            raise NotFound(f"no node matches {selector!r}\n\n{self.html}")
        return found

    def find_all(self, selector):
        matcher = _compile(selector)
        return [Node(self._app, n) for n in _walk(self._node) if matcher(n)]

    def query(self, selector):
        matcher = _compile(selector)
        for node in _walk(self._node):
            if matcher(node):
                return Node(self._app, node)
        return None

    def get_by_text(self, text, selector=None):
        """The innermost element whose text is `text`, optionally narrowed by a selector.

        Innermost, because the root's text contains every string on the page and matching
        the outermost would answer `<div id=app>` for everything.
        """
        matcher = _compile(selector) if selector else (lambda n: True)
        found = [n for n in _walk(self._node) if matcher(n) and _text(n) == text]
        if not found:
            raise NotFound(f"no node has the text {text!r}\n\n{self.html}")
        return Node(self._app, found[-1])

    def get_by_label(self, label):
        for node in _walk(self._node):
            if node.tag != "label":
                continue
            own = "".join(c.text for c in node.children if c.tag is None and not c.comment).strip()
            if own != label:
                continue
            for child in _walk(node):
                if child.tag in ("input", "select", "textarea", "button"):
                    return Node(self._app, child)
            raise NotFound(f"the label {label!r} names nothing: {node.to_html()}")
        raise NotFound(f"no label reads {label!r}\n\n{self.html}")

    # -- driving ----------------------------------------------------------------------------

    def click(self, settle=True, **fields):
        self._app._fire(self._node, "click", settle, **fields)
        return self

    def type(self, text, settle=True):
        """Put `text` in the control and tell the page, exactly as a keystroke does.

        The property first and the event second, in that order, because a `bind_value`
        handler reads `ev.target.value` — set them the other way round and the signal takes
        the previous text.
        """
        self._node.props["value"] = text
        self._app._fire(self._node, "input", settle)
        return self

    def check(self, on=True, settle=True):
        self._node.props["checked"] = bool(on)
        self._app._fire(self._node, "change", settle)
        return self

    def select(self, value, settle=True):
        self._node.props["value"] = value
        self._app._fire(self._node, "change", settle)
        return self

    def submit(self, settle=True):
        self._app._fire(self._node, "submit", settle)
        return self

    def fire(self, event, settle=True, **fields):
        """Any other event, by name: `node.fire("keydown", key="Enter")`."""
        self._app._fire(self._node, event, settle, **fields)
        return self


# --- text and traversal -----------------------------------------------------------------------


def _walk(node):
    """`node` and its descendants, in document order."""
    yield node
    for child in node.children:
        if child.tag is not None:
            yield from _walk(child)


def _text(node):
    parts = []

    def visit(n):
        if n.tag is None:
            if not n.comment:
                parts.append(n.text)
            return
        for child in n.children:
            visit(child)

    visit(node)
    return " ".join("".join(parts).split())


# --- the selector subset ----------------------------------------------------------------------
#
# Tag, `.class`, `#id`, `[attr]`, `[attr=value]`, any of those compounded (`button.inc`), and
# a descendant chain (`form .fr-error`). Not a CSS engine: `>`, `+`, `:nth-child` and the rest
# raise rather than quietly matching something else, because a selector that silently means
# less than it says is a test that passes for the wrong reason.

_UNSUPPORTED = (">", "+", "~", ",", ":", "*")


def _split(selector):
    """The descendant steps of a selector: whitespace separates them, except inside `[…]`,
    where a value may hold a space (`[aria-label=Good answer]`)."""
    parts = []
    current = ""
    depth = 0
    for char in selector:
        if char == "[":
            depth += 1
        elif char == "]":
            if depth == 0:
                raise ValueError(f"{selector!r}: a ']' with no '['")
            depth -= 1
        if char.isspace() and depth == 0:
            if current:
                parts.append(current)
            current = ""
            continue
        current += char
    if depth:
        raise ValueError(f"{selector!r}: an attribute test is not closed")
    if current:
        parts.append(current)
    return parts


def _compile(selector):
    steps = [_step(part) for part in _split(selector)]
    if not steps:
        raise ValueError("empty selector")
    if len(steps) == 1:
        return steps[0]

    def matches(node):
        if not steps[-1](node):
            return False
        remaining = steps[:-1]
        parent = node.parent
        while remaining and parent is not None:
            if remaining[-1](parent):
                remaining = remaining[:-1]
            parent = parent.parent
        return not remaining

    return matches


def _step(part):
    for bad in _UNSUPPORTED:
        if bad in part:
            raise ValueError(
                f"{part!r}: frontage.testing understands a tag, .class, #id, [attr], [attr=value] "
                f"and a descendant chain, and nothing else — {bad!r} is not supported. "
                "Give the element a class or an id and select that."
            )
    tag = None
    classes = []
    node_id = None
    attrs = []
    rest = part
    while rest:
        if rest[0] == "[":
            end = rest.index("]")
            body = rest[1:end]
            rest = rest[end + 1 :]
            if "=" in body:
                name, value = body.split("=", 1)
                attrs.append((name, value.strip("\"'")))
            else:
                attrs.append((body, None))
            continue
        cut = min([i for i in (rest.find(".", 1), rest.find("#", 1), rest.find("[", 1)) if i > 0] or [len(rest)])
        token, rest = rest[:cut], rest[cut:]
        if token.startswith("."):
            classes.append(token[1:])
        elif token.startswith("#"):
            node_id = token[1:]
        elif token:
            tag = token

    def matches(node):
        if node.tag is None:
            return False
        if tag is not None and node.tag != tag:
            return False
        if node_id is not None and node.attrs.get("id") != node_id:
            return False
        if classes:
            have = str(node.attrs.get("class", "")).split()
            if any(c not in have for c in classes):
                return False
        for name, value in attrs:
            if name not in node.attrs and name not in node.props:
                return False
            if value is not None and str(node.attrs.get(name, node.props.get(name))) != value:
                return False
        return True

    return matches
