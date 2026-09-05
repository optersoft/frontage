"""The browser renderer: the `Renderer` seam over the real DOM, through `pyscript`.

Every method here is a bridge crossing from Python to JavaScript. Events are delegated: one
document listener per bubbling event type, dispatching to the handler registered for the
element (found by a `data-fr` id walking up from the target), so a page has one JavaScript
proxy per event type instead of one per handler.
"""

from .reactive import on_cleanup
from .renderer import Renderer
from .runtime import create_proxy, document, in_browser

__all__ = ["DomRenderer", "is_node", "resolve"]

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


class DomRenderer(Renderer):
    def __init__(self):
        if not in_browser:
            raise RuntimeError("DomRenderer needs a browser; use HtmlRenderer on the server")
        self._handlers = {}  # element id -> {event: handler}
        self._next_id = 1
        self._delegated = set()
        self._proxies = {}

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

    # -- templates ----------------------------------------------------------------------------

    _templates = {}

    def clone_template(self, html):
        template = DomRenderer._templates.get(html)
        if template is None:
            template = document.createElement("template")
            template.innerHTML = html
            DomRenderer._templates[html] = template
        return template.content.firstChild.cloneNode(True)

    def find_holes(self, root):
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

    def _make_dispatcher(self, event):
        handlers = self._handlers

        def dispatch(ev):
            node = ev.target
            while is_node(node) and node.nodeType == 1:
                fid = node.getAttribute("data-fr")
                if fid:
                    handler = handlers.get(fid, {}).get(event)
                    if handler is not None and not getattr(node, "disabled", False):
                        handler(ev)
                        if getattr(ev, "cancelBubble", False):
                            return
                node = node.parentNode

        return dispatch


def _unused():  # keeps on_cleanup imported for the M2 direct-listener owner wiring
    return on_cleanup
