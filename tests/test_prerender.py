"""`python -m frontage prerender` and the fences hydration reads. No browser."""

import json
from pathlib import Path

import pytest

from frontage import For, Show, Signal, component, h, render_to_string
from frontage.cli import check
from frontage.cli.prerender import find_entry, import_app, inject, prerender, relocate

ROOT = Path(__file__).resolve().parents[1]


def test_markers_fence_every_hole_and_keep_bindings():
    items = Signal(["a", "b"])
    flag = Signal(True)

    @component
    def app():
        return h.div(
            h.p("n = ", lambda: len(items()), id="n"),
            h.ul(For(items, lambda item, i: h.li(item))),
            Show(flag, h.b("on"), h.i("off")),
            h.button("go", on_click=lambda ev: None),
        )

    plain = render_to_string(app)
    assert "<!--" not in plain and "data-fr-h" not in plain
    fenced = render_to_string(app, hydration_markers=True)
    # Every hole is fenced; static template text keeps its marker too (hydration finds the
    # text by it), so there are more `h` than `[`.
    assert fenced.count("<!--[-->") == 4 and fenced.count("<!--h-->") == 9
    assert '<p id="n">n = <!--h--><!--[-->2<!--h--></p>' in fenced
    assert "<!--[--><li>a<!--h--></li><li>b<!--h--></li><!--h-->" in fenced
    assert "<!--[--><b>on<!--h--></b><!--h-->" in fenced
    assert 'data-fr-h="' in fenced  # the button's event binding is findable again


def test_prerender_counter(tmp_path):
    out = tmp_path / "counter"
    results = prerender(ROOT / "examples" / "counter", out, bundle_pyscript=False)
    assert [r.path for r in results] == ["/"]
    page = (out / "index.html").read_text()
    assert '<div id="app" data-fr-hydrate>' in page
    assert "Loading…" not in page
    assert "Value: <!--h--><!--[-->0<!--h-->, doubled: <!--h--><!--[-->0<!--h-->" in page
    assert "__frontage_replay" in page and page.index("__frontage_replay") < page.index("<body>")
    assert "data-fr-data" not in page  # no resources, no data block
    # The wasm shape: the app's source beside the page, the framework as one precompiled
    # archive, and no loose `frontage/*.py` for the browser to fetch and compile.
    assert (out / "counter.py").exists()
    assert (out / "_frontage" / "frontage.tar").exists()
    assert (out / "_frontage" / "micropython.wasm").exists()
    assert not (out / "frontage").exists()
    assert 'data-fr-entry="counter"' in page


def test_prerender_waits_for_resources_and_writes_their_values(tmp_path):
    out = tmp_path / "fetch"
    results = prerender(ROOT / "examples" / "fetch", out, bundle_pyscript=False)
    selector, inner, values = results[0].mounts[0]
    assert selector == "#app"
    assert values["resources"] == [{"id": 1, "name": "Ada Lovelace"}]
    assert [v for _, v in values["memos"]] == [3]  # the async memo, by its ordinal among the mount's memos
    assert "Ada Lovelace" in inner and "<!--[-->posts: 3<!--h-->" in inner and "loading" not in inner.lower()
    page = (out / "index.html").read_text()
    block = '<script type="application/json" data-fr-data="app">'
    assert block in page
    assert json.loads(page.split(block)[1].split("</script>")[0]) == values


def test_prerender_routes(tmp_path):
    app = tmp_path / "site"
    app.mkdir()
    (app / "index.html").write_text(
        '<!DOCTYPE html>\n<html><head><link rel="stylesheet" href="./style.css"></head>\n'
        '<body><main id="app">Loading…</main>\n<script type="mpy" src="./app.py" config="./pyscript.json"></script></body></html>\n'
    )
    (app / "app.py").write_text(
        "from frontage import A, Route, Router, h, mount\n"
        "router = Router(Route('/', lambda: h.h1('home', id='home')), Route('/about', lambda: h.h1('about', id='about')),\n"
        "                root=lambda children: h.div(A('/about', 'about', id='link'), children), mode='history')\n"
        "mount(router, '#app')\n"
    )
    results = prerender(app, tmp_path / "out", routes=("/", "/about"), bundle_pyscript=False)
    assert [r.path for r in results] == ["/", "/about"]
    home = (tmp_path / "out" / "index.html").read_text()
    about = (tmp_path / "out" / "about" / "index.html").read_text()
    assert '<h1 id="home">home' in home and 'href="/about"' in home
    assert '<h1 id="about">about' in about and 'id="home"' not in about
    # A page one directory down reaches the app's files through `../`.
    assert 'src="../app.py"' in about and 'href="../style.css"' in about and 'config="../pyscript.json"' in about
    assert 'src="./app.py"' in home


def test_prerender_reports_a_failed_resource(tmp_path):
    app = tmp_path / "bad"
    app.mkdir()
    (app / "index.html").write_text('<div id="app"></div><script type="mpy" src="./app.py"></script>')
    (app / "app.py").write_text(
        "from frontage import Loading, Resource, h, mount\n"
        "async def boom():\n    raise RuntimeError('no data')\n"
        "def app():\n    data = Resource(boom)\n    return Loading(h.i('…'), lambda: h.b(data))\n"
        "mount(app, '#app')\n"
    )
    with pytest.raises(RuntimeError, match="no data"):
        prerender(app, tmp_path / "out", bundle_pyscript=False)


