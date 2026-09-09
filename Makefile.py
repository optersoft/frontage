"""Tasks for the `frontage` repo -- a Python frontend framework for PyScript.

    mk sync                 .venv with every dependency group
    mk test                 unit tests (no browser)
    mk test --browser       the examples in Chromium, on the runtime in WebAssembly
    mk runtime.build        build the runtime from rust/ into frontage/_runtime/ (cargo, wasm-opt)
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
    mk site.dev             the dev server for web/ (the landing page, the gallery index)
    mk site.build           frontage.optersoft.com into ./www: the site, the gallery, wheels, playground
    mk site.deploy          build, then publish ./www to Cloudflare Pages by hand (fallback)

PyPI gets the package from CI on a `vX.Y.Z` tag (.github/workflows/ci.yml);
nothing here publishes a package. The site ships the same way: the Cloudflare
Pages project `frontage` is connected to github.com/optersoft/frontage
(2026-09-06), so a push to `main` builds and deploys frontage.optersoft.com.
`mk site.deploy` is the hand deploy from before that, kept as a fallback when
the Pages build is broken. Documentation lives on academy.optersoft.com, not
here, and since 2026-09-06 the chapters run their apps in the page (the academy's
`::: pyscript` frames, MicroPython, the released wheel by URL). frontage.optersoft.com
serves its own landing page and the gallery index (web/, an Astro site on the Optersoft
chrome `@optersoft/astro`, the sibling checkout at ../astro) and links there, plus the built
gallery apps, the playground and /dist/ (the wheels, which the chapters pin by URL). examples/ is
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

    The browser suite needs the runtime's compiler (`cargo build --profile native -p fpy` in
    rust/, or a release's binary) and a Chromium once: `uv run playwright install chromium`.

    Args:
        browser: run tests/browser (Playwright, the runtime in wasm) instead of the unit tests
        verbose: show each test name
    """
    target = list(paths) or (["tests/browser", "--browser", "chromium"] if browser else [])
    sh("uv", "run", "--frozen", "pytest", "-q", *target, *(["-v"] if verbose else []))


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
    # The package resolves its public names lazily; the stub is what an editor and ty read.
    sh("uv", "run", "--frozen", "python", "tools/exports.py", "--check")


@task(requires=["uv"])
def types() -> None:
    """Type-check the package and the tests with ty."""
    sh("uv", "run", "--frozen", "ty", "check")


@task(needs=[lint, types, test])
def check() -> None:
    """The gate: everything CI runs on a push, minus the browser suite."""
    note("lint, types and unit tests passed")


@task(name="components.wasm", requires=["cargo"])
def components_wasm() -> None:
    """Build every crate in rust/components/ and vendor the .wasm into the component that ships it.

    These are not the runtime: they are ordinary libraries an app calls through `data-fr-js`
    (`rust/components/README.md`). The built files are committed, so `pip install frontage`
    needs no Rust."""
    crates = {"dsp": ROOT / "frontage" / "dsp" / "_browser" / "dsp.wasm"}
    for name, destination in crates.items():
        crate = ROOT / "rust" / "components" / name
        sh("cargo", "test", "--release", cwd=crate)
        sh("cargo", "build", "--release", "--target", "wasm32-unknown-unknown", cwd=crate)
        built = crate / "target" / "wasm32-unknown-unknown" / "release" / f"{name}.wasm"
        shutil.copy2(built, destination)
        note(f"{destination.relative_to(ROOT)}: {destination.stat().st_size:,} bytes")


@task(name="runtime.build", requires=["cargo", "wasm-opt"])
def runtime_build() -> None:
    """Build the runtime from rust/ and vendor it into frontage/_runtime/.

    Two wasms — `frontage.wasm` (no parser in the page) and `frontage-compiler.wasm` (with
    the compiler, for the playground and the runner) — through `cargo build -p frontage-web
    --profile wasms` and `wasm-opt -Os`, the three scripts beside them (`glue.js`, `boot.js`,
    and `island.js`, the loader a static page carries), and the compiler `fpy` for this
    machine (`--profile native`). Commit the five files: a wheel ships them, `frontage build`
    copies them, `frontage serve` serves them."""
    rust = ROOT / "rust"
    dest = ROOT / "frontage" / "_runtime"
    dest.mkdir(parents=True, exist_ok=True)
    built = rust / "target" / "wasm32-unknown-unknown" / "wasms" / "frontage_web.wasm"
    for name, features in (("frontage.wasm", []), ("frontage-compiler.wasm", ["--features", "compiler"])):
        sh(
            "cargo",
            "build",
            "-p",
            "frontage-web",
            "--profile",
            "wasms",
            "--target",
            "wasm32-unknown-unknown",
            *features,
            cwd=rust,
        )
        sh("wasm-opt", "-Os", "--all-features", str(built), "-o", str(dest / name))
    sh("cargo", "build", "--profile", "native", "-p", "fpy", cwd=rust)
    for name in ("glue.js", "boot.js", "island.js"):
        shutil.copy2(rust / "web" / name, dest / name)
    for name in ("frontage.wasm", "frontage-compiler.wasm"):
        print(f"{dest / name}: {(dest / name).stat().st_size:,} bytes")


