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
import html as html_module
import importlib.util
import json
import re
import sys
from pathlib import Path

from .. import head
from . import PROG
from . import build as build_cli

# Queued until `mount` hydrates, then replayed on the same targets (see DomRenderer.end_hydration).
#
# `__frontage_replay(root)` replays only what happened inside `root` and keeps listening; that
# is what an island page needs, because its islands hydrate one at a time and the queue must
# survive the first of them. Without an argument — an app's whole-page mount — it replays
# everything and stops, which is the original behaviour. It also stops on its own once no
# `<fr-island>` on the page is still waiting, so a page of islands does not capture for ever;
# a trigger that never fires (an unmatched `media:`) is why the queue is capped as well.
REPLAY = """<script>
(function(){var q=[],c=100,t=["click","input","change"],on=function(e){if(q.length<c)q.push([e.type,e.target])};
t.forEach(function(n){document.addEventListener(n,on,true)});
var stop=function(){t.forEach(function(n){document.removeEventListener(n,on,true)});q=[]};
window.__frontage_replay=function(root){var keep=[];
q.forEach(function(p){var n=p[1];
if(root&&!(n&&root.contains&&root.contains(n))){keep.push(p);return}
if(n&&n.isConnected){n.dispatchEvent(p[0]==="click"?new MouseEvent("click",{bubbles:true,cancelable:true}):new Event(p[0],{bubbles:true}))}});
q=keep;
if(!root||!document.querySelector("fr-island[data-fr-island]:not([data-fr-mounted])"))stop()};
})();
</script>
"""

# What a wasm page declares, and the whole of what the prerenderer has to read from it.
_BOOT_ENTRY = re.compile(r"""data-fr-entry\s*=\s*["']([\w.-]+)["']""")
# The PyScript page's entry, found by hunting inline JavaScript. Goes with `export` at 1.0.
_ENTRY = re.compile(r"""src\s*=\s*["']\./([\w./-]+\.py)["']""")


class Prerendered:
    """One route's output: the page HTML and, per mount, what went into it."""

    def __init__(self, path, html, mounts, islands=(), static=False):
        self.path = path
        self.html = html
        # [(selector, inner html, values)]: the values are the resources' as a list, or a
        # dict {"resources": […], "memos": [[ordinal, value], …]} when async memos settled too.
        self.mounts = mounts
        # [(spec, when)] for the islands on this page, and whether the page itself is static:
        # rendered once, no boot tag, no runtime unless an island's trigger asks for one.
        self.islands = list(islands)
        self.static = static


def import_app(entry, path="/"):
    """Import the app's entry module with prerendering on; returns the registered mounts."""
    from frontage import aio, view
    from frontage.runtime import prerender

    entry = Path(entry).resolve()
    prerender.active = True
    prerender.path = path
    prerender.mounts = []
    prerender.islands = []
    prerender.static = False
    prerender.entry = entry.stem
    prerender.app = str(entry.parent)  # where `frontage.content` looks for `content/`
    view._ids[0] = 0  # `unique_id` counts from the same point the browser will
    aio._begin_prerender()
    sys.path.insert(0, str(entry.parent))
    # A private name, so each route re-runs the entry rather than reusing the last one's
    # module — and recorded, because an island's spec must name the module the *page* knows
    # (`app`), not this one.
    name = f"_frontage_app_{abs(hash((str(entry), path)))}"
    prerender.entry_module = name
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


async def render_mount(view, debug, fallback, timeout, selector="#app", static=False, scope=None):
    """Render one registered mount to `(html, values)`, resources and async memos settled.
    The values are the resources' as a list, or a dict with the memos' too (see `Prerendered`)."""
    from frontage import aio, reactive
    from frontage.aio import ERRORED, PENDING, REFRESHING
    from frontage.renderer import HtmlRenderer
    from frontage.runtime import prerender as _prerender
    from frontage.view import mount

    registry = aio._begin_prerender()
    memos = reactive._begin_prerender()
    renderer = HtmlRenderer(hydration_markers=True)
    root = renderer.create_element("div")
    # `static`: an `island` inside a `when="never"` page registers itself instead of
    # rendering, so the prerenderer can give it a pass — and a data block — of its own.
    _prerender.static = static
    # `scope`: `unique_id` counts per mount, named after the target, exactly as the browser will.
    handle = mount(view, root, renderer, debug=debug, fallback=fallback, scope=scope or selector.lstrip("#"))
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
        # Taken before the dispose below: `Title` and `Meta` take their entry away with their
        # owner, exactly as they must in a browser, so after the dispose the page says nothing.
        # A list rather than a return value, because a page may hold several mounts and the
        # signature of this one is what two test modules read.
        heads.append(head.snapshot())
        return html, values
    finally:
        _prerender.static = False
        handle.dispose()
        aio._end_prerender()
        reactive._end_prerender()


