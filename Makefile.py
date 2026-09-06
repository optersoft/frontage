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
    mk export APP [--out D] a self-contained static directory for one app (examples/counter, …)
    mk site.build           frontage.optersoft.com into ./www: web/ + the live examples
    mk site.deploy          build, then publish ./www to Cloudflare Pages by hand (fallback)

PyPI gets the package from CI on a `vX.Y.Z` tag (.github/workflows/ci.yml);
nothing here publishes a package. The site ships the same way: the Cloudflare
Pages project `frontage` is connected to github.com/optersoft/frontage
(2026-09-06), so a push to `main` builds and deploys frontage.optersoft.com.
`mk site.deploy` is the hand deploy from before that, kept as a fallback when
the Pages build is broken. Documentation lives on academy.optersoft.com, not
here. `mk` with no arguments lists everything.
"""

# /// script
# requires-python = ">=3.11"
# dependencies = ["mkrun>=0.3"]
# ///

from __future__ import annotations

import shutil
from pathlib import Path

from make import MakeError, note, sh, task

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
    # The rules the browser interpreters enforce and a desktop Python does not.
    sh("uv", "run", "--frozen", "python", "-m", "frontage", "check", "examples", "web", "frontage")


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
    """Serve the examples and the local PyScript, reading ./frontage live; the page reloads when a file changes.

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


@task(requires=["uv"])
def export(app: str, *, out: str = "", no_pyscript: bool = False) -> None:
    """Export one app directory as static files that run without this repo, PyPI or a CDN.

    Args:
        app: the app directory (it has an index.html and the .py files)
        out: destination directory (default build/<app name>)
        no_pyscript: link PyScript from pyscript.net instead of bundling the local copy
    """
    args = ["-m", "frontage", "export", app]
    if out:
        args += ["--out", out]
    if no_pyscript:
        args.append("--no-pyscript")
    else:
        bundles = sorted((ROOT / "tools" / "pyscript").glob("*/pyscript"))
        if bundles:
            args += ["--pyscript", str(bundles[-1])]
    sh("uv", "run", "--frozen", "python", *args)


@task(name="site.build", needs=[pyscript_fetch])
def site_build() -> None:
    """Assemble frontage.optersoft.com into ./www (fetching the PyScript bundle when absent).

    web/ is the landing page; examples/ goes under /examples/, the package under /frontage/
    and the local PyScript bundle (without source maps) under /pyscript/: the same three
    absolute paths tools/serve.py serves, so an example runs unchanged in both places.
    """
    if WWW.exists():
        shutil.rmtree(WWW)
    shutil.copytree(ROOT / "web", WWW)
    # The playground fetches the package by absolute path like the examples do; the
    # frontage/ copy below serves both.
    shutil.copytree(ROOT / "examples", WWW / "examples", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(
        ROOT / "frontage", WWW / "frontage", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "cli", "__main__.py")
    )
    bundles = sorted((ROOT / "tools" / "pyscript").glob("*/pyscript"))
    if not bundles:
        raise MakeError("no local PyScript bundle: run `mk pyscript.fetch` first")
    shutil.copytree(bundles[-1], WWW / "pyscript", ignore=shutil.ignore_patterns("*.map"))
    # The wheel, so a pyscript.json can name it by URL with no PyPI hop. Every wheel ever
    # released stays at its URL: the academy chapters and their repos pin one by version, and
    # a deploy must not break them.
    sh("uv", "build", "--wheel", "--out-dir", str(WWW / "dist"))
    _released_wheels(WWW / "dist")
    files = sum(1 for f in WWW.rglob("*") if f.is_file())
    size = sum(f.stat().st_size for f in WWW.rglob("*") if f.is_file()) // (1024 * 1024)
    note(f"www/ assembled: {files} files, {size} MB")


def _released_wheels(dest: Path) -> None:
    """Download the wheel of every frontage release on PyPI into `dest` (skipping those present)."""
    import json
    import urllib.request

    with urllib.request.urlopen("https://pypi.org/pypi/frontage/json", timeout=30) as r:
        releases = json.load(r)["releases"]
    for version, files in sorted(releases.items()):
        for f in files:
            if f["packagetype"] != "bdist_wheel" or (dest / f["filename"]).exists():
                continue
            urllib.request.urlretrieve(f["url"], dest / f["filename"])
            note(f"dist/{f['filename']} (PyPI, {version})")


@task(name="site.deploy", needs=[site_build], requires=["wrangler"], dangerous=True)
def site_deploy() -> None:
    """Publish ./www to Cloudflare Pages as the production deployment of `frontage`."""
    sh("wrangler", "pages", "deploy", str(WWW), "--project-name", "frontage", "--branch", "main", "--commit-dirty=true")


VSCODE = ROOT / "editors" / "vscode"


@task(name="vscode.package", requires=["npm"])
def vscode_package() -> None:
    """Build the VS Code extension into editors/vscode/*.vsix."""
    sh("npm", "install", "--silent", cwd=VSCODE)
    sh("npx", "--yes", "@vscode/vsce", "package", "--no-git-tag-version", cwd=VSCODE)
    built = sorted(VSCODE.glob("*.vsix"))
    note(f"built {built[-1].relative_to(ROOT)}" if built else "no .vsix produced")


@task(name="vscode.install", needs=[vscode_package], requires=["code"])
def vscode_install() -> None:
    """Install the freshly built extension into the local VS Code."""
    built = sorted(VSCODE.glob("*.vsix"))
    if not built:
        raise MakeError("no .vsix in editors/vscode; run `mk vscode.package` first")
    sh("code", "--install-extension", str(built[-1]), "--force")


@task(name="lsp.probe", requires=["uv"])
def lsp_probe(path: str = "") -> None:
    """Print what the language server reports for a file, without an editor in the way."""
    sh("uv", "run", "--frozen", "python", "tools/lsp_probe.py", path or "examples/todo/todo.py")
