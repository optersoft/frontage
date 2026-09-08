"""`python -m frontage prerender APP`: the app's pages as finished HTML, hydrated on load.

Builds the app (see `build`), then imports it on this CPython for each route, renders every
`mount` with the HTML renderer, waits for its resources and async memos, and writes the result into
the page's target element with the fences hydration reads, the settled values as JSON, and a
script that queues clicks and input until Python is ready. In the browser, `mount` finds the
`data-fr-hydrate` target and adopts the HTML instead of building it.

The app is imported with `frontage.runtime.prerender.active`: `mount(view, "#app")` registers,
the router starts at the route being rendered, `Portal` renders nothing. What the app touches
at import must exist on CPython (no `window`, no `pyscript`; those belong in effects and
handlers). Resource and async memo values must be JSON, and a failed load fails the build."""

import argparse
import asyncio
import importlib.util
import json
import re
import sys
from pathlib import Path

from . import PROG
from . import build as build_cli

# Queued until `mount` hydrates, then replayed on the same targets (see DomRenderer.end_hydration).
REPLAY = """<script>
(function(){var q=[],t=["click","input","change"],on=function(e){q.push([e.type,e.target])};
t.forEach(function(n){document.addEventListener(n,on,true)});
window.__frontage_replay=function(){t.forEach(function(n){document.removeEventListener(n,on,true)});
q.forEach(function(p){var n=p[1];if(n&&n.isConnected){n.dispatchEvent(p[0]==="click"?new MouseEvent("click",{bubbles:true,cancelable:true}):new Event(p[0],{bubbles:true}))}});q=[]};
})();
</script>
"""

# What a wasm page declares, and the whole of what the prerenderer has to read from it.
_BOOT_ENTRY = re.compile(r"""data-fr-entry\s*=\s*["']([\w.-]+)["']""")
# The PyScript page's entry, found by hunting inline JavaScript. Goes with `export` at 1.0.
_ENTRY = re.compile(r"""src\s*=\s*["']\./([\w./-]+\.py)["']""")


class Prerendered:
    """One route's output: the page HTML and, per mount, what went into it."""

    def __init__(self, path, html, mounts):
        self.path = path
        self.html = html
        # [(selector, inner html, values)]: the values are the resources' as a list, or a
        # dict {"resources": […], "memos": [[ordinal, value], …]} when async memos settled too.
        self.mounts = mounts


def import_app(entry, path="/"):
    """Import the app's entry module with prerendering on; returns the registered mounts."""
    from frontage import aio, view
    from frontage.runtime import prerender

    entry = Path(entry).resolve()
    prerender.active = True
    prerender.path = path
    prerender.mounts = []
    view._ids[0] = 0  # `unique_id` counts from the same point the browser will
    aio._begin_prerender()
    sys.path.insert(0, str(entry.parent))
    name = f"_frontage_app_{abs(hash((str(entry), path)))}"
    try:
        spec = importlib.util.spec_from_file_location(name, entry)
        assert spec is not None and spec.loader is not None, entry
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(entry.parent))
        sys.modules.pop(name, None)
        prerender.active = False
    return list(prerender.mounts)


async def render_mount(view, debug, fallback, timeout, selector="#app"):
    """Render one registered mount to `(html, values)`, resources and async memos settled.
    The values are the resources' as a list, or a dict with the memos' too (see `Prerendered`)."""
    from frontage import aio, reactive
    from frontage.aio import ERRORED, PENDING, REFRESHING
    from frontage.renderer import HtmlRenderer
    from frontage.view import mount

    registry = aio._begin_prerender()
    memos = reactive._begin_prerender()
    renderer = HtmlRenderer(hydration_markers=True)
    root = renderer.create_element("div")
    # `scope`: `unique_id` counts per mount, named after the target, exactly as the browser will.
    handle = mount(view, root, renderer, debug=debug, fallback=fallback, scope=selector.lstrip("#"))
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while (
            any(r.state() in (PENDING, REFRESHING) and not _gone(r) for r in registry)
            or any(m.loading() for m in memos)
            or any(m.loading() for m in reactive._memo_started or [])
        ):
            if loop.time() > deadline:
                raise TimeoutError(f"resources still loading after {timeout}s")
            await asyncio.sleep(0.005)
        failed = [r for r in registry if r.state() == ERRORED and not _gone(r)]
        if failed:
            raise RuntimeError(f"resource #{registry.index(failed[0])} failed: {failed[0].error()!r}")
        for ordinal, memo in enumerate(memos):
            if memo.is_async() and memo.error() is not None:
                raise RuntimeError(f"async memo #{ordinal} failed: {memo.error()!r}")
        html = "".join(child.to_html(comments=True) for child in root.children)
        if 'class="frontage-error"' in html:
            raise RuntimeError("the view raised while rendering:\n" + _error_text(html))
        values = [r.peek() for r in registry]
        settled = [[ordinal, memo.peek()] for ordinal, memo in enumerate(memos) if memo.is_async()]
        if settled:
            values = {"resources": values, "memos": settled}
        try:
            json.dumps(values)
        except TypeError as exc:
            raise RuntimeError(f"a settled value is not JSON ({exc}); hydration needs JSON values") from None
        return html, values
    finally:
        handle.dispose()
        aio._end_prerender()
        reactive._end_prerender()


