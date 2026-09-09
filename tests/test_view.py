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
    view = h.label(h.input(type_="text", data_id=7, aria_label="Name"), for_="x", class_="c")
    assert (
        render_to_string(view) == '<label for="x" class="c"><input type="text" data-id="7" aria-label="Name"></label>'
    )


def test_children_are_flattened_and_booleans_and_none_are_dropped():
    view = h.div(None, ["a", ["b", None]], False, 3)
    assert render_to_string(view) == "<div>ab3</div>"


def test_text_is_escaped_and_attributes_quoted():
    view = h.p("<b>", title='"q"')
    assert render_to_string(view) == '<p title="&quot;q&quot;">&lt;b&gt;</p>'


def test_custom_element_tags_use_hyphens():
    assert render_to_string(h.sl_button("Go")) == "<sl-button>Go</sl-button>"
    assert render_to_string(h("my-tag", "x")) == "<my-tag>x</my-tag>"


def test_build_clones_one_template_and_fills_the_text_holes():
    r = RecordingRenderer()
    build(h.ul(h.li("a"), h.li("b")), r)
    assert r.count("clone_template") == 1 and r.count("find_holes") == 1
    assert r.count("create_element") == 0
    assert r.count("create_text") == 2 and r.count("replace_node") == 2
    assert r.count("insert_node") == 0


@pytest.mark.parametrize("tag", ["br", "hr", "img"])
def test_void_tags(tag):
    assert render_to_string(getattr(h, tag)()) == f"<{tag}>"


# --- raw text elements ---------------------------------------------------------------------


def test_script_and_style_hold_raw_text_not_markup():
    """`<script>` and `<style>` are raw text elements: escaping their content is wrong.

    An inline theme script with `&&` in it came out as `&amp;&amp;` and stopped being
    JavaScript — and the `<!--h-->` the template compiler wrote between its lines was not a
    marker there but a line of the script, so the template found one marker fewer than it
    had written and raised on the next row.
    """
    from frontage.view import h, render_to_string

    assert render_to_string(lambda: h.script("if (a && b) x(1);")) == "<script>if (a && b) x(1);</script>"
    assert render_to_string(lambda: h.style('.a::after{content:"<"}')) == '<style>.a::after{content:"<"}</style>'
    # Only in those two: everything else is markup and is escaped.
    assert render_to_string(lambda: h.p("a && b")) == "<p>a &amp;&amp; b</p>"
    # And a script is text, not a place to put a view: the boundary shows the sentence.
    assert "&lt;script&gt; holds text" in render_to_string(lambda: h.script(h.b("no")))


def test_a_comment_is_a_view_node_and_survives_serialisation():
    """A comment can be functional: Cloudflare's `<!--email_off-->` opts a region out of its
    email obfuscation, and dropping it rewrites every address on the page it protects.

    `comments=False` drops the framework's hydration *markers*, not an author's comment.
    """
    from frontage.view import comment, h, render_to_string

    out = render_to_string(lambda: h.div(comment("email_off"), h.p("x"), comment("/email_off")))
    assert out == "<div><!--email_off--><p>x</p><!--/email_off--></div>"
    # A hole's own markers are still the framework's and still go.
    assert render_to_string(lambda: h.p("a", lambda: "b")) == "<p>ab</p>"
