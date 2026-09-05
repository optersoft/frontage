import pytest

from frontage import Element, RecordingRenderer, Text, build, h, render_to_string, text


def test_call_form_builds_a_tree():
    view = h.div(h.p("Hello", cls="lead"), "tail", id="root")
    assert isinstance(view, Element)
    assert view.tag == "div" and view.attrs == {"id": "root"}
    assert [type(c) for c in view.children] == [Element, Text]
    assert render_to_string(view) == '<div id="root"><p class="lead">Hello</p>tail</div>'


def test_with_form_appends_to_the_open_element():
    with h.ul(cls="menu") as menu:
        for label in ("a", "b"):
            h.li(label)
        with h.li():
            text("nested")
    assert render_to_string(menu) == '<ul class="menu"><li>a</li><li>b</li><li>nested</li></ul>'


def test_with_form_does_not_leak_after_the_block():
    with h.div():
        h.span("inside")
    outside = h.span("outside")
    assert render_to_string(outside) == "<span>outside</span>"


def test_attribute_name_spellings():
    view = h.input(type_="text", data_id=7, aria_label="Name", for_="x", class_="c")
    assert view.attrs == {"type": "text", "data-id": 7, "aria-label": "Name", "for": "x", "class": "c"}


def test_children_are_flattened_and_booleans_and_none_are_dropped():
    view = h.div(None, ["a", ["b", None]], False, 3)
    assert render_to_string(view) == "<div>ab3</div>"


def test_text_is_escaped_and_attributes_quoted():
    view = h.p("<b>", title='"q"')
    assert render_to_string(view) == '<p title="&quot;q&quot;">&lt;b&gt;</p>'


def test_custom_element_tags_use_hyphens():
    assert render_to_string(h.sl_button("Go")) == "<sl-button>Go</sl-button>"
    assert render_to_string(h("my-tag", "x")) == "<my-tag>x</my-tag>"


def test_build_counts_renderer_operations():
    r = RecordingRenderer()
    build(h.ul(h.li("a"), h.li("b")), r)
    assert r.count("create_element") == 3
    assert r.count("create_text") == 2
    assert r.count("insert_node") == 4


@pytest.mark.parametrize("tag", ["br", "hr", "img"])
def test_void_tags(tag):
    assert render_to_string(getattr(h, tag)()) == f"<{tag}>"
