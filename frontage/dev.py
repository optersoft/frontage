"""Replace the app's modules in a running page, without reloading it.

`frontage serve` drives this when a file changes. The interpreter stays up, the WebAssembly is
not fetched again, and the page is rebuilt from the new bytecode in a few milliseconds.

What a swap is:

1. the server compiles every changed module, so a typo cannot take the page apart (the
   compile fails on the host and the page keeps the last working version),
2. the page's script hands the new bytecode to the runtime (`rt.addModule`),
3. dispose each mount and give the document back its delegated listeners,
4. drop the app's modules so the next import reads the new bytecode,
5. run the entry again, as `__main__`.

Signal values do not survive: the page is rebuilt, not patched. What survives is the
interpreter, the framework, and the scroll position.

Only the *app* swaps. A change under `frontage/` reloads the page, because the framework's
own module objects are what everything else is holding — `Owner`, the context keys, the
renderer classes — and replacing those under a live page means two frameworks at once.

The playground uses `teardown` between Runs. Imported by the dev server's page and the
playground, never by a built app.
"""

import sys

from . import view


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


def swap(entry, names, root=None):
    """Re-run `entry` after `names` changed; returns the number of modules replaced.

    In the browser the runtime already holds the new bytecode (the page's script fetched it
    and called `addModule`), so this drops the modules and runs the entry from it. On CPython
    (the tests, `root` a directory of sources) it compiles every module first, so a typo
    cannot take the page apart, then execs the entry in a namespace of its own."""
    names = list(names)
    if entry not in names:
        names.append(entry)
    try:
        import _frontage
    except ImportError:
        _frontage = None
    sources = {}
    if _frontage is None:
        for name in names:
            with open((root or ".") + "/" + name + ".py") as handle:
                sources[name] = handle.read()
        for name in names:
            compile(sources[name], name + ".py", "exec")  # raises before anything is taken apart
    teardown()
    for name in names:
        sys.modules.pop(name, None)
    # `unique_id` counts per mount and per page; a swap is a fresh page as far as ids go, so
    # the ones the new render hands out match what a reload would have produced.
    view._ids[0] = 0
    view._mounts[0] = 0
    if _frontage is not None:
        _frontage.run_module_as_main(entry)
    else:
        # A namespace of its own, so last run's module-level names cannot linger and shadow
        # one the edit removed. `__name__` is `__main__` because that is what the entry ran as.
        exec(sources[entry], {"__name__": "__main__"})
    return len(names)
