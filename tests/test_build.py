"""`python -m frontage build` and the runtime image behind it (no network, no browser)."""

import tarfile
from pathlib import Path

import pytest

from frontage.cli import build
from frontage.cli import micropython as mp

ROOT = Path(__file__).resolve().parents[1]

APP = "from frontage import Signal, h, mount\n\nmount(lambda: h.p('hi'), '#app')\n"


def write_app(tmp_path, **files):
    app = tmp_path / "app"
    app.mkdir()
    for name, text in files.items():
        (app / f"{name}.py").write_text(text)
    return app


# --- what ships ------------------------------------------------------------------------


def test_browser_modules_are_the_top_level_ones_without_dunder_main():
    names = {p.name for p in mp.browser_modules()}
    assert "__main__.py" not in names
    # debug.py ships: an app imports it to get the hydration report. The old pyscript.json
    # listed fifteen modules and left it out, which is why this is asserted rather than counted.
    assert "debug.py" in names
    assert {"reactive.py", "view.py", "dom.py", "runtime.py", "version.py"} <= names
    assert not any("/" in n for n in names)


def test_the_vendored_runtime_is_present_and_is_the_pinned_build():
    for name in mp.WANTED + ("boot.js", mp.IMAGE_NAME):
        assert (mp.RUNTIME_DIR / name).exists(), f"{name} missing: run `mk runtime.fetch`"
    # The pin is a single line; if it moves, the image and the tests move with it.
    assert mp.UPSTREAM_TAG.startswith("v1.29.")
    wasm = (mp.RUNTIME_DIR / "micropython.wasm").read_bytes()
    # Frontage's own variant, not the upstream npm build: a third smaller, and with wasm
    # exception handling in place of the JavaScript `invoke_*` longjmp trampolines that
    # upstream imports (FASTER.md §2). A fetched fallback build fails both.
    assert 200_000 < len(wasm) < 300_000, "run `mk runtime.wasm`"
    assert b"invoke_" not in wasm, "the upstream build, not frontage's variant: run `mk runtime.wasm`"


def test_the_framework_image_holds_every_browser_module(tmp_path):
    out, compiled = mp.image(tmp_path, quiet=True)
    with tarfile.open(out) as tf:
        members = tf.getnames()
    assert len(members) == len(mp.browser_modules())
    assert all(m.startswith("frontage/") for m in members)
    stems = {Path(m).stem for m in members}
    assert stems == {p.stem for p in mp.browser_modules()}
    if compiled:
        assert all(m.endswith(".mpy") for m in members)


def test_the_framework_image_is_reproducible(tmp_path):
    # mtime is pinned to 0 so the same sources give the same bytes; CI compares them rather
    # than trusting a timestamp, which a wheel install flattens anyway.
    first, _ = mp.image(tmp_path / "a", quiet=True)
    second, _ = mp.image(tmp_path / "b", quiet=True)
    assert first.read_bytes() == second.read_bytes()


# --- choosing the entry ----------------------------------------------------------------


def test_the_entry_is_the_module_that_mounts(tmp_path):
    app = write_app(tmp_path, helpers="X = 1\n", ui=APP)
    assert build.find_entry(app) == "ui"


def test_a_conventional_name_wins_when_several_modules_mount(tmp_path):
    app = write_app(tmp_path, app=APP, other=APP)
    assert build.find_entry(app) == "app"


def test_a_lone_module_is_the_entry_even_without_mount(tmp_path):
    app = write_app(tmp_path, thing="X = 1\n")
    assert build.find_entry(app) == "thing"


def test_an_ambiguous_directory_says_so_instead_of_guessing(tmp_path):
    app = write_app(tmp_path, one=APP, two=APP)
    with pytest.raises(SystemExit) as exc:
        build.find_entry(app)
    assert "one" in str(exc.value) and "two" in str(exc.value) and "--entry" in str(exc.value)


