"""The language server: the scanner, the rules with ranges, the features, and one session.

No editor and no browser — the server is a function from messages to messages, so a pipe of
bytes is the whole harness. `tests/test_cli.py` covers the same three rules through
`frontage check`, which is the point: one implementation, two front ends.
"""

import io

import pytest

from frontage.cli import check
from frontage.lsp import features, rules
from frontage.lsp.documents import Document, Documents
from frontage.lsp.protocol import Connection, Disconnected, read_message, write_message
from frontage.lsp.scanner import context_at, emit_tokens, scan_templates
from frontage.lsp.server import Server, path_from_uri, uri_from_path

URI = "file:///tmp/app.py"


def document(text):
    return Document(URI, text)


def at(text, needle, after=0):
    """The offset just past `needle`, plus `after`."""
    return text.index(needle) + len(needle) + after


# --- the scanner ---------------------------------------------------------------------------------


def test_scan_finds_only_t_strings():
    src = 'a = "plain"\nb = f"{x}"\nc = html(t"<p>hi</p>")\nd = t"not markup"\n'
    found = scan_templates(src)
    assert len(found) == 2
    assert [t.is_html for t in found] == [True, False]
    assert src[found[0].body_start : found[0].body_end] == "<p>hi</p>"


def test_scan_handles_triple_quotes_and_raw_prefixes():
    src = 'x = html(rt"""<p>a\\d</p>""")\n'
    found = scan_templates(src)
    assert len(found) == 1 and found[0].is_raw and found[0].quote == '"""'


def test_scan_tolerates_an_unterminated_template():
    src = 'x = html(t"<ul><li'
    found = scan_templates(src)
    assert len(found) == 1 and found[0].body_end == len(src)


def test_scan_ignores_strings_in_comments_and_quotes_inside_interpolations():
    src = '# html(t"<p>x</p>")\ny = html(t"<b>{d[\'k\']}</b>")\n'
    found = scan_templates(src)
    assert len(found) == 1
    assert [kind for kind, _, _ in found[0].parts] == ["text", "hole", "text"]


def test_escaped_braces_are_text_not_holes():
    src = 'x = html(t"<p>{{literal}}</p>")\n'
    (template,) = scan_templates(src)
    assert [kind for kind, _, _ in template.parts] == ["text"]


def test_html_is_recognised_through_an_attribute_call():
    src = "x = frontage.html(t'<p>a</p>')\n"
    assert scan_templates(src)[0].is_html


def test_a_bare_t_string_is_not_a_template():
    src = 'q = t"select {n}"\n'
    assert context_at(src, at(src, "select")) is None


# --- where is the cursor -------------------------------------------------------------------------

TEMPLATE = (
    "from frontage import html\n"
    "def view():\n"
    '    return html(t"""\n'
    '      <div class="row {cls}">\n'
    "        <button on:click={go}>ok</button>\n"
    "      </div>\n"
    '    """)\n'
)


@pytest.mark.parametrize(
    "needle,after,kind,tag",
    [
        ("<di", 0, "tag", "di"),
        ("class", 0, "attr", "div"),
        ('class="ro', 0, "value", "div"),
        ("{cls", 0, "interp", ""),
        ("on:cl", 0, "attr", "button"),
        (">ok", 0, "text", ""),
        ("</but", 0, "endtag", "button"),
    ],
)
def test_context_at_reads_the_position(needle, after, kind, tag):
    context = context_at(TEMPLATE, at(TEMPLATE, needle, after))
    assert context is not None
    assert context.kind == kind
    if tag:
        assert context.tag == tag


def test_context_tracks_the_open_element_stack():
    context = context_at(TEMPLATE, at(TEMPLATE, ">ok"))
    assert context.stack == ["div", "button"]


def test_context_is_none_outside_a_template():
    assert context_at(TEMPLATE, at(TEMPLATE, "def view")) is None


