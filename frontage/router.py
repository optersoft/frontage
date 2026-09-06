"""The router: the URL drives state; routes nest; plain links work.

    router = Router(
        Route("/", Home),
        Route("/contacts", ContactList, children=[
            Route(":id", Contact, preload=load_contact),
            Route("", SelectOne),
        ]),
        Route("*", NotFound),
        mode="hash",
    )
    mount(router, "#app")

A `Route` has a path relative to its parent (`:name` captures a segment, `*rest` the
remainder, `""` matches its parent exactly), a component, optional children and an optional
`preload(params, location)` coroutine. A route with children is called as
`component(children=outlet)`, where the outlet is a hole for the matched child; a leaf is
called as `component()`.

Navigating re-renders only the levels whose route changed: a level whose route object is the
same keeps its nodes and its state, and `use_params()` is an accessor, so a component that
reads a param updates in place. Three modes: `history` (pushState), `hash` (the no-server
case, and what static hosting wants), `memory` (no browser; the test suite runs on it).
"""

from . import reactive
from .aio import Action
from .flow import _Branch
from .reactive import Context, Memo, Owner, Signal, batch, get_owner, on_cleanup, provide, run_with_owner, untrack, use
from .runtime import create_proxy, document, in_browser, window
from .view import Mounted, _build_nodes, h

__all__ = [
    "A",
    "ActionForm",
    "Navigate",
    "Redirect",
    "Route",
    "Router",
    "query",
    "use_before_leave",
    "use_is_routing",
    "use_location",
    "use_match",
    "use_navigate",
    "use_params",
    "use_query",
    "use_router",
    "use_submission",
]

_ROUTER = Context(None)
_LEVEL = Context(None)


class Redirect(Exception):
    """Raise from a route component (or an action) to navigate somewhere else instead."""

    def __init__(self, path, replace=True):
        super().__init__(path)
        self.path = path
        self.replace = replace


# --- URL helpers (no urllib: MicroPython has none) -----------------------------------------------


