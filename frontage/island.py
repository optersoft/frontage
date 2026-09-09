"""Islands: the parts of a static page that come alive, and when.

A page that mounts nothing interactive ships no runtime — `mount(view, "#app",
when="never")` is rendered once, at build time, and the browser downloads HTML and
stylesheets and stops there. An **island** is the exception a content page makes:

    from frontage import h, island, mount

    def page():
        return h.main(
            h.article(...),                                  # static: rendered once
            island(comments, when="visible", post="hello"),   # alive when it is seen
            island(theme_toggle, when="idle"),
        )

    mount(page, "#app", when="never")

At build time an island renders like any other view, inside a wrapper the loader can find.
In the browser, `_frontage/island.js` — 1.3 KB over the wire, and the only script such a
page carries — watches the triggers and, the first time one fires, boots the runtime
**once**. Every island on the page shares it; each then hydrates its own wrapper with its
own component, so a page with a theme toggle and a chart pays for the chart when the chart
is seen.

| `when=` | boots |
|---|---|
| `"load"` | at once |
| `"idle"` | `requestIdleCallback`, else a short timeout |
| `"visible"` | `IntersectionObserver` (the fetch starts 200px early) |
| `"media:(max-width: 50em)"` | while the query matches |
| `"never"` | rendered at build, never hydrated: plain HTML |
| `"only"` | not rendered at build; mounted fresh on load |

**Props are JSON and immutable.** They cross as a JSON attribute on the wrapper, the way a
prerendered resource's value does, so anything that is not JSON is a build error naming the
island. **Shared state is a module**: islands on one page share one interpreter, so a signal
they both import is one signal — which is what a Solid or Svelte developer expects and what
three React islands cannot have.

**An island named by a string is a chunk.** `island("comments:thread")` names the module
instead of importing it, exactly as `Route(lazy=…)` does, so `frontage build` leaves it out
of the first payload and the page fetches it when the trigger fires.
"""

import json
import sys

# Absolute imports throughout: on a page of islands this module is what the boot *runs*, as
# `__main__`, and a relative import there resolves against `__main__` and fails.
from frontage.runtime import in_browser, prerender, window

__all__ = ["island"]

#: The wrapper: an unknown element, laid out as if it were not there.
TAG = "fr-island"
STYLE = "display:contents"

#: Every `when=` this understands but the parametrised `media:…`.
TRIGGERS = ("load", "idle", "visible", "never", "only")

_DEFAULT_ATTR = "page"


def _check(when):
    if when in TRIGGERS or (isinstance(when, str) and when.startswith("media:") and len(when) > 6):
        return when
    raise ValueError(f"island(when={when!r}): expected one of {', '.join(TRIGGERS)} or 'media:<query>'")


def spec_of(view):
    """`"comments:thread"` for an island's component: the module the browser imports and the
    name in it. A string is taken as written; a function is asked where it came from.

    A component defined in the app's entry answers `__main__` in a browser and, while the
    prerenderer is importing it, a private name of its own — so the entry's real module name
    is substituted here, which is the one the page's manifest knows it by.
    """
    if isinstance(view, str):
        module, _, attr = view.partition(":")
        return f"{module}:{attr or _DEFAULT_ATTR}"
    module = getattr(view, "__module__", None)
    name = getattr(view, "__name__", None)
    if not module or not name:
        raise TypeError(f"island() wants a component function or a 'module:name' string, not {view!r}")
    if module == getattr(prerender, "entry_module", None):
        module = prerender.entry
    return f"{module}:{name}"


def target_of(spec):
    """The component a spec names, imported here and now (CPython: the build, the tests)."""
    module, _, attr = spec.partition(":")
    __import__(module)
    found = getattr(sys.modules[module], attr, None)
    if found is None:
        raise ImportError(f"island({spec!r}): {module} has no attribute {attr!r}")
    return found