def test_import_app_registers_mounts_and_restores_the_flag(tmp_path):
    from frontage.runtime import prerender as flag

    entry = tmp_path / "app.py"
    entry.write_text(
        "from frontage import h, mount\nmount(lambda: h.b('x'), '#one')\nmount(lambda: h.i('y'), '#two')\n"
    )
    mounts = import_app(entry, "/x")
    assert [m[0] for m in mounts] == ["#one", "#two"] and flag.active is False


def test_mount_without_a_browser_or_prerender_is_an_error():
    with pytest.raises(RuntimeError, match="prerender"):
        from frontage import mount

        mount(lambda: h.b("x"), "#app")


def test_inject_and_helpers():
    page = '<html><body>\n<div id="app" class="c">old <b>x</b></div>\n<div id="app2"></div></body></html>'
    out = inject(page, "#app", "<p>new</p>", [{"a": 1}])
    assert '<div id="app" class="c" data-fr-hydrate><p>new</p></div>' in out
    assert '<script type="application/json" data-fr-data="app">[{"a":1}]</script>\n<div id="app2">' in out
    assert inject(page, "#app2", "<i>z</i>", []).count("data-fr-data") == 0
    with pytest.raises(ValueError):
        inject(page, ".app", "<p></p>", [])
    with pytest.raises(ValueError):
        inject(page, "#missing", "<p></p>", [])
    assert find_entry('s.src = "./counter.py";') == "counter.py"
    assert find_entry('<script type="py" src="./a/b.py">') == "a/b.py"
    assert (
        relocate('src="./a.py" href="http://x/y" data="./z"', 2) == 'src="../../a.py" href="http://x/y" data="../../z"'
    )


def test_a_wasm_page_names_its_entry_instead_of_being_guessed_at():
    tag = '<script type="module" src="./_frontage/boot.js" data-fr-boot data-fr-entry="counter"></script>'
    assert find_entry(tag) == "counter.py"
    # The attribute wins over anything that merely looks like an entry elsewhere in the page.
    assert find_entry(f'<script src="./decoy.py"></script>\n{tag}') == "counter.py"
    assert find_entry("<p>no boot tag here</p>") is None


def test_only_the_boot_tag_needs_relocating_at_depth():
    # Everything else the loader fetches resolves from `import.meta.url`, so a nested route
    # rewrites exactly one path. This is why the loader must never take a document-relative one.
    page = '<script type="module" src="./_frontage/boot.js" data-fr-boot data-fr-entry="app"></script>'
    assert relocate(page, 2) == page.replace('src="./', 'src="../../')
    assert 'data-fr-entry="app"' in relocate(page, 2)  # a module name, not a path


def test_prerender_can_still_write_a_pyscript_page(tmp_path):
    """0.9.x only: the academy's nine chapter repos boot that way until they move.

    The input is a PyScript-shaped app, not an example: `examples/` boots from WebAssembly
    now, so feeding one to `--boot pyscript` would assert nothing about a PyScript page.
    """
    app = tmp_path / "app"
    app.mkdir()
    (app / "index.html").write_text(
        "<!DOCTYPE html>\n<html><head>\n"
        '<script type="module" src="https://pyscript.net/releases/2026.7.3/core.js"></script>\n'
        '</head><body><div id="app">Loading…</div>\n'
        '<script type="mpy" src="./app.py" config="./pyscript.json"></script></body></html>\n'
    )
    (app / "app.py").write_text("from frontage import h, mount\n\nmount(lambda: h.p('hi'), '#app')\n")
    out = tmp_path / "out"
    prerender(app, out, bundle_pyscript=False, boot="pyscript")
    page = (out / "index.html").read_text()
    assert (out / "frontage" / "view.py").exists() and (out / "pyscript.json").exists()
    assert not (out / "_frontage").exists()
    assert '<script type="mpy" src="./app.py"' in page  # the PyScript boot survived
    assert '<div id="app" data-fr-hydrate>' in page  # hydration is the same either way
    assert "<p>hi<!--h--></p>" in page  # rendered, with the fence hydration reads


def test_check_flags_html_the_browser_rewrites():
    found = check.check_source('from frontage import html\nx = html(t"<p><div>{name}</div></p>")\n')
    assert len(found) == 1 and "<div> inside <p>" in found[0][2]
    found = check.check_source('x = html(t"<table><tr><td>{v}</td></tr></table>")\n')
    assert any("<tbody>" in f[2] for f in found)
    assert check.check_source('x = html(t"<table><tbody><tr><td>{v}</td></tr></tbody></table>")\n') == []
    assert check.check_source('x = html(t"<p><span>{v}</span></p>")\n') == []


def test_prerender_tracker_routes_and_the_memo_loaded_detail(tmp_path):
    out = tmp_path / "tracker"
    results = prerender(ROOT / "examples" / "tracker", out, routes=("/", "/issues", "/issues/1"), bundle_pyscript=False)
    assert [r.path for r in results] == ["/", "/issues", "/issues/1"]
    dashboard = (out / "index.html").read_text()
    assert 'id="open"' in dashboard and "loading" not in dashboard.lower()
    issues = (out / "issues" / "index.html").read_text()
    assert issues.count("<li") - issues.count("<link") == 5 and 'id="pick"' in issues
    detail = (out / "issues" / "1" / "index.html").read_text()
    assert "Signals lose a subscriber after dispose" in detail and 'id="error"' not in detail
    _, _, values = results[2].mounts[0]
    assert isinstance(values, dict) and values["memos"]  # the detail's async memo, by ordinal
