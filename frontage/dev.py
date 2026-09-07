"""Replace the app's modules in a running page, without reloading it.

`frontage serve` calls this when a file changes. The interpreter stays up, the WebAssembly is
not fetched again, and the page is rebuilt from the new source in a few milliseconds. Dioxus
needs linker tricks to hot-patch Rust; a bytecode VM just needs to be asked.

What a swap is:

1. compile every app module, so a typo cannot take the page apart,
2. dispose each mount and give the document back its delegated listeners,
3. drop the app's modules so the next import reads the new file,
4. run the entry again, as `__main__`, in a namespace of its own.

Signal values do not survive: the page is rebuilt, not patched. What survives is the
interpreter, the framework, and the scroll position.

Only the *app* swaps. A change under `frontage/` reloads the page, because the framework's
own module objects are what everything else is holding — `Owner`, the context keys, the
renderer classes — and replacing those under a live page means two frameworks at once.

This module is imported by the dev server's page, never by a built one.
"""

import sys

from . import view

# `compile` is optional in MicroPython (MICROPY_PY_BUILTINS_COMPILE). Where it is missing the
# swap still works; it just finds a syntax error a moment later, with the page already down.
try:
    _compile = compile
except NameError:  # pragma: no cover - depends on the interpreter's build
    _compile = None


def teardown():
    """Undo every live mount: dispose its owner, then let its renderer clean up the document.

    Order matters. The owner's cleanups remove the listeners bound to nodes; the renderer's
    `teardown` removes the delegated dispatchers on `document`, which no owner holds.
    """
    for root in list(view._mounted):
        renderer = root.renderer
        root.dispose()
        teardown_renderer = getattr(renderer, "teardown", None)
        if teardown_renderer is not None:
            teardown_renderer()
    del view._mounted[:]


def read(name, root="/lib"):
    """The source of app module `name`, as the dev server last wrote it."""
    with open(root + "/" + name + ".py") as handle:
        return handle.read()


def swap(entry, names, root="/lib"):
    """Re-run `entry` after `names` changed on the filesystem; returns the number replaced.

    Raises before touching the page if any module fails to compile, so a half-typed file
    leaves the last working version on screen.
    """
    names = list(names)
    if entry not in names:
        names.append(entry)

    sources = {}
    for name in names:
        sources[name] = read(name, root)
    if _compile is not None:
        for name in names:
            _compile(sources[name], name + ".py", "exec")

    teardown()
    for name in names:
        sys.modules.pop(name, None)

    # `unique_id` counts per mount and per page; a swap is a fresh page as far as ids go, so
    # the ones the new render hands out match what a reload would have produced.
    view._ids[0] = 0
    view._mounts[0] = 0

    # A namespace of its own, so last run's module-level names cannot linger and shadow one
    # the edit removed. `__name__` is `__main__` because that is what the entry ran as.
    namespace = {"__name__": "__main__"}
    exec(sources[entry], namespace)
    return len(names)