def test_context_at_and_emit_tokens_agree():
    """The two readings of the same grammar; `scanner.emit_tokens` promises this."""
    expected = {
        "tag": {"tag", "endtag"},
        "attr": {"attr"},
        "prefixed": {"attr"},
        "value": {"value"},
        "comment": {"comment"},
    }
    (template,) = scan_templates(TEMPLATE)
    checked = 0
    for kind, start, end in emit_tokens(TEMPLATE, template):
        if kind not in expected or end - start < 2:
            continue
        context = context_at(TEMPLATE, start + 1)
        assert context is not None and context.kind in expected[kind], (kind, TEMPLATE[start:end])
        checked += 1
    assert checked > 5


# --- the rules -----------------------------------------------------------------------------------


def slice_of(src, finding):
    return src.splitlines()[finding.line - 1][finding.col : finding.end_col]


def test_nesting_finding_points_at_the_offending_tag():
    src = 'x = html(t"<p>a<div>b</div></p>")\n'
    (finding,) = rules.findings(src, "app.py")
    assert finding.code == "html-nesting" and finding.severity == rules.WARNING
    assert slice_of(src, finding) == "<div"


def test_an_image_with_nothing_to_read_out_is_flagged():
    src = "x = html(t'<img src=\"cat.png\">')\n"
    (finding,) = rules.findings(src, "app.py")
    assert finding.code == "img-alt" and finding.severity == rules.WARNING
    assert slice_of(src, finding) == "<img"
    assert "alt" in finding.message


def test_an_image_that_says_it_is_decorative_is_not_flagged():
    """`alt=""` is a decision; only the missing attribute is a finding."""
    assert rules.findings('x = html(t\'<img src="line.png" alt="">\')\n', "app.py") == []
    assert rules.findings('x = html(t\'<img src="cat.png" alt="A cat.">\')\n', "app.py") == []


def test_an_alt_that_comes_from_a_hole_counts():
    """The attribute is there; what it says is the app's business, not the rule's."""
    assert rules.findings('x = html(t"<img src={url} alt={caption}>")\n', "app.py") == []


def test_a_row_outside_a_body_is_flagged_where_it_sits():
    src = 'x = html(t"<table><tr><td>1</td></tr></table>")\n'
    (finding,) = rules.findings(src, "app.py")
    assert slice_of(src, finding) == "<tr"


def test_lambda_finding_covers_the_interpolation():
    # Parenthesised, because CPython 3.14 rejects a bare `lambda` in an interpolation
    # outright — its `:` is the format spec. The parenthesised form parses here and is
    # exactly the one that reaches MicroPython and fails there, so it is the rule's job.
    src = 'x = html(t"<b on:click={(lambda ev: None)}>hi</b>")\n'
    (finding,) = rules.findings(src, "app.py")
    assert finding.code == "lambda-in-template" and finding.severity == rules.ERROR
    assert slice_of(src, finding) == "{(lambda ev: None)}"


def test_an_unparenthesised_lambda_is_left_to_python():
    # CPython calls this a SyntaxError itself, so the server says nothing and the editor's
    # Python language server reports it once instead of twice.
    src = 'x = html(t"<b on:click={lambda ev: None}>hi</b>")\n'
    (finding,) = rules.findings(src, "app.py")
    assert finding.code == "syntax"


def test_f_string_finding_covers_the_call():
    src = 'name = "x"\ny = html(f"<b>{name}</b>")\n'
    (finding,) = rules.findings(src, "app.py")
    assert finding.code == "f-string-template"
    assert slice_of(src, finding) == 'html(f"<b>{name}</b>")'


def test_a_clean_template_has_nothing_to_say():
    assert rules.findings('x = html(t"<div><p>ok</p></div>")\n') == []


def test_ranges_survive_a_multibyte_line():
    src = 'x = html(t"<p>Àlex ☃</p>")\ny = html(t"<p>a<div>b</div></p>")\n'
    (finding,) = rules.findings(src, "app.py")
    assert slice_of(src, finding) == "<div"