# --- islands ------------------------------------------------------------------------------
#
# A `when="never"` mount is a static page: rendered here, written as HTML, and never
# hydrated. The islands inside it registered themselves instead of rendering (see
# `frontage.island`), and each gets a pass of its own — its own resources, its own memos, its
# own `unique_id` scope, its own data block — because in the browser each is its own `mount`.
# The wrapper it left behind carries `data-fr-index`, and that is where its HTML goes back in.


async def render_islands(registrations, timeout, debug=True):
    """Render each registered island; returns `[(island, html, values)]`.

    An `only` island is the exception, and the exception is its whole point: it is not
    rendered here at all, so its wrapper goes into the page empty and the browser builds it
    from nothing. That is for a component with no server-side meaning — one that reads the
    document, a canvas, a clock — where prerendering it would put something on screen that
    the first frame then has to throw away.
    """
    out = []
    for entry in registrations:
        if entry.when == "only":
            out.append((entry, "", None))
            continue
        html, values = await render_mount(entry.view(), debug, None, timeout, selector=f"#{entry.id}", scope=entry.id)
        out.append((entry, html, values))
    return out


def splice_islands(page_html, rendered):
    """Put each island's HTML inside its wrapper, and its settled values beside it."""
    from frontage.island import TAG

    for entry, inner, values in rendered:
        tail = f' data-fr-index="{entry.index}"></{TAG}>'
        if tail not in page_html:
            raise RuntimeError(f"island {entry.spec}: its wrapper is not in the rendered page")
        data = ""
        if values:
            text = json.dumps(values, separators=(",", ":")).replace("</", "<\\/")
            data = f'<script type="application/json" data-fr-data="{entry.id}">{text}</script>'
        page_html = page_html.replace(tail, f' data-fr-index="{entry.index}">{inner}</{TAG}>{data}', 1)
    return page_html


# The tag `build` wrote, and the preload hints that go with it: a static page needs none of
# them, and leaving them in is exactly the 265 KB this release exists to stop shipping.
_BOOT_TAG = re.compile(r"""[ \t]*<script[^>]*\bdata-fr-boot\b[^>]*>\s*</script>[ \t]*\n?""", re.I)
_HINT = re.compile(
    r"""[ \t]*<link[^>]*href=["\']\.[^"\']*_frontage/(?:boot\.js|glue\.js|frontage[^"\']*\.wasm)["\'][^>]*>[ \t]*\n?""",
    re.I,
)
_FR_JS = re.compile(r"""\bdata-fr-js\s*=\s*["\']([^"\']*)["\']""", re.I)


def island_script(page_html, prefix="./"):
    """`page_html` with the boot tag and its hints gone, and the island loader in their place.

    The loader is the only script such a page carries: about a kilobyte, no imports of its
    own, and nothing else fetched until a trigger fires. Whatever the boot tag declared with
    `data-fr-js` moves onto it, since a component's JavaScript is still the island's to use.

    `prefix` is where `_frontage/` is from the page: `./` for an app, whose pages are
    relocated by depth, and `/` for a site, whose references are root-absolute — a page at
    `/blog/a-post/` asking for `./_frontage/island.js` asks two directories too deep.
    """
    tag = _BOOT_TAG.search(page_html)
    declarations = ""
    if tag is not None:
        found = _FR_JS.search(tag.group(0))
        if found:
            declarations = f' data-fr-js="{found.group(1)}"'
        page_html = page_html[: tag.start()] + page_html[tag.end() :]
    page_html = _HINT.sub("", page_html)
    script = f'<script type="module" src="{prefix}_frontage/island.js" data-fr-islands{declarations}></script>'
    if script in page_html:
        return page_html
    return page_html.replace("</body>", f"{script}\n</body>", 1) if "</body>" in page_html else page_html + script


def strip_boot(page_html):
    """`page_html` with the boot tag and its preload hints gone: a page with nothing to boot."""
    return _HINT.sub("", _BOOT_TAG.sub("", page_html))


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


