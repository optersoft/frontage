"""`python -m frontage build` and the runtime image behind it (no network, no browser)."""

import json
import re
from pathlib import Path

import pytest

from frontage.cli import build, frontage_rt

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
    names = {p.name for p in frontage_rt.browser_modules()}
    assert "__main__.py" not in names
    # debug.py ships: an app imports it to get the hydration report. The old pyscript.json
    # listed fifteen modules and left it out, which is why this is asserted rather than counted.
    assert "debug.py" in names
    assert {"reactive.py", "view.py", "dom.py", "runtime.py", "version.py"} <= names
    assert not any("/" in n for n in names)


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

    for name in ("boot.js", "glue.js", "manifest.json"):
        assert (out / "_frontage" / name).exists()
    # The manifest lists every module but the entry, and only what the entry reaches (the
    # router is not imported here); each module and the wasm sit at a content-hashed name,
    # which `_headers` lets a host cache forever, and the page preloads them.
    manifest = json.loads((out / "_frontage" / "manifest.json").read_text())
    assert "counter" not in manifest["modules"] and "frontage.reactive" in manifest["modules"]
    assert "frontage.router" not in manifest["modules"]
    files = manifest["files"]
    assert re.fullmatch(r"counter\.[0-9a-f]{8}\.fbc", files["counter"]) and manifest["entry"] == files["counter"]
    assert (out / "_frontage" / files["frontage.reactive"]).exists()
    assert re.fullmatch(r"frontage\.[0-9a-f]{8}\.wasm", manifest["wasm"])
    assert (out / "_frontage" / manifest["wasm"]).read_bytes()[:4] == b"\0asm"
    assert "immutable" in (out / "_headers").read_text()
    page = (out / "index.html").read_text()
    assert f'<link rel="preload" href="./_frontage/{manifest["wasm"]}" as="fetch" crossorigin>' in page
    assert '<link rel="modulepreload" href="./_frontage/boot.js">' in page

    page = (out / "index.html").read_text()
    assert 'data-fr-entry="counter"' in page and "data-fr-boot" in page
    assert "_frontage/boot.js" in page
    # Nothing of PyScript survives: no config, no core.js, no interpreter type attribute.
    assert "pyscript" not in page.lower()
    assert not (out / "pyscript.json").exists()


def test_a_template_string_does_not_stop_the_import_walk(tmp_path):
    """The walk reads the app with `ast`, and a build host may be older than 3.14, where a
    t-string is a syntax error. An import cannot live inside one, so they are blanked."""
    from frontage.cli.graph import Graph, _without_templates

    source = 'import helpers\nfrom frontage import html, mount\n\n\ndef view():\n    return html(t"""\n        <p>{helpers.NAME}</p>\n    """)\n'
    blanked = _without_templates(source)
    assert blanked is not None
    assert blanked.count("\n") == source.count("\n"), "line numbers must survive"
    assert "import helpers" in blanked and "<p>" not in blanked
    compile(blanked, "app.py", "exec")  # parses on any interpreter this package supports

    app = write_app(tmp_path, app=source, helpers='NAME = "Ada"\n')
    graph = Graph(app)
    assert "helpers" in graph.deps("app") and "frontage" in graph.deps("app")
    assert _without_templates("import helpers\n") is None


def test_a_module_the_entry_does_not_import_is_not_shipped(tmp_path):
    app = write_app(tmp_path, counter=APP, helpers="X = 1\n")
    out = build.build(app, tmp_path / "out", quiet=True)
    files = json.loads((out / "_frontage" / "manifest.json").read_text())["files"]
    assert "counter" in files and "helpers" not in files


def test_a_rebuild_keeps_the_names_of_what_did_not_change(tmp_path):
    """Content hashes: a change to one module moves that file's URL and no other's."""
    app = write_app(tmp_path, counter=APP, helpers="X = 1\n")
    (tmp_path / "app" / "counter.py").write_text(APP + "import helpers\n")
    first = json.loads((build.build(app, tmp_path / "out", quiet=True) / "_frontage" / "manifest.json").read_text())
    (tmp_path / "app" / "helpers.py").write_text("X = 2\n")
    second = json.loads((build.build(app, tmp_path / "out", quiet=True) / "_frontage" / "manifest.json").read_text())
    assert first["files"]["helpers"] != second["files"]["helpers"]
    assert first["files"]["counter"] == second["files"]["counter"]
    assert first["files"]["frontage.reactive"] == second["files"]["frontage.reactive"]
    assert first["wasm"] == second["wasm"]


