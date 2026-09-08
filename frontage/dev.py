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
    kept = _preserve(names, _entry_ns[0] if _frontage is None else None)
    try:
        if _frontage is not None:
            _frontage.run_module_as_main(entry)
        else:
            # A namespace of its own, so last run's module-level names cannot linger and shadow
            # one the edit removed. `__name__` is `__main__` because that is what the entry ran as.
            namespace = {"__name__": "__main__"}
            exec(sources[entry], namespace)
            _entry_ns[0] = namespace
    except Exception as exc:
        report(entry, exc)
        raise
    _restore(kept, _entry_ns[0] if _frontage is None else None)
    clear_report()
    return len(names)


# -- state across a swap -------------------------------------------------------------------------
#
# A module-level `Signal`, `Store` or `State` keeps its value across a swap, matched by its
# qualified name (`app.count`, `store.todos`). This is Vue's rule rather than React's: the name
# is what identifies the state, so renaming the variable resets it and moving it to another
# module resets it, both of which are what the names say. The entry counts as `__main__`,
# because that is what it runs as.
#
# The restore happens *after* the rebuild, not during it: the page renders once with the
# module's own initial value and is then written to, in one batch, before the browser paints.
# So an edit that changes `Signal(0)` to `Signal(5)` shows 0 again — reload the page to start
# from the source's own values.


#: The entry's namespace from the last run, on the CPython path, where the entry is exec'd
#: into a dict of its own rather than imported. In the browser it is `sys.modules["__main__"]`.
_entry_ns = [None]


def _members(name, namespace):
    """`(attribute, value)` pairs of a module by name, or of the entry's own namespace."""
    if name == "__main__" and namespace is not None:
        return [(key, value) for key, value in namespace.items() if not key.startswith("_")]
    module = sys.modules.get(name)
    if module is None:
        return []
    return [(attr, getattr(module, attr, None)) for attr in dir(module) if not attr.startswith("_")]


def _preserve(names, namespace):
    """The module-level state of the modules about to be dropped, by qualified name."""
    kept = {}
    for name in list(names) + ["__main__"]:
        for attr, value in _members(name, namespace):
            state = _value_of(value)
            if state is not None:
                kept[name + "." + attr] = state
    return kept


def _value_of(value):
    """What is worth keeping about this object, or None if it is not state."""
    from .reactive import Signal

    # A page holds only the modules its app imports, so `frontage.store` is here exactly when
    # the app uses a Store — importing it unconditionally is what a page without one cannot do.
    try:
        from .store import Store
    except ImportError:
        Store = None

    if type(value) is Signal:
        return ("signal", value.peek())
    if Store is not None and type(value) is Store:
        raw = object.__getattribute__(value, "_raw")
        return ("store", raw.copy())
    signals = getattr(value, "_signals", None)
    if isinstance(signals, dict) and signals:  # a `State` instance
        return ("state", {key: node.peek() for key, node in signals.items()})
    return None


def _restore(kept, namespace):
    """Write the preserved values back into the modules that came out of the rebuild."""
    if not kept:
        return
    from .reactive import batch

    with batch():
        for qualified, (kind, value) in kept.items():
            name, _, attr = qualified.rpartition(".")
            target = dict(_members(name, namespace)).get(attr)
            state = _value_of(target)
            if state is None or state[0] != kind:
                continue  # gone, renamed, or a different kind of thing now: it starts fresh
            _write(kind, target, value)


def _write(kind, target, value):
    if kind == "signal":
        target.set(value)
    elif kind == "store":
        target.set(lambda store: _fill(store, value))
    else:
        signals = target._signals
        for key, item in value.items():
            node = signals.get(key)
            if node is not None:
                node.set(item)


def _fill(store, value):
    raw = object.__getattribute__(store, "_raw")
    if type(raw) is list:
        store.clear()
        store.extend(value)
    else:
        for key in list(raw):
            if key not in value:
                del store[key]
        store.update(value)


def report(entry, exc):
    """Put a swap's traceback on the dev server's error overlay, if this page has one.

    The console has it too, but a page that has just been torn down and failed to build again
    shows nothing at all, and a blank page is the worst way to learn that a save was bad. The
    overlay belongs to `frontage serve`; a built page has no `devError` and this does nothing.
    """
    from .errors import format_exception
    from .runtime import in_browser, window

    if not in_browser:
        return
    show = getattr(window, "frontageDevError", None)
    if show is not None:
        show(f"{entry}.py raised while the page was rebuilding", format_exception(exc))


def clear_report():
    from .runtime import in_browser, window

    if not in_browser:
        return
    clear = getattr(window, "frontageDevErrorClear", None)
    if clear is not None:
        clear()