def inject(page_html, selector, inner, values, hydrate=True):
    """`page_html` with the element `selector` (an id) holding `inner`, marked for
    hydration, followed by the settled values (resources, async memos) when there are any.

    With `hydrate=False` — a `when="never"` page — the HTML goes in and nothing else does:
    no marker, no data block, because nothing in the browser will ever come back for them.
    """
    if not selector.startswith("#") or not re.fullmatch(r"#[\w-]+", selector):
        raise ValueError(f"prerender mounts into an element by id (`#app`), not {selector!r}")
    element_id = selector[1:]
    span = _element_span(page_html, element_id)
    if span is None:
        raise ValueError(f"no element with id {element_id!r} in the page")
    open_start, open_end, close_start, close_end = span
    opening = page_html[open_start:open_end]
    if hydrate and "data-fr-hydrate" not in opening:
        opening = opening[:-1] + " data-fr-hydrate>"
    data = ""
    if values and hydrate:
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


#: What each mount said about itself, in render order, for the route being written.
heads = []


def _merge(snapshots):
    """Several mounts on one page: the last one to say something has the last word."""
    title, meta = None, []
    for snapshot in snapshots:
        if snapshot.get("title") is not None:
            title = snapshot["title"]
        for item in snapshot.get("meta") or []:
            meta = [kept for kept in meta if kept[:2] != item[:2]] + [item]
    return {"title": title, "meta": meta}


def apply_head(page_html, head):
    """`page_html` with the title and meta tags the page set through `frontage.head`.

    A crawler, a link preview and a search result read this HTML and never run the page, so a
    per-route title has to be *in* it. An existing `<title>` is replaced and an existing meta
    tag of the same name is rewritten, so the static page keeps whatever it says by hand and
    the app has the last word on what it set itself.
    """
    title = head.get("title")
    if title is not None:
        text = html_module.escape(str(title))
        if re.search(r"<title\b[^>]*>.*?</title>", page_html, re.I | re.S):
            page_html = re.sub(
                r"<title\b[^>]*>.*?</title>", f"<title>{text}</title>", page_html, count=1, flags=re.I | re.S
            )
        else:
            page_html = _into_head(page_html, f"<title>{text}</title>")
    for attribute, name, content in head.get("meta") or []:
        tag = f'<meta {attribute}="{html_module.escape(name, quote=True)}" content="{html_module.escape(str(content), quote=True)}">'
        pattern = rf"<meta\b[^>]*\b{attribute}\s*=\s*[\"\']{re.escape(name)}[\"\'][^>]*>"
        if re.search(pattern, page_html, re.I):
            page_html = re.sub(pattern, tag, page_html, count=1, flags=re.I)
        else:
            page_html = _into_head(page_html, tag)
    return page_html


def _into_head(page_html, tag):
    for closing in ("</head>", "</body>"):
        i = page_html.lower().find(closing)
        if i >= 0:
            return page_html[:i] + tag + page_html[i:]
    return tag + page_html


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
    name = (entry or "").removesuffix(".py")
    out = build_cli.build(app, out, entry=name, quiet=quiet)
    page = (out / "index.html").read_text()
    entry = entry or find_entry(page)
    if entry is None:
        raise ValueError("cannot tell which .py the page runs; pass --entry")
    entry_path = Path(app).resolve() / entry
    if not entry_path.exists():
        raise FileNotFoundError(f"{entry_path} does not exist")
    queue = list(routes)
    seen = set(queue)
    # The app's directory stays on the path for the whole run: an island named by a string
    # (`island("charts:sparkline")`) is imported when its own pass renders it, which is long
    # after `import_app` has put the path back the way it found it.
    sys.path.insert(0, str(entry_path.parent))
    try:
        pages = _render_routes(entry, entry_path, queue, seen, timeout, crawl, limit)
    finally:
        sys.path.remove(str(entry_path.parent))
    # What the render found that the import walk could not: an island named in Markdown. The
    # build is run again with those specs, so their modules are chunks and `frontage.island`
    # — which the boot runs on a page of islands — is in the payload. `compile_module` is
    # cached by mtime, so the second pass compiles only what is new.
    specs = sorted({island.spec for rendered in pages for island in rendered.islands})
    if specs and _unbuilt(out, specs):
        static = all(rendered.static for rendered in pages)
        out = build_cli.build(app, out, entry=entry.removesuffix(".py"), quiet=True, islands=specs, static=static)
        page = (out / "index.html").read_text()
    return [_write(out, page, rendered) for rendered in pages]