def _unquote(s):
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "%" and i + 2 < n + 0 and i + 2 <= n - 1:
            try:
                out.append(chr(int(s[i + 1 : i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(" " if c == "+" else c)
        i += 1
    return "".join(out)


def parse_query(search):
    """`?a=1&b=x&b=y` → `{"a": ["1"], "b": ["x", "y"]}`; a bare key maps to `[""]`."""
    out = {}
    if search.startswith("?"):
        search = search[1:]
    if not search:
        return out
    for part in search.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        out.setdefault(_unquote(key), []).append(_unquote(value))
    return out


class Location:
    def __init__(self, url):
        self.url = url
        path, _, hash_ = url.partition("#")
        pathname, _, search = path.partition("?")
        self.pathname = _normalize(pathname)
        self.search = "?" + search if search else ""
        self.hash = "#" + hash_ if hash_ else ""
        self.query = parse_query(search)

    def __repr__(self):
        return f"Location({self.url!r})"


def _normalize(pathname):
    if not pathname.startswith("/"):
        pathname = "/" + pathname
    if len(pathname) > 1 and pathname.endswith("/"):
        pathname = pathname[:-1]
    return pathname


def _segments(path):
    return [s for s in path.split("/") if s]


def _join(prefix, path):
    """Join a relative `path` to `prefix`, resolving `.` and `..` segments."""
    if path.startswith("/"):
        return _normalize(path)
    out = _segments(prefix)
    for part in path.split("/"):
        if part == "" or part == ".":
            continue
        if part == "..":
            if out:
                out.pop()
        else:
            out.append(part)
    return "/" + "/".join(out)


# --- routes and matching ----------------------------------------------------------------------------


class Route:
    def __init__(self, path, component=None, children=None, preload=None):
        self.path = path
        self.segments = _segments(path)
        self.component = component
        self.children = list(children or [])
        self.preload = preload

    def __repr__(self):
        return f"Route({self.path!r})"


class Match:
    """One matched level: the route, the params it captured, and the path prefix up to it."""

    def __init__(self, route, params, prefix):
        self.route = route
        self.params = params
        self.prefix = prefix


def match_routes(routes, pathname):
    """The chain of `Match` from the root route to the leaf, or None."""
    return _match(routes, _segments(pathname), {}, "")


def _match(routes, segments, params, prefix):
    for route in routes:
        captured = dict(params)
        rest = _match_segments(route.segments, segments, captured)
        if rest is None:
            continue
        consumed = segments[: len(segments) - len(rest)]
        here = Match(route, captured, prefix + "".join("/" + s for s in consumed))
        if route.children:
            tail = _match(route.children, rest, captured, here.prefix)
            if tail is not None:
                return [here] + tail
            continue
        if rest and not (route.segments and route.segments[-1].startswith("*")):
            continue
        return [here]
    return None


def _match_segments(pattern, segments, params):
    """Match `pattern` against the start of `segments`; returns the unmatched rest or None."""
    i = 0
    for part in pattern:
        if part.startswith("*"):
            name = part[1:] or "rest"
            params[name] = "/".join(segments[i:])
            return []
        if i >= len(segments):
            return None
        if part.startswith(":"):
            params[part[1:]] = _unquote(segments[i])
        elif part != segments[i]:
            return None
        i += 1
    return segments[i:]


# --- modes -------------------------------------------------------------------------------------------


class MemoryMode:
    """A history kept in a list. No browser needed; what the tests use."""

    def __init__(self, initial="/"):
        self.entries = [initial]
        self.index = 0
        self.listener = None

    def current(self):
        return self.entries[self.index]

    def push(self, url):
        del self.entries[self.index + 1 :]
        self.entries.append(url)
        self.index += 1

    def replace(self, url):
        self.entries[self.index] = url

    def go(self, delta):
        target = self.index + delta
        if 0 <= target < len(self.entries):
            self.index = target
            if self.listener is not None:
                self.listener(self.current())

    def listen(self, fn):
        self.listener = fn
        return lambda: setattr(self, "listener", None)


def _manual_scroll_restoration():
    """The router restores scroll positions itself (U10). The browser must not: with `auto` it
    moves the page before `popstate`/`hashchange` fires, so the position the router would
    remember for the page being left is already the other page's."""
    try:
        window.history.scrollRestoration = "manual"
    except Exception:
        pass


class HistoryMode:
    def __init__(self):
        _manual_scroll_restoration()

    def current(self):
        loc = window.location
        return str(loc.pathname) + str(loc.search) + str(loc.hash)

    def push(self, url):
        window.history.pushState(None, "", url)

    def replace(self, url):
        window.history.replaceState(None, "", url)

    def go(self, delta):
        window.history.go(delta)

    def listen(self, fn):
        proxy = create_proxy(lambda ev: fn(self.current()))
        window.addEventListener("popstate", proxy)
        return lambda: window.removeEventListener("popstate", proxy)


class HashMode:
    def __init__(self):
        _manual_scroll_restoration()

    def current(self):
        # Only a fragment that is a path is a route: `#section` (an anchor) or a runner's
        # `#{"code": …}` payload means "the root", not "no such page".
        raw = str(window.location.hash)
        return raw[1:] if raw.startswith("#/") else "/"

    def push(self, url):
        window.location.hash = url

    def replace(self, url):
        window.location.replace("#" + url)

    def go(self, delta):
        window.history.go(delta)

    def listen(self, fn):
        proxy = create_proxy(lambda ev: fn(self.current()))
        window.addEventListener("hashchange", proxy)
        return lambda: window.removeEventListener("hashchange", proxy)


# --- the router ------------------------------------------------------------------------------------------


class Router:
    def __init__(self, *routes, mode="history", root=None, fallback=None, initial="/", base="", transition=False):
        self.routes = list(routes)
        self.root = root
        self.fallback = fallback
        self.base = base.rstrip("/")
        # `transition=True`: every navigation (a link, `navigate`, back and forward) runs as a
        # `transition()`: the new route is built off screen, its resources load, and the page
        # changes when they are ready, with no fallback in between. `navigate(…,
        # transition=…)` decides for one call.
        self.transition = transition
        if mode == "memory" or not in_browser:
            # Without a browser (tests, `python -m frontage prerender`) every mode is the
            # memory one; the prerenderer says which path is being rendered.
            from .runtime import prerender

            self.mode = MemoryMode(prerender.path if prerender.active else initial)
        elif mode == "hash":
            self.mode = HashMode()
        elif mode == "history":
            self.mode = HistoryMode()
        else:
            raise ValueError(f"unknown router mode {mode!r}; use 'history', 'hash' or 'memory'")
        self.mode_name = mode
        self.url = Signal(self.mode.current())
        self.location = Memo(lambda: Location(self.url()))
        self.matches = Memo(lambda: match_routes(self.routes, self._strip_base(self.location().pathname)))
        self.params = Memo(lambda: dict(self.matches()[-1].params) if self.matches() else {})
        self.is_routing = Signal(False)
        self._inflight = 0  # preloads started by the current navigation and still running
        self._guards = []
        self._scroll = {}
        self._unlisten = None

    def _strip_base(self, pathname):
        """The app path for a document path: without `base`, and with the document file
        itself (`/index.html`) counting as the root, so a static page can use history mode."""
        if self.base and pathname.startswith(self.base):
            pathname = pathname[len(self.base) :] or "/"
        if pathname.endswith(".html") and "/" not in pathname[1:]:
            return "/"
        return pathname

    # -- rendering -------------------------------------------------------------------------------

    def __call__(self):
        """The router as a component: `mount(router, "#app")`."""
        provide(_ROUTER, self)
        self._unlisten = self.mode.listen(self._on_history)
        on_cleanup(self._dispose)
        if in_browser and self.mode_name != "memory":
            self._intercept_links()
        outlet = self._level(0)
        if self.root is not None:
            return self.root(children=outlet)
        return outlet

    def _dispose(self):
        if self._unlisten is not None:
            self._unlisten()
            self._unlisten = None

    def _level(self, depth):
        """The hole for level `depth` of the match: keeps its nodes while the route there is
        the same object, rebuilds when it changes."""
        home = get_owner()
        state = _Branch()  # key = the route object rendered at this level
        on_cleanup(state.dispose)

        def accessor():
            from . import view as _view

            renderer = _view._current_renderer
            chain = self.matches()
            if chain is None or depth >= len(chain):
                route = None
            else:
                route = chain[depth].route
            if route is state.key and state.owner is not None:
                return Mounted(state.nodes)
            state.dispose()
            state.key = route
            owner = Owner(parent=home)
            state.owner = owner

            def make():
                if route is None:
                    if depth == 0 and self.fallback is not None:
                        content = (
                            untrack(self.fallback)
                            if callable(self.fallback) and not hasattr(self.fallback, "tag")
                            else self.fallback
                        )
                        return _build_nodes(content, renderer)
                    return []
                level = _LevelContext(self, depth)
                provide(_LEVEL, level)
                try:
                    if route.preload is not None:
                        self._preload_one(route, chain[depth].params, "navigate")
                    if route.children:
                        content = untrack(lambda: route.component(children=self._level(depth + 1)))
                    else:
                        content = untrack(route.component)
                except Redirect as redirect:
                    self._deferred_navigate(redirect.path, redirect.replace)
                    return []
                return _build_nodes(content, renderer) if content is not None else []

            state.nodes = run_with_owner(owner, make)
            return Mounted(state.nodes)

        return accessor

    # -- navigation ------------------------------------------------------------------------------

    def navigate(self, path, replace=False, scroll=True, transition=None):
        """Go to `path` (absolute, or relative to the current route level when called from a
        component). Guards from `use_before_leave` may cancel. Returns True if it happened.
        `transition` (default: the router's) holds the page until the new route's data is in."""
        target = self._full(self.resolve(path))
        current = self.url.peek()
        if target == current:
            return True
        for guard in list(self._guards):
            if guard(target, current) is False:
                return False
        self._remember_scroll(current)
        if replace:
            self.mode.replace(target)
        else:
            self.mode.push(target)
        self._change(target, (lambda: self._scroll_to(0)) if scroll else None, transition)
        return True

    def _change(self, url, after, transition):
        """Apply a URL change, as a transition when asked; `after` runs once the page shows it."""
        from .reactive import on_mount
        from .reactive import transition as run_transition

        use = self.transition if transition is None else transition
        if use:
            t = run_transition(self._set_url, url)
            if after is not None:
                t.on_commit(after)
        else:
            self._set_url(url)
            if after is not None:
                on_mount(after)

    def _deferred_navigate(self, path, replace):
        # A Redirect during a render: apply once the current update has settled.
        from .reactive import on_mount

        on_mount(lambda: self.navigate(path, replace=replace))

    def _on_history(self, url):
        current = self.url.peek()
        for guard in list(self._guards):
            if guard(url, current) is False:
                self.mode.replace(current) if self.mode_name != "memory" else None
                return
        self._remember_scroll(current)
        y = self._scroll.get(url, 0)
        self._change(url, lambda: self._scroll_to(y), None)  # once the page is back on screen

    def _set_url(self, url):
        from .reactive import on_mount

        # The route effects this update runs start the preloads and create the new route's
        # resources and async memos, which count toward `is_routing` (`reactive._navigation`)
        # until the update has settled: `_settle_routing` runs after the render effects of
        # whichever batch flushes this (the caller's transition, or this one) and closes the window.
        reactive._navigation = self  # ty: ignore[invalid-assignment]
        with batch():
            self.is_routing.set(True)
            self.url.set(url)
            on_mount(self._settle_routing)

    def _settle_routing(self):
        if reactive._navigation is self:
            reactive._navigation = None
        if self._inflight == 0 and self.is_routing.peek():
            self.is_routing.set(False)

    def _track_load(self, node):
        """A Resource or an async Memo the new route created: its first load counts."""
        self._inflight += 1

    def _load_done(self, node):
        self._inflight -= 1
        self._settle_routing()

    async def _tracked(self, coro):
        try:
            await coro
        finally:
            self._inflight -= 1
            self._settle_routing()

    def back(self):
        self.mode.go(-1)

    def forward(self):
        self.mode.go(1)

    def resolve(self, path):
        """The app path for `path`: absolute paths as given, relative ones joined to the current
        route level's prefix (with `.` and `..` resolved). No base: see `_full`."""
        if path.startswith("/"):
            return _normalize(path)
        level = use(_LEVEL)
        prefix = level.prefix() if level is not None else "/"
        return _join(prefix, path)

    def _full(self, app_path):
        """The URL the history sees for an app path: the base goes in front in history mode."""
        if self.base and self.mode_name != "hash":
            return _normalize(self.base + ("" if app_path == "/" else app_path))
        return app_path

    def _remember_scroll(self, url):
        if in_browser and self.mode_name != "memory":
            try:
                self._scroll[url] = window.scrollY
            except Exception:
                pass

    def _scroll_to(self, y):
        if in_browser and self.mode_name != "memory":
            try:
                window.scrollTo(0, y)
            except Exception:
                pass

    # -- preloading ------------------------------------------------------------------------------

    def preload(self, path, intent="preload"):
        """Run the preload functions of the routes `path` would match."""
        chain = match_routes(self.routes, Location(self.resolve(path)).pathname)
        for m in chain or []:
            if m.route.preload is not None:
                self._preload_one(m.route, m.params, intent)

    def _preload_one(self, route, params, intent):
        try:
            result = route.preload(dict(params), self.location.peek(), intent)
        except TypeError:
            result = route.preload(dict(params))
        if hasattr(result, "send") and hasattr(result, "throw"):
            from .reactive import spawn

            if intent == "navigate":
                self._inflight += 1
                result = self._tracked(result)
            spawn(result, None)

    # -- links -----------------------------------------------------------------------------------

    def _intercept_links(self):
        router = self

        def on_click(ev):
            if ev.defaultPrevented or ev.button != 0 or ev.metaKey or ev.ctrlKey or ev.shiftKey or ev.altKey:
                return
            node = ev.target
            while node is not None and getattr(node, "nodeType", 0) == 1 and str(node.tagName).lower() != "a":
                node = node.parentNode
            if node is None or getattr(node, "nodeType", 0) != 1:
                return
            href = node.getAttribute("href")
            if (
                not href
                or node.getAttribute("target")
                or node.hasAttribute("download")
                or node.getAttribute("rel") == "external"
            ):
                return
            if href.startswith("http://") or href.startswith("https://") or href.startswith("//"):
                return
            if router.mode_name == "hash":
                if not href.startswith("#"):
                    return
                href = href[1:] or "/"
            elif href.startswith("#"):
                return
            else:
                # An intercepted href is a document URL: take the base off before routing.
                loc = Location(href)
                href = router._strip_base(loc.pathname) + loc.search + loc.hash
            ev.preventDefault()
            router.navigate(href)

        proxy = create_proxy(on_click)
        document.addEventListener("click", proxy)
        on_cleanup(lambda: document.removeEventListener("click", proxy))

    def href(self, path):
        """The `href` attribute for a link to `path` in this mode."""
        target = self.resolve(path)
        return "#" + target if self.mode_name == "hash" else self._full(target)

    # -- actions ---------------------------------------------------------------------------------

    def action(self, fn):
        """An `Action` whose function may raise `Redirect` to navigate when it is done."""
        router = self

        async def run(*args):
            try:
                return await fn(*args)
            except Redirect as redirect:
                router.navigate(redirect.path, replace=redirect.replace)
                return None

        return Action(run)


class _LevelContext:
    def __init__(self, router, depth):
        self.router = router
        self.depth = depth

    def prefix(self):
        chain = self.router.matches()
        if chain is None or self.depth >= len(chain):
            return "/"
        return chain[self.depth].prefix or "/"

    def params(self):
        chain = self.router.matches()
        if chain is None or self.depth >= len(chain):
            return {}
        return dict(chain[self.depth].params)


# --- hooks -----------------------------------------------------------------------------------------------


def use_router():
    router = use(_ROUTER)
    if router is None:
        raise RuntimeError("no Router above this component")
    return router


def use_params():
    """An accessor of the merged params of the current match: `use_params()["id"]`."""
    return use_router().params


def use_query():
    router = use_router()
    return Memo(lambda: router.location().query)


def use_location():
    return use_router().location


def use_navigate():
    return use_router().navigate


def use_is_routing():
    return use_router().is_routing


def use_match(path):
    """An accessor: the params if the current URL matches `path` (relative to this level), else None."""
    router = use_router()
    target = router.resolve(path)
    pattern = _segments(target)

    def check():
        params = {}
        rest = _match_segments(pattern, _segments(router._strip_base(router.location().pathname)), params)
        return params if rest == [] else None

    return Memo(check)


def use_before_leave(fn):
    """`fn(to, from)` runs before every navigation; return False to cancel it."""
    router = use_router()
    router._guards.append(fn)
    on_cleanup(lambda: router._guards.remove(fn) if fn in router._guards else None)
    return fn


def use_submission(action):
    """The reactive state of an action: the Action itself (pending, value, input, error)."""
    return action


# --- components -----------------------------------------------------------------------------------------


def A(href, *children, active_class="active", end=False, **attrs):
    """A link: resolves `href` against the current route level, sets `active_class` while the
    location is within it (`end=True`: only on an exact match), and preloads on hover."""
    router = use_router()
    target = router.resolve(href)

    def is_active():
        path = router._strip_base(router.location().pathname)
        return path == target if end else (path == target or path.startswith(target.rstrip("/") + "/"))

    def on_hover(ev):
        router.preload(target)

    attrs.setdefault("href", router.href(target))
    return h.a(*children, **{f"class_{active_class}": is_active}, on_mouseenter=on_hover, **attrs)


def Navigate(to, replace=True):
    """Navigates to `to` when it mounts; renders nothing."""
    router = use_router()
    from .reactive import on_mount

    on_mount(lambda: router.navigate(to, replace=replace))
    return None


def ActionForm(action, *children, **attrs):
    """A `<form>` that submits its fields (as a dict) to `action` instead of reloading."""

    def on_submit(ev):
        ev.preventDefault()
        action.dispatch(form_data(ev.target))

    return h.form(*children, on_submit=on_submit, **attrs)


def form_data(form):
    """The named fields of a form as a dict (a list for repeated names)."""
    out = {}
    if in_browser and hasattr(form, "elements"):
        data = window.FormData.new(form)
        entries = data.entries()
        while True:
            item = entries.next()
            if item.done:
                break
            key, value = item.value[0], item.value[1]
            _add_field(out, str(key), str(value))
        return out
    for node in _walk(form):
        name = getattr(node, "attrs", {}).get("name")
        if name:
            props = getattr(node, "props", {})
            if node.attrs.get("type") in ("checkbox", "radio") and not props.get(
                "checked", node.attrs.get("checked", False)
            ):
                continue
            _add_field(out, name, props.get("value", node.attrs.get("value", "")))
    return out


def _add_field(out, key, value):
    if key in out:
        if isinstance(out[key], list):
            out[key].append(value)
        else:
            out[key] = [out[key], value]
    else:
        out[key] = value


def _walk(node):
    for child in getattr(node, "children", []):
        yield child
        for sub in _walk(child):
            yield sub


# --- query cache ------------------------------------------------------------------------------------------


class _Query:
    """A keyed cache over an async function: concurrent calls with the same arguments share
    one run; later calls return the cached value until `revalidate()`."""

    def __init__(self, fn, name=None):
        self.fn = fn
        self.name = name or getattr(fn, "__name__", "query")
        self.cache = {}
        self._running = {}

    async def __call__(self, *args):
        import asyncio

        key = args
        if key in self.cache:
            return self.cache[key]
        if key in self._running:
            await self._running[key].wait()
            if key in self.cache:
                return self.cache[key]
            raise RuntimeError(f"query {self.name}{key!r} failed")
        event = asyncio.Event()
        self._running[key] = event
        try:
            value = await self.fn(*args)
            self.cache[key] = value
            return value
        finally:
            self._running.pop(key, None)
            event.set()

    def revalidate(self, *args):
        """Forget one key, or everything."""
        if args:
            self.cache.pop(args, None)
        else:
            self.cache.clear()

    def key_for(self, *args):
        return args


def query(fn, name=None):
    return _Query(fn, name)
