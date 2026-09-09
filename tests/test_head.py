"""SPEC: what a page says about itself — `Title`, `Meta`, and `Route(title=)`."""

import pytest

from frontage import Route, Router, Show, Signal, h, head, mount
from frontage.renderer import HtmlRenderer


@pytest.fixture(autouse=True)
def clean():
    head.forget()
    yield
    head.forget()


def render(view):
    renderer = HtmlRenderer()
    root = renderer.create_element("div")
    return mount(view, root, renderer), root


def test_a_title_is_recorded_off_the_browser_where_the_prerenderer_reads_it():
    render(lambda: h.div(head.Title("Contacts"), h.p("hello")))
    assert head.snapshot()["title"] == "Contacts"


def test_a_title_renders_nothing():
    _, root = render(lambda: h.div(head.Title("x"), h.p("only me")))
    assert "".join(child.to_html() for child in root.children) == "<div><p>only me</p></div>"


def test_a_title_over_a_signal_follows_it():
    name = Signal("Ann")
    render(lambda: h.div(head.Title(lambda: f"{name()} — Contacts")))
    assert head.snapshot()["title"] == "Ann — Contacts"
    name.set("Bob")
    assert head.snapshot()["title"] == "Bob — Contacts"


def test_the_innermost_title_wins_and_the_outer_one_comes_back():
    inner = Signal(True)
    render(
        lambda: h.div(
            head.Title("Site"),
            Show(inner, lambda: h.div(head.Title("Page"))),
        )
    )
    assert head.snapshot()["title"] == "Page"
    inner.set(False)
    assert head.snapshot()["title"] == "Site"


def test_meta_takes_exactly_one_of_name_or_property():
    with pytest.raises(TypeError, match="name= or property="):
        head.Meta("x")
    with pytest.raises(TypeError, match="name= or property="):
        head.Meta("x", name="a", property="b")


def test_meta_records_the_attribute_it_was_given():
    render(
        lambda: h.div(
            head.Meta("A page about pages.", name="description"),
            head.Meta("Pages", property="og:title"),
        )
    )
    assert head.snapshot()["meta"] == [
        ("name", "description", "A page about pages."),
        ("property", "og:title", "Pages"),
    ]


def test_a_meta_that_goes_away_is_forgotten():
    show = Signal(True)
    render(lambda: h.div(Show(show, lambda: h.div(head.Meta("gone soon", name="description")))))
    assert head.snapshot()["meta"] != []
    show.set(False)
    assert head.snapshot()["meta"] == []


# `Route(title=)` ---------------------------------------------------------------------------
def test_a_route_names_the_page_and_a_child_route_wins():
    router = Router(
        Route("/", lambda: h.p("home"), title="Home"),
        Route(
            "/contacts",
            lambda children: h.div(children),
            title="Contacts",
            children=[Route(":id", lambda: h.p("one"), title=lambda params: f"Contact {params['id']}")],
        ),
        mode="memory",
    )
    render(router)
    assert head.snapshot()["title"] == "Home"
    router.navigate("/contacts/7")
    assert head.snapshot()["title"] == "Contact 7"
    router.navigate("/")
    assert head.snapshot()["title"] == "Home"


def test_a_route_without_a_title_does_not_keep_the_last_one():
    router = Router(
        Route("/", lambda: h.p("home"), title="Home"),
        Route("/plain", lambda: h.p("plain")),
        mode="memory",
    )
    render(router)
    assert head.snapshot()["title"] == "Home"
    router.navigate("/plain")
    assert head.snapshot()["title"] is None


# `Tag` -------------------------------------------------------------------------------------
def test_a_tag_is_recorded_as_html_and_renders_nothing():
    _, root = render(lambda: h.div(head.Tag(h.link(rel="canonical", href="https://x.test/a")), h.p("only me")))
    assert head.snapshot()["tags"] == ['<link rel="canonical" href="https://x.test/a">']
    assert "".join(child.to_html() for child in root.children) == "<div><p>only me</p></div>"


def test_a_script_tag_keeps_its_javascript_unescaped():
    render(lambda: h.div(head.Tag(h.script("if (a && b) go();", type="application/ld+json"))))
    assert head.snapshot()["tags"] == ['<script type="application/ld+json">if (a && b) go();</script>']


def test_a_tag_that_goes_away_is_forgotten():
    show = Signal(True)
    render(lambda: h.div(Show(show, lambda: h.div(head.Tag(h.link(rel="me", href="/gone"))))))
    assert head.snapshot()["tags"] != []
    show.set(False)
    assert head.snapshot()["tags"] == []


def test_the_prerenderer_writes_tags_into_the_head():
    from frontage.cli.prerender import apply_head

    page = "<html><head><title>x</title></head><body></body></html>"
    written = apply_head(page, {"tags": ['<link rel="canonical" href="/a">']})
    assert '<link rel="canonical" href="/a"></head>' in written
    # A tag the template already carries is not written twice.
    assert apply_head(written, {"tags": ['<link rel="canonical" href="/a">']}) == written
