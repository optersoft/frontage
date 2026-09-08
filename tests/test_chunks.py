"""SPEC: code splitting. A chunk is a module the page fetches the first time it needs it."""

import sys

import pytest

from frontage import RecordingRenderer, Route, Router, chunks, mount
from frontage.cli.frontage_rt import manifest, split


def write(tmp_path, **files):
    for name, source in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return tmp_path


# what a chunk is ------------------------------------------------------------------------------
def test_a_spec_names_a_module_and_defaults_to_page():
    assert chunks._split("pages.map") == ("pages.map", "page")
    assert chunks._split("pages.map:view") == ("pages.map", "view")


def test_split_leaves_a_chunks_modules_out_of_the_first_payload(tmp_path):
    app = write(
        tmp_path,
        **{
            "app.py": "from frontage import Route, Router\nimport shared\nRouter(Route('/m', lazy='pages.map'))\n",
            "shared.py": "",
            "pages/__init__.py": "",
            "pages/map.py": "import shared\nfrom . import geo\n",
            "pages/geo.py": "",
        },
    )
    modules, chunk = split(app, "app")
    names = [name for name, _ in modules]
    assert chunk == {"pages.map": ["pages", "pages.geo", "pages.map"]}
    # Every module is written; `shared`, which the entry already reaches, stays out of the chunk.
    assert {"app", "shared", "pages", "pages.map", "pages.geo"} <= set(names)

    out = manifest(names, "app", chunks=chunk)
    import json

    data = json.loads(out)
    assert "pages.map" not in data["modules"] and "shared" in data["modules"]
    assert data["chunks"] == chunk


def test_two_chunks_that_share_a_module_share_its_file(tmp_path):
    """A shared module is written once and named by both chunks; whichever route is visited
    first fetches it, and the second skips it because the interpreter already has it."""
    app = write(
        tmp_path,
        **{
            "app.py": "from frontage import Route, Router\nRouter(Route('/a', lazy='a'), Route('/b', lazy='b'))\n",
            "a.py": "import common\n",
            "b.py": "import common\n",
            "common.py": "",
        },
    )
    modules, chunk = split(app, "app")
    assert chunk == {"a": ["a", "common"], "b": ["b", "common"]}
    assert [name for name, _ in modules].count("common") == 1


def test_the_files_of_a_chunk_are_its_hashed_names_minus_what_the_page_has(monkeypatch):
    page = {
        "chunks": {"pages.map": ["pages", "pages.map"]},
        "files": {"pages": "pages.aaaa1111.fbc", "pages.map": "pages.map.bbbb2222.fbc"},
    }
    monkeypatch.setattr(chunks, "_manifest", lambda: page)
    monkeypatch.setitem(sys.modules, "pages", object())
    assert chunks._files("pages.map") == [("pages.map", "pages.map.bbbb2222.fbc")]
    # A module the manifest names without a file falls back to that file's own name.
    monkeypatch.setattr(chunks, "_manifest", lambda: {"chunks": {"x": ["x"]}})
    assert chunks._files("x") == [("x", "x.fbc")]
    # A module that is not a chunk at all is in the page already: nothing to fetch.
    assert chunks._files("y") == []


def test_no_manifest_means_nothing_to_fetch(monkeypatch):
    """`frontage serve` ships every module in one archive, so a lazy route there is an import."""
    monkeypatch.setattr(chunks, "_manifest", lambda: None)
    assert chunks._files("pages.map") == []


# off the browser ------------------------------------------------------------------------------
def test_outside_the_browser_a_lazy_route_renders_like_any_other(tmp_path, monkeypatch):
    write(tmp_path, **{"late.py": "from frontage import h\n\n\ndef page():\n    return h.p('late', id='p')\n"})
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "late", raising=False)
    chunks._ready.clear()

    router = Router(Route("/", lazy="late:page"), mode="memory")
    renderer = RecordingRenderer()
    root = renderer.inner.create_element("div")
    mount(router, root, renderer)
    assert "late" in "".join(child.to_html() for child in root.children)


def test_prefetch_and_load_do_no_fetching_off_the_browser(tmp_path, monkeypatch):
    write(tmp_path, **{"soon.py": "VALUE = 1\n\n\ndef page():\n    return None\n"})
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "soon", raising=False)
    chunks._ready.clear()
    assert chunks.loaded("soon:page") is False
    chunks.prefetch("soon:page")  # a no-op, not an error
    import asyncio

    assert asyncio.run(chunks.load("soon:page")) is sys.modules["soon"].page
    assert chunks.loaded("soon:page") is True


def test_a_spec_whose_attribute_is_missing_says_which(tmp_path, monkeypatch):
    write(tmp_path, **{"thin.py": "\n"})
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "thin", raising=False)
    chunks._ready.clear()
    import asyncio

    with pytest.raises(ImportError, match="no attribute 'page'"):
        asyncio.run(chunks.load("thin"))


def test_a_route_needs_a_component_or_a_lazy_spec():
    with pytest.raises(TypeError, match="component or lazy"):
        Route("/x")


def test_the_dev_server_resolves_a_package_back_to_its_init(tmp_path):
    """`frontage serve` compiles a module per request from its dotted name; a chunk names the
    package its module lives in, and a package is a directory."""
    from frontage.cli.frontage_rt import module_file

    app = write(tmp_path, **{"pages/__init__.py": "", "pages/map.py": "", "solo.py": ""})
    assert module_file("pages", app) == app / "pages" / "__init__.py"
    assert module_file("pages.map", app) == app / "pages" / "map.py"
    assert module_file("solo", app) == app / "solo.py"
