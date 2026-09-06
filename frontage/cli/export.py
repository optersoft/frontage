"""`python -m frontage export APP`: a directory of static files that runs the app anywhere files
can be served.

Copies the app directory, the `frontage` package (as files, the way `pyscript.json` lists
them) and PyScript's offline bundle, and rewrites the app's `pyscript.json` and HTML so the
package and PyScript are found beside the app. The result has no dependency on this machine,
PyPI or a CDN. With `--no-pyscript` the HTML links PyScript from pyscript.net instead."""

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import PROG, pyscript


def export(app, out=None, bundle_pyscript=True, pyscript_dir=None, quiet=False):
    """Export `app` (a directory with an index.html) into `out`; returns `out`."""
    import frontage

    app = Path(app).resolve()
    if not (app / "index.html").exists():
        raise FileNotFoundError(f"{app} has no index.html")
    out = Path(out).resolve() if out else Path.cwd() / "build" / app.name
    if out == app or app in out.parents:
        raise ValueError(f"the output {out} must not be inside the app {app}")
    package = Path(frontage.__file__).resolve().parent
    if out.exists():
        shutil.rmtree(out)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(app, out, ignore=ignore)
    # The browser gets the top-level modules only: `cli/` and `__main__.py` are for CPython.
    modules = sorted(p for p in package.glob("*.py") if p.name != "__main__.py")
    (out / "frontage").mkdir()
    for p in modules:
        shutil.copy(p, out / "frontage" / p.name)
    config = out / "pyscript.json"
    existing = json.loads(config.read_text()) if config.exists() else {}
    existing["files"] = {**existing.get("files", {}), **{f"./frontage/{p.name}": f"frontage/{p.name}" for p in modules}}
    # The modules above are the package; a `frontage` wheel in `packages` (how an app installs
    # it while developing) would install it a second time.
    packages = [p for p in existing.get("packages", []) if not _is_frontage_wheel(p)]
    if packages:
        existing["packages"] = packages
    else:
        existing.pop("packages", None)
    config.write_text(json.dumps(existing, indent=2) + "\n")
    html = (out / "index.html").read_text()
    release = f"https://pyscript.net/releases/{pyscript.VERSION}"
    if bundle_pyscript:
        bundle = Path(pyscript_dir) if pyscript_dir else pyscript.fetch(quiet=quiet)
        if not (bundle / "core.js").exists():
            raise FileNotFoundError(f"{bundle} holds no PyScript bundle (no core.js)")
        shutil.copytree(bundle, out / "pyscript", ignore=shutil.ignore_patterns("*.map"))
        html = html.replace('"/pyscript/', '"./pyscript/')
        # A page that links PyScript from its CDN (the three-file layout) now loads the bundle
        # beside it; `offline` makes PyScript resolve the interpreters there too.
        html = html.replace(f'src="{release}/core.js"', 'src="./pyscript/core.js" offline').replace(
            f'"{release}/core.css"', '"./pyscript/core.css"'
        )
    else:
        html = (
            html.replace("/pyscript/core.js", f"{release}/core.js")
            .replace("/pyscript/core.css", f"{release}/core.css")
            .replace(" offline>", ">")
        )
    html = html.replace('"../pyscript.json"', '"./pyscript.json"')
    (out / "index.html").write_text(html)
    return out


def _is_frontage_wheel(entry):
    """`frontage-0.4.0-py3-none-any.whl`, by path or URL."""
    return entry.rsplit("/", 1)[-1].startswith("frontage-") and entry.endswith(".whl")


def main(argv=None):
    parser = argparse.ArgumentParser(prog=f"{PROG} export", description=__doc__)
    parser.add_argument("app", help="a directory with an index.html and the app's .py files")
    parser.add_argument("--out", default=None, help="destination (default: ./build/<app name>)")
    parser.add_argument(
        "--no-pyscript", action="store_true", help="link PyScript from pyscript.net instead of bundling it"
    )
    parser.add_argument("--pyscript", default=None, help="an unpacked bundle (the directory with core.js) to copy")
    args = parser.parse_args(argv)
    try:
        out = export(args.app, args.out, bundle_pyscript=not args.no_pyscript, pyscript_dir=args.pyscript)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) // 1024
    print(f"exported {Path(args.app).name} to {out} ({size} KB); serve it with any static file server")
    return 0


if __name__ == "__main__":
    sys.exit(main())
