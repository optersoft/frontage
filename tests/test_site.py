"""`frontage site`: a directory of pages as a directory of files.

The browser half — a page that fetches nothing, and the one page that does — is
`tests/browser/test_site.py`.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from frontage.cli import frontage_rt
from frontage.cli.site import Route, Site, SiteError, build, routes

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "site"


def _route(name, root="pages"):
    base = Path(root)
    return Route(base / name, base)


# --- the URL a file makes -----------------------------------------------------------------------


def test_the_tree_is_the_site_map():
    assert _route("index.py").url() == "/"
    assert _route("about.py").url() == "/about/"
    assert _route("blog/index.py").url() == "/blog/"
    assert _route("blog/hello.py").url() == "/blog/hello/"


def test_a_bracketed_name_is_one_page_per_value():
    route = _route("blog/[slug].py")
    assert route.parameter == "slug" and route.rest is False
    assert route.url({"slug": "hello"}) == "/blog/hello/"
    with pytest.raises(SiteError, match="gave no 'slug'"):
        route.url({})


def test_a_rest_parameter_swallows_the_path():
    route = _route("docs/[...path].py")
    assert route.parameter == "path" and route.rest is True
    assert route.url({"path": "guide/install"}) == "/docs/guide/install/"


def test_a_name_with_a_suffix_is_an_endpoint_at_that_name():
    route = _route("sitemap.xml.py")
    assert route.is_endpoint and route.url() == "/sitemap.xml"
    assert _route("feed/rss.xml.py").url() == "/feed/rss.xml"
    assert not _route("about.py").is_endpoint


def test_a_directory_without_pages_is_not_a_site(tmp_path):
    with pytest.raises(SiteError, match="has no pages/ directory"):
        routes(tmp_path)
    (tmp_path / "pages").mkdir()
    with pytest.raises(SiteError, match="has no pages"):
        routes(tmp_path)


def test_site_urls_are_absolute_only_when_base_says_so():
    assert Site("https://x.test/", ["/a/"]).url("/a/") == "https://x.test/a/"
    assert Site("", ["/a/"]).url("/a/") == "/a/"


# --- building the example -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    build(EXAMPLE, out, quiet=True)
    return out


def test_every_page_is_a_file_at_its_own_url(built):
    for path in ("index.html", "about/index.html", "blog/index.html", "blog/a-site-of-files/index.html"):
        assert (built / path).is_file(), path
    # One page per post, from `static_paths()`.
    assert len(list((built / "blog").glob("*/index.html"))) == 3


def test_a_page_with_nothing_interactive_carries_no_script(built):
    page = (built / "blog" / "a-site-of-files" / "index.html").read_text()
    assert "<script" not in page and "_frontage" not in page
    # The layout's Title and Meta are in the head, not set by a script that never runs.
    assert "<title>A site of files — Notes</title>" in page
    assert 'name="description"' in page


def test_only_the_page_with_an_island_carries_the_loader(built):
    page = (built / "blog" / "one-island-per-site" / "index.html").read_text()
    assert "data-fr-islands" in page and "data-fr-boot" not in page
    assert 'data-fr-island="widgets:reactions"' in page
    # Root-absolute: a site is served at a root, and `./_frontage/` two directories down
    # would ask for a loader that is not there.
    assert '"/_frontage/island.js"' in page


def test_the_runtime_is_written_once_and_the_island_is_a_chunk(built):
    import json

    manifest = json.loads((built / "_frontage" / frontage_rt.MANIFEST).read_text())
    assert manifest["islands"] is True
    assert manifest["chunks"] == {"widgets": ["widgets"]}
    assert frontage_rt.ISLAND_MODULE in manifest["modules"]


def test_an_endpoint_is_a_module_with_a_get(built):
    sitemap = (built / "sitemap.xml").read_text()
    assert sitemap.startswith("<?xml")
    # `site.pages` is every URL the build made, because the build made them first.
    for url in ("/", "/about/", "/blog/", "/blog/a-site-of-files/"):
        assert f"<loc>https://notes.example{url}</loc>" in sitemap
    assert "Sitemap: https://notes.example/sitemap.xml" in (built / "robots.txt").read_text()


def test_a_page_that_asks_for_site_is_given_one(built):
    assert "It has 6 pages, and it lives at https://notes.example." in (built / "about" / "index.html").read_text()


def test_redirects_and_public_and_headers(built):
    assert (built / "_redirects").read_text().splitlines()[0] == "/posts/*  /blog/:splat  301"
    assert (built / "site.css").is_file(), "public/ was not copied"
    assert "immutable" in (built / "_headers").read_text()


# --- what goes wrong --------------------------------------------------------------------------------


def _site(tmp_path, **files):
    (tmp_path / "pages").mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        path = tmp_path / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def test_a_page_module_without_a_page_says_so(tmp_path):
    _site(tmp_path, **{"pages__index.py": "x = 1\n"})
    with pytest.raises(SiteError, match="defines `page\\(\\)`"):
        build(tmp_path, tmp_path / "out", quiet=True)


def test_a_dynamic_page_without_static_paths_says_what_it_wanted(tmp_path):
    _site(tmp_path, **{"pages__[slug].py": "from frontage import h\n\n\ndef page(slug):\n    return h.p(slug)\n"})
    with pytest.raises(SiteError, match="getStaticPaths"):
        build(tmp_path, tmp_path / "out", quiet=True)


def test_a_page_that_raises_names_the_url_and_the_file(tmp_path):
    _site(tmp_path, **{"pages__index.py": "def page():\n    raise ValueError('nope')\n"})
    with pytest.raises(SiteError) as raised:
        build(tmp_path, tmp_path / "out", quiet=True)
    assert "index.py" in str(raised.value) and "nope" in str(raised.value)


def test_a_template_without_a_mount_point_says_so(tmp_path):
    _site(tmp_path, **{"pages__index.py": "from frontage import h\n\n\ndef page():\n    return h.p('x')\n"})
    (tmp_path / "index.html").write_text("<html><body></body></html>")
    with pytest.raises(SiteError, match='id="app"'):
        build(tmp_path, tmp_path / "out", quiet=True)


def test_a_site_with_no_island_writes_no_runtime_at_all(tmp_path):
    _site(tmp_path, **{"pages__index.py": "from frontage import h\n\n\ndef page():\n    return h.p('static')\n"})
    out = tmp_path / "out"
    build(tmp_path, out, quiet=True)
    assert not (out / "_frontage").exists()
    assert "<script" not in (out / "index.html").read_text()


def test_the_site_command_runs(tmp_path):
    _site(tmp_path, **{"pages__index.py": "from frontage import h\n\n\ndef page():\n    return h.p('ok')\n"})
    run = subprocess.run(
        [sys.executable, "-m", "frontage", "site", str(tmp_path), "--out", str(tmp_path / "out")],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert run.returncode == 0, run.stderr
    assert "1 page(s)" in run.stdout and "no runtime" in run.stdout


# --- assets from outside the site --------------------------------------------------------------


def test_static_takes_directories_from_outside_the_site(tmp_path):
    """A shared chrome brings a stylesheet and four fonts, and none of them are the site's."""
    package = tmp_path / "elsewhere"
    (package / "fonts").mkdir(parents=True)
    (package / "chrome.css").write_text("body{}")
    (package / "fonts" / "a.woff2").write_bytes(b"font")
    site = tmp_path / "site"
    _site(site, **{"pages__index.py": "from frontage import h\n\n\ndef page():\n    return h.p('x')\n"})
    (site / "site.py").write_text(f"STATIC = [({str(package)!r}, 'brand')]\n")
    out = tmp_path / "out"
    build(site, out, quiet=True)
    assert (out / "brand" / "chrome.css").read_text() == "body{}"
    assert (out / "brand" / "fonts" / "a.woff2").is_file()