def _gone(resource):
    """A resource whose owner was disposed mid-render (a branch that went away) never settles."""
    owner = getattr(resource, "_owner", None)
    return owner is not None and getattr(owner, "_disposed", False)


def _error_text(html):
    import html as html_module

    match = re.search(r'<pre class="frontage-error">(.*?)</pre>', html, re.S)
    return html_module.unescape(match.group(1)) if match else html


def find_entry(page_html):
    """The app's Python file, as the page names it.

    A wasm page says so outright, in the boot tag's `data-fr-entry`. The attribute exists
    because the old way — hunting `src="./app.py"` through inline JavaScript with a regex —
    could only guess, and guessed from a string that was not addressed to it.

    A PyScript page still gets the regex, until the academy's chapters move off it.
    """
    attribute = _BOOT_ENTRY.search(page_html)
    if attribute:
        return attribute.group(1) + ".py"
    match = _ENTRY.search(page_html)
    return match.group(1) if match else None


def inject(page_html, selector, inner, values):
    """`page_html` with the element `selector` (an id) holding `inner`, marked for
    hydration, followed by the settled values (resources, async memos) when there are any."""
    if not selector.startswith("#") or not re.fullmatch(r"#[\w-]+", selector):
        raise ValueError(f"prerender mounts into an element by id (`#app`), not {selector!r}")
    element_id = selector[1:]
    span = _element_span(page_html, element_id)
    if span is None:
        raise ValueError(f"no element with id {element_id!r} in the page")
    open_start, open_end, close_start, close_end = span
    opening = page_html[open_start:open_end]
    if "data-fr-hydrate" not in opening:
        opening = opening[:-1] + " data-fr-hydrate>"
    data = ""
    if values:
        text = json.dumps(values, separators=(",", ":")).replace("</", "<\\/")
        data = f'<script type="application/json" data-fr-data="{element_id}">{text}</script>'
    return page_html[:open_start] + opening + inner + page_html[close_start:close_end] + data + page_html[close_end:]


def _element_span(page_html, element_id):
    """(start of the opening tag, its end, start of the closing tag, its end)."""
    from html.parser import HTMLParser

    lines = page_html.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)

    class Find(HTMLParser):
        def __init__(self):
            HTMLParser.__init__(self)
            self.depth = None
            self.tag = None
            self.span = None

        def _offset(self):
            line, col = self.getpos()
            return offsets[line - 1] + col

        def handle_starttag(self, tag, attrs):
            if self.span is not None:
                return
            if self.depth is None:
                if dict(attrs).get("id") == element_id:
                    self.depth = 0
                    self.tag = tag
                    start = self._offset()
                    self.open = (start, start + len(self.get_starttag_text() or ""))
            elif tag == self.tag:
                self.depth += 1

        def handle_endtag(self, tag):
            if self.depth is None or self.span is not None or tag != self.tag:
                return
            if self.depth == 0:
                start = self._offset()
                end = page_html.index(">", start) + 1
                self.span = (self.open[0], self.open[1], start, end)
            else:
                self.depth -= 1

    finder = Find()
    finder.feed(page_html)
    finder.close()
    return finder.span


def add_replay(page_html):
    if "__frontage_replay" in page_html:
        return page_html
    if "</head>" in page_html:
        return page_html.replace("</head>", REPLAY + "</head>", 1)
    return REPLAY + page_html


_HREF = re.compile(r"""href\s*=\s*["']([^"']*)["']""")


