"""Code the page fetches when it first needs it.

`frontage build` ships the modules your entry imports. A module named as a *chunk root* is
left out of that first payload and written beside it, with whatever only it reaches; the page
asks for it the first time something wants it:

    from frontage import Route, Router

    Router(
        Route("/", home),
        Route("/map", lazy="pages.map:map_page"),   # `pages.map` and its own imports
    )

`lazy="pages.map"` alone means the module's `page` attribute. A route written this way shows
the nearest `Loading` fallback while its chunk is in flight, exactly as a route waiting for
data does, and `A` starts the fetch on hover — so by the time the click lands it is usually
already there.

Outside the browser there are no chunks: `load` imports the module and returns, which is what
the tests, the language server and the prerenderer need.
"""

import sys

from .runtime import in_browser, window

__all__ = ["load", "loaded", "prefetch"]

_DEFAULT_ATTR = "page"

# What a spec resolved to, by spec: the attribute, once its chunk is in.
_ready = {}
# Chunks whose fetch has started, by module name, so two links and a click ask once.
_started = {}


def _split(spec):
    """`"pages.map:page"` → `("pages.map", "page")`; `"pages.map"` → `("pages.map", "page")`."""
    module, _, attr = spec.partition(":")
    return module, attr or _DEFAULT_ATTR


def _attribute(module, attr, spec):
    target = getattr(sys.modules[module], attr, None)
    if target is None:
        raise ImportError(f"{spec}: {module} has no attribute {attr!r}")
    return target


def loaded(spec):
    """Is this spec's chunk already in the page? A hover prefetch that hit makes this True."""
    module, attr = _split(spec)
    if spec in _ready:
        return True
    if module in sys.modules:
        _ready[spec] = _attribute(module, attr, spec)
        return True
    return False


async def load(spec):
    """Fetch the chunk if it is not here, import the module, and return the attribute."""
    if loaded(spec):
        return _ready[spec]
    module, attr = _split(spec)
    if in_browser:
        await _fetch(module)
    __import__(module)
    _ready[spec] = _attribute(module, attr, spec)
    return _ready[spec]


def prefetch(spec):
    """Start the fetch and return at once. `A` calls this on hover, through the router."""
    if not in_browser or loaded(spec):
        return
    module, _ = _split(spec)
    if module in _started:
        return
    from .reactive import spawn

    # No owner: a prefetch outlives the link that started it, which is the point of hovering.
    spawn(_fetch(module), None, name=f"prefetch({module})")


def _entry(mapping, key, default=None):
    """`mapping[key]`, or `default`. Subscripting, not `getattr`: a module name has dots in
    it, and a manifest is a mapping in both worlds — a JavaScript object here, a dict in a
    test — where `getattr` reads a *property* and would answer for neither."""
    if mapping is None:
        return default
    try:
        value = mapping[key]
    except (KeyError, TypeError, AttributeError):
        return default
    return default if value is None else value


def _manifest():
    runtime = getattr(window, "frontage", None)
    return getattr(runtime, "manifest", None) if runtime is not None else None


def _files(module):
    """The `(name, file)` pairs this chunk needs that the page does not already have.

    A module the manifest does not list as a chunk needs nothing fetched: it is in the page's
    archive already. That is every module under `frontage serve`, where the archive is
    synthesised from the directory, and it is also a chunk root whose closure the first
    payload happens to cover.
    """
    manifest = _manifest()
    names = _entry(_entry(manifest, "chunks"), module)
    if not names:
        return []
    files = _entry(manifest, "files")
    return [(name, _entry(files, name, name + ".fbc")) for name in names if name not in sys.modules]


async def _fetch(module):
    """One request per module of the chunk, in parallel, registered with the runtime."""
    started = _started.get(module)
    if started is not None:
        await started
        return
    from .runtime import to_js

    pairs = _files(module)
    if not pairs:
        return
    runtime = window.frontage
    promise = runtime.loadChunk(to_js([list(pair) for pair in pairs]))
    _started[module] = promise
    try:
        await promise
    except Exception:
        # A failed fetch must not poison the chunk: a retry (a second click) may well work.
        _started.pop(module, None)
        raise


def component(spec):
    """A component that renders `spec`'s target, waiting for its chunk the first time.

    The wait is an **async memo** read inside a hole, which is the framework's answer to
    "this is not here yet": a `Loading` boundary shows its fallback, `is_routing` stays up
    until the chunk lands, a transition holds the old page, and an error reaches the nearest
    `Errored`. The hole matters — the router calls a route's component under `untrack`, so a
    memo read *there* would never be a dependency of anything and the page would sit on the
    old route forever. Outside the browser the memo is not async at all: the module is simply
    imported, so the prerenderer renders a lazy route like any other.
    """

    def render(**props):
        from .flow import Dynamic
        from .reactive import Memo, untrack

        memo = Memo(lambda: _resolve(spec))
        # Start it here, where the router is still inside its navigation window, so the fetch
        # counts toward `is_routing` as a route's own resource does. The hole below is what
        # re-renders when it settles; this read only wakes it.
        try:
            untrack(memo)
        except Exception:  # NotReady while it is in flight, or a failure the hole re-raises
            pass
        return Dynamic(memo, **props)

    return render


def _resolve(spec):
    """What the memo computes: the target, or the coroutine that fetches it first."""
    if loaded(spec):
        return _ready[spec]
    if not in_browser:
        module, attr = _split(spec)
        __import__(module)
        _ready[spec] = _attribute(module, attr, spec)
        return _ready[spec]
    return load(spec)
