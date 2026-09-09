"""Content collections: a directory of Markdown checked by a schema, rendered once, on CPython.

None of this ships. The browser half of it is one thing — an `::: island` container in prose
becomes a mount with a trigger — and `tests/browser/test_content.py` is that.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from frontage.cli import frontage_rt
from frontage.content import (
    ContentError,
    collection,
    jsonable,
    markdown,
    split_front_matter,
    view_of,
)
from frontage.content import _render as render_body
from frontage.runtime import prerender as prerender_state
from frontage.schema import iso_date, record, text
from frontage.view import render_to_string

ROOT = Path(__file__).resolve().parents[1]

Post = record(("title", text(min=1)), ("date", iso_date()), ("summary", text(), None))

HELLO = """---
title: Hello
date: 2026-09-02
summary: The first one.
---

A paragraph with **bold**.
"""

LATER = """---
title: Later
date: 2026-09-07
---

Another one.
"""


@pytest.fixture
def posts(tmp_path):
    directory = tmp_path / "posts"
    directory.mkdir()
    (directory / "hello.md").write_text(HELLO)
    (directory / "later.md").write_text(LATER)
    return directory


# --- reading a file ---------------------------------------------------------------------------


def test_front_matter_is_the_first_fence_and_only_the_first():
    assert split_front_matter("---\ntitle: x\n---\nbody\n") == ("title: x", "body\n")
    # A horizontal rule further down is three dashes too, and eating half a post over it
    # would be the kind of bug nobody reports because they assume they wrote it wrong.
    assert split_front_matter("no front matter\n\n---\n\nmore\n")[0] == ""
    with pytest.raises(ContentError, match="never closed"):
        split_front_matter("---\ntitle: x\nbody with no closing fence\n")


def test_yaml_dates_come_back_as_iso_strings():
    # `date: 2026-09-02` is a `datetime.date` to YAML, and a schema says `iso_date()` because
    # the browser has no date type — so without this the field that looks most obviously
    # right is the one that fails, with "expected a string".
    assert jsonable({"date": __import__("datetime").date(2026, 9, 2)}) == {"date": "2026-09-02"}
    assert jsonable([1, "a", None, True]) == [1, "a", None, True]


def test_a_value_that_is_not_json_names_the_field_it_sits_in():
    with pytest.raises(ContentError, match=r"tags\[0\]: set is not JSON"):
        jsonable({"tags": [set()]})


def test_json_and_yaml_files_are_data_with_no_body(tmp_path):
    (tmp_path / "a.json").write_text('{"title": "A"}')
    (tmp_path / "b.yaml").write_text("title: B\ntags: [x, y]\n")
    people = collection("people", root=tmp_path)
    assert [(e.slug, e.data, e.body) for e in people.entries()] == [
        ("a", {"title": "A"}, ""),
        ("b", {"title": "B", "tags": ["x", "y"]}, ""),
    ]


# --- collections -------------------------------------------------------------------------------


def test_entries_are_newest_first_when_every_one_has_a_date(posts):
    found = collection("posts", Post, root=posts).entries()
    assert [e.slug for e in found] == ["later", "hello"]
    assert found[1].data["summary"] == "The first one."
    assert found[0].data["summary"] is None  # optional, and absent


def test_without_dates_entries_are_in_slug_order(tmp_path):
    for name in ("c", "a", "b"):
        (tmp_path / f"{name}.md").write_text(f"---\ntitle: {name}\n---\n")
    assert [e.slug for e in collection("x", root=tmp_path).entries()] == ["a", "b", "c"]


def test_order_and_reverse_are_the_reader_s_to_choose(posts):
    found = collection("posts", Post, root=posts)
    assert [e.slug for e in found.entries(order="title")] == ["hello", "later"]
    assert [e.slug for e in found.entries(order="date", reverse=False)] == ["hello", "later"]


def test_get_by_slug_lists_what_there_is_when_it_misses(posts):
    found = collection("posts", Post, root=posts)
    assert found.get("hello").data["title"] == "Hello"
    with pytest.raises(ContentError, match="no entry 'nope' .*hello, later"):
        found.get("nope")


def test_a_missing_directory_says_so(tmp_path):
    with pytest.raises(ContentError, match="is not a directory"):
        collection("ghosts", root=tmp_path / "nowhere").entries()


def test_bad_front_matter_fails_the_build_naming_the_file_and_the_field(tmp_path):
    """`ISLAND.md` step D's gate, exactly as it is written there."""
    (tmp_path / "draft.md").write_text("---\ntitle: ''\ndate: not-a-date\n---\n\nbody\n")
    with pytest.raises(ContentError) as raised:
        collection("posts", Post, root=tmp_path).entries()
    message = str(raised.value)
    assert "draft.md" in message
    assert "title" in message and "date" in message


