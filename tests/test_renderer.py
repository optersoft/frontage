from frontage.renderer import HtmlRenderer, RecordingRenderer, escape


def test_escape_text_and_attribute_values():
    assert escape("<a & b>") == "&lt;a &amp; b&gt;"
    assert escape('say "hi"', quote=True) == "say &quot;hi&quot;"
    assert escape('say "hi"') == 'say "hi"'


def test_element_attributes_and_children_serialise():
    r = HtmlRenderer()
    div = r.create_element("div")
    r.set_property(div, "class", "box")
    r.set_property(div, "hidden", True)
    r.set_property(div, "title", 'a "quoted" title')
    r.insert_node(div, r.create_text("x < y"))
    assert div.to_html() == '<div class="box" hidden title="a &quot;quoted&quot; title">x &lt; y</div>'


def test_false_and_none_remove_an_attribute():
    r = HtmlRenderer()
    el = r.create_element("input")
    r.set_property(el, "disabled", True)
    r.set_property(el, "disabled", False)
    r.set_property(el, "value", "v")
    r.set_property(el, "value", None)
    assert el.to_html() == "<input>"


def test_void_elements_have_no_closing_tag():
    r = HtmlRenderer()
    assert r.create_element("br").to_html() == "<br>"
    assert r.create_element("img").to_html() == "<img>"


def test_insert_before_anchor_and_remove():
    r = HtmlRenderer()
    ul = r.create_element("ul")
    a, b, c = (r.create_element("li") for _ in range(3))
    r.insert_node(ul, a)
    r.insert_node(ul, c)
    r.insert_node(ul, b, anchor=c)
    assert ul.children == [a, b, c]
    assert r.first_child(ul) is a
    assert r.next_sibling(a) is b
    assert r.next_sibling(c) is None
    assert r.parent(b) is ul
    r.remove_node(ul, b)
    assert ul.children == [a, c]
    assert b.parent is None


def test_moving_a_node_detaches_it_from_its_old_parent():
    r = HtmlRenderer()
    p1, p2 = r.create_element("div"), r.create_element("div")
    x = r.create_text("x")
    r.insert_node(p1, x)
    r.insert_node(p2, x)
    assert p1.children == [] and p2.children == [x]


def test_recording_renderer_logs_every_operation():
    r = RecordingRenderer()
    el = r.create_element("p")
    t = r.create_text("hi")
    r.insert_node(el, t)
    r.replace_text(t, "bye")
    r.set_property(el, "id", "x")
    assert [op[0] for op in r.log] == ["create_element", "create_text", "insert_node", "replace_text", "set_property"]
    assert r.count("insert_node") == 1
    assert el.to_html() == '<p id="x">bye</p>'
