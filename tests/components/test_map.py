"""frontage-map: the wrapper's contract, with the JavaScript half stubbed.

`frontage.map.map` imports `map`, which in a page is the module `frontage build` registered
from `_browser/index.js`. On CPython there is no such module, so these tests supply one and
assert what Python sends across the boundary — which is the only part we own. Leaflet's own
behaviour is Leaflet's problem.
"""

import sys
import types

import pytest


class FakeJs:
    def __init__(self):
        self.drawn = []
        self.destroyed = []

    def draw(self, node, points, options, on_click, on_move):
        self.drawn.append((points, options, on_click, on_move))

    def destroy(self, node):
        self.destroyed.append(node)


@pytest.fixture
def js(monkeypatch):
    """Stand in for the registered JavaScript module, before the wrapper imports it."""
    fake = FakeJs()
    module = types.ModuleType("map")
    module.draw = fake.draw  # ty: ignore[unresolved-attribute]
    module.destroy = fake.destroy  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "map", module)
    for name in [n for n in sys.modules if n.startswith("frontage.map")]:
        monkeypatch.delitem(sys.modules, name)
    return fake


def test_a_map_is_an_element_with_a_class_and_a_height(js):
    from frontage import render_to_string
    from frontage.map import map_view

    out = render_to_string(lambda: map_view([], height=420))
    assert "fr-map" in out
    assert "height: 420px" in out


def test_a_height_given_as_a_string_is_used_as_written(js):
    from frontage import render_to_string
    from frontage.map import map_view

    assert "height: 60vh" in render_to_string(lambda: map_view([], height="60vh"))


def test_the_points_accessor_is_read_and_forwarded(js):
    from frontage import render_to_string
    from frontage.map import map_view

    render_to_string(lambda: map_view(lambda: [{"lat": 1, "lon": 2}], zoom=9))
    assert js.drawn, "the effect never ran, so nothing would ever be drawn"
    points, options, _, _ = js.drawn[-1]
    assert points == [{"lat": 1, "lon": 2}]
    assert options["zoom"] == 9


def test_plain_points_work_as_well_as_an_accessor(js):
    from frontage import render_to_string
    from frontage.map import map_view

    render_to_string(lambda: map_view([[1, 2], [3, 4]]))
    assert js.drawn[-1][0] == [[1, 2], [3, 4]]


def test_no_points_is_an_empty_list_not_none(js):
    """`for (const point of points)` in the JavaScript half would throw on null."""
    from frontage import render_to_string
    from frontage.map import map_view

    render_to_string(lambda: map_view())
    assert js.drawn[-1][0] == []


def test_a_signal_write_redraws_and_nothing_else_does(js):
    from frontage import Signal, h, mount
    from frontage.map import map_view
    from frontage.renderer import HtmlRenderer

    points = Signal([[0, 0]])
    renderer = HtmlRenderer()
    root = renderer.create_element("div")
    mount(lambda: h.div(map_view(points)), root, renderer)
    before = len(js.drawn)
    points.set([[0, 0], [1, 1]])
    assert len(js.drawn) == before + 1
    assert len(js.drawn[-1][0]) == 2


def test_the_handlers_cross_as_callables_the_browser_can_hold(js):
    from frontage import render_to_string
    from frontage.map import map_view

    seen = []
    render_to_string(lambda: map_view([], on_click=lambda *a: seen.append(a), on_move=lambda *a: None))
    _, _, on_click, on_move = js.drawn[-1]
    assert on_click is not None and on_move is not None
    on_click(1.5, 2.5)
    assert seen == [(1.5, 2.5)]


def test_no_handler_crosses_as_none_so_the_browser_can_test_it(js):
    from frontage import render_to_string
    from frontage.map import map_view

    render_to_string(lambda: map_view([]))
    assert js.drawn[-1][2] is None and js.drawn[-1][3] is None


def test_handlers_are_not_forwarded_as_map_options(js):
    """They are arguments, not options: Leaflet would not know what to do with a function."""
    from frontage import render_to_string
    from frontage.map import map_view

    render_to_string(lambda: map_view([], on_click=lambda *a: None, height=300, cls="wide"))
    options = js.drawn[-1][1]
    assert "on_click" not in options and "height" not in options and "cls" not in options


def test_disposing_the_view_lets_the_library_go(js):
    from frontage import Show, Signal, h, mount
    from frontage.map import map_view
    from frontage.renderer import HtmlRenderer

    shown = Signal(True)
    renderer = HtmlRenderer()
    root = renderer.create_element("div")
    mount(lambda: h.div(Show(shown, lambda: map_view([[0, 0]]))), root, renderer)
    assert not js.destroyed
    shown.set(False)
    assert js.destroyed, "destroy() was never called, so Leaflet would keep the map alive"