def _unbuilt(out, specs):
    """Is any island's module missing from the manifest the build just wrote?"""
    from . import frontage_rt

    try:
        manifest = json.loads((out / "_frontage" / frontage_rt.MANIFEST).read_text())
    except (OSError, ValueError):
        return True
    known = set(manifest.get("modules") or [])
    known.update(name for names in (manifest.get("chunks") or {}).values() for name in names)
    if frontage_rt.ISLAND_MODULE not in known:
        return True
    return any(spec.partition(":")[0] not in known for spec in specs)


def _render_routes(entry, entry_path, queue, seen, timeout, crawl, limit):
    """Render every queued route, and whatever `--crawl` finds; nothing is written yet.

    Writing waits because rendering is what discovers the islands: an `::: island` container
    in a Markdown file names a module in prose, and no amount of reading the app's imports
    finds it. The build has to be told, and it can only be told afterwards.
    """
    from frontage.runtime import prerender as prerender_state

    pages = []
    while queue:
        route = queue.pop(0)
        head.forget()  # each route says what it says; nothing carries over from the last
        del heads[:]
        mounts = import_app(entry_path, route)
        if not mounts:
            raise RuntimeError(f"{entry} never called mount(view, '#id') while importing for {route}")
        rendered = []
        prerender_state.islands = []
        static = bool(mounts) and all(when == "never" for *_, when in mounts)
        for selector, view, debug, fallback, when in mounts:
            live = when != "never"
            inner, values = asyncio.run(render_mount(view, debug, fallback, timeout, selector, static=not live))
            rendered.append((selector, inner, values, live))
            if crawl:
                for path in links_in(inner, view):
                    if path not in seen and len(seen) < limit:
                        seen.add(path)
                        queue.append(path)
        islands = list(prerender_state.islands)
        drawn = asyncio.run(render_islands(islands, timeout)) if islands else []
        pages.append(_Page(route, rendered, islands, drawn, _merge(heads), static))
    return pages


class _Page:
    """One route, rendered and not yet written."""

    def __init__(self, route, mounts, islands, drawn, head, static):
        self.route = route
        self.mounts = mounts  # [(selector, inner html, values, live)]
        self.islands = islands
        self.drawn = drawn  # [(island, html, values)]
        self.head = head
        self.static = static


def _write(out, page_html, rendered):
    """Assemble one rendered route into the page and write it where its path says."""
    html = page_html
    for selector, inner, values, live in rendered.mounts:
        html = inject(html, selector, inner, values, hydrate=live)
    if rendered.drawn:
        html = splice_islands(html, rendered.drawn)
    html = apply_head(html, rendered.head)
    if rendered.static:
        # Zero by default: a page whose every mount is `when="never"` gets the island
        # loader if anything on it is an island, and otherwise not one byte of script.
        html = island_script(html) if rendered.islands else strip_boot(html)
    if not rendered.static or rendered.islands:
        html = add_replay(html)
    parts = [p for p in rendered.route.strip("/").split("/") if p]
    target = out.joinpath(*parts) / "index.html" if parts else out / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(relocate(html, len(parts)))
    return Prerendered(
        rendered.route,
        html,
        [(s, i, v) for s, i, v, _ in rendered.mounts],
        [(i.spec, i.when) for i in rendered.islands],
        rendered.static,
    )


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
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    try:
        results = prerender(
            args.app,
            args.out,
            routes=tuple(args.route or ["/"]),
            entry=args.entry,
            timeout=args.timeout,
            quiet=args.quiet,
            crawl=args.crawl,
        )
    except (FileNotFoundError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.quiet:
        return 0
    out = Path(args.out).resolve() if args.out else Path.cwd() / "build" / Path(args.app).resolve().name
    for result in results:
        settled = sum(_count(values) for _, _, values in result.mounts)
        islands = f", {len(result.islands)} island(s)" if result.islands else ""
        static = " (static: no boot tag)" if result.static else ""
        print(f"prerendered {result.path}: {len(result.mounts)} mount(s), {settled} settled value(s){islands}{static}")
    print(f"written to {out}; serve it with any static file server")
    return 0


if __name__ == "__main__":
    sys.exit(main())
