"""`frontage.testing`: an app mounted without a browser, driven and read."""

import asyncio

import pytest

from frontage import Errored, For, Loading, Resource, Show, Signal, component, h
from frontage.testing import App, NotFound
from frontage.widgets import button, text_input


@component
def counter(start=0):
    count = Signal(start)
    return h.div(
        h.span(count, cls="count"),
        h.button("+", on_click=lambda ev: count.update(lambda n: n + 1), cls="inc"),
        h.button("-", on_click=lambda ev: count.update(lambda n: n - 1), cls="dec"),
        cls="counter",
    )


def test_mount_and_read():
    with App(counter) as app:
        assert app.find(".count").text == "0"
        assert app.find(".counter").tag == "div"
        assert '<span class="count">0</span>' in app.html


def test_click_updates_one_node():
    with App(counter) as app:
        app.click("button.inc")
        app.click("button.inc")
        assert app.find(".count").text == "2"
        app.click("button.dec")
        assert app.find(".count").text == "1"


def test_text_collapses_whitespace():
    with App(lambda: h.p("  two   words\n")) as app:
        assert app.text == "two words"


def test_find_all_and_query():
    with App(counter) as app:
        assert len(app.find_all("button")) == 2
        assert app.query(".nope") is None
        with pytest.raises(NotFound):
            app.find(".nope")


def test_descendant_selector():
    view = lambda: h.div(h.form(h.span("in", cls="x")), h.span("out", cls="x"))  # noqa: E731
    with App(view) as app:
        assert app.find("form .x").text == "in"
        assert len(app.find_all(".x")) == 2


def test_attribute_selector():
    with App(lambda: h.input(type="email", name="who")) as app:
        assert app.find("[name=who]").attrs["type"] == "email"
        assert app.find("input[type=email]").attrs["name"] == "who"


@pytest.mark.parametrize("selector", ["div > p", "p:first-child", "a, b", "*"])
def test_unsupported_selector_says_so(selector):
    with App(lambda: h.p("x")) as app:
        with pytest.raises(ValueError, match="not supported"):
            app.find(selector)


def test_get_by_text_takes_the_innermost():
    with App(lambda: h.div(h.p("Save"))) as app:
        assert app.get_by_text("Save").tag == "p"


def test_get_by_label_finds_the_control():
    name = Signal("")

    def view():
        return h.form(text_input(name, "Name"), text_input(Signal(""), "Email"))

    with App(view) as app:
        app.get_by_label("Name").type("Ada")
        assert name() == "Ada"
        assert app.get_by_label("Name").value == "Ada"
        with pytest.raises(NotFound):
            app.get_by_label("Nope")


def test_typing_drives_a_bound_signal():
    text = Signal("")

    def view():
        return h.div(h.input(bind_value=text), h.span(text, cls="echo"))

    with App(view) as app:
        app.type("input", "hello")
        assert app.find(".echo").text == "hello"


def test_checkbox_and_show():
    on = Signal(False)

    def view():
        return h.div(h.input(type="checkbox", bind_checked=on), Show(on, lambda: h.p("yes", cls="yes")))

    with App(view) as app:
        assert app.query(".yes") is None
        app.check("input")
        assert app.find(".yes").text == "yes"


def test_for_rows():
    items = Signal(["a", "b"])

    def view():
        return h.ul(For(items, lambda item, i: h.li(item)))

    with App(view) as app:
        assert [n.text for n in app.find_all("li")] == ["a", "b"]
        items.set(["a", "b", "c"])
        app.settle()
        assert [n.text for n in app.find_all("li")] == ["a", "b", "c"]


def test_disabled_reads_the_property():
    with App(lambda: button("Save", disabled=True)) as app:
        assert app.find("button").disabled


# -- async ---------------------------------------------------------------------------------


def test_resource_is_settled_before_the_first_assertion():
    async def load():
        await asyncio.sleep(0.01)
        return "Girona"

    def view():
        city = Resource(load)
        return Loading(h.p("…", cls="wait"), lambda: h.p(city, cls="city"))

    with App(view) as app:
        assert app.find(".city").text == "Girona"


