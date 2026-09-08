"""The browser renderer: the `Renderer` seam over the real DOM, through the runtime's op stream.

Every method here is a bridge crossing from Python to JavaScript. Events are delegated: one
document listener per bubbling event type, dispatching to the handler registered for the
element (found by a `data-fr` id walking up from the target), so a page has one JavaScript
proxy per event type instead of one per handler.
"""

from .reactive import get_owner, spawn
from .renderer import Renderer
from .runtime import create_proxy, document, in_browser, to_js, warn, window

try:  # the runtime's native template path (rust/vm/src/view.rs)
    import _view
except ImportError:
    _view = None


class _NoDom:
    """Stands in for `_dom` outside the runtime (CPython imports this module for `Hydration`)."""

    available = False

    def __getattr__(self, name):
        raise AttributeError(f"_dom.{name}: this runtime has no DOM op stream")


try:  # the runtime's DOM op stream (rust/vm/src/dom.rs)
    import _dom
except ImportError:
    _dom = _NoDom()

__all__ = ["DomRenderer", "Hydration", "is_node", "resolve"]

# Events that bubble, so one listener on the document can serve every element.
DELEGATED = {
    "beforeinput",
    "change",
    "click",
    "contextmenu",
    "dblclick",
    "focusin",
    "focusout",
    "input",
    "keydown",
    "keypress",
    "keyup",
    "mousedown",
    "mousemove",
    "mouseout",
    "mouseover",
    "mouseup",
    "pointerdown",
    "pointermove",
    "pointerout",
    "pointerover",
    "pointerup",
    "submit",
    "touchend",
    "touchmove",
    "touchstart",
}

# DOM properties that must be set as properties, not attributes, to take effect after load.
PROPERTIES = {"value", "checked", "selected", "textContent", "innerHTML", "muted", "volume", "currentTime"}
BOOLEAN_ATTRS = {
    "disabled",
    "hidden",
    "readonly",
    "required",
    "open",
    "multiple",
    "autofocus",
    "autoplay",
    "controls",
    "loop",
    "novalidate",
    "reversed",
    "selected",
    "checked",
}


def is_node(value):
    """True for a DOM node. JavaScript `null` reaches Python as `None` on MicroPython but as a
    `JsNull` proxy on Pyodide, so `is None` alone is not a null check here."""
    return value is not None and getattr(value, "nodeType", None) is not None


def resolve(target):
    """A node from a CSS selector, or the node itself."""
    if isinstance(target, str):
        node = document.querySelector(target)
        if not is_node(node):
            raise LookupError(f"mount: nothing matches {target!r}")
        return node
    return target