def test_markdown_blocks_report_their_real_line():
    text = '# Title\n\n```python\nx = html(f"<b>hi</b>")\n```\n'
    (finding,) = rules.findings_in_markdown(text, "page.md")
    assert finding.line == 4


def test_check_and_the_server_report_the_same_things():
    src = 'x = html(t"<p>a<div>b</div></p>")\ny = html(f"<i>hi</i>")\n'
    assert [message for _, _, message in check.check_source(src, "app.py")] == sorted(
        finding.message for finding in rules.findings(src, "app.py")
    )


# --- documents -----------------------------------------------------------------------------------


def test_positions_count_utf16_units():
    doc = document("x = '☃𝄞'\ny = 2\n")
    # The treble clef is astral: two UTF-16 units for one Python character.
    end = doc.position_at(doc.text.index("\n"))
    assert end == {"line": 0, "character": 9}
    assert doc.offset_at({"line": 0, "character": 9}) == doc.text.index("\n")


def test_ast_columns_are_bytes():
    doc = document('x = "Àlex"\n')
    # `ast` would report column 10 for the end of that line: À is two bytes.
    assert doc.offset_of(1, 10) == 9


def test_documents_forget_what_is_closed():
    docs = Documents()
    docs.open(URI, "x = 1\n")
    assert len(docs) == 1
    docs.close(URI)
    assert docs.get(URI) is None


# --- features ------------------------------------------------------------------------------------


def labels(items):
    return [item["label"] for item in items]


def test_completion_offers_elements_after_a_left_angle():
    items = features.complete(document(TEMPLATE), at(TEMPLATE, "<di"))
    assert "div" in labels(items) and "section" in labels(items)
    (div,) = [i for i in items if i["label"] == "div"]
    assert div["insertText"] == "div>$0</div>"
    (br,) = [i for i in items if i["label"] == "br"]
    assert br["insertText"] == "br"  # void: nothing to close


def test_completion_closes_the_innermost_element_first():
    items = features.complete(document(TEMPLATE), at(TEMPLATE, "</but"))
    assert labels(items)[:2] == ["button", "div"]


def test_attribute_completion_puts_frontage_prefixes_first():
    items = features.complete(document(TEMPLATE), at(TEMPLATE, "on:cl"))
    assert all(label.startswith("on:") for label in labels(items))
    assert "on:click" in labels(items)


def test_attribute_completion_mixes_prefixes_element_and_global_attributes():
    src = 'x = html(t"<input >")\n'
    items = features.complete(document(src), at(src, "<input "))
    order = labels(items)
    assert order[0].startswith("on:") and "ref" in order
    assert order.index("placeholder") < order.index("tabindex")  # element before global


def test_bind_completion_offers_only_the_three_targets():
    src = 'x = html(t"<input bind:>")\n'
    items = features.complete(document(src), at(src, "bind:"))
    assert labels(items) == ["bind:value", "bind:checked", "bind:group"]


def test_value_completion_knows_input_types():
    src = "x = html(t\"<input type=''>\")\n"
    items = features.complete(document(src), at(src, "type='"))
    assert "checkbox" in labels(items) and "range" in labels(items)


def test_interpolation_completion_offers_flow_components_last():
    src = 'x = html(t"<div>{}</div>")\n'
    items = features.complete(document(src), at(src, "{"))
    assert "Show" in labels(items) and "For" in labels(items)
    assert all(item["sortText"].startswith("9") for item in items)


def test_completion_is_silent_outside_a_template():
    assert features.complete(document(TEMPLATE), at(TEMPLATE, "def view")) == []


def test_hover_explains_an_element_a_prefix_and_an_api_name():
    src = 'from frontage import html, Signal\nx = html(t"<input bind:value={n}>")\ny = Signal(0)\n'
    doc = document(src)
    assert "form control" in features.hover(doc, at(src, "<inp"))["contents"]["value"]
    assert "Two-way binding" in features.hover(doc, at(src, "bind:val"))["contents"]["value"]
    assert "remembers who read it" in features.hover(doc, at(src, "y = Sig"))["contents"]["value"]


