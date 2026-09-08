"""`frontage.dev`: replacing an app's modules in a running page without reloading it."""

import pytest

from frontage import dev, h, mount, view
from frontage.renderer import HtmlRenderer

APP = """from frontage import h, mount
mount(lambda: h.p("{text}"), TARGET, renderer=RENDERER)
"""


@pytest.fixture(autouse=True)
def clean_registry():
    """Every test starts and ends with nothing mounted."""
    del view._mounted[:]
    yield
    del view._mounted[:]


def mount_one(text="one"):
    renderer = HtmlRenderer()
    root = renderer.create_element("div")
    return mount(lambda: h.p(text), root, renderer), root


# --- the registry ------------------------------------------------------------------------


def test_a_mount_registers_itself_and_a_dispose_removes_it():
    assert view._mounted == []
    handle, _ = mount_one()
    assert view._mounted == [handle]
    handle.dispose()
    assert view._mounted == []
    handle.dispose()  # idempotent: a swap disposes what a test may already have


def test_the_handle_remembers_what_a_remount_would_need():
    handle, root = mount_one()
    assert handle.renderer is not None and handle.parent is root


# --- teardown ----------------------------------------------------------------------------


def test_teardown_disposes_every_mount_and_empties_the_registry():
    first, _ = mount_one("a")
    second, _ = mount_one("b")
    assert len(view._mounted) == 2
    dev.teardown()
    assert view._mounted == []
    assert first.owner._disposed and second.owner._disposed


def test_teardown_asks_the_renderer_to_clean_up_the_document():
    """The delegated dispatchers live on `document` and no owner holds them, so the renderer
    has to be asked. A renderer without `teardown` (the HTML one) is simply skipped."""
    called = []

    class Recording(HtmlRenderer):
        def teardown(self):
            called.append(True)

    renderer = Recording()
    root = renderer.create_element("div")
    mount(lambda: h.p("x"), root, renderer)
    dev.teardown()
    assert called == [True]


# --- swapping ----------------------------------------------------------------------------


def write_app(tmp_path, text, name="app"):
    (tmp_path / f"{name}.py").write_text(
        "from frontage import h, mount\n"
        "from frontage.renderer import HtmlRenderer\n"
        "_r = HtmlRenderer()\n"
        "_root = _r.create_element('div')\n"
        f"mount(lambda: h.p({text!r}), _root, _r)\n"
    )


def test_a_swap_disposes_the_old_page_and_runs_the_entry_again(tmp_path):
    write_app(tmp_path, "first")
    dev.swap("app", ["app"], root=str(tmp_path))
    assert len(view._mounted) == 1
    first = view._mounted[0]

    write_app(tmp_path, "second")
    dev.swap("app", ["app"], root=str(tmp_path))
    assert len(view._mounted) == 1  # the old one went, exactly one replaced it
    assert view._mounted[0] is not first
    assert first.owner._disposed


def test_a_syntax_error_is_caught_before_anything_is_taken_apart(tmp_path):
    """The point of compiling first. A half-typed file must leave the working page up."""
    write_app(tmp_path, "good")
    dev.swap("app", ["app"], root=str(tmp_path))
    live = view._mounted[0]

    (tmp_path / "app.py").write_text("def broken(:\n")
    with pytest.raises(SyntaxError):
        dev.swap("app", ["app"], root=str(tmp_path))
    assert view._mounted == [live] and not live.owner._disposed


def test_a_swap_resets_the_id_counters_so_a_swap_matches_a_reload(tmp_path):
    write_app(tmp_path, "x")
    view._ids[0] = 7
    view._mounts[0] = 3
    dev.swap("app", ["app"], root=str(tmp_path))
    assert view._ids[0] == 0 and view._mounts[0] == 1  # the mount this swap made


def test_the_entry_is_swapped_even_when_only_a_sibling_changed(tmp_path):
    write_app(tmp_path, "x")
    (tmp_path / "helpers.py").write_text("VALUE = 1\n")
    assert dev.swap("app", ["helpers"], root=str(tmp_path)) == 2


def test_the_entry_runs_as_dunder_main(tmp_path):
    """What `<script type="mpy" src>` gave it, and what `boot.js` gives it on a first load."""
    (tmp_path / "app.py").write_text("import sys\nsys.modules['probe'] = __name__\n")
    dev.swap("app", ["app"], root=str(tmp_path))
    import sys

    assert sys.modules.pop("probe") == "__main__"


# --- state across a swap -----------------------------------------------------------------


STATEFUL = """from frontage import Signal, Store, h, mount
from frontage.state import State, field

count = Signal({count})
todos = Store(["milk"])
settings = Store({{"theme": "light"}})


class Prefs(State):
    name = field("ann")


prefs = Prefs()
mount(lambda: h.p("{text}"), TARGET, renderer=RENDERER)
"""


def write_stateful(tmp_path, text, count=0):
    source = STATEFUL.format(text=text, count=count)
    renderer = HtmlRenderer()
    root = renderer.create_element("div")
    source = source.replace("TARGET", "__target__").replace("RENDERER", "__renderer__")
    import builtins

    builtins.__target__ = root  # ty: ignore[unresolved-attribute]
    builtins.__renderer__ = renderer  # ty: ignore[unresolved-attribute]
    (tmp_path / "app.py").write_text(source)


def entry_value(name):
    namespace = dev._entry_ns[0]
    assert namespace is not None, "the entry has not run yet"
    return namespace[name]


def test_module_level_state_survives_a_swap(tmp_path):
    """Vue's rule: the qualified name identifies the state, so editing the view around it
    leaves the values where the user put them."""
    write_stateful(tmp_path, "one")
    dev.swap("app", ["app"], root=str(tmp_path))
    entry_value("count").set(7)
    entry_value("todos").set(lambda todos: todos.append("bread"))
    entry_value("settings").set_path("theme", "dark")
    entry_value("prefs").name = "bob"

    write_stateful(tmp_path, "two")
    dev.swap("app", ["app"], root=str(tmp_path))
    assert entry_value("count")() == 7
    assert list(entry_value("todos")) == ["milk", "bread"]
    assert entry_value("settings")["theme"] == "dark"
    assert entry_value("prefs").name == "bob"


def test_an_edit_to_the_initial_value_does_not_win_over_the_live_one(tmp_path):
    """The state is restored after the rebuild, so the source's new starting value is
    overwritten. Reloading the page is what starts from the source again."""
    write_stateful(tmp_path, "one", count=0)
    dev.swap("app", ["app"], root=str(tmp_path))
    entry_value("count").set(3)

    write_stateful(tmp_path, "one", count=99)
    dev.swap("app", ["app"], root=str(tmp_path))
    assert entry_value("count")() == 3


def test_state_that_was_renamed_or_removed_starts_fresh(tmp_path):
    write_stateful(tmp_path, "one")
    dev.swap("app", ["app"], root=str(tmp_path))
    entry_value("count").set(5)

    (tmp_path / "app.py").write_text(
        "from frontage import Signal, h, mount\ntally = Signal(0)\nmount(lambda: h.p('x'), __target__, renderer=__renderer__)\n"
    )
    dev.swap("app", ["app"], root=str(tmp_path))
    assert entry_value("tally")() == 0
