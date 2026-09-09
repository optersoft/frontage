"""`python -m frontage site DIR`: a directory of pages as a directory of files.

A site is `pages/`, and the tree is the site map:

    site/
      pages/
        index.py            → /
        about.py            → /about/
        blog/index.py       → /blog/
        blog/[slug].py      → /blog/<slug>/, one per `static_paths()`
        docs/[...path].py   → /docs/<anything>/, one per `static_paths()`
        sitemap.xml.py      → /sitemap.xml, an endpoint
      layouts/site.py       a component taking `children`; no new concept
      content/posts/*.md    a collection (`frontage.content`)
      public/               copied as it is
      site.py               optional: `redirects()`, `BASE`

A **page** module defines `page(**params)` returning a view, and a dynamic one — a file whose
name is `[slug]` or `[...path]` — also defines `static_paths()` returning the params to build,
which is Astro's `getStaticPaths` in Python. An **endpoint** defines `get()` instead, returning
a string or bytes, or `(body, content_type)`; it is written at its own name, so `sitemap.xml.py`
is `/sitemap.xml`. A page that takes an argument named `site` is handed the same object an
endpoint is: `pages` (every URL the build made) and `base`.

Every page is rendered on CPython, and **a page with nothing interactive on it ships no
runtime**: no boot tag, no manifest, not one request under `_frontage/`. What comes alive is
the `island`s in it (`frontage.island`), each on a trigger of its own, and the runtime is
written once, beside the pages, only if some page has one.
"""

import argparse
import inspect
import re
import shutil
import sys
from pathlib import Path

from . import PROG, frontage_rt
from . import build as build_cli

#: The one parameter name the build knows something about: the locale. `pages/[lang]/…` is
#: the tree §3.5 of ISLAND.md describes, and the *default* locale contributes no segment, so
#: English lives at `/` and Spanish at `/es/` — which is what a site with a main language
#: actually wants, and what Astro spells `prefixDefaultLocale: false`.
LOCALE = "lang"

PAGES = "pages"
LAYOUTS = "layouts"
PUBLIC = "public"
CONFIG = "site.py"
TEMPLATE = "index.html"