def test_a_bare_static_path_lands_at_the_root(tmp_path):
    package = tmp_path / "elsewhere"
    package.mkdir()
    (package / "favicon.ico").write_bytes(b"icon")
    site = tmp_path / "site"
    _site(site, **{"pages__index.py": "from frontage import h\n\n\ndef page():\n    return h.p('x')\n"})
    (site / "site.py").write_text(f"STATIC = [{str(package)!r}]\n")
    out = tmp_path / "out"
    build(site, out, quiet=True)
    assert (out / "favicon.ico").is_file()


def test_a_static_directory_that_is_not_there_says_so(tmp_path):
    site = tmp_path / "site"
    _site(site, **{"pages__index.py": "from frontage import h\n\n\ndef page():\n    return h.p('x')\n"})
    (site / "site.py").write_text("STATIC = ['nowhere']\n")
    with pytest.raises(SiteError, match="is not a directory"):
        build(site, tmp_path / "out", quiet=True)


# --- a site whose URLs have no trailing slash --------------------------------------------------


def test_a_page_may_compute_its_own_url(tmp_path):
    """optersoft.com's paths are translated slugs — `/es/tecnologia` — so they come from a
    table the site has and the framework does not. `PATH` may be a function of the params."""
    _site(
        tmp_path,
        **{
            "pages__all.py": (
                'ROUTES = {"home": {"en": "/", "es": "/es"}, "tech": {"en": "/technology", "es": "/es/tecnologia"}}\n\n'
                "from frontage import h  # noqa: E402\n\n\n"
                "def static_paths():\n    return [{'name': n, 'lang': l} for n in ROUTES for l in ROUTES[n]]\n\n\n"
                "def PATH(name, lang):\n    return ROUTES[name][lang]\n\n\n"
                "def page(name, lang):\n    return h.p(f'{name}/{lang}')\n"
            )
        },
    )
    out = tmp_path / "out"
    build(tmp_path, out, quiet=True)
    made = sorted(str(p.relative_to(out)) for p in out.rglob("*.html"))
    # `/es` is `es.html`, not `es` — which could not coexist with the `es/` directory that
    # `/es/tecnologia` needs, and which no static host would serve for `/es` anyway.
    assert made == ["es.html", "es/tecnologia.html", "index.html", "technology.html"]


def test_a_computed_path_still_needs_static_paths(tmp_path):
    _site(
        tmp_path,
        **{
            "pages__all.py": (
                "from frontage import h\n\n\ndef PATH(name):\n    return '/' + name\n\n\n"
                "def page(name):\n    return h.p(name)\n"
            )
        },
    )
    with pytest.raises(SiteError, match="a `PATH\\(\\)` that computes its URL"):
        build(tmp_path, tmp_path / "out", quiet=True)