class Hydration:
    """The cursor `mount(hydrate=True)` walks over prerendered HTML.

    Each hole positions the cursor at its own fence (`push`), adopts nodes in document order
    (`claim_*`), and takes back what it claimed (`pop`) for `finish`, which removes the fence
    and any node the server wrote that nothing adopted. A claim that does not match what the
    cursor is on counts as a mismatch: the caller creates the node instead, and the sweep
    drops the server's one. One warning names the count at the end.
    """

    def __init__(self, data=None):
        # The page's data block: a list is the resources' values in creation order (pages
        # prerendered before 0.7.0); a dict also carries the async memos' values by ordinal.
        if isinstance(data, dict):
            self.data = data.get("resources") or None
            self.memos = data.get("memos") or None
        else:
            self.data = data
            self.memos = None
        self.cursor = None
        self.active = False
        self.claimed = []
        self.stack = []
        self.mismatches = 0
        self.details = []  # one line per mismatch, for `frontage.debug`

    def _note(self, message):
        self.mismatches += 1
        self.details.append(message)

    @staticmethod
    def describe(node):
        """A node in a few characters: `<li class="x">`, `text 'Ada'`, `<!--h-->`."""
        if not is_node(node):
            return "the end of the content"
        kind = node.nodeType
        if kind == 3:
            text = str(node.data)
            return f"text {text[:40]!r}" + ("…" if len(text) > 40 else "")
        if kind == 8:
            return f"<!--{str(node.data)[:20]}-->"
        if kind == 1:
            html = str(node.outerHTML)
            end = html.find(">")
            return html[: end + 1] if 0 < end < 80 else html[:80]
        return f"node type {kind}"

    def push(self, node):
        self.stack.append((self.cursor, self.active, self.claimed))
        self.cursor = node
        self.active = node is not None
        self.claimed = []

    def pop(self):
        claimed = self.claimed
        self.cursor, self.active, self.claimed = self.stack.pop()
        return claimed

    def _advance(self, node):
        following = node.nextSibling
        self.cursor = following if is_node(following) else None

    def claim_text(self, text):
        node = self.cursor
        if is_node(node) and node.nodeType == 3:  # ty: ignore[unresolved-attribute]
            self._advance(node)
            if str(node.data) != text:  # ty: ignore[unresolved-attribute]
                node.data = text  # ty: ignore[invalid-assignment]
            self.claimed.append(node)
            return node
        return None  # empty text renders nothing on the server; no mismatch

    def claim_element(self, tag):
        node = self.cursor
        if is_node(node) and node.nodeType == 1 and str(node.tagName).lower() == tag:  # ty: ignore[unresolved-attribute]
            self._advance(node)
            self.claimed.append(node)
            return node
        self._note(f"expected <{tag}>, found {self.describe(node)}")
        return None

    def claim_hole(self):
        """A floating hole's marker, when the cursor is on its fence; the whole span is
        claimed, and the hole itself adopts its content from the fence later."""
        start = self.cursor
        if not (is_node(start) and start.nodeType == 8 and str(start.data) == "["):  # ty: ignore[unresolved-attribute]
            return None
        depth = 0
        node = start.nextSibling  # ty: ignore[unresolved-attribute]
        while is_node(node):
            if node.nodeType == 8:
                data = str(node.data)
                if data == "[":
                    depth += 1
                elif data == "h":
                    if depth == 0:
                        self._advance(node)
                        self.claimed.append(("span", start, node))
                        return node
                    depth -= 1
            node = node.nextSibling
        return None

    @staticmethod
    def start_of(marker):
        """The `<!--[-->` fence that opens the content ending at `marker`, or None."""
        depth = 0
        node = marker.previousSibling
        while is_node(node):
            if node.nodeType == 8:
                data = str(node.data)
                if data == "h":
                    depth += 1
                elif data == "[":
                    if depth == 0:
                        return node
                    depth -= 1
            node = node.previousSibling
        return None

    def finish(self, parent, start, marker, claimed, current):
        keep = [c for c in claimed if not isinstance(c, tuple)] + list(current)
        spans = [c for c in claimed if isinstance(c, tuple)]
        node = start.nextSibling
        while is_node(node) and not node.isSameNode(marker):
            following = node.nextSibling
            span = None
            for s in spans:
                if node.isSameNode(s[1]):
                    span = s
                    break
            if span is not None:
                following = span[2].nextSibling
            elif not any(node.isSameNode(k) for k in keep):
                self._note(f"dropped {self.describe(node)}: nothing in the view adopted it")
                parent.removeChild(node)
            node = following
        parent.removeChild(start)

    def find_holes(self, root, n_elements=0, n_markers=0):
        """`find_holes` for an adopted element: only this template's own `data-fr-h` elements
        and markers. Everything between a `[` fence and its `h` is a hole's content, whose
        elements and markers belong to the templates built inside it, so it is skipped."""
        elements = {}
        markers = []

        def walk(element):
            if element.hasAttribute("data-fr-h"):
                elements[int(str(element.getAttribute("data-fr-h")))] = element
            depth = 0
            node = element.firstChild
            while is_node(node):
                kind = node.nodeType
                if kind == 8:
                    data = str(node.data)
                    if data == "[":
                        depth += 1
                    elif data == "h":
                        if depth > 0:
                            depth -= 1
                            if depth == 0:
                                markers.append(node)
                        else:
                            markers.append(node)
                elif kind == 1 and depth == 0:
                    walk(node)
                node = node.nextSibling

        walk(root)
        return [elements[i] for i in sorted(elements)], markers

    def root_marker(self, parent):
        last = parent.lastChild
        if is_node(last) and last.nodeType == 8 and str(last.data) == "h":
            return last
        return None