def test_a_collection_is_iterable_and_sized(posts):
    found = collection("posts", Post, root=posts)
    assert len(found) == 2
    assert [e.slug for e in found] == ["later", "hello"]
    assert found.entries()[0]["title"] == "Later"


# --- Markdown ------------------------------------------------------------------------------------


def test_markdown_renders_commonmark_and_tables():
    html = markdown("# Title\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert "<h1>Title</h1>" in html and "<table>" in html and "<td>1</td>" in html


def test_a_container_becomes_a_div_of_that_class():
    html = markdown("::: aside note A title\ninside\n:::\n")
    assert '<div class="aside" data-args="note A title">' in html
    assert "<p>inside</p>" in html


def test_an_island_container_is_taken_out_of_the_html_and_named():
    html, islands = render_body('Before.\n\n::: island posts:comments when="visible" post="hello"\n:::\n\nAfter.\n')
    assert islands == [("posts:comments", "visible", {"post": "hello"})]
    assert "<!--fr-island:0-->" in html
    assert "comments" not in html.replace("<!--fr-island:0-->", "")
    assert "<p>Before.</p>" in html and "<p>After.</p>" in html


def test_an_island_container_with_no_component_says_what_it_wanted():
    with pytest.raises(ContentError, match="names its component"):
        render_body('::: island when="visible"\n:::\n')


def test_island_props_are_read_as_json_where_they_look_like_it():
    _, islands = render_body('::: island x:y when="idle" n=3 flag=true name="a b"\n:::\n')
    assert islands == [("x:y", "idle", {"n": 3, "flag": True, "name": "a b"})]


# --- prose as a view ---------------------------------------------------------------------------


def test_prose_becomes_a_view_and_an_island_in_it_registers():
    html, islands = render_body('# T\n\nText.\n\n::: island widgets:poll when="visible"\n:::\n')
    prerender_state.static = True
    prerender_state.islands = []
    try:
        out = render_to_string(lambda: view_of(html, islands))
    finally:
        prerender_state.static = False
    assert "<h1>T</h1>" in out and "<p>Text.</p>" in out
    assert '<fr-island id="fr-island-0"' in out and 'data-fr-when="visible"' in out
    assert [(i.spec, i.when) for i in prerender_state.islands] == [("widgets:poll", "visible")]


def test_entry_view_is_the_body_and_entry_html_is_the_string(posts):
    entry = collection("posts", Post, root=posts).get("hello")
    assert entry.html().strip() == "<p>A paragraph with <strong>bold</strong>.</p>"
    assert render_to_string(entry.view).strip() == "<p>A paragraph with <strong>bold</strong>.</p>"


# --- the build ------------------------------------------------------------------------------------


def test_an_island_named_in_markdown_reaches_the_manifest(tmp_path):
    """The import walk cannot see a module named in prose, so the render has to tell the build."""
    modules, chunks, islands = frontage_rt.analyse(_content_app(tmp_path), "app", islands=["widgets:poll"])
    assert islands is True
    assert chunks == {"widgets": ["widgets"]}
    names = [name for name, _ in modules]
    assert "widgets" in names and frontage_rt.ISLAND_MODULE in names


def _content_app(tmp_path):
    (tmp_path / "app.py").write_text("from frontage import h, mount\n\nmount(lambda: h.p('x'), '#app', when='never')\n")
    (tmp_path / "widgets.py").write_text("from frontage import h\n\n\ndef poll():\n    return h.b('poll')\n")
    return tmp_path


@pytest.mark.skipif(not frontage_rt.available(), reason="the runtime is not vendored")
def test_the_blog_example_prerenders_to_a_page_with_no_boot_tag(tmp_path):
    out = tmp_path / "blog"
    run = subprocess.run(
        [sys.executable, "-m", "frontage", "prerender", str(ROOT / "examples" / "blog"), "--out", str(out), "--quiet"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert run.returncode == 0, run.stderr
    page = (out / "index.html").read_text()
    assert "data-fr-boot" not in page and "island.js" in page
    assert 'data-fr-island="widgets:reactions"' in page
    # The prose is in the page: rendered on CPython, from Markdown, at build time.
    assert "<blockquote>" in page and "Zero by default" in page
    # The three posts came out newest first.
    assert page.index("An island in prose") < page.index("Zero by default") < page.index("Front matter is a schema")
    manifest = json.loads((out / "_frontage" / "manifest.json").read_text())
    assert manifest["islands"] is True and manifest["chunks"] == {"widgets": ["widgets"]}
    # Only the islands decide a static page's components, and this one's island uses none.
    assert "components/schema" not in page