def test_settle_false_leaves_the_page_mid_flight():
    async def load():
        await asyncio.sleep(0.02)
        return "late"

    def view():
        city = Resource(load)
        return h.div(
            h.button("go", on_click=lambda ev: city.refetch(), cls="go"),
            Loading(h.p("…", cls="wait"), lambda: h.p(city, cls="city")),
        )

    with App(view) as app:
        assert app.find(".city").text == "late"
        app.click("button.go", settle=False)
        assert app.find(".wait").text == "…"  # mid-flight: the Loading fallback is back
        app.settle()
        assert app.find(".city").text == "late"


def test_a_click_that_fetches_finishes_before_the_assertion():
    who = Signal(None)

    async def load(target):
        if target is None:
            return "nobody"
        await asyncio.sleep(0.01)
        return target.upper()

    def view():
        name = Resource(load, source=who)
        return h.div(
            h.button("go", on_click=lambda ev: who.set("ada"), cls="go"),
            Loading(h.p("…"), lambda: h.p(name, cls="name")),
        )

    with App(view) as app:
        assert app.find(".name").text == "nobody"
        app.click("button.go")
        assert app.find(".name").text == "ADA"


def test_a_failing_resource_reaches_errored():
    async def load():
        raise ValueError("no")

    def view():
        broken = Resource(load)
        return Errored(lambda exc, reset: h.p(f"failed: {exc}", cls="err"), lambda: h.p(broken))

    with App(view) as app:
        assert app.find(".err").text == "failed: no"


def test_settle_times_out_with_a_useful_message():
    async def never():
        await asyncio.sleep(10)

    def view():
        Resource(never)
        return h.p("hi")

    with pytest.raises(TimeoutError, match="resource #0"):
        App(view, timeout=0.05)


def test_dispose_is_idempotent_and_refuses_further_work():
    app = App(counter)
    app.dispose()
    app.dispose()
    with pytest.raises(RuntimeError, match="disposed"):
        app.click("button.inc")


def test_an_attribute_value_may_hold_a_space():
    with App(lambda: h.button("x", aria_label="Good answer")) as app:
        assert app.find("[aria-label=Good answer]").text == "x"


def test_an_unclosed_attribute_test_says_so():
    with App(lambda: h.p("x")) as app:
        with pytest.raises(ValueError, match="not closed"):
            app.find("[name=who")


# -- from_module ----------------------------------------------------------------------------


def _write(tmp_path, monkeypatch, body, name="entry_app"):
    import sys

    (tmp_path / f"{name}.py").write_text(body)
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(name, None)
    return name


ENTRY = """
from frontage import Signal, h, mount

count = Signal(0)
view = lambda: h.div(h.span(count, cls="n"), h.button("+", on_click=lambda ev: count.update(lambda n: n + 1)))
mount(view, "#app")
"""


def test_from_module_mounts_the_entry_file(tmp_path, monkeypatch):
    name = _write(tmp_path, monkeypatch, ENTRY)
    with App.from_module(name) as app:
        assert app.find(".n").text == "0"
        app.click("button")
        assert app.find(".n").text == "1"


def test_from_module_imports_fresh_so_two_tests_do_not_share_state(tmp_path, monkeypatch):
    name = _write(tmp_path, monkeypatch, ENTRY)
    with App.from_module(name) as app:
        app.click("button")
        assert app.find(".n").text == "1"
    with App.from_module(name) as app:
        assert app.find(".n").text == "0"


def test_from_module_says_so_when_nothing_was_mounted(tmp_path, monkeypatch):
    name = _write(tmp_path, monkeypatch, "x = 1\n")
    with pytest.raises(AssertionError, match="mounted nothing"):
        App.from_module(name)


def test_from_module_needs_a_selector_when_a_page_holds_several(tmp_path, monkeypatch):
    body = ENTRY + '\nmount(lambda: h.p("aside", cls="aside"), "#side")\n'
    name = _write(tmp_path, monkeypatch, body)
    with pytest.raises(AssertionError, match="has 2 mounts"):
        App.from_module(name)
    with App.from_module(name, selector="#side") as app:
        assert app.find(".aside").text == "aside"
