"""The import walk behind `frontage build`: what a page reaches, read with `ast`, never imported."""

from pathlib import Path

from frontage.cli import build
from frontage.cli.graph import Graph

ROOT = Path(__file__).resolve().parents[1]


def write(tmp_path, **files):
    app = tmp_path / "app"
    for name, text in files.items():
        path = app / name.replace(".", "/").replace("/py", ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return app


def framework(names):
    return sorted(n.removeprefix("frontage.") for n in names if n.startswith("frontage"))


def test_a_counter_reaches_the_reactive_core_and_the_view_layer_and_nothing_else(tmp_path):
    app = write(tmp_path, **{"app.py": "from frontage import Signal, h, mount\nmount(h.div('x'), '#app')\n"})
    g = Graph(app)
    reached = g.closure(["app", "frontage"])
    assert "app" in reached
    assert {"frontage", "frontage._exports", "frontage.version", "frontage.reactive", "frontage.view"} <= reached
    assert (
        not {"frontage.router", "frontage.store", "frontage.template", "frontage.widgets", "frontage.state"} & reached
    )


def test_the_router_and_the_store_come_only_when_named(tmp_path):
    app = write(tmp_path, **{"app.py": "from frontage import Router, Route, Store\n"})
    reached = Graph(app).closure(["app", "frontage"])
    assert {"frontage.router", "frontage.store", "frontage.aio", "frontage.flow"} <= reached


def test_a_bare_import_frontage_is_read_through_its_attributes(tmp_path):
    app = write(
        tmp_path, **{"app.py": "import frontage\nn = frontage.Signal(1)\nfrontage.mount(frontage.h.p(n), '#app')\n"}
    )
    reached = Graph(app).closure(["app", "frontage"])
    assert {"frontage.reactive", "frontage.view"} <= reached
    assert "frontage.router" not in reached


def test_an_attribute_the_walk_cannot_name_means_the_whole_framework(tmp_path):
    app = write(tmp_path, **{"app.py": "import frontage\nthing = getattr(frontage, NAME)\n"})
    g = Graph(app)
    reached = g.closure(["app", "frontage"])
    assert g.framework_modules <= reached


def test_app_modules_and_packages_are_followed_through_every_import_form(tmp_path):
    app = write(
        tmp_path,
        **{
            "app.py": "import data\nfrom pages.map import view\n\ndef later():\n    from helpers import fmt\n",
            "data.py": "ROWS = []\n",
            "helpers.py": "def fmt(x): return x\n",
            "pages/__init__.py": "",
            "pages/map.py": "from . import shared\nfrom .. import data\n",
            "pages/shared.py": "",
            "unused.py": "",
        },
    )
    reached = Graph(app).closure(["app"])
    assert {"app", "data", "helpers", "pages", "pages.map", "pages.shared"} <= reached
    assert "unused" not in reached


def test_a_route_naming_a_module_is_a_chunk_root(tmp_path):
    app = write(
        tmp_path,
        **{
            "app.py": (
                "from frontage import Router, Route\nfrom frontage import chunks\n"
                "Router(Route('/', home), Route('/map', lazy='pages.map'), Route('/r', lazy='pages.reports:Reports'))\n"
                "chunks.load('dialogs.export')\n"
            ),
            "pages/map.py": "",
            "pages/reports.py": "",
            "dialogs/export.py": "",
        },
    )
    g = Graph(app)
    roots = g.lazy_roots(["app"])
    assert set(roots) == {"pages.map", "pages.reports", "dialogs.export"}
    assert roots["pages.map"] == ["app"]


def test_the_include_comment_is_the_escape_hatch_for_dynamic_imports(tmp_path):
    app = write(
        tmp_path,
        **{
            "app.py": "# frontage: include plugins.*, extra\nmod = __import__('plugins.' + NAME)\n",
            "plugins/__init__.py": "",
            "plugins/a.py": "",
            "plugins/b.py": "",
            "extra.py": "",
            "other.py": "",
        },
    )
    reached = Graph(app).closure(["app"])
    assert {"plugins", "plugins.a", "plugins.b", "extra"} <= reached
    assert "other" not in reached


def test_a_component_is_reached_module_by_module(tmp_path):
    app = write(tmp_path, **{"app.py": "from frontage.schema import validate\n"})
    g = Graph(app, components=build.builtin())
    reached = g.closure(["app", "frontage"])
    assert "frontage.schema" in reached
    assert g.component_modules["frontage.schema"].name == "schema"
    # The form and the JSON Schema reader are separate modules, and this app named neither.
    assert "frontage.schema.form" not in reached
    assert "frontage.chart" not in reached


def test_a_component_pulls_in_what_it_imports_itself(tmp_path):
    app = write(tmp_path, **{"app.py": "from frontage.chart import line_chart\n"})
    g = Graph(app, components=build.builtin())
    reached = g.closure(["app", "frontage"])
    assert {"frontage.chart", "frontage.chart.plot"} <= reached
    assert "frontage.reactive" in reached  # plot.py reaches the core through `from frontage import …`


def test_the_examples_reach_less_than_the_whole_framework():
    for name in ("counter", "todo", "tracker"):
        g = Graph(ROOT / "examples" / name)
        reached = framework(g.closure([name, "frontage"]))
        assert "reactive" in reached and "view" in reached
        assert len(reached) < len(g.framework_modules), name
