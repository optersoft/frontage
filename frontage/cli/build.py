"""`python -m frontage build APP`: a directory that runs the app from WebAssembly.

The output is static and self-contained — no repo, no PyPI, no CDN, no server:

    index.html                 the page, with the boot tag
    app.py, …                  the app's sources, still readable
    _frontage/boot.js          the loader
    _frontage/micropython.mjs  the interpreter's glue
    _frontage/micropython.wasm the interpreter
    _frontage/frontage.tar     the framework, precompiled
    _frontage/app.tar          the app's modules, as the interpreter imports them

Four requests to first paint, and every one of them but `app.tar` is immutable for a given
frontage version, so a second app on the same site pays for none of it again.

This replaces `export`, which wrote a PyScript page: a `pyscript.json`, the framework as
sixteen separate `.py` files fetched and compiled on every page view, and PyScript's own
bundle on top. `export` keeps working through 0.9.x for the pages that still need it.
"""

import argparse
import re
import shutil
import sys
import tarfile
from pathlib import Path

from . import PROG
from . import micropython as mp

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "_frontage", "*.tar")

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{title}</title>
</head>
<body>
<div id="app">Loading…</div>
{tag}
</body>
</html>
"""


# PyScript's two page-level assets. An app being migrated still names them, and left in place
# they are two 404s and a console error on a page that otherwise works. Only these two are
# touched: an app's own inline JavaScript is its own business, and a `<script type="mpy">` that
# PyScript never claims is inert anyway.
_PYSCRIPT_ASSET = re.compile(
    r"""[ \t]*<(?:script[^>]*\bsrc|link[^>]*\bhref)\s*=\s*["'][^"']*\bcore\.(?:js|css)["'][^>]*>"""
    r"""(?:\s*</script>)?[ \t]*\n?""",
    re.I,
)


def strip_pyscript(html):
    """`html` without PyScript's `core.js` / `core.css` tags."""
    return _PYSCRIPT_ASSET.sub("", html)


def boot_tag(entry, prefix="./"):
    return f'<script type="module" src="{prefix}_frontage/boot.js" data-fr-boot data-fr-entry="{entry}"></script>'


def find_entry(app):
    """The module that mounts the app, in the order a person would guess it.

    The one that calls `mount(`, then a conventional name, then the only module there is. A
    directory that answers to none of those gets an error naming its candidates rather than a
    guess: picking the wrong entry produces a blank page and no explanation.
    """
    modules = sorted(p for p in app.glob("*.py") if not p.name.startswith("_"))
    if not modules:
        raise SystemExit(f"error: no .py files in {app}")
    mounting = [p for p in modules if "mount(" in p.read_text()]
    if len(mounting) == 1:
        return mounting[0].stem
    names = {p.stem for p in modules}
    for guess in ("app", "main", app.name):
        if guess in names:
            return guess
    if len(modules) == 1:
        return modules[0].stem
    raise SystemExit(f"error: cannot tell which module mounts the app ({', '.join(sorted(names))}); pass --entry")


def app_image(app, out):
    """`app.tar`: every module in the app directory, as source."""
    modules = sorted(app.glob("*.py"))
    with tarfile.open(out, "w", format=tarfile.USTAR_FORMAT) as tf:
        for path in modules:
            info = tarfile.TarInfo(path.name)
            info.size = path.stat().st_size
            info.mtime = 0
            with path.open("rb") as fh:
                tf.addfile(info, fh)
    return modules


def framework_image(dest, quiet=False):
    """The vendored `frontage.tar`, rebuilt first when we are running from a checkout."""
    source = mp.RUNTIME_DIR / mp.IMAGE_NAME
    checkout = (mp.RUNTIME_DIR.parent.parent / "pyproject.toml").exists()
    if checkout or not source.exists():
        mp.image(quiet=quiet)
    shutil.copy2(source, dest / mp.IMAGE_NAME)


def build(app, out="", entry="", quiet=False):
    app = Path(app).resolve()
    if not app.is_dir():
        raise SystemExit(f"error: {app} is not a directory")
    out = Path(out).resolve() if out else Path("dist") / app.name
    entry = entry or find_entry(app)
    if not (app / f"{entry}.py").exists():
        raise SystemExit(f"error: no {entry}.py in {app}")

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(app, out, ignore=IGNORE)

    runtime = out / "_frontage"
    runtime.mkdir(parents=True, exist_ok=True)
    mp.fetch(quiet=quiet)  # a no-op once the wheel's copy is in place
    for name in mp.WANTED + ("boot.js",):
        shutil.copy2(mp.RUNTIME_DIR / name, runtime / name)
    framework_image(runtime, quiet=quiet)
    modules = app_image(app, runtime / "app.tar")

    page = out / "index.html"
    if page.exists():
        html = strip_pyscript(page.read_text())
        if "data-fr-boot" not in html:
            tag = boot_tag(entry)
            html = html.replace("</body>", f"{tag}\n</body>") if "</body>" in html else html + f"\n{tag}\n"
        page.write_text(html)
    else:
        page.write_text(PAGE.format(title=app.name, tag=boot_tag(entry)))

    if not quiet:
        total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
        print(f"{out}: entry {entry}, {len(modules)} app modules, {total:,} bytes")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog=f"{PROG} build", description=__doc__)
    parser.add_argument("app", help="the app directory")
    parser.add_argument("--out", default="", help="where to write (default: dist/<app>)")
    parser.add_argument("--entry", default="", help="the module that mounts (default: inferred)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    try:
        build(args.app, args.out, args.entry, quiet=args.quiet)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0
