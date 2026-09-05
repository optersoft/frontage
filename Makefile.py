"""Tasks for the `frontage` repo -- a Python frontend framework for PyScript.

    mk sync                 .venv with every dependency group
    mk test                 unit tests (no browser)
    mk test --browser       the examples in Chromium under MicroPython and Pyodide
    mk pyscript.fetch       PyScript's offline bundle (core + both interpreters) into tools/pyscript/
    mk lint [--fix]         ruff check + ruff format, as CI runs them
    mk types                ty
    mk check                the gate: lint, types, unit tests
    mk serve [--port N]     the examples at http://127.0.0.1:8000/examples/, package read live
    mk dist.build           sdist + wheel into ./dist, then import the wheel once
    mk site.build           frontage.optersoft.com into ./www: web/ + the live examples
    mk site.deploy          build, then publish ./www to Cloudflare Pages (project `frontage`)

PyPI gets the package from CI on a `vX.Y.Z` tag (.github/workflows/ci.yml);
nothing here publishes a package. The site is the exception: `mk site.deploy`
pushes ./www to the Cloudflare Pages project `frontage` from this machine with
wrangler, because the project is not git-connected (2026-09-05). Documentation
lives on academy.optersoft.com, not here. `mk` with no arguments lists everything.
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["mkrun>=0.3"]
# ///

from __future__ import annotations

import shutil
from pathlib import Path

from make import note, sh, task

ROOT = Path(__file__).parent
WWW = ROOT / "www"


@task(requires=["uv"])
def sync() -> None:
    """Create .venv and install every dependency group (CI adds --frozen)."""
    sh("uv", "sync", "--all-groups")


@task(requires=["uv"])
def test(*paths: str, browser: bool = False, verbose: bool = False) -> None:
    """Run the tests. Unit tests by default; the browser suite with --browser.

    The browser suite needs `mk pyscript.fetch` once, and a Chromium once:
    `uv run playwright install chromium`.

    Args:
        browser: run tests/browser (Playwright, both interpreters) instead of the unit tests
        verbose: show each test name
    """
    target = list(paths) or (["tests/browser", "--browser", "chromium"] if browser else [])
    sh("uv", "run", "--frozen", "pytest", "-q", *target, *(["-v"] if verbose else []))


@task(name="pyscript.fetch", requires=["uv"])
def pyscript_fetch() -> None:
    """Unpack PyScript's offline bundle into tools/pyscript/<version>/ (a no-op once present)."""
    sh("uv", "run", "--frozen", "python", "tools/fetch_pyscript.py")


@task(requires=["uv"])
def lint(*, fix: bool = False) -> None:
    """Check lint rules and formatting, exactly as CI checks them.

    Args:
        fix: rewrite files instead of only reporting
    """
    sh("uv", "run", "--frozen", "ruff", "check", *(["--fix"] if fix else []), ".")
    sh("uv", "run", "--frozen", "ruff", "format", *([] if fix else ["--check"]), ".")


@task(requires=["uv"])
def types() -> None:
    """Type-check the package and the tests with ty."""
    sh("uv", "run", "--frozen", "ty", "check")


@task(needs=[lint, types, test])
def check() -> None:
    """The gate: everything CI runs on a push, minus the browser suite."""
    note("lint, types and unit tests passed")


@task(requires=["uv"], needs=[pyscript_fetch])
def serve(*, port: int = 8000) -> None:
    """Serve the examples and the local PyScript, reading ./frontage live so an edit shows on reload.

    Args:
        port: TCP port to listen on
    """
    sh("uv", "run", "--frozen", "python", "tools/serve.py", "--port", str(port))


@task(name="dist.build", requires=["uv"])
def dist_build() -> None:
    """Build sdist + wheel into ./dist and import the wheel once, as CI does before publishing."""
    sh("uv", "build")
    sh(
        "sh",
        "-c",
        'uv run --isolated --no-project --with dist/*.whl -- python -c "import frontage; print(frontage.__version__)"',
    )


@task(name="site.build")
def site_build() -> None:
    """Assemble frontage.optersoft.com into ./www.

    web/ is the landing page; examples/ goes under /examples/ unchanged, and the package
    goes to /frontage/ because every example's pyscript.json fetches it from that
    absolute path (the same layout serve_examples.py serves locally).
    """
    if WWW.exists():
        shutil.rmtree(WWW)
    shutil.copytree(ROOT / "web", WWW)
    shutil.copytree(
        ROOT / "examples", WWW / "examples", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "__init__.py")
    )
    shutil.copytree(ROOT / "frontage", WWW / "frontage", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    files = sum(1 for f in WWW.rglob("*") if f.is_file())
    note(f"www/ assembled: {files} files")


@task(name="site.deploy", needs=[site_build], requires=["wrangler"], dangerous=True)
def site_deploy() -> None:
    """Publish ./www to Cloudflare Pages as the production deployment of `frontage`."""
    sh("wrangler", "pages", "deploy", str(WWW), "--project-name", "frontage", "--branch", "main", "--commit-dirty=true")
