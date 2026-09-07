"""What `frontage build` requires of a component, asserted on both packages.

These are the rules of `COMPONENTS.md` §5. A component that breaks one of them installs
cleanly, imports cleanly, and does nothing at all in a page.
"""

from importlib import metadata
from pathlib import Path

import pytest

PACKAGES = [
    ("layout", "frontage_layout"),
    ("chart", "frontage_chart"),
    ("table", "frontage_table"),
    ("map", "frontage_map"),
    ("supabase", "frontage_supabase"),
]


@pytest.mark.parametrize(("name", "package"), PACKAGES)
def test_each_package_declares_its_entry_point(name, package):
    entries = {e.name: e.value for e in metadata.entry_points(group="frontage.components")}
    assert entries.get(name) == package, f"{package} is not discoverable as {name!r}"


@pytest.mark.parametrize(("name", "package"), PACKAGES)
def test_each_package_ships_a_browser_entry_module(name, package):
    """Located, not imported — the same rule `build.discover()` follows, and for the same
    reason: a component's Python is written for the browser, so importing it here runs it on the
    wrong interpreter. `frontage_chart` opens with `import chart`, which exists only in a page,
    so this test used to pass only when a file that stubs `chart` had run first."""
    from importlib import util

    spec = util.find_spec(package)
    assert spec is not None and spec.origin, f"{package} is not installed"
    browser = Path(spec.origin).parent / "_browser"
    assert (browser / "index.js").is_file(), "build declares _browser/index.js in data-fr-js"


@pytest.mark.parametrize(("name", "package"), PACKAGES)
def test_the_build_discovers_it(name, package):
    """The real path, not `--component`: installed, found by entry point, assets located."""
    from frontage.cli.build import discover

    found = {c.name: c for c in discover()}
    assert name in found
    assert (found[name].browser / "index.js").is_file()
    assert [n for n, _ in found[name].modules()], "no Python would reach the page"


@pytest.mark.parametrize(("name", "package"), PACKAGES)
def test_no_browser_asset_is_packed_as_python(name, package):
    from frontage.cli.build import discover

    component = {c.name: c for c in discover()}[name]
    assert all("_browser" not in n for n, _ in component.modules())
