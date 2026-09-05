"""Which Python is running us, and the browser globals that depend on it.

Frontage runs in three places: Pyodide and MicroPython in the browser, and plain CPython
on a server or in the tests. The names exported here are the JavaScript globals on the
two browser runtimes and stand-ins on the server, where nothing that touches them runs.
"""

import sys

PLATFORM_PYODIDE = "pyodide"
PLATFORM_MICROPYTHON = "micropython"
PLATFORM_CPYTHON = "cpython"


def _detect_platform():
    if sys.platform == "emscripten":
        return PLATFORM_PYODIDE
    elif sys.platform == "webassembly" and sys.implementation.name == "micropython":
        return PLATFORM_MICROPYTHON
    elif sys.implementation.name == "cpython":
        return PLATFORM_CPYTHON


platform = _detect_platform()
is_server_side = platform not in (PLATFORM_PYODIDE, PLATFORM_MICROPYTHON)


class _Unavailable:
    """A browser global on the server: falsy, and loud if anything actually uses it.

    Standing in with an object instead of `None` gives a clear error at the point of
    use rather than an `AttributeError` on `None`, and lets the type checker see that
    attribute access on these names is intended.
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


if platform == PLATFORM_PYODIDE:
    from pyodide.ffi import create_proxy
    from pyodide.ffi.wrappers import add_event_listener, remove_event_listener
elif platform == PLATFORM_MICROPYTHON:
    from pyscript.ffi import create_proxy

    def add_event_listener(elt, event, listener):
        return elt.addEventListener(event, listener)

    def remove_event_listener(elt, event, listener):
        return elt.removeEventListener(event, create_proxy(listener))

else:
    add_event_listener = _Unavailable("add_event_listener")
    remove_event_listener = _Unavailable("remove_event_listener")

    def create_proxy(obj):
        return obj


if is_server_side:
    document = _Unavailable("document")
    window = _Unavailable("window")
    history = _Unavailable("history")
    setTimeout = _Unavailable("setTimeout")
    Object = _Unavailable("Object")
    CustomEvent = _Unavailable("CustomEvent")

    def next_tick(fn):
        fn()

else:
    from js import setTimeout

    def next_tick(fn):
        setTimeout(create_proxy(fn), 100)