#: The document every page goes into when the site has no `index.html` of its own. The body
#: *is* the mount target, so a page's own markup is the body's children and no wrapper div
#: stands between the layout and the document.
DEFAULT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{title}</title>
</head>
<body id="app">
</body>
</html>
"""

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".*")


class SiteError(Exception):
    """A site that cannot be built, said in one sentence a person can act on."""


class Site:
    """What a page or an endpoint is handed when it asks: the URLs, the locales, the site's own.

    `LOCALES` in `site.py` is a list whose **first entry is the default**, and the default
    contributes no URL segment: `["en", "es", "ca"]` makes `/`, `/es/` and `/ca/`.
    """

    def __init__(self, base="", pages=(), locales=()):
        self.base = base.rstrip("/")
        self.pages = list(pages)
        self.locales = list(locales)

    @property
    def default_locale(self):
        return self.locales[0] if self.locales else None

    def url(self, path):
        """An absolute URL for a path, when `BASE` is set; the path itself when it is not."""
        return f"{self.base}{path}" if self.base else path

    def paths(self, name=LOCALE):
        """`static_paths()` for a `pages/[lang]/…` tree: one build per locale."""
        return [{name: locale} for locale in self.locales]

    def locale_of(self, path):
        """Which locale a path is in, by its first segment; the default when it has none."""
        first = path.strip("/").split("/")[0] if path.strip("/") else ""
        return first if first in self.locales and first != self.default_locale else self.default_locale

    def translate(self, path, locale):
        """The same page in another locale: `/es/blog/` and `en` is `/blog/`.

        A path, not a guess — every URL the build made is in `pages`, so a language switcher
        can be plain links, and on a static site it should be: a switcher that is an island
        makes the reader wait for a runtime to follow a link the page already knows.
        """
        current = self.locale_of(path)
        rest = path
        if current != self.default_locale:
            rest = "/" + path.strip("/")[len(current) :].lstrip("/")
        if not rest.endswith("/"):
            rest += "/"
        if locale == self.default_locale:
            return rest
        return f"/{locale}{rest}" if rest != "/" else f"/{locale}/"

    def alternates(self, path):
        """`[(locale, path)]` for every locale this page exists in, the current one included."""
        found = []
        for locale in self.locales:
            other = self.translate(path, locale)
            if not self.pages or other in self.pages:
                found.append((locale, other))
        return found

    def __repr__(self):
        return f"<Site {self.base or '(no BASE)'}: {len(self.pages)} pages, {len(self.locales)} locales>"


# --- the routes a directory describes ---------------------------------------------------------


class Route:
    """One file under `pages/`, and the URL or URLs it makes."""

    def __init__(self, path, root):
        self.path = Path(path)
        self.relative = self.path.relative_to(root)
        self.module = None

    @property
    def name(self):
        """A dotted name for the module, unique per file and never imported by it."""
        return "_frontage_page_" + "_".join(_slug(part) for part in self.relative.with_suffix("").parts)

    @property
    def parts(self):
        """The URL segments before the file's own, e.g. `blog` for `pages/blog/[slug].py`."""
        return list(self.relative.parts[:-1])

    @property
    def stem(self):
        return self.relative.stem

    @property
    def is_endpoint(self):
        """`sitemap.xml.py` is one by its name; anything else is one by defining `get`.

        A bracketed name is never one, whatever it looks like: `[...path]` has a dot in it,
        so `Path.suffix` finds `.path]` and calls a rest route a file called `path]`.
        """
        if self.parameter is not None:
            return False
        return bool(Path(self.stem).suffix) or (self.module is not None and hasattr(self.module, "get"))

    @property
    def parameter(self):
        """`slug` for `[slug].py`, `path` for `[...path].py`, else None."""
        return _parameter(self.stem)

    @property
    def parameters(self):
        """Every parameter in the path, directories first: `pages/[lang]/blog/[slug].py` is
        `["lang", "slug"]`, and `static_paths()` returns a dict with both in it."""
        found = [_parameter(part) for part in self.parts]
        return [name for name in found + [self.parameter] if name]

    @property
    def rest(self):
        """Does `[...path]` swallow the rest of the URL?"""
        return self.stem.startswith("[...")

    def url(self, params=None, default_locale=None):
        """The URL this file makes, for these params.

        A `[lang]` segment whose value is the default locale contributes nothing, so the main
        language is at `/` and the others under `/es/`, `/ca/`.

        A page module may set `PATH` to say where it goes instead. A URL that does not end in
        `/` is written as **that file** rather than as `<url>/index.html`, which is how a site
        gets a `404.html` — the file a static host serves, with a 404 status, for a path that
        matches nothing.
        """
        fixed = getattr(self.module, "PATH", None) if self.module is not None else None
        if fixed:
            return fixed if fixed.startswith("/") else "/" + fixed
        params = params or {}
        parts = []
        for part in self.parts:
            parts += self._segment(part, params, default_locale)
        if self.is_endpoint:
            return "/" + "/".join(parts + [self.stem])
        if self.parameter is not None:
            parts += self._segment(self.stem, params, default_locale)
        elif self.stem != "index":
            parts.append(self.stem)
        return "/" + "".join(part + "/" for part in parts)

    def _segment(self, part, params, default_locale):
        name = _parameter(part)
        if name is None:
            return [part]
        value = str(params.get(name, "")).strip("/")
        if name == LOCALE and value and value == default_locale:
            return []
        if not value:
            raise SiteError(f"{self.relative}: static_paths() gave no {name!r} for one of its pages")
        return value.split("/")


def _parameter(part):
    """`slug` for `[slug]`, `path` for `[...path]`, None for a literal segment."""
    if part.startswith("[") and part.endswith("]"):
        return part[1:-1].lstrip(".")
    return None


def _slug(part):
    return "".join(c if c.isalnum() else "_" for c in part)


def routes(root):
    """Every page and endpoint under `pages/`, in the order a person would list them."""
    pages = Path(root) / PAGES
    if not pages.is_dir():
        raise SiteError(f"{Path(root)} is not a site: it has no {PAGES}/ directory")
    found = [
        Route(path, pages)
        for path in sorted(pages.rglob("*.py"))
        if "__pycache__" not in path.parts and path.name != "__init__.py"
    ]
    if not found:
        raise SiteError(f"{pages} has no pages: a page is a module with a `page()` in it")
    return found


