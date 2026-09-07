"""Tasks for the `frontage` repo -- a Python frontend framework for PyScript.

    mk sync                 .venv with every dependency group
    mk test                 unit tests (no browser)
    mk test --browser       the examples in Chromium, on MicroPython in WebAssembly
    mk runtime.fetch        the pinned micropython.mjs + .wasm into frontage/_runtime/
    mk runtime.build        cross-compile the framework into frontage/_runtime/frontage.tar
    mk pyscript.fetch       PyScript's offline bundle (core + both interpreters) into tools/pyscript/
    mk lint [--fix]         ruff check + ruff format, as CI runs them
    mk types                ty
    mk check                the gate: lint, types, unit tests
    mk serve [--port N]     the examples at http://127.0.0.1:8000/examples/, package read live
    mk dist.build           sdist + wheel into ./dist, then import the wheel once
    mk build APP [--out D]  a self-contained static directory for one app, booting from wasm
    mk export APP [--out D]  the same as a PyScript page (0.9.x only; `build` replaces it)
    mk vscode.test          the extension: manifest, snippets, client, grammar (needs npm)
    mk gallery              build every example, measure it in Chromium, write www/gallery/
    mk site.build           frontage.optersoft.com into ./www: the gallery, wheels, playground
    mk site.deploy          build, then publish ./www to Cloudflare Pages by hand (fallback)

PyPI gets the package from CI on a `vX.Y.Z` tag (.github/workflows/ci.yml);
nothing here publishes a package. The site ships the same way: the Cloudflare
Pages project `frontage` is connected to github.com/optersoft/frontage
(2026-09-06), so a push to `main` builds and deploys frontage.optersoft.com.
`mk site.deploy` is the hand deploy from before that, kept as a fallback when
the Pages build is broken. Documentation lives on academy.optersoft.com, not
here, and since 2026-09-06 the chapters run their apps in the page (the academy's
`::: pyscript` frames, MicroPython, the released wheel by URL): frontage.optersoft.com
redirects there and serves only /dist/ (the wheels) and /playground/. examples/ is
the browser suite's and the benchmark's material. `mk` with no arguments lists everything.
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

    The browser suite needs `mk runtime.fetch` once, and a Chromium once:
    `uv run playwright install chromium`.

    Args:
        browser: run tests/browser (Playwright, MicroPython in wasm) instead of the unit tests
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


@task(name="runtime.fetch", requires=["uv"])
def runtime_fetch() -> None:
    """Download the pinned MicroPython WebAssembly build into frontage/_runtime/.

    The version is one line, `frontage/cli/micropython.py:VERSION`, the way the PyScript pin
    was. It is the same build PyScript shipped, so bumping it is a browser run, not a port.
    """
    sh("uv", "run", "--frozen", "python", "-m", "frontage", "runtime", "fetch")


@task(name="runtime.build", requires=["uv"], needs=[runtime_fetch])
def runtime_build() -> None:
    """Cross-compile the framework to bytecode and pack frontage/_runtime/frontage.tar.

    Needs mpy-cross (the dev group). The tar is reproducible -- mtimes are pinned to 0 -- so
    CI rebuilds it and compares bytes rather than trusting a timestamp a wheel install
    flattens. Run this after any change to a top-level module in frontage/.
    """
    sh("uv", "run", "--frozen", "python", "-m", "frontage", "runtime", "image")


@task(requires=["uv"], needs=[runtime_fetch])
def serve(*, port: int = 8000) -> None:
    """Serve the examples, reading ./frontage live; the page reloads when a file changes.

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


@task(requires=["uv"], needs=[runtime_build])
def build(app: str, *, out: str = "", entry: str = "") -> None:
    """Build one app directory into static files that boot from WebAssembly.

    Four requests to first paint and no PyScript: the interpreter, the framework as
    precompiled bytecode, the app as source, and a 4 KB loader.

    Args:
        app: the app directory (its .py files, and an index.html if it wants one)
        out: destination directory (default dist/<app name>)
        entry: the module that mounts (default: inferred)
    """
    args = ["-m", "frontage", "build", app]
    if out:
        args += ["--out", out]
    if entry:
        args += ["--entry", entry]
    sh("uv", "run", "--frozen", "python", *args)


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


@task(requires=["uv"], needs=[runtime_fetch])
def gallery(*, out: str = "", quick: bool = False) -> None:
    """Build every gallery app, measure it in Chromium, and write www/gallery/.

    The gallery is the marketing and an acceptance test at once: every app is built with the
    real `frontage build`, then loaded cold in a browser, so a broken one fails the build and
    a slower one changes the number on the page. `site.build` runs this.

    Args:
        out: destination (default www/gallery)
        quick: skip the browser and publish sizes only
    """
    args = ["python", "tools/gallery.py"]
    if out:
        args += ["--out", out]
    if quick:
        args.append("--quick")
    sh("uv", "run", "--frozen", *args)


@task(name="site.build", needs=[gallery])
def site_build() -> None:
    """Assemble frontage.optersoft.com into ./www.

    web/ holds the redirects to the academy and the playground. The playground carries its
    own copy of the WebAssembly runtime at /playground/_frontage/, which is where its boot
    tag points; `boot.js` finds the interpreter and both archives from its own URL, so
    nothing here needs a rewrite rule.

    `mk gallery` has already written www/gallery/ by the time this runs, so it is preserved
    rather than rebuilt: the numbers on that page come from a real browser and are not
    something a site assembly step should be inventing.
    """
    gallery_built = WWW / "gallery"
    keep = ROOT / "build" / "_gallery-keep"
    if gallery_built.exists():
        if keep.exists():
            shutil.rmtree(keep)
        shutil.move(str(gallery_built), str(keep))
    if WWW.exists():
        shutil.rmtree(WWW)
    shutil.copytree(ROOT / "web", WWW)
    if keep.exists():
        shutil.move(str(keep), str(WWW / "gallery"))
    runtime = ROOT / "frontage" / "_runtime"
    if not (runtime / "micropython.wasm").exists():
        raise MakeError("no runtime: run `mk runtime.fetch` first")
    shutil.copytree(runtime, WWW / "playground" / "_frontage")
    # A second copy at the site root, for `runner.html`. Not shared with the playground's:
    # `boot.js` finds `app.tar` beside itself, and the runner has no app to find, so one copy
    # cannot serve both without breaking the rule that makes nested routes work.
    shutil.copytree(runtime, WWW / "_frontage")
    # The playground's own source is its app, packed the way `build` packs one.
    import tarfile

    with tarfile.open(WWW / "playground" / "_frontage" / "app.tar", "w", format=tarfile.USTAR_FORMAT) as archive:
        for module in sorted((ROOT / "web" / "playground").glob("*.py")):
            info = tarfile.TarInfo(module.name)
            info.size = module.stat().st_size
            info.mtime = 0
            with module.open("rb") as handle:
                archive.addfile(info, handle)
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


@task(name="vscode.test", requires=["npm"])
def vscode_test() -> None:
    """Test the VS Code extension: the manifest, the snippets, the client's server discovery,
    and the TextMate grammar tokenised by the engine VS Code itself uses."""
    sh("npm", "install", "--silent", cwd=VSCODE)
    sh("npm", "test", cwd=VSCODE)


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