def test_an_empty_directory_says_so(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    with pytest.raises(SystemExit):
        build.find_entry(app)


# --- the built directory ---------------------------------------------------------------


def test_build_writes_a_page_that_boots_from_wasm(tmp_path):
    app = write_app(tmp_path, counter=APP)
    out = build.build(app, tmp_path / "out", quiet=True)

    for name in ("boot.js", "micropython.mjs", "micropython.wasm", "frontage.tar", "app.tar"):
        assert (out / "_frontage" / name).exists()

    page = (out / "index.html").read_text()
    assert 'data-fr-entry="counter"' in page and "data-fr-boot" in page
    assert "_frontage/boot.js" in page
    # Nothing of PyScript survives: no config, no core.js, no interpreter type attribute.
    assert "pyscript" not in page.lower()
    assert not (out / "pyscript.json").exists()


def test_the_app_image_holds_the_app_modules_as_source(tmp_path):
    app = write_app(tmp_path, counter=APP, helpers="X = 1\n")
    out = build.build(app, tmp_path / "out", quiet=True)
    with tarfile.open(out / "_frontage" / "app.tar") as tf:
        assert sorted(tf.getnames()) == ["counter.py", "helpers.py"]
        member = tf.extractfile("helpers.py")
        assert member is not None
        assert member.read() == b"X = 1\n"
    # The sources stay readable in the output too, which is the point of a teaching framework.
    assert (out / "counter.py").exists()


def test_an_existing_page_keeps_its_markup_and_gains_the_tag(tmp_path):
    app = write_app(tmp_path, counter=APP)
    (app / "index.html").write_text("<!DOCTYPE html>\n<body>\n<main id='app'>x</main>\n</body>\n")
    out = build.build(app, tmp_path / "out", quiet=True)
    page = (out / "index.html").read_text()
    assert "<main id='app'>x</main>" in page
    assert page.count("data-fr-boot") == 1


def test_a_page_that_already_declares_the_tag_is_left_alone(tmp_path):
    app = write_app(tmp_path, counter=APP)
    tag = build.boot_tag("counter")
    (app / "index.html").write_text(f"<!DOCTYPE html>\n<body>\n{tag}\n</body>\n")
    out = build.build(app, tmp_path / "out", quiet=True)
    assert (out / "index.html").read_text().count("data-fr-boot") == 1


def test_build_does_not_copy_a_previous_build(tmp_path):
    app = write_app(tmp_path, counter=APP)
    (app / "_frontage").mkdir()
    (app / "_frontage" / "stale.wasm").write_bytes(b"old")
    out = build.build(app, tmp_path / "out", quiet=True)
    assert not (out / "_frontage" / "stale.wasm").exists()


def test_an_unknown_entry_is_an_error(tmp_path):
    app = write_app(tmp_path, counter=APP)
    with pytest.raises(SystemExit) as exc:
        build.build(app, tmp_path / "out", entry="nope", quiet=True)
    assert "nope.py" in str(exc.value)


# --- components ---------------------------------------------------------------------------


def make_component(tmp_path, name="frontage_chart", style=True):
    """A component package on disk: Python beside a `_browser/` the page will load."""
    from frontage.cli.build import Component

    package = tmp_path / "site-packages" / name
    (package / "_browser").mkdir(parents=True)
    (package / "__init__.py").write_text("from .plot import line_chart\n")
    (package / "plot.py").write_text("def line_chart(data):\n    return data\n")
    (package / "_browser" / "index.js").write_text("export function draw() {}\n")
    if style:
        (package / "_browser" / "index.css").write_text(".chart { display: block }\n")
    # Must not ship either: a private module is the component's CPython half (a server, a
    # compiler), full of imports the page cannot satisfy and dead weight at best.
    (package / "_server.py").write_text("import fastapi\n")
    # Must not ship: browser assets are not Python, and caches are nobody's business.
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "plot.cpython-314.pyc").write_bytes(b"\x00")
    return Component("chart", package)


def test_discover_finds_the_builtin_components_without_importing_anything():
    # Frontage's own components are found by their `_browser/` directory, and never imported:
    # their Python is written for the browser, and running it here would be the wrong
    # interpreter. No third-party entry point is declared in this repo.
    import sys

    before = set(sys.modules)
    found = build.discover()
    assert [c.name for c in found] == ["chart", "layout", "map", "remote", "schema", "supabase", "table"]
    assert all(c.import_name == f"frontage.{c.name}" for c in found)
    names = {c.name for c in found}
    imported = [m for m in set(sys.modules) - before if m.startswith("frontage.") and m.split(".")[1] in names]
    assert imported == []


