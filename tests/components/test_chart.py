"""frontage-chart: the wrapper's contract, with the JavaScript half stubbed.

`frontage.chart.plot` imports `chart`, which in a page is the module `frontage build`
registered from `_browser/index.js`. On CPython there is no such module, so these tests supply
one and assert what Python sends across the boundary — which is the only part we own.
"""

import sys
import types

import pytest


class FakeJs:
    def __init__(self):
        self.drawn = []
        self.destroyed = []

    def draw(self, node, series, options):
        self.drawn.append((series, options))

    def destroy(self, node):
        self.destroyed.append(node)


@pytest.fixture
def js(monkeypatch):
    """Stand in for the registered JavaScript module, before the wrapper imports it."""
    fake = FakeJs()
    module = types.ModuleType("chart")
    module.draw = fake.draw  # ty: ignore[unresolved-attribute]
    module.destroy = fake.destroy  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "chart", module)
    for name in [n for n in sys.modules if n.startswith("frontage.chart")]:
        monkeypatch.delitem(sys.modules, name)
    return fake


def test_a_chart_is_an_element_with_a_class_to_hang_css_on(js):
    from frontage import render_to_string
    from frontage.chart import line_chart

    out = render_to_string(lambda: line_chart(lambda: [[0, 1], [2, 3]]))
    assert "fr-chart" in out


def test_the_data_accessor_is_read_and_forwarded(js):
    from frontage import render_to_string
    from frontage.chart import line_chart

    render_to_string(lambda: line_chart(lambda: [[0, 1], [5, 6]], labels=["a"]))
    assert js.drawn, "the effect never ran, so nothing would ever be drawn"
    series, options = js.drawn[-1]
    assert list(series[0]) == [0, 1] and list(series[1]) == [5, 6]
    assert options["labels"] == ["a"]


def test_plain_data_works_as_well_as_an_accessor(js):
    from frontage import render_to_string
    from frontage.chart import line_chart

    render_to_string(lambda: line_chart([[0, 1], [2, 3]]))
    assert js.drawn


def test_a_signal_write_redraws_and_nothing_else_does(js):
    from frontage import Signal, h, mount
    from frontage.chart import line_chart
    from frontage.renderer import HtmlRenderer

    n = Signal(2)
    renderer = HtmlRenderer()
    root = renderer.create_element("div")
    mount(lambda: h.div(line_chart(lambda: [list(range(n())), list(range(n()))])), root, renderer)
    before = len(js.drawn)
    n.set(3)
    assert len(js.drawn) == before + 1
    assert len(js.drawn[-1][0][0]) == 3


@pytest.mark.parametrize("kind", ["line", "area", "bar", "scatter"])
def test_each_kind_says_which_it_is(js, kind):
    import frontage.chart
    from frontage import render_to_string

    chart = getattr(frontage.chart, f"{kind}_chart")
    render_to_string(lambda: chart(lambda: [[0], [1]]))
    assert js.drawn[-1][1]["kind"] == kind


def test_disposing_the_view_lets_the_library_go(js):
    from frontage import Show, Signal, h, mount
    from frontage.chart import line_chart
    from frontage.renderer import HtmlRenderer

    shown = Signal(True)
    renderer = HtmlRenderer()
    root = renderer.create_element("div")
    mount(lambda: h.div(Show(shown, lambda: line_chart(lambda: [[0], [1]]))), root, renderer)
    assert not js.destroyed
    shown.set(False)
    assert js.destroyed, "destroy() was never called, so uPlot would keep the canvas alive"
