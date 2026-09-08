"""What `frontage build` requires of a component, asserted on every subpackage that is one.

These are the rules of `COMPONENTS.md` §5. A component that breaks one of them installs
cleanly, imports cleanly, and does nothing at all in a page.
"""

from pathlib import Path

import pytest

from frontage.cli.build import BROWSER_DIR, COMPONENT_ENTRY, builtin, discover

ROOT = Path(__file__).resolve().parents[2]
NAMES = ["chart", "chat", "dsp", "layout", "map", "remote", "schema", "supabase", "table"]


def test_every_builtin_component_is_found_and_only_those():
    assert [c.name for c in builtin()] == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_each_component_ships_a_browser_entry_module(name):
    """Located, not imported — the same rule `build.discover()` follows, and for the same
    reason: a component's Python is written for the browser, so importing it here runs it on
    the wrong interpreter."""
    assert (ROOT / "frontage" / name / BROWSER_DIR / COMPONENT_ENTRY).is_file()


@pytest.mark.parametrize("name", NAMES)
def test_the_build_discovers_it_under_its_package_path(name):
    component = {c.name: c for c in discover()}[name]
    assert component.import_name == f"frontage.{name}"
    archive_paths = [n for n, _ in component.modules()]
    assert archive_paths, "no Python to pack"
    assert all(n.startswith(f"frontage/{name}/") for n in archive_paths)
    assert f"frontage/{name}/__init__.py" in archive_paths


@pytest.mark.parametrize("name", NAMES)
def test_no_browser_asset_or_cpython_half_is_packed_as_python(name):
    component = {c.name: c for c in discover()}[name]
    packed = [n for n, _ in component.modules()]
    assert all(BROWSER_DIR not in n for n in packed)
    assert all(not Path(n).name.startswith("_") or Path(n).name == "__init__.py" for n in packed)
