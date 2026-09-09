"""Islands: the wrapper a build writes, the page it does not write a boot tag for, and the
chunk an island named by a string becomes.

The browser half — a trigger that fires, a runtime booted once, a chunk fetched on scroll —
is `tests/browser/test_island.py`; nothing here needs a browser.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from frontage import component, h, island, render_to_string
from frontage.cli import frontage_rt
from frontage.cli import prerender as prerender_cli
from frontage.island import TAG, spec_of
from frontage.runtime import prerender as prerender_state

ROOT = Path(__file__).resolve().parents[1]


def widget(label="hi"):
    return h.b(label)


@component
def decorated(label="hi"):
    return h.b(label)


# --- the API ------------------------------------------------------------------------------


def test_an_island_outside_a_static_page_is_just_the_component():
    assert render_to_string(lambda: island(widget, when="visible", label="there")) == "<b>there</b>"


def test_a_decorated_component_still_says_where_it_lives():
    # `component` wraps the function, and without carrying `__module__` over every island
    # claimed to come from `frontage.view`, which the page could not import.
    assert spec_of(decorated) == f"{__name__}:decorated"
    assert spec_of(widget) == f"{__name__}:widget"
    assert spec_of("charts:sparkline") == "charts:sparkline"
    assert spec_of("charts") == "charts:page"


def test_an_unknown_trigger_says_what_it_expected():
    with pytest.raises(ValueError, match="expected one of"):
        island(widget, when="sometimes")
    with pytest.raises(ValueError):
        island(widget, when="media:")


def test_props_that_are_not_json_fail_the_build_naming_the_island():
    prerender_state.static = True
    prerender_state.islands = []
    try:
        with pytest.raises(TypeError, match="props must be JSON"):
            island(widget, when="visible", label=object())
    finally:
        prerender_state.static = False


def test_a_registered_island_leaves_a_wrapper_the_prerenderer_can_find():
    prerender_state.static = True
    prerender_state.islands = []
    try:
        html = render_to_string(lambda: island(widget, when="visible", label="there"))
    finally:
        prerender_state.static = False
    assert f'<{TAG} id="fr-island-0"' in html
    assert 'data-fr-when="visible"' in html
    assert f'data-fr-index="0"></{TAG}>' in html, "the tail the splice needs is not there"
    assert "<b>" not in html, "the island rendered inline instead of registering"
    assert len(prerender_state.islands) == 1
    assert prerender_state.islands[0].props == {"label": "there"}


def test_a_never_island_is_plain_html_even_on_a_static_page():
    prerender_state.static = True
    prerender_state.islands = []
    try:
        html = render_to_string(lambda: island(widget, when="never", label="there"))
    finally:
        prerender_state.static = False
    assert html == "<b>there</b>"
    assert prerender_state.islands == []


# --- the page -----------------------------------------------------------------------------

PAGE = """<!DOCTYPE html>
<html><head><link rel="modulepreload" href="./_frontage/boot.js">
  <link rel="preload" href="./_frontage/frontage.abcd1234.wasm" as="fetch" crossorigin>
</head><body><div id="app"></div>
<script type="module" src="./_frontage/boot.js" data-fr-boot data-fr-entry="app" data-fr-js="chart=./x.js"></script>
</body></html>
"""


def test_a_static_page_with_no_island_keeps_no_script_at_all():
    out = prerender_cli.strip_boot(PAGE)
    assert "data-fr-boot" not in out
    assert "modulepreload" not in out and ".wasm" not in out


def test_a_static_page_with_islands_swaps_the_boot_tag_for_the_loader():
    out = prerender_cli.island_script(PAGE)
    assert "data-fr-boot" not in out and "boot.js" not in out
    assert '<script type="module" src="./_frontage/island.js" data-fr-islands' in out
    # A component's JavaScript is still the island's to use, so the declaration moves over.
    assert 'data-fr-js="chart=./x.js"' in out


def test_inject_writes_no_hydration_marker_for_a_static_page():
    out = prerender_cli.inject(PAGE, "#app", "<p>hi</p>", ["a value"], hydrate=False)
    assert "data-fr-hydrate" not in out and "data-fr-data" not in out
    assert "<p>hi</p>" in out


# --- the build ----------------------------------------------------------------------------


def test_an_island_named_by_a_string_is_a_chunk_and_the_entry_stays_importable(tmp_path):
    (tmp_path / "app.py").write_text(
        "from frontage import h, island, mount\n\n"
        "def toggle():\n    return h.b('t')\n\n"
        "def page():\n    return h.div(island(toggle), island('big:chart', when='visible'))\n\n"
        "mount(page, '#app', when='never')\n"
    )
    (tmp_path / "big.py").write_text(
        "from bulk import ROWS\nfrom frontage import h\n\ndef chart():\n    return h.b(len(ROWS))\n"
    )
    (tmp_path / "bulk.py").write_text("ROWS = [1, 2, 3]\n")
    modules, chunks, islands = frontage_rt.analyse(tmp_path, "app")
    assert islands is True
    assert chunks == {"big": ["big", "bulk"]}
    manifest = json.loads(frontage_rt.manifest([n for n, _ in modules], "app", chunks=chunks, islands=True))
    assert manifest["islands"] is True
    # The entry stays in the list: nothing runs it, but the island defined in it has to be
    # importable, and the boot's own entry on such a page is `frontage.island`.
    assert "app" in manifest["modules"]
    assert "big" not in manifest["modules"] and "bulk" not in manifest["modules"]


def test_an_app_without_islands_still_leaves_its_entry_out(tmp_path):
    (tmp_path / "app.py").write_text("from frontage import h, mount\n\nmount(lambda: h.b('x'), '#app')\n")
    modules, chunks, islands = frontage_rt.analyse(tmp_path, "app")
    assert islands is False
    manifest = json.loads(frontage_rt.manifest([n for n, _ in modules], "app", chunks=chunks, islands=islands))
    assert "app" not in manifest["modules"] and "islands" not in manifest


# --- end to end ---------------------------------------------------------------------------


@pytest.mark.skipif(not frontage_rt.available(), reason="the runtime is not vendored")
def test_the_example_prerenders_to_a_page_with_no_boot_tag(tmp_path):
    out = tmp_path / "islands"
    run = subprocess.run(
        [sys.executable, "-m", "frontage", "prerender", str(ROOT / "examples" / "islands"), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert run.returncode == 0, run.stderr
    page = (out / "index.html").read_text()
    assert "data-fr-boot" not in page
    assert "island.js" in page
    assert 'data-fr-island="widgets:theme_toggle"' in page
    assert 'data-fr-island="charts:sparkline"' in page
    # The islands' HTML is in the page: a reader sees the toggle and the chart before, and
    # whether or not, any of it ever becomes interactive.
    assert "Dark mode" in page and 'class="spark"' in page
    manifest = json.loads((out / "_frontage" / "manifest.json").read_text())
    assert manifest["islands"] is True
    assert manifest["chunks"] == {"charts": ["charts", "samples"]}
