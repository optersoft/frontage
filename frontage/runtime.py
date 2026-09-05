"""Which Python is running us, and the bridge to the browser when there is one.

Frontage runs in three places: Pyodide and MicroPython in the browser, and plain CPython on
a server or in the tests. The names exported here are the browser globals and the FFI
helpers on the two browser runtimes, and stand-ins on the server that say so if touched.
Nothing else in the package imports `pyscript` or `js` directly.
"""

import sys

# Most of these names exist to be re-exported. Without this list an unused-import
# autofix deletes them and the package stops importing in the browser.
__all__ = [
    "CPYTHON",
    "MICROPYTHON",
    "PYODIDE",
    "Unavailable",
    "create_proxy",
    "document",
    "in_browser",
    "platform",
    "to_js",
    "window",
]

PYODIDE = "pyodide"
MICROPYTHON = "micropython"
CPYTHON = "cpython"


def _detect():
    if sys.platform == "emscripten":
        return PYODIDE
    if sys.platform == "webassembly" and sys.implementation.name == "micropython":
        return MICROPYTHON
    return CPYTHON


platform = _detect()
in_browser = platform in (PYODIDE, MICROPYTHON)


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


if in_browser:
    from pyscript import document, window
    from pyscript.ffi import create_proxy, to_js
else:
    document = Unavailable("document")
    window = Unavailable("window")

    def create_proxy(obj):
        return obj

    def to_js(obj):
        return obj