def test_a_component_ships_its_assets_its_python_and_a_declaration(tmp_path):
    app = write_app(tmp_path, counter=APP)
    component = make_component(tmp_path)
    out = build.build(app, tmp_path / "out", quiet=True, components=[component])

    assets = out / "_frontage" / "components" / "chart"
    assert (assets / "index.js").is_file()
    assert (assets / "index.css").is_file()

    page = (out / "index.html").read_text()
    assert 'data-fr-js="chart=./_frontage/components/chart/index.js"' in page
    assert '<link rel="stylesheet" href="./_frontage/components/chart/index.css">' in page

    # A third-party component's Python travels under its package name, so `import frontage_chart` works in the page.
    with tarfile.open(out / "_frontage" / "app.tar") as tf:
        names = sorted(tf.getnames())
    assert names == ["counter.py", "frontage_chart/__init__.py", "frontage_chart/plot.py"]


def test_a_private_module_stays_on_cpython(tmp_path):
    component = make_component(tmp_path)
    names = [n for n, _ in component.modules()]
    assert names == ["frontage_chart/__init__.py", "frontage_chart/plot.py"]


def test_a_component_without_a_stylesheet_links_nothing(tmp_path):
    app = write_app(tmp_path, counter=APP)
    out = build.build(app, tmp_path / "out", quiet=True, components=[make_component(tmp_path, style=False)])
    assert "stylesheet" not in (out / "index.html").read_text()


def test_declarations_merge_into_a_hand_written_boot_tag(tmp_path):
    """The examples hand-write their tag. Rewriting it would throw away what the author put
    there; ignoring it would make an installed component silently do nothing."""
    app = write_app(tmp_path, counter=APP)
    tag = '<script type="module" src="./_frontage/boot.js" data-fr-boot data-fr-entry="counter"></script>'
    (app / "index.html").write_text(f"<!DOCTYPE html>\n<body>\n{tag}\n</body>\n")
    out = build.build(app, tmp_path / "out", quiet=True, components=[make_component(tmp_path)])
    page = (out / "index.html").read_text()
    assert page.count("data-fr-boot") == 1
    assert 'data-fr-entry="counter"' in page and "chart=./_frontage/components/chart/index.js" in page


def test_an_author_declaration_wins_and_is_not_duplicated():
    tag = '<script data-fr-boot data-fr-entry="app" data-fr-js="chart=./mine.js"></script>'
    merged = build.declare(tag, ["chart=./theirs.js", "grid=./grid.js"])
    assert merged.count("data-fr-js") == 1
    assert "chart=./mine.js" in merged and "chart=./theirs.js" not in merged
    assert "grid=./grid.js" in merged


def test_declare_leaves_a_page_with_no_boot_tag_alone():
    assert build.declare("<p>nothing here</p>", ["chart=./x.js"]) == "<p>nothing here</p>"


def test_only_the_components_the_app_imports_are_shipped(tmp_path, monkeypatch):
    """Installed is not the same question as used.

    Without this, a developer with five components installed ships five: an app with no chart
    downloads uPlot, registers it as a JavaScript module and links its stylesheet. The extra
    ones work perfectly, so nothing fails — the page is just bigger, which is the exact
    opposite of the rule the component design rests on.
    """
    app = write_app(tmp_path, counter="import frontage_chart\n" + APP)
    chart = make_component(tmp_path, name="frontage_chart")
    table = make_component(tmp_path, name="frontage_table")
    table.name = "table"

    monkeypatch.setattr(build, "discover", lambda: [chart, table])
    out = build.build(app, tmp_path / "out", quiet=True)
    assert (out / "_frontage" / "components" / "chart").is_dir()
    assert not (out / "_frontage" / "components" / "table").exists()
    page = (out / "index.html").read_text()
    assert "chart=" in page and "table=" not in page


def test_a_component_pulls_in_the_component_it_imports_itself(tmp_path, monkeypatch):
    """A table built out of layout's container needs layout, whatever the app said."""
    app = write_app(tmp_path, counter="import frontage_table\n" + APP)
    layout = make_component(tmp_path, name="frontage_layout")
    layout.name = "layout"
    table = make_component(tmp_path, name="frontage_table")
    table.name = "table"
    (table.package / "grid.py").write_text("from frontage_layout import container\n")

    monkeypatch.setattr(build, "discover", lambda: [layout, table])
    out = build.build(app, tmp_path / "out", quiet=True)
    assert (out / "_frontage" / "components" / "layout").is_dir()
    assert (out / "_frontage" / "components" / "table").is_dir()


def test_an_explicit_component_bypasses_the_scan(tmp_path):
    """`--component` is for developing one, which usually means before the app imports it."""
    app = write_app(tmp_path, counter=APP)
    component = make_component(tmp_path)
    out = build.build(app, tmp_path / "out", quiet=True, components=[component])
    assert (out / "_frontage" / "components" / "chart").is_dir()
