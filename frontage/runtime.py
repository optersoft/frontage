"""Which Python is running us, and the bridge to the browser when there is one.

Frontage runs in two places: its own runtime in the browser (`rust/`, since 0.10), and plain
CPython on a server or in the tests. The names exported here are the browser globals and the
FFI helpers on the runtime, and stand-ins on the server that say so if touched. Nothing else
in the package imports `js` or `jsffi` directly.
"""

import sys

# Most of these names exist to be re-exported. Without this list an unused-import
# autofix deletes them and the package stops importing in the browser.
__all__ = [
    "CPYTHON",
    "FRONTAGE",
    "Unavailable",
    "create_proxy",
    "document",
    "in_browser",
    "platform",
    "prerender",
    "to_js",
    "warn",
    "window",
]

CPYTHON = "cpython"
FRONTAGE = "frontage"  # frontage's own runtime (rust/), in the browser


def _detect():
    if sys.implementation.name == "frontage":
        try:
            import js  # only the browser build has one, and only a page has a document

            js.document  # noqa: B018
            return FRONTAGE
        except (ImportError, AttributeError):
            return CPYTHON
    return CPYTHON


platform = _detect()
in_browser = platform == FRONTAGE


class _Prerender:
    """What `python -m frontage prerender` tells the package while it imports an app on
    CPython: `active`, the `path` being rendered (the router starts there), and where
    `mount` registers instead of drawing."""

    def __init__(self):
        self.active = False
        self.path = "/"
        self.mounts = []


prerender = _Prerender()


def warn(message):
    """A warning in the browser console, or on stderr."""
    if in_browser:
        try:
            window.console.warn(message)
            return
        except Exception:
            pass
    print(f"frontage: {message}", file=sys.stderr)


class Unavailable:
    """A browser global on the server: falsy, and loud if anything actually uses it.

    Standing in with an object rather than `None` gives a sentence naming the global at
    the point of use, instead of an `AttributeError` on `None` somewhere downstream.
    """

    def __init__(self, name):
        object.__setattr__(self, "_name", name)

    def __bool__(self):
        return False

    def __getattr__(self, attr):
        raise RuntimeError(f"{self._name}.{attr}: {self._name} is only available in the browser")

    def __setattr__(self, attr, value):
        raise RuntimeError(f"{self._name}.{attr}: {self._name} is only available in the browser")

    def __call__(self, *args, **kwargs):
        raise RuntimeError(f"{self._name} is only available in the browser")

    def __repr__(self):
        return f"<{self._name}: unavailable outside the browser>"


if platform == FRONTAGE:
    # The runtime's bridge: `js` is the JavaScript global scope, `jsffi` the proxies and the
    # conversions (rust/web/src/jsffi.py).
    from js import document, window
    from jsffi import create_proxy, to_js
else:
    document = Unavailable("document")
    window = Unavailable("window")

    def create_proxy(obj):
        return obj

    def to_js(obj):
        return obj
