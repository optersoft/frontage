"""Three languages, one page tree: `pages/[lang]/…`, and what a page says about the others.

The default locale has no URL segment, so a site with a main language keeps `/` for it —
which is what `optersoft.com` does today, and what this has to reproduce.
"""

from pathlib import Path

import pytest

from frontage.cli.site import LOCALE, Route, Site, SiteError, build
from frontage.content import collection
from frontage.i18n import hreflang, switcher
from frontage.view import render_to_string

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "locales"

THREE = ["en", "es", "ca"]


def _route(name, root="pages"):
    base = Path(root)
    return Route(base / name, base)


# --- the tree ---------------------------------------------------------------------------------


def test_a_parameter_can_be_a_directory():
    route = _route("[lang]/blog/[slug].py")
    assert route.parameters == ["lang", "slug"]
    assert route.url({"lang": "es", "slug": "hello"}) == "/es/blog/hello/"


def test_the_default_locale_has_no_segment():
    route = _route("[lang]/index.py")
    assert route.url({"lang": "en"}, default_locale="en") == "/"
    assert route.url({"lang": "es"}, default_locale="en") == "/es/"
    # Only `lang` is special, and only against the default: a slug that reads like one is a slug.
    assert _route("blog/[slug].py").url({"slug": "en"}, default_locale="en") == "/blog/en/"


def test_static_paths_that_leaves_a_parameter_out_says_which(tmp_path):
    pages = tmp_path / "pages" / "[lang]"
    pages.mkdir(parents=True)
    (pages / "[slug].py").write_text(
        "from frontage import h\n\n\n"
        "def static_paths():\n    return [{'lang': 'en'}]\n\n\n"
        "def page(lang, slug):\n    return h.p(slug)\n"
    )
    with pytest.raises(SiteError, match="left out slug"):
        build(tmp_path, tmp_path / "out", quiet=True)


# --- what a site knows about its locales ---------------------------------------------------------


def test_translate_moves_a_path_between_locales():
    site = Site("https://x.test", locales=THREE)
    assert site.default_locale == "en"
    assert site.translate("/blog/hello/", "es") == "/es/blog/hello/"
    assert site.translate("/es/blog/hello/", "ca") == "/ca/blog/hello/"
    assert site.translate("/ca/blog/hello/", "en") == "/blog/hello/"
    assert site.translate("/", "es") == "/es/"
    assert site.translate("/es/", "en") == "/"


def test_locale_of_reads_the_first_segment():
    site = Site(locales=THREE)
    assert site.locale_of("/") == "en"
    assert site.locale_of("/blog/") == "en"
    assert site.locale_of("/es/blog/") == "es"
    # A page whose first segment is not a locale is in the default one.
    assert site.locale_of("/blog/es/") == "en"


def test_alternates_are_only_the_pages_that_exist():
    site = Site(locales=THREE, pages=["/blog/", "/es/blog/"])
    assert site.alternates("/blog/") == [("en", "/blog/"), ("es", "/es/blog/")]


def test_site_paths_is_one_build_per_locale():
    assert Site(locales=THREE).paths() == [{LOCALE: "en"}, {LOCALE: "es"}, {LOCALE: "ca"}]


# --- what a page writes --------------------------------------------------------------------------


def test_hreflang_names_every_locale_and_a_default():
    site = Site("https://x.test", pages=["/a/", "/es/a/", "/ca/a/"], locales=THREE)
    html = render_to_string(lambda: hreflang(site, "/es/a/"))
    assert '<link rel="alternate" hreflang="en" href="https://x.test/a/">' in html
    assert '<link rel="alternate" hreflang="ca" href="https://x.test/ca/a/">' in html
    # x-default points at the default locale's copy, which is what a search engine falls back to.
    assert '<link rel="alternate" hreflang="x-default" href="https://x.test/a/">' in html


def test_the_switcher_is_links_and_the_current_one_is_not():
    site = Site(pages=["/a/", "/es/a/", "/ca/a/"], locales=THREE)
    html = render_to_string(lambda: switcher(site, "/es/a/", labels={"en": "English", "es": "Español"}))
    assert '<a href="/a/" lang="en" hreflang="en">English' in html
    assert '<span class="current" lang="es" aria-current="true">Español' in html
    assert "<a" in html and 'href="/es/a/"' not in html, "the page you are on is not a link to itself"


# --- a collection per language ---------------------------------------------------------------------


def test_a_collection_has_a_directory_per_language(tmp_path):
    for lang, title in (("en", "Hello"), ("es", "Hola")):
        directory = tmp_path / "posts" / lang
        directory.mkdir(parents=True)
        (directory / "greeting.md").write_text(f"---\ntitle: {title}\n---\n\nbody\n")
    posts = collection("posts", root=tmp_path / "posts")
    assert posts.locale("es").get("greeting").data["title"] == "Hola"
    assert posts.locale("en").get("greeting").data["title"] == "Hello"


# --- the example ------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("locales")
    build(EXAMPLE, out, quiet=True)
    return out


def test_the_same_tree_exists_under_every_locale(built):
    made = sorted(str(p.relative_to(built).parent) for p in built.rglob("index.html"))
    assert made == [
        ".",
        "blog",
        "blog/links-not-islands",
        "blog/one-tree",
        "ca",
        "ca/blog",
        "ca/blog/links-not-islands",
        "ca/blog/one-tree",
        "es",
        "es/blog",
        "es/blog/links-not-islands",
        "es/blog/one-tree",
    ]


def test_each_page_says_which_language_it_is_in(built):
    assert '<html lang="en">' in (built / "index.html").read_text()
    assert '<html lang="es">' in (built / "es" / "index.html").read_text()
    assert '<html lang="ca">' in (built / "ca" / "blog" / "one-tree" / "index.html").read_text()


def test_a_multilingual_site_still_ships_no_runtime(built):
    for page in built.rglob("index.html"):
        assert "<script" not in page.read_text(), page
    assert not (built / "_frontage").exists()


def test_the_sitemap_carries_the_alternates(built):
    sitemap = (built / "sitemap.xml").read_text()
    assert sitemap.count("<url>") == 12
    assert '<xhtml:link rel="alternate" hreflang="ca" href="https://tres.example/ca/blog/one-tree/"/>' in sitemap