@task(requires=["uv"])
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


@task(requires=["uv"])
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


WEB = ROOT / "web"
#: The Optersoft chrome, a path dependency like every other sibling here. On the laptop it is
#: the checkout beside this repo; on a builder that has only this one (Cloudflare's),
#: `site.build` clones it. `web/site.py` imports it, so it has to be importable.
BRAND = ROOT.parent / "brand"
BRAND_GIT = "https://github.com/optersoft/brand.git"


def _web_deps() -> None:
    if not BRAND.is_dir():
        note(f"cloning the chrome into {BRAND}")
        sh("git", "clone", "--depth", "1", BRAND_GIT, str(BRAND))


def _web_env() -> dict:
    """The environment `frontage site` needs for web/: the chrome on the path."""
    import os

    path = os.environ.get("PYTHONPATH", "")
    return {"PYTHONPATH": f"{BRAND}{os.pathsep}{path}" if path else str(BRAND)}


@task(name="site.dev", requires=["uv"])
def site_dev(*args: str) -> None:
    """The dev server for web/ on :8000, rebuilding the site when a file changes.

    `--prerender` because a site has no file at `/gallery/` until something makes one; the
    gallery index needs `mk gallery` to have run for its numbers.
    """
    _web_deps()
    sh(
        "uv",
        "run",
        "--frozen",
        "python",
        "-m",
        "frontage",
        "serve",
        str(WEB),
        "--prerender",
        *args,
        env=_web_env(),
    )


@task(name="site.build", needs=[gallery])
def site_build() -> None:
    """Assemble frontage.optersoft.com into ./www.

    web/ is a **frontage site** — `pages/` is the site map, the chrome is `optersoft_brand`,
    and every page of it ships no runtime — built straight into www/ beside the gallery apps.
    Under public/ the playground and the runner are static files; the playground carries its
    own copy of the WebAssembly runtime at /playground/_frontage/, which is where its boot
    tag points, and `boot.js` finds the interpreter and both archives from its own URL, so
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
    _web_deps()
    sh(
        "uv",
        "run",
        "--frozen",
        "python",
        "-m",
        "frontage",
        "site",
        str(WEB),
        "--out",
        str(WWW),
        "--tailwind",
        env=_web_env(),
    )
    if keep.exists():
        # Merged into the gallery directory the build just made, one entry at a time.
        # `shutil.move`
        # of the whole directory would put it *inside* that one — `www/gallery/_gallery-keep/`
        # — and every card on the page links to `./<app>/`, so the whole gallery 404s while
        # the index that lists it looks perfectly well.
        target = WWW / "gallery"
        target.mkdir(parents=True, exist_ok=True)
        for entry in keep.iterdir():
            destination = target / entry.name
            if destination.exists():
                shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
            shutil.move(str(entry), str(destination))
        shutil.rmtree(keep)
    runtime = ROOT / "frontage" / "_runtime"
    if not (runtime / "frontage-compiler.wasm").exists():
        raise MakeError("no runtime: run `mk runtime.build` first")
    # The playground is an app: built the way any app is, then given the compiler build and
    # every framework module, since a typed program may import any of it. A second copy at
    # the site root, for `runner.html`: `boot.js` finds its files beside itself, and the
    # runner has no app directory, so one copy cannot serve both.
    sh(
        "uv",
        "run",
        "--frozen",
        "python",
        "-m",
        "frontage",
        "build",
        "web/public/playground",
        "--out",
        str(WWW / "playground"),
        "--quiet",
    )
    sh(
        "uv",
        "run",
        "--frozen",
        "python",
        "-c",
        "from frontage.cli.frontage_rt import site_files; site_files('www/playground/_frontage'); site_files('www/_frontage')",
    )
    # The wheel, so a page can name it by URL with no PyPI hop. Every wheel ever released
    # stays at its URL: the academy chapters and their repos pin one by version, and a deploy
    # must not break them.
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