def links_in(inner_html, view):
    """The app paths the rendered HTML links to, for `--crawl`: same-app hrefs, a route of
    the mounted `Router` when the view is one (in hash mode, the part after `#`)."""
    from frontage.router import Router, match_routes

    router = view if isinstance(view, Router) else None
    found = []
    for href in _HREF.findall(inner_html):
        href = href.strip()
        if not href or href.startswith(("http:", "https:", "//", "mailto:", "tel:", "javascript:", "data:")):
            continue
        if router is not None and router.mode_name == "hash":
            if not href.startswith("#/"):
                continue
            path = href[1:]
        else:
            if href.startswith("#"):
                continue
            path = href
        path = path.split("?", 1)[0].split("#", 1)[0]
        if not path.startswith("/"):
            continue
        if router is not None:
            path = router._strip_base(path)
            if match_routes(router.routes, path) is None:
                continue
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        if path not in found:
            found.append(path)
    return found


def relocate(page_html, depth):
    """Relative `./` references in a page written `depth` directories below the app."""
    if depth == 0:
        return page_html
    return re.sub(r"""(["'])\./""", lambda m: m.group(1) + "../" * depth, page_html)


def prerender(
    app,
    out=None,
    routes=("/",),
    entry=None,
    timeout=30.0,
    quiet=True,
    crawl=False,
    limit=1000,
):
    """Build `app` into `out` and write its prerendered pages there; returns the outputs.
    With `crawl`, every route a rendered page links to (an `A`, a plain `<a href>`) is rendered
    too, until no new one turns up or `limit` pages are written.

    Prerendering runs on this CPython and writes HTML; the page then boots the runtime and
    hydrates."""
    out = Path(out).resolve() if out else Path.cwd() / "build" / Path(app).resolve().name
    out = build_cli.build(app, out, entry=(entry or "").removesuffix(".py"), quiet=quiet)
    page = (out / "index.html").read_text()
    entry = entry or find_entry(page)
    if entry is None:
        raise ValueError("cannot tell which .py the page runs; pass --entry")
    entry_path = Path(app).resolve() / entry
    if not entry_path.exists():
        raise FileNotFoundError(f"{entry_path} does not exist")
    results = []
    queue = list(routes)
    seen = set(queue)
    while queue:
        route = queue.pop(0)
        mounts = import_app(entry_path, route)
        if not mounts:
            raise RuntimeError(f"{entry} never called mount(view, '#id') while importing for {route}")
        html = page
        rendered = []
        for selector, view, debug, fallback in mounts:
            inner, values = asyncio.run(render_mount(view, debug, fallback, timeout, selector))
            html = inject(html, selector, inner, values)
            rendered.append((selector, inner, values))
            if crawl:
                for path in links_in(inner, view):
                    if path not in seen and len(seen) < limit:
                        seen.add(path)
                        queue.append(path)
        html = add_replay(html)
        parts = [p for p in route.strip("/").split("/") if p]
        target = out.joinpath(*parts) / "index.html" if parts else out / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(relocate(html, len(parts)))
        results.append(Prerendered(route, html, rendered))
    return results


def _count(values):
    if isinstance(values, dict):
        return len(values.get("resources") or []) + len(values.get("memos") or [])
    return len(values)


def main(argv=None):
    parser = argparse.ArgumentParser(prog=f"{PROG} prerender", description=__doc__)
    parser.add_argument("app", help="a directory with an index.html and the app's .py files")
    parser.add_argument("--out", default=None, help="destination (default: ./build/<app name>)")
    parser.add_argument("--route", action="append", default=None, help="a path to render (repeatable; default /)")
    parser.add_argument("--entry", default=None, help="the app's .py file (default: the one the page names)")
    parser.add_argument(
        "--crawl", action="store_true", help="also render every route a rendered page links to (A, <a href>)"
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for resources per route")
    args = parser.parse_args(argv)
    try:
        results = prerender(
            args.app,
            args.out,
            routes=tuple(args.route or ["/"]),
            entry=args.entry,
            timeout=args.timeout,
            quiet=False,
            crawl=args.crawl,
        )
    except (FileNotFoundError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out).resolve() if args.out else Path.cwd() / "build" / Path(args.app).resolve().name
    for result in results:
        settled = sum(_count(values) for _, _, values in result.mounts)
        print(f"prerendered {result.path}: {len(result.mounts)} mount(s), {settled} settled value(s)")
    print(f"written to {out}; serve it with any static file server")
    return 0


if __name__ == "__main__":
    sys.exit(main())
