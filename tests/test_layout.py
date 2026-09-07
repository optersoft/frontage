"""frontage-layout: what each element renders, and the rules it must not break."""

import pytest
from frontage import Signal, render_to_string
from frontage_layout import (
    STYLESHEET,
    columns,
    container,
    divider,
    expander,
    metric,
    progress,
    spinner,
    tabs,
)


def html(view):
    return render_to_string(lambda: view)


# --- columns ------------------------------------------------------------------------------


def test_columns_are_a_grid_with_equal_tracks_by_default():
    out = html(columns("a", "b", "c"))
    assert "grid-template-columns:repeat(3, 1fr)" in out.replace(" ;", ";")
    assert out.count('class="fr-col"') == 3


def test_relative_widths_become_fr_tracks():
    assert "grid-template-columns:1fr 3fr" in html(columns("a", "b", widths=[1, 3]))


# --- metric -------------------------------------------------------------------------------


def test_a_metric_shows_label_value_and_delta():
    out = html(metric("Revenue", "€1.2M", delta="+4%"))
    assert "Revenue" in out and "€1.2M" in out and "+4%" in out


def test_a_negative_delta_is_styled_as_a_fall():
    assert "fr-down" in html(metric("Churn", "1.8%", delta="-0.3%"))
    assert "fr-up" in html(metric("Churn", "1.8%", delta="+0.3%"))


def test_a_metric_over_a_signal_updates_rather_than_rebuilding():
    value = Signal(1)
    out = html(metric("N", lambda: f"{value()}"))
    assert ">1<" in out  # the accessor was read, not stringified as a function


# --- progress -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, "0.0%"), (0.5, "50.0%"), (1.0, "100.0%"), (-3, "0.0%"), (7, "100.0%")],
)
def test_progress_clamps_to_the_track(value, expected):
    assert f"width:{expected}" in html(progress(value)).replace(" ", "")


# --- tabs ---------------------------------------------------------------------------------


def test_tabs_render_a_strip_and_only_the_selected_panel():
    out = html(tabs([("One", "first"), ("Two", "second")]))
    assert out.count("fr-tab ") + out.count('fr-tab"') >= 2
    assert "first" in out and "second" not in out  # only the open panel is built


def test_the_first_pair_opens():
    assert "fr-active" in html(tabs([("One", "first"), ("Two", "second")]))


def test_tabs_refuse_a_dict_because_micropython_loses_the_order():
    """CPython guarantees insertion order since 3.7 and MicroPython does not, so a dict here
    puts the tabs in an arbitrary order and opens the wrong one. Caught in a real browser."""
    with pytest.raises(TypeError, match="pairs, not a dict"):
        tabs({"One": "first", "Two": "second"})


def test_tabs_need_a_panel():
    with pytest.raises(ValueError):
        tabs([])


def test_a_caller_may_own_the_selection():
    which = Signal("Two")
    out = html(tabs([("One", "first"), ("Two", "second")], active=which))
    assert "second" in out and "first" not in out


# --- the rest -----------------------------------------------------------------------------


def test_expander_is_a_details_element():
    out = html(expander("More", "hidden thing"))
    assert "<details" in out and "<summary" in out and "More" in out


def test_expander_can_start_open():
    assert "open" in html(expander("More", "x", open=True))


def test_container_and_divider():
    assert "fr-container" in html(container("x"))
    assert "<hr" in html(divider())


def test_spinner_says_what_it_is_waiting_for():
    assert "Fetching" in html(spinner("Fetching"))


# --- the stylesheet -------------------------------------------------------------------------


def test_every_class_the_package_emits_has_a_rule():
    """The stylesheet and the elements are written in different files; nothing but a test keeps
    them honest."""
    emitted = set()
    for view in (
        columns("a", widths=[1]),
        container("a"),
        divider(),
        expander("l", "b"),
        metric("l", "v", delta="+1"),
        progress(0.5, label="p"),
        spinner(),
        tabs([("a", "b")]),
    ):
        out = html(view)
        for chunk in out.split('class="')[1:]:
            emitted.update(chunk.split('"')[0].split())
    missing = {c for c in emitted if c.startswith("fr-") and f".{c}" not in STYLESHEET}
    assert not missing, f"classes with no rule: {sorted(missing)}"


def test_the_shipped_stylesheet_matches_the_source():
    """`_browser/index.css` is generated from `style.py`; two copies drift."""
    from pathlib import Path

    import frontage_layout

    shipped = Path(frontage_layout.__file__).parent / "_browser" / "index.css"
    assert shipped.read_text() == STYLESHEET
