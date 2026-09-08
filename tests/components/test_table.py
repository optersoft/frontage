"""frontage-table: formatting, sorting, filtering, and the point of the whole thing —
that the number of elements does not follow the number of rows."""

import pytest

from frontage import Signal, render_to_string
from frontage.table import STYLESHEET, Column, table

PEOPLE = [
    {"name": "Ada", "qty": 1200, "team": "north"},
    {"name": "Grace", "qty": 70, "team": "south"},
    {"name": "Barbara", "qty": 340, "team": "north"},
]


def html(view):
    return render_to_string(lambda: view)


def rows_in(out):
    return out.count('class="fr-tr"')


# --- columns ------------------------------------------------------------------------------


def test_a_column_formats_with_a_str_format_spec():
    assert Column("qty", "Qty", ",").text({"qty": 1234567}) == "1,234,567"


def test_a_column_accepts_a_callable():
    assert Column("qty", format=lambda v: f"<{v}>").text({"qty": 3}) == "<3>"


def test_a_bad_format_falls_back_to_str_rather_than_raising():
    # A column spec is written once and meets every row; one odd value must not kill the page.
    assert Column("name", format=",").text({"name": "Ada"}) == "Ada"


def test_a_missing_value_is_empty_not_none():
    assert Column("nope").text({"name": "Ada"}) == ""


def test_inferred_columns_are_sorted_not_dict_ordered():
    """MicroPython does not preserve insertion order, so inferring from a row's keys would
    shuffle the header in the browser. Sorted is arbitrary but at least the same everywhere."""
    out = html(table(lambda: PEOPLE))
    assert out.index(">name<") < out.index(">qty<") < out.index(">team<")


# --- what the reader sees -------------------------------------------------------------------


def test_the_header_and_the_rows_render():
    out = html(table(lambda: PEOPLE, columns=[("name", "Name"), ("qty", "Qty", ",")]))
    assert "Name" in out and "Qty" in out
    assert "Ada" in out and "1,200" in out


def test_the_footer_counts_the_rows_after_filtering():
    query = Signal("north")
    out = html(table(lambda: PEOPLE, search=query))
    assert "2 rows" in out


def test_search_matches_any_displayed_cell():
    query = Signal("grace")  # case-insensitive, and it is a name not a number
    out = html(table(lambda: PEOPLE, search=query))
    assert "Grace" in out and "Ada" not in out


def test_an_empty_search_keeps_everything():
    out = html(table(lambda: PEOPLE, search=Signal("   ")))
    assert "3 rows" in out


# --- virtualisation, which is the whole point ----------------------------------------------


@pytest.mark.parametrize("count", [1_000, 100_000])
def test_the_elements_do_not_follow_the_row_count(count):
    data = [{"n": i} for i in range(count)]
    out = html(table(lambda: data, height=320, row_height=32))
    # 320/32 = 10 visible, plus 4 rows of overscan at each edge.
    assert rows_in(out) <= 20, f"{rows_in(out)} row elements for {count:,} rows"
    assert f"{count:,} rows" in out  # the footer still knows how many there are


def test_the_spacer_is_the_full_height_so_the_scrollbar_is_honest():
    data = [{"n": i} for i in range(1000)]
    out = html(table(lambda: data, row_height=32))
    assert "height:32000px" in out.replace(" ", "")


def test_a_short_table_renders_every_row():
    out = html(table(lambda: PEOPLE, height=320))
    assert rows_in(out) == 3


# --- the stylesheet ---------------------------------------------------------------------------


def test_every_class_has_a_rule():
    out = html(table(lambda: PEOPLE, search=Signal("")))
    emitted = set()
    for chunk in out.split('class="')[1:]:
        emitted.update(chunk.split('"')[0].split())
    missing = {c for c in emitted if c.startswith("fr-") and f".{c}" not in STYLESHEET}
    assert not missing, f"classes with no rule: {sorted(missing)}"


def test_the_shipped_stylesheet_matches_the_source():
    from pathlib import Path

    import frontage.table

    shipped = Path(frontage.table.__file__).parent / "_browser" / "index.css"
    assert shipped.read_text() == STYLESHEET


# --- sorting ---------------------------------------------------------------------------------


def test_numbers_sort_as_numbers_not_as_their_formatted_text():
    """`"1,200" < "70"` as strings, so sorting formatted text is wrong as well as slow —
    914 ms against 111 ms for 50,000 rows on MicroPython."""
    out = html(table(lambda: PEOPLE, columns=[("name", "Name"), ("qty", "Qty", ",")], sort=("qty", False)))
    assert out.index("Grace") < out.index("Barbara") < out.index("Ada")  # 70, 340, 1200


def test_a_descending_sort_reverses_it():
    out = html(table(lambda: PEOPLE, columns=[("name", "Name"), ("qty", "Qty")], sort=("qty", True)))
    assert out.index("Ada") < out.index("Barbara") < out.index("Grace")


def test_sorting_a_string_column_is_alphabetical():
    out = html(table(lambda: PEOPLE, columns=[("name", "Name")], sort=("name", False)))
    assert out.index("Ada") < out.index("Barbara") < out.index("Grace")


def test_a_column_of_mixed_types_still_sorts():
    """None beside a number raises in CPython's `sorted`; the text fallback catches it."""
    mixed = [{"v": 3}, {"v": None}, {"v": 1}]
    assert "3 rows" in html(table(lambda: mixed, columns=[("v", "V")], sort=("v", False)))


def test_an_unknown_sort_key_is_ignored_rather_than_fatal():
    assert "3 rows" in html(table(lambda: PEOPLE, columns=[("name", "Name")], sort=("nope", False)))


def test_the_raw_value_is_what_sorting_compares():
    from frontage.table import Column

    column = Column("qty", format=",")
    assert column.value({"qty": 1200}) == 1200 and column.text({"qty": 1200}) == "1,200"