def island(view, when="load", **props):
    """An island: `view` rendered at build time, and hydrated in the browser when `when` says.

    `view` is a component function or a `"module:name"` string (a string makes it a chunk).
    `props` are the arguments it is called with, and must be JSON — they are written into the
    page and read back in the browser.

    Outside a static build — in the dev server, inside an app that mounts the whole page —
    there is nothing to defer, so this is just the component, rendered where it stands.
    """
    when = _check(when)
    spec = spec_of(view)
    if when == "never" or not prerender.static:
        # Nothing to defer: the dev server, a test, an app that mounts the whole page. The
        # island is the component, rendered where it stands — except `only`, which by
        # definition has no build-time rendering, and a string spec in the browser, which is
        # a chunk and so waits the way a lazy route does (a hole, a `Loading` boundary).
        if when == "only" and not in_browser:
            return None
        if callable(view):
            return view(**props)
        if in_browser:
            from frontage.chunks import component

            return component(spec)(**props)
        return target_of(spec)(**props)
    try:
        encoded = json.dumps(props, separators=(",", ":"))
    except TypeError as exc:
        raise TypeError(f"island({spec!r}): props must be JSON ({exc})") from None
    index = len(prerender.islands)
    prerender.islands.append(_Island(index, spec, when, props, view if callable(view) else None))
    from frontage.view import h

    # `data-fr-index` last: the prerenderer splices the rendered content in on the tail of
    # this tag, and the tail has to be a string it can be sure of.
    return h(
        TAG,
        id=f"fr-island-{index}",
        style=STYLE,
        **{
            "data-fr-island": spec,
            "data-fr-when": when,
            "data-fr-props": encoded,
            "data-fr-index": str(index),
        },
    )


class _Island:
    """One registration, for `frontage prerender` to render in a pass of its own."""

    def __init__(self, index, spec, when, props, target=None):
        self.index = index
        self.spec = spec
        self.when = when
        self.props = props
        # The component itself when the page passed one: the prerenderer renders it in a pass
        # of its own, later, and by then the app is out of `sys.modules` again.
        self.target = target

    @property
    def id(self):
        return f"fr-island-{self.index}"

    def view(self):
        target = self.target or target_of(self.spec)
        props = self.props
        return lambda: target(**props)


# --- the browser -------------------------------------------------------------------------
#
# `island.js` collects the wrappers whose trigger has fired and boots the runtime once; the
# boot then runs this module as `__main__`, which is what the last line of the file does.
# Everything below needs a browser and a page the loader wrote.


def _bridge():
    return getattr(window, "__frontageIslands", None)


#: The wrappers already taken, by their id. The guard is here rather than an attribute on the
#: element because the mount is a chunk fetch away, and `data-fr-mounted` should mean the
#: island *is* alive — it is what a test, and a person reading the DOM, will take it for.
_taken = set()


def hydrate(element):
    """Bring one wrapper to life: fetch its chunk if it has one, then mount into it."""
    from frontage.reactive import spawn

    if element is None:
        return
    key = str(element.id)
    if key in _taken:
        return
    _taken.add(key)
    spawn(_hydrate(element), None, name=f"island({key})")


async def _hydrate(element):
    from frontage.chunks import load
    from frontage.runtime import warn
    from frontage.view import mount

    spec = str(element.getAttribute("data-fr-island") or "")
    raw = str(element.getAttribute("data-fr-props") or "{}")
    try:
        target = await load(spec)
    except Exception as exc:  # a chunk that never arrives leaves the HTML in place
        warn(f"island {spec}: {exc}")
        _taken.discard(str(element.id))
        return
    props = json.loads(raw) if raw else {}
    only = str(element.getAttribute("data-fr-when") or "") == "only"
    mount(lambda: target(**props), element, hydrate=not only, clear=only, scope=str(element.id))
    element.setAttribute("data-fr-mounted", "")


def hydrate_pending():
    """Take over from the loader: hydrate what it queued, and answer every later trigger.

    Run once, by `island.js`, the first time any trigger fires. The queue exists because the
    triggers fire while the runtime is still downloading, and the page must not lose them.
    """
    from frontage.runtime import create_proxy

    bridge = _bridge()
    if bridge is None:
        return
    bridge.hydrate = create_proxy(hydrate)
    queue = bridge.queue
    while queue.length:
        hydrate(queue.shift())


if __name__ == "__main__":
    # On a page of islands this module *is* what the boot runs: there is no app entry to run,
    # because the page's HTML was written at build time. Everything above is a definition;
    # this is the one line that does something.
    hydrate_pending()