class _ProxyRenderer(Renderer):
    """The DOM through JavaScript proxies, one crossing per operation: what hydration walks
    (its cursor moves over real nodes), and the base the streaming renderer falls back to for
    a node that came from JavaScript."""

    def __init__(self):
        if not in_browser:
            raise RuntimeError("DomRenderer needs a browser; use HtmlRenderer on the server")
        self._handlers = {}  # element id -> {event: handler}
        self._next_id = 1
        self._delegated = set()
        self._proxies = {}
        self.hydration = None

    # -- hydration ----------------------------------------------------------------------------

    def hydratable(self, node):
        return getattr(node, "nodeType", 0) == 1 and bool(node.hasAttribute("data-fr-hydrate"))

    def begin_hydration(self, node):
        import json

        node.removeAttribute("data-fr-hydrate")
        data = None
        target_id = str(node.id or "")
        if target_id:
            script = document.querySelector(f'script[data-fr-data="{target_id}"]')
            if is_node(script):
                data = json.loads(str(script.textContent))
                script.remove()
        self.hydration = Hydration(data)
        return self.hydration

    def end_hydration(self):
        import sys

        hyd, self.hydration = self.hydration, None
        debug = sys.modules.get("frontage.debug")
        if debug is not None:
            debug.last_hydration = hyd  # ty: ignore[unresolved-attribute]
        if hyd is not None and hyd.mismatches:
            warn(f"hydration: {hyd.mismatches} node(s) differed from the prerendered page and were rebuilt")
            if debug is not None:
                for line in hyd.details:
                    warn(f"hydration: {line}")
            else:
                warn("hydration: `import frontage.debug` in the app to see each mismatch")
        try:  # the prerendered page queues early clicks and input for the app to replay
            replay = getattr(window, "__frontage_replay", None)
            if replay is not None:
                replay()
        except Exception as exc:
            warn(f"hydration: replaying early events failed: {exc}")

    def previous_sibling(self, node):
        previous = node.previousSibling
        return previous if is_node(previous) else None

    # -- nodes --------------------------------------------------------------------------------

    def create_element(self, tag):
        return document.createElement(tag)

    def create_text(self, text):
        return document.createTextNode(str(text))

    def replace_text(self, node, text):
        node.data = str(text)

    def set_property(self, node, name, value):
        if name in PROPERTIES:
            setattr(node, name, "" if value is None else value)
        elif name in BOOLEAN_ATTRS or value is True or value is False:
            if value:
                node.setAttribute(name, "")
            else:
                node.removeAttribute(name)
        elif value is None:
            node.removeAttribute(name)
        else:
            node.setAttribute(name, str(value))

    def insert_node(self, parent, node, anchor=None):
        if anchor is None:
            parent.appendChild(node)
        else:
            parent.insertBefore(node, anchor)

    def remove_node(self, parent, node):
        parent.removeChild(node)

    def is_text(self, node):
        return node.nodeType == 3

    def parent(self, node):
        parent = node.parentNode
        return parent if is_node(parent) else None

    def is_connected(self, node):
        return bool(getattr(node, "isConnected", True))

    def first_child(self, node):
        child = node.firstChild
        return child if is_node(child) else None

    def next_sibling(self, node):
        sibling = node.nextSibling
        return sibling if is_node(sibling) else None

    def toggle_class(self, node, name, on):
        node.classList.toggle(name, bool(on))

    def set_style(self, node, prop, value):
        if value is None or value is False:
            node.style.removeProperty(prop)
        else:
            node.style.setProperty(prop, str(value))

    def replace_node(self, parent, new, old):
        parent.replaceChild(new, old)

    def dispatch_event(self, node, name, detail=None):
        options = {"bubbles": True, "cancelable": True}
        if detail is not None:
            options["detail"] = detail
        node.dispatchEvent(window.CustomEvent.new(name, to_js(options)))

    # -- templates ----------------------------------------------------------------------------

    _templates = {}

    def clone_template(self, html):
        template = DomRenderer._templates.get(html)
        if template is None:
            template = document.createElement("template")
            template.innerHTML = html
            DomRenderer._templates[html] = template
        return template.content.firstChild.cloneNode(True)

    def find_holes(self, root, n_elements=0, n_markers=0):
        elements = []
        if root.hasAttribute("data-fr-h"):
            elements.append(root)
        found = root.querySelectorAll("[data-fr-h]")
        for i in range(found.length):
            elements.append(found.item(i))
        # Elements come back in document order; the template numbers them in that order too.
        markers = []
        walker = document.createTreeWalker(root, 128)  # NodeFilter.SHOW_COMMENT
        node = walker.nextNode()
        while is_node(node):
            if node.data == "h":
                markers.append(node)
            node = walker.nextNode()
        return elements, markers

    # -- events -------------------------------------------------------------------------------

    def add_listener(self, node, event, handler, capture=False):
        if event in DELEGATED and not capture:
            return self._delegate(node, event, handler)
        proxy = create_proxy(handler)
        node.addEventListener(event, proxy, bool(capture))

        def remove():
            node.removeEventListener(event, proxy, bool(capture))
            destroy = getattr(proxy, "destroy", None)
            if destroy is not None:
                destroy()

        return remove

    def _delegate(self, node, event, handler):
        fid = node.getAttribute("data-fr")
        if not fid:
            fid = str(self._next_id)
            self._next_id += 1
            node.setAttribute("data-fr", fid)
        self._handlers.setdefault(fid, {})[event] = handler
        if event not in self._delegated:
            self._delegated.add(event)
            proxy = create_proxy(self._make_dispatcher(event))
            self._proxies[event] = proxy
            document.addEventListener(event, proxy)

        def remove():
            table = self._handlers.get(fid)
            if table is not None:
                table.pop(event, None)
                if not table:
                    self._handlers.pop(fid, None)

        return remove

    def teardown(self):
        """Give the document back what this renderer put on it.

        Disposing a mount's owner removes every listener bound to a node, but not these: one
        dispatcher per delegated event type lives on `document`, shared by every element the
        renderer handles, so no owner holds it. That went unnoticed while a page mounted once
        and then ended. A dev swap mounts again, and would leave twenty-four of them behind
        each time, every one still holding the old handler table.
        """
        for event in list(self._proxies):
            proxy = self._proxies.pop(event)
            document.removeEventListener(event, proxy)
            destroy = getattr(proxy, "destroy", None)
            if destroy is not None:
                destroy()
        # Cleared in place, not rebound: `_make_dispatcher` closes over this dict, so a new
        # one would leave any surviving dispatcher reading a table nothing writes to.
        self._delegated.clear()
        self._handlers.clear()

    def _make_dispatcher(self, event):
        handlers = self._handlers

        def dispatch(ev):
            node = ev.target
            while is_node(node) and node.nodeType == 1:
                fid = node.getAttribute("data-fr")
                if fid:
                    handler = handlers.get(fid, {}).get(event)
                    if handler is not None and not getattr(node, "disabled", False):
                        _set_current_target(ev, node)
                        handler(ev)
                        if getattr(ev, "cancelBubble", False):
                            return
                node = node.parentNode

        return dispatch