# --- rendering ---------------------------------------------------------------------------------


def load(route, root):
    """Import one page module, with the site root on the path so `layouts.site` resolves.

    By file, not by name: `[slug].py` is not an identifier, and two `index.py` files in
    different directories are two modules however you spell it.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(route.name, route.path)
    if spec is None or spec.loader is None:
        raise SiteError(f"{route.relative}: cannot be imported")
    module = importlib.util.module_from_spec(spec)
    sys.modules[route.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(route.name, None)
        raise SiteError(f"{route.relative}: {type(exc).__name__}: {exc}") from exc
    route.module = module
    return module


def targets(route, site):
    """`[params]` for this route: one empty dict for a static page, `static_paths()` for a
    dynamic one — and a sentence rather than a traceback when a dynamic page has none.

    `static_paths()` may take `site`, which is how a `pages/[lang]/…` tree says "one per
    locale" without importing the site's own config: `return site.paths()`.
    """
    names = route.parameters
    if not names:
        return [{}]
    paths = getattr(route.module, "static_paths", None)
    if paths is None:
        bracketed = ", ".join(f"[{name}]" for name in names)
        raise SiteError(
            f"{route.relative}: a page with {bracketed} in its path is built once per value, "
            "so it needs a `static_paths()` returning the params — like Astro's getStaticPaths"
        )
    found = call(paths, {}, site)
    if not isinstance(found, (list, tuple)):
        raise SiteError(f"{route.relative}: static_paths() returns a list of dicts, not {type(found).__name__}")
    out = [dict(item) if isinstance(item, dict) else {names[-1]: item} for item in found]
    for params in out:
        missing = [name for name in names if name not in params]
        if missing:
            raise SiteError(f"{route.relative}: static_paths() left out {', '.join(missing)} for one of its pages")
    return out


def call(function, params, site):
    """Call a page or an endpoint with what it asked for: its params, and `site` if named."""
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function(**params)
    wanted = dict(params)
    if "site" in signature.parameters and "site" not in wanted:
        wanted["site"] = site
    return function(**wanted)


def render(route, params, url, root, site, timeout=30.0, debug=True):
    """One page: its view rendered to HTML, its islands rendered in passes of their own.

    Returns `(inner html, [(island, html, values)], head snapshot)`. The page is rendered the
    way a `when="never"` mount is — `static` is up, so an `island` in it registers instead of
    drawing — because that is what a page of a site *is*.
    """
    import asyncio

    from .. import head
    from ..runtime import prerender
    from ..view import _ids
    from . import prerender as prerender_cli

    function = getattr(route.module, "page", None)
    if function is None:
        raise SiteError(f"{route.relative}: a page module defines `page()` returning a view")
    head.forget()
    del prerender_cli.heads[:]
    _ids[0] = 0
    prerender.path = url
    prerender.app = str(root)
    prerender.islands = []
    # The page is *called inside the mount*, not before it: an `island` — in the page's own
    # code or in a `::: island` container in the Markdown it renders — registers only while
    # the static pass is up, and the static pass is what `render_mount` opens.
    try:
        inner, _ = asyncio.run(
            prerender_cli.render_mount(lambda: call(function, params, site), debug, None, timeout, "#app", static=True)
        )
    except SiteError:
        raise
    except Exception as exc:
        raise SiteError(f"{url} ({route.relative}): {type(exc).__name__}: {exc}") from exc
    islands = list(prerender.islands)
    drawn = asyncio.run(prerender_cli.render_islands(islands, timeout)) if islands else []
    return inner, islands, drawn, prerender_cli._merge(prerender_cli.heads)


def write_page(out, template, url, inner, islands, drawn, head, lang=None):
    """Assemble one page and write it at `<url>index.html`."""
    from . import prerender as prerender_cli

    html = prerender_cli.inject(set_lang(template, lang), "#app", inner, [], hydrate=False)
    if drawn:
        html = prerender_cli.splice_islands(html, drawn)
    html = prerender_cli.apply_head(html, head)
    # Zero by default: the loader only where an island is, and nothing at all where none is.
    # `/`, not `./`: a site's references are root-absolute, and a page at `/blog/a-post/`
    # asking for `./_frontage/island.js` asks two directories too deep.
    html = prerender_cli.island_script(html, "/") if islands else prerender_cli.strip_boot(html)
    if islands:
        html = prerender_cli.add_replay(html)
    target, _ = written_at(out, url)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Not `relocate`d, unlike an app's prerendered routes. A site's references are
    # root-absolute — it is served at a root, its links are `/blog/`, and `translate` answers
    # in the same shape — so rewriting `./` by depth would only reach what a *page* wrote:
    # `./counter/` on the gallery index at `/gallery/` became `../counter/`, and every card
    # on the page pointed one directory too high.
    target.write_text(html)
    return html


_HTML_TAG = re.compile(r"<html\b([^>]*)>", re.I)
_LANG_ATTR = re.compile(r"""\blang\s*=\s*["'][^"']*["']""", re.I)


def set_lang(template, lang):
    """`<html lang="es">` for a page in Spanish.

    A layout cannot reach the `<html>` element — it is above everything a page renders — and
    a page that says nothing here says "English" to a screen reader, to a translator and to a
    hyphenation engine, whatever else on it is Catalan. The build knows the locale from the
    `[lang]` in the path, so it writes it.
    """
    if not lang:
        return template
    match = _HTML_TAG.search(template)
    if match is None:
        return template
    attrs = match.group(1)
    attrs = _LANG_ATTR.sub(f'lang="{lang}"', attrs) if _LANG_ATTR.search(attrs) else f'{attrs} lang="{lang}"'
    return template[: match.start()] + f"<html{attrs}>" + template[match.end() :]


def written_at(out, url):
    """`(file, depth)` for a URL: `<url>/index.html` for a directory, the file itself for a
    `PATH` that names one — and how many directories deep it sits, which is what `relocate`
    and a stylesheet link need."""
    parts = [p for p in url.strip("/").split("/") if p]
    if url.endswith("/") or not parts:
        return (out.joinpath(*parts) / "index.html" if parts else out / "index.html"), len(parts)
    return out.joinpath(*parts), len(parts) - 1


def write_endpoint(out, route, site):
    """Run an endpoint and write what it returned at its own name."""
    function = getattr(route.module, "get", None)
    if function is None:
        raise SiteError(f"{route.relative}: an endpoint module defines `get()` returning its body")
    try:
        answer = call(function, {}, site)
    except Exception as exc:
        raise SiteError(f"{route.relative}: {type(exc).__name__}: {exc}") from exc
    body = answer[0] if isinstance(answer, tuple) else answer
    if isinstance(body, str):
        body = body.encode("utf-8")
    if not isinstance(body, (bytes, bytearray)):
        raise SiteError(f"{route.relative}: get() returns a string or bytes, not {type(body).__name__}")
    target = out.joinpath(*route.parts, route.stem)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(body))
    return target


# --- the assets a site's islands need -----------------------------------------------------------


def write_runtime(out, root, specs, quiet=True):
    """The runtime, the modules the islands need, and the manifest — written once, or not at all.

    The entry here is `frontage.island` itself: a site has no single module that mounts, and on
    a page of islands that is what the boot runs anyway. Each island's module is a chunk, so a
    page pays for the islands it has and a reader for the ones they reach.
    """
    if not specs:
        return []
    runtime = out / "_frontage"
    runtime.mkdir(parents=True, exist_ok=True)
    if not frontage_rt.available():
        raise SiteError("the runtime is missing from frontage/_runtime: run `mk runtime.build`")
    for name in ("glue.js", "boot.js", "island.js"):
        shutil.copy2(frontage_rt.RUNTIME_DIR / name, runtime / name)
    wasm_bytes = (frontage_rt.RUNTIME_DIR / "frontage.wasm").read_bytes()
    wasm_file = frontage_rt.hashed("frontage", wasm_bytes, "wasm")
    (runtime / wasm_file).write_bytes(wasm_bytes)

    found = list(build_cli.discover())
    installed = build_cli.required(root, found, sources=build_cli._browser_sources(root, found, specs))
    declarations, styles = [], []
    for component in installed:
        assets = runtime / "components" / component.name
        shutil.copytree(component.browser, assets, dirs_exist_ok=True)
        declarations.append(f"{component.name}=./_frontage/components/{component.name}/{build_cli.COMPONENT_ENTRY}")
        if (assets / build_cli.COMPONENT_STYLE).is_file():
            styles.append(f"./_frontage/components/{component.name}/{build_cli.COMPONENT_STYLE}")

    entry = frontage_rt.ISLAND_MODULE
    members, chunks, _ = frontage_rt.analyse(root, entry, installed, specs)
    files = {}
    for name, path in members:
        data = frontage_rt.compile_module(path)
        files[name] = frontage_rt.hashed(name, data, "fbc")
        (runtime / files[name]).write_bytes(data)
    (runtime / frontage_rt.MANIFEST).write_bytes(
        frontage_rt.manifest([n for n, _ in members], entry, files, wasm_file, chunks, islands=True)
    )
    if not (out / "_headers").exists():
        (out / "_headers").write_text(frontage_rt.HEADERS)
    if not quiet:
        print(f"{len(members)} modules for {len(specs)} island(s), {len(chunks)} chunk(s)")
    return declarations, styles


# --- the build ------------------------------------------------------------------------------------


def build(root, out=None, quiet=False, timeout=30.0, tailwind=False):
    """Build the site at `root` into `out`; returns the URLs it wrote."""
    root = Path(root).resolve()
    out = Path(out).resolve() if out else Path.cwd() / "dist" / root.name
    found = routes(root)
    config = _config(root)
    template = _template(root)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    # Before anything is imported: a module-level `collection("posts", Post)` in a page or in
    # a module it imports asks where `content/` is the moment it is read.
    from ..runtime import prerender

    prerender.app = str(root)
    sys.path.insert(0, str(root))
    try:
        for route in found:
            load(route, root)
        # The site is made in two halves: what the config says, so `static_paths(site)` can
        # ask for the locales, and then the URLs, which only exist once it has.
        site = Site(getattr(config, "BASE", ""), locales=getattr(config, "LOCALES", ()))
        pages = [
            (route, params, route.url(params, site.default_locale))
            for route in found
            if not route.is_endpoint
            for params in targets(route, site)
        ]
        site.pages = [url for _, _, url in pages]
        # The locale travels with the page: `<html lang>` is above everything a layout can
        # reach, so the build is what writes it.
        rendered = [
            (url, params.get(LOCALE), *render(route, params, url, root, site, timeout)) for route, params, url in pages
        ]
        endpoints = [write_endpoint(out, route, site) for route in found if route.is_endpoint]
    finally:
        sys.path.remove(str(root))
        for route in found:
            sys.modules.pop(route.name, None)
        _forget(root)

    specs = sorted({island.spec for _, _, _, islands, _, _ in rendered for island in islands})
    declarations, styles = write_runtime(out, root, specs, quiet=quiet) or ([], [])
    template = _declare(template, declarations, styles)
    for url, lang, inner, islands, drawn, head in rendered:
        write_page(out, template, url, inner, islands, drawn, head, lang)

    if (root / PUBLIC).is_dir():
        shutil.copytree(root / PUBLIC, out, dirs_exist_ok=True, ignore=IGNORE)
    _static(out, root, config)
    _redirects(out, config)
    if tailwind:
        link = build_cli.build_tailwind(root, out, quiet=quiet)
        for url, *_ in rendered:
            _link(out, url, link)
    if not quiet:
        total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
        extra = f", {len(endpoints)} endpoint(s)" if endpoints else ""
        extra += f", {len(specs)} island(s)" if specs else ", no runtime"
        print(f"{out}: {len(rendered)} page(s){extra}, {total:,} bytes")
    return [url for url, *_ in rendered]


def _forget(root):
    """Drop every module that came from under the site, so the next build re-reads them.

    A page's `from posts import posts` is an ordinary import and lands in `sys.modules`, and
    its module-level `collection("posts", Post)` reads the directory once. Left there, a dev
    rebuild renders the site the way it was when the server started — the pages come out
    fresh and their content does not, which looks like the watcher is broken.
    """
    root = str(Path(root).resolve())
    for name, module in list(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if origin and str(Path(origin).resolve()).startswith(root + "/"):
            sys.modules.pop(name, None)


def _config(root):
    """`site.py` at the root, if there is one: `BASE`, `redirects()`."""
    path = Path(root) / CONFIG
    if not path.is_file():
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location("_frontage_site_config", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise SiteError(f"{CONFIG}: {type(exc).__name__}: {exc}") from exc
    return module


def _template(root):
    """The document every page goes into: the site's `index.html`, or the default one.

    Its own `./` references are made root-absolute. The template is one file behind pages at
    every depth, so `./site.css` is right for `/` and a 404 for `/blog/a-post/` — and a
    missing stylesheet does not raise, it just renders the site unstyled. A *page's* `./` is
    the author's and is left alone.
    """
    path = Path(root) / TEMPLATE
    if path.is_file():
        html = path.read_text()
        if 'id="app"' not in html:
            raise SiteError(f'{TEMPLATE}: a site\'s template needs an element with id="app" for the page to go in')
        return _absolute(html)
    return DEFAULT_TEMPLATE.format(title=Path(root).name)


_RELATIVE = re.compile(r"""\b(href|src)\s*=\s*(["'])\./""")


def _absolute(html):
    return _RELATIVE.sub(lambda m: f"{m.group(1)}={m.group(2)}/", html)


def _declare(template, declarations, styles):
    """The components an island uses, on the template every page is made from."""
    for href in styles:
        link = f'<link rel="stylesheet" href="{href}">'
        if link not in template:
            template = template.replace("</head>", f"  {link}\n</head>", 1)
    if not declarations:
        return template
    # There is no boot tag on a site's template, so the declarations ride on a tag of their own
    # that `island_script` will find and move onto the loader.
    tag = build_cli.boot_tag("app", declarations=declarations)
    return template.replace("</body>", f"{tag}\n</body>", 1)


def _static(out, root, config):
    """`STATIC` in `site.py`: directories from outside the site, copied in.

    `public/` is the site's own files. A **package's** are not the site's — a shared chrome
    brings a stylesheet, four font files and a favicon, and none of them belong in a site's
    repository — so a site names where they are and where they should land:

        import optersoft_brand
        STATIC = [(optersoft_brand.static, "brand")]     # → /brand/…

    A bare path lands at the root. Nothing is *discovered*: a directory that ends up in the
    output is one the site asked for by name, which is the difference between assets and
    surprises.
    """
    for item in getattr(config, "STATIC", ()) or ():
        source, where = item if isinstance(item, (list, tuple)) else (item, "")
        source = Path(source)
        if not source.is_absolute():
            source = root / source
        if not source.is_dir():
            raise SiteError(f"STATIC: {source} is not a directory")
        target = out.joinpath(*[p for p in str(where).strip("/").split("/") if p])
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target, dirs_exist_ok=True, ignore=IGNORE)


