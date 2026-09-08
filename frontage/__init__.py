"""Frontage: a fine-grained reactive UI framework for Python in the browser.

M5 of the rewrite (see DESIGN.md): the reactive core, the store, reactive views with the
insert rules, templates (`h` and `html(t"…")`), control flow and boundaries, Resource and
Action, the router, widgets, State, delegated events, and the DOM renderer.
"""

import sys

from ._exports import EXPORTS
from .version import __version__

__all__ = sorted(EXPORTS) + ["__version__"]


def __getattr__(name):
    """`from frontage import Signal` loads `frontage.reactive` and nothing else.

    The package used to import every module up front, so a counter shipped the router, the
    store and the template parser. Resolving names on first use (PEP 562, which MicroPython
    supports) is what lets `frontage build` pack only the modules a page reaches — the table
    in `_exports.py` is what both this function and the build read.
    """
    module = EXPORTS.get(name)
    if module is None:
        # `from . import reactive` inside the package: CPython resolves a submodule itself when
        # the attribute is missing, MicroPython asks here first. A name that is neither a
        # public name nor a module is the usual AttributeError.
        try:
            __import__("frontage." + name)
        except ImportError:
            raise AttributeError("module 'frontage' has no attribute '%s'" % name) from None
        return sys.modules["frontage." + name]
    qualified = "frontage." + module
    __import__(qualified)
    value = getattr(sys.modules[qualified], name)
    globals()[name] = value  # resolved once; the next access is a plain lookup
    return value