def _set_current_target(ev, node):
    """Make `ev.currentTarget` the element whose handler runs, as a direct listener would."""
    try:
        window.Object.defineProperty(ev, "currentTarget", to_js({"configurable": True, "value": node}))
    except Exception:
        pass


class StreamRenderer(_ProxyRenderer):
    """The renderer a page uses, over the runtime's op stream: a node is an integer id in the glue's array,
    every operation is appended to a buffer the glue executes in one crossing (at the end of
    a batch of effects, before a question about the document, when control returns to
    JavaScript), and delegated events are walked in JavaScript, which calls one Python
    dispatcher with the id. A negative id `-m` stands for the parent of node `m`, so a hole
    never asks for its parent. Nodes that come from JavaScript (the mount target, adopted
    nodes while hydrating) are registered on first sight and used by id from then on."""

    _template_ids = {}

    def __init__(self):
        super().__init__()
        self._dispatcher = None

    @staticmethod
    def _id(node):
        return node if type(node) is int else _dom.id_of(node)

    def real_node(self, node):
        return _dom.node(node) if type(node) is int else node

    # -- hydration keeps the proxy path for what it walks; the nodes it hands back are ids ----

    def hydratable(self, node):
        return super().hydratable(self.real_node(node))

    def begin_hydration(self, node):
        return super().begin_hydration(self.real_node(node))

    # A node hydration is walking is a proxy, and the cursor must stay one: the walk answers
    # with the proxy path for a proxy and with ids for ids. A proxy reads the document as it
    # is, so what is pending in the stream goes out first.

    def previous_sibling(self, node):
        if type(node) is not int:
            _dom.flush()
            return super().previous_sibling(node)
        sibling = _dom.query(3, node)
        return sibling or None

    # -- nodes --------------------------------------------------------------------------------

    def create_element(self, tag):
        return _dom.create_element(tag)

    def create_text(self, text):
        return _dom.create_text(str(text))

    def create_marker(self, text="h"):
        return _dom.create_comment(text)

    def replace_text(self, node, text):
        _dom.set_text(self._id(node), str(text))

    def set_property(self, node, name, value):
        node = self._id(node)
        if name in PROPERTIES:
            if value is True or value is False:
                _dom.set_prop_bool(node, name, value)
            else:
                _dom.set_prop(node, name, "" if value is None else str(value))
        elif name in BOOLEAN_ATTRS or value is True or value is False:
            if value:
                _dom.set_attr(node, name, "")
            else:
                _dom.remove_attr(node, name)
        elif value is None:
            _dom.remove_attr(node, name)
        else:
            _dom.set_attr(node, name, str(value))

    def insert_node(self, parent, node, anchor=None):
        if anchor is None:
            _dom.append(self._id(parent), self._id(node))
        else:
            _dom.insert(self._id(parent), self._id(node), self._id(anchor))

    def remove_node(self, parent, node):
        _dom.remove(self._id(parent), self._id(node))

    def is_text(self, node):
        if type(node) is not int:
            _dom.flush()
            return super().is_text(node)
        return _dom.query(5, node) == 3

    def hole_parent(self, marker):
        return -self._id(marker)  # "the parent of node": answered without asking

    def parent(self, node):
        if type(node) is not int:
            _dom.flush()
            return super().parent(node)
        parent = _dom.query(0, node)
        return parent or None

    def is_connected(self, node):
        if type(node) is not int:
            _dom.flush()
            return super().is_connected(node)
        return bool(_dom.query(6, node))

    def first_child(self, node):
        if type(node) is not int:
            _dom.flush()
            return super().first_child(node)
        child = _dom.query(1, node)
        return child or None

    def next_sibling(self, node):
        if type(node) is not int:
            _dom.flush()
            return super().next_sibling(node)
        sibling = _dom.query(2, node)
        return sibling or None

    def mark_root(self, node):
        pass

    def toggle_class(self, node, name, on):
        _dom.toggle_class(self._id(node), name, bool(on))

    def set_style(self, node, prop, value):
        if value is None or value is False:
            _dom.remove_style(self._id(node), prop)
        else:
            _dom.set_style(self._id(node), prop, str(value))

    def replace_node(self, parent, new, old):
        _dom.replace(self._id(parent), self._id(new), self._id(old))

    def dispatch_event(self, node, name, detail=None):
        super().dispatch_event(self.real_node(node), name, detail)

    # -- templates ----------------------------------------------------------------------------

    def clone_template(self, html):
        tid = StreamRenderer._template_ids.get(html)
        if tid is None:
            tid = _dom.define_template(html)
            StreamRenderer._template_ids[html] = tid
        return _dom.clone(tid)

    def find_holes(self, root, n_elements=0, n_markers=0):
        if not (n_elements or n_markers):
            return [], []
        first = _dom.find_holes(self._id(root), n_elements, n_markers, self.hydration_markers)
        elements = [first + i for i in range(n_elements)]
        markers = [first + n_elements + i for i in range(n_markers)]
        return elements, markers

    # -- events -------------------------------------------------------------------------------

    def add_listener(self, node, event, handler, capture=False):
        if event in DELEGATED and not capture:
            return self._delegate(node, event, handler)
        return super().add_listener(self.real_node(node), event, handler, capture)

    def _delegate(self, node, event, handler):
        node = self._id(node)
        if self._dispatcher is None:
            self._dispatcher = create_proxy(self._dispatch)
            _dom.set_dispatcher(self._dispatcher)
        self._handlers[node, event] = (handler, get_owner())
        _dom.listen(node, event)

        def remove():
            if self._handlers.pop((node, event), None) is not None:
                _dom.unlisten(node, event)

        return remove

    def _dispatch(self, node, event, ev):
        entry = self._handlers.get((node, event))
        if entry is not None:
            handler, owner = entry
            result = handler(ev)
            # An `async def` handler returns a coroutine: a task owned where it was bound.
            if hasattr(result, "send") and hasattr(result, "throw"):
                spawn(result, owner)

    def teardown(self):
        super().teardown()
        self._handlers.clear()
        _dom.teardown()


DomRenderer = StreamRenderer

if _dom.available:
    if _view is not None and _view.available:
        # The native template path needs the view's classes and its Python fallbacks.
        from . import view as _view_module

        _view.setup(
            Element=_view_module.Element,
            Text=_view_module.Text,
            Mounted=_view_module.Mounted,
            StreamRenderer=StreamRenderer,
            module=_view_module,
            build_template=_view_module._build_template,
            apply_attr=_view_module._apply_attr,
            listen=_view_module._listen,
            build_nodes=_view_module._build_nodes,
        )