def test_hover_says_nothing_about_plain_python():
    src = "import os\nvalue = os.getcwd()\n"
    assert features.hover(document(src), at(src, "getc")) is None


def test_definition_finds_a_component_named_inside_a_template():
    src = 'from frontage import html, component\n\n@component\ndef row():\n    pass\n\nx = html(t"<ul>{row}</ul>")\n'
    doc = document(src)
    found = features.definition(doc, at(src, "{ro"))
    assert found["uri"] == URI and found["range"]["start"]["line"] == 3


def test_definition_declines_outside_an_interpolation():
    assert features.definition(document(TEMPLATE), at(TEMPLATE, "<di")) is None


def test_semantic_tokens_are_five_ints_each_and_sorted():
    data = features.semantic_tokens(document(TEMPLATE))["data"]
    assert data and len(data) % 5 == 0
    assert all(delta >= 0 for delta in data[::5])


# --- the protocol and one session ----------------------------------------------------------------


def test_framing_round_trips():
    stream = io.BytesIO()
    write_message(stream, {"jsonrpc": "2.0", "method": "hi", "params": {"n": 1}})
    stream.seek(0)
    assert read_message(stream)["params"] == {"n": 1}


def test_reading_past_the_end_disconnects():
    with pytest.raises(Disconnected):
        read_message(io.BytesIO(b""))


def test_uri_and_path_round_trip():
    assert path_from_uri(uri_from_path("/tmp/a b.py")) == "/tmp/a b.py"
    assert path_from_uri("untitled:Untitled-1") is None


def session(messages):
    """Run a whole conversation through the server and collect what it said."""
    incoming = io.BytesIO()
    for message in messages:
        write_message(incoming, message)
    incoming.seek(0)
    outgoing = io.BytesIO()
    Server(Connection(incoming, outgoing)).run()
    outgoing.seek(0)
    said = []
    while True:
        try:
            said.append(read_message(outgoing))
        except Disconnected:
            return said


def opened(text, extra=()):
    return session(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {"textDocument": {"uri": URI, "languageId": "python", "version": 1, "text": text}},
            },
            *extra,
            {"jsonrpc": "2.0", "id": 99, "method": "shutdown", "params": {}},
            {"jsonrpc": "2.0", "method": "exit", "params": {}},
        ]
    )


def diagnostics(said):
    return [m["params"] for m in said if m.get("method") == "textDocument/publishDiagnostics"]


def test_a_session_initializes_and_publishes_diagnostics():
    said = opened('x = html(t"<p>a<div>b</div></p>")\n')
    (initialize,) = [m for m in said if m.get("id") == 1]
    assert "hoverProvider" in initialize["result"]["capabilities"]
    (published,) = diagnostics(said)
    assert published["uri"] == URI
    assert published["diagnostics"][0]["code"] == "html-nesting"
    assert published["diagnostics"][0]["source"] == "frontage"


def test_a_syntax_error_publishes_nothing_rather_than_flashing():
    said = opened('x = html(t"<p>a</p>"\ndef broken(\n')
    assert diagnostics(said) == []


def test_closing_a_file_clears_its_diagnostics():
    said = opened(
        'x = html(t"<p>a<div>b</div></p>")\n',
        [{"jsonrpc": "2.0", "method": "textDocument/didClose", "params": {"textDocument": {"uri": URI}}}],
    )
    assert diagnostics(said)[-1]["diagnostics"] == []


def test_an_unknown_request_is_refused_and_the_server_keeps_going():
    said = opened("x = 1\n", [{"jsonrpc": "2.0", "id": 7, "method": "textDocument/nonsense", "params": {}}])
    (refused,) = [m for m in said if m.get("id") == 7]
    assert refused["error"]["code"] == -32601
    assert any(m.get("id") == 99 for m in said)  # shutdown still answered


def test_an_unknown_notification_is_ignored():
    said = opened("x = 1\n", [{"jsonrpc": "2.0", "method": "$/somethingNew", "params": {}}])
    assert not any("error" in m for m in said)
