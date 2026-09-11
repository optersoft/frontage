"""The server's own wheel and the binary it goes looking for (`API.md` §6.5).

`pip install frontage-api` gives a library and no server — the server is Rust, with the VM
the handlers run on compiled into it — so the wheel is one half of a release and the release
asset is the other. These are the assertions that keep the two halves describing each other.
"""

import tomllib
from pathlib import Path

import pytest

from frontage.version import __version__
from frontage_api import _binary

ROOT = Path(__file__).resolve().parent.parent
API_PROJECT = ROOT / "packaging" / "api"


@pytest.fixture(scope="module")
def project():
    with open(API_PROJECT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def test_the_second_wheel_is_the_server_and_carries_the_package(project):
    assert project["project"]["name"] == "frontage-api"
    included = project["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert included == {"../../frontage_api": "frontage_api"}


def test_it_builds_a_wheel_and_no_sdist(project):
    """A tarball has no `..`, so a wheel built from an unpacked sdist would look for the
    package above the tree it was unpacked into. The source travels in `frontage`'s sdist
    instead — which is what the next test checks."""
    assert "sdist" not in project["tool"]["hatch"]["build"]["targets"]


def test_the_frontage_sdist_carries_the_server_source():
    with open(ROOT / "pyproject.toml", "rb") as f:
        root = tomllib.load(f)
    include = root["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "frontage_api" in include
    assert "packaging" in include


def test_the_two_wheels_are_one_release(project):
    """The binary has the runtime compiled into it and that runtime executes `frontage`'s own
    modules, so a mismatched pair is a bug report rather than a supported combination — hence
    `==` and not `>=`. Asserted on the hook's source and its inputs rather than by running
    hatchling, which is a build backend and not a test dependency."""
    assert "dependencies" in project["project"]["dynamic"]
    assert "custom" in project["tool"]["hatch"]["metadata"]["hooks"]
    hook = (API_PROJECT / "hatch_build.py").read_text(encoding="utf-8")
    assert '"frontage==" + namespace["__version__"]' in hook

    # The two paths the hook reads, resolved from where it runs, are the ones that exist.
    version_file = API_PROJECT / "../../frontage/version.py"
    assert version_file.resolve() == (ROOT / "frontage" / "version.py")
    namespace = {}
    exec(version_file.read_text(encoding="utf-8"), namespace)
    assert namespace["__version__"] == __version__


def test_the_console_script_points_at_the_binary_finder(project):
    assert project["project"]["scripts"] == {"frontage-api": "frontage_api._binary:main"}


@pytest.mark.parametrize(
    "system,machine,asset",
    [
        ("Darwin", "arm64", "frontage-api-macos-arm64"),
        ("Darwin", "x86_64", "frontage-api-macos-x64"),
        ("Linux", "x86_64", "frontage-api-linux-x64"),
        ("Linux", "aarch64", "frontage-api-linux-arm64"),
    ],
)
def test_the_asset_name_matches_what_ci_uploads(system, machine, asset):
    assert _binary.asset_name(system, machine) == asset


def test_the_ci_matrix_and_the_asset_names_are_the_same_list():
    """The one that would otherwise be found by a user, months later: CI uploads
    `frontage-api-linux-x64` and the wheel asks for something spelled differently, and the
    only symptom is a 404 on first run."""
    import yaml

    with open(ROOT / ".github" / "workflows" / "ci.yml", encoding="utf-8") as f:
        workflow = yaml.safe_load(f)
    uploaded = {entry["asset"] for entry in workflow["jobs"]["server"]["strategy"]["matrix"]["include"]}
    wanted = {
        _binary.asset_name(system, machine)
        for system, machine in [("Darwin", "arm64"), ("Darwin", "x86_64"), ("Linux", "x86_64"), ("Linux", "aarch64")]
    }
    assert uploaded == wanted


def test_the_wheel_checks_resolve_against_the_local_frontage():
    """⚠ The release's own chicken and egg, and it failed the first v0.14.0 run. The server's
    wheel pins `frontage==` the version being released, which PyPI does not have until the
    publish step below it — so every check that installs the api wheel has to be handed the
    local `frontage` wheel too, or it fails with "no version of frontage==X.Y.Z", which reads
    like a bad pin and is really an ordering problem."""
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    using = [line for line in workflow.splitlines() if "api-dist/*.whl" in line and "--with" in line]
    assert using, "no step installs the api wheel"
    for line in using:
        assert "--with dist/*.whl" in line, line


def test_windows_says_so_rather_than_404ing_later():
    with pytest.raises(SystemExit, match="Windows"):
        _binary.asset_name("Windows", "AMD64")


def test_the_binary_is_named_explicitly_or_found_in_a_checkout(monkeypatch, tmp_path):
    named = tmp_path / "somewhere" / "frontage-api"
    named.parent.mkdir()
    named.write_text("")
    monkeypatch.setenv("FRONTAGE_API_BIN", str(named))
    assert _binary.binary() == named


def test_path_is_not_in_the_search_order():
    """⚠ The wheel installs a console script called `frontage-api`, so a PATH lookup finds
    *this* and execs itself forever. The absence is the feature."""
    assert not hasattr(_binary, "shutil"), "_binary imports shutil, which is how this goes wrong"


def test_a_checkout_build_wins_over_a_download(monkeypatch):
    monkeypatch.delenv("FRONTAGE_API_BIN", raising=False)
    found = _binary._checkout()
    if found is None:
        pytest.skip("no built server in this checkout")
    assert found.name == "frontage-api"
    assert _binary.binary() == found