def test_the_vendored_runtime_is_present():
    for name in frontage_rt.ASSETS:
        assert (frontage_rt.RUNTIME_DIR / name).is_file(), f"{name} missing: run `mk runtime.rs`"
    wasm = (frontage_rt.RUNTIME_DIR / "frontage.wasm").read_bytes()
    assert wasm[:4] == b"\0asm" and 400_000 < len(wasm) < 1_000_000
    # The built app never compiles in the page; only the playground and the runner do.
    compiler = (frontage_rt.RUNTIME_DIR / "frontage-compiler.wasm").read_bytes()
    assert compiler[:4] == b"\0asm" and len(compiler) > len(wasm)


def test_the_runtime_stays_within_its_size_budget():
    """What every page downloads, compressed the way a host serves it. The number is the
    budget, not a measurement: a change that crosses it needs a reason in the commit
    (2026-09-08: 261 KB gzip, 209 KB brotli, with the native core)."""
    import gzip

    wasm = (frontage_rt.RUNTIME_DIR / "frontage.wasm").read_bytes()
    assert len(gzip.compress(wasm, 9)) < 300_000


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
    assert [c.name for c in found] == ["chart", "chat", "layout", "map", "remote", "schema", "supabase", "table"]
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

    # A third-party component's Python travels under its package name, as bytecode, so
    # `import frontage_chart` works in the page — when the app imports it.
    assert not (out / "_frontage" / "frontage_chart.fbc").exists()
    assert not (out / "_frontage" / "app.tar").exists()


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


# --- Tailwind ---------------------------------------------------------------------------


def fake_tailwind(tmp_path, monkeypatch):
    """A stand-in for Tailwind's CLI: writes `--output`, records how it was called."""
    import sys

    from frontage.cli import tailwind as tailwind_cli

    script = tmp_path / "fake-tailwind.py"
    script.write_text(
        "import sys\n"
        "args = sys.argv[1:]\n"
        "out = args[args.index('--output') + 1]\n"
        "source = open(args[args.index('--input') + 1]).read()\n"
        "open(out, 'w').write('/*' + source.strip() + '*/.p{color:red}')\n"
        "open(out + '.argv', 'w').write(repr(args))\n"
    )
    binary = tmp_path / "fake-tailwind"
    binary.write_text(f'#!/bin/sh\nexec {sys.executable} {script} "$@"\n')
    binary.chmod(0o755)
    monkeypatch.setattr(tailwind_cli, "binary", lambda *a, **k: binary)
    return binary


def test_build_tailwind_generates_the_stylesheet_and_links_it(tmp_path, monkeypatch):
    app = write_app(tmp_path, app=APP)
    (app / "index.html").write_text("<html><head><title>t</title></head><body><div id='app'></div></body></html>")
    fake_tailwind(tmp_path, monkeypatch)

    out = build.build(app, tmp_path / "out", quiet=True, tailwind=True)
    css = out / build.TAILWIND_OUTPUT
    assert css.exists() and ".p{color:red}" in css.read_text()
    assert '<link rel="stylesheet" href="./tailwind.out.css">' in (out / "index.html").read_text()
    # The input is written into the app (it is the app's configuration) and is not shipped:
    # a page that downloaded `@import "tailwindcss";` would have downloaded nothing useful.
    assert (app / build.TAILWIND_INPUT).read_text().startswith("@import")
    assert not (out / build.TAILWIND_INPUT).exists()


def test_the_app_directory_is_what_tailwind_scans(tmp_path, monkeypatch):
    """A class name in a template string is a class name in a `.py` file, which is all
    Tailwind's scanner asks for — so the app directory is the whole configuration."""
    app = write_app(tmp_path, app=APP)
    fake_tailwind(tmp_path, monkeypatch)
    out = build.build(app, tmp_path / "out", quiet=True, tailwind=True)
    argv = (out / (build.TAILWIND_OUTPUT + ".argv")).read_text()
    assert str(app / build.TAILWIND_INPUT) in argv and "--minify" in argv


def test_without_the_flag_nothing_tailwind_happens(tmp_path, monkeypatch):
    app = write_app(tmp_path, app=APP)
    fake_tailwind(tmp_path, monkeypatch)
    out = build.build(app, tmp_path / "out", quiet=True)
    assert not (out / build.TAILWIND_OUTPUT).exists()
    assert not (app / build.TAILWIND_INPUT).exists()
    assert "tailwind" not in (out / "index.html").read_text()