def _redirects(out, config):
    """`_redirects`, from a `redirects()` in `site.py`. Every static host reads this shape."""
    function = getattr(config, "redirects", None) if config else None
    if function is None:
        return
    lines = []
    for rule in function():
        if isinstance(rule, (list, tuple)):
            source, target = rule[0], rule[1]
            status = rule[2] if len(rule) > 2 else 301
        else:
            raise SiteError("redirects() returns (from, to) or (from, to, status) pairs")
        lines.append(f"{source}  {target}  {status}")
    if lines:
        (out / "_redirects").write_text("\n".join(lines) + "\n")


def _link(out, url, link):
    """Put a stylesheet link into a page that is already written. Root-absolute, like
    everything else a site writes: one stylesheet, one URL, whatever depth the page is at."""
    target, _ = written_at(out, url)
    html = target.read_text()
    link = link.replace('href="./', 'href="/')
    if link in html:
        return
    target.write_text(html.replace("</head>", f"  {link}\n</head>", 1))


def main(argv=None):

    parser = argparse.ArgumentParser(prog=f"{PROG} site", description=__doc__)
    parser.add_argument("dir", nargs="?", default=".", help="the site directory (the one with pages/)")
    parser.add_argument("--out", default="", help="where to write (default: dist/<name>)")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for a page's resources")
    parser.add_argument("--tailwind", action="store_true", help="generate the Tailwind stylesheet and link it")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    try:
        build(args.dir, args.out or None, quiet=args.quiet, timeout=args.timeout, tailwind=args.tailwind)
    except SiteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
