"""`frontage export`: a directory of static files that runs an app anywhere files can be served.

    uv run python tools/export.py examples/counter --out build/counter [--interpreter mpy|py]

Copies the app directory, the `frontage` package (as files, the way `pyscript.json` lists
them) and the local PyScript bundle, and rewrites the app's `pyscript.json` and HTML so the
package and PyScript are found beside the app. The result has no dependency on this repo,
PyPI or a CDN. Stdlib only, so it can run from any Python."""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("app", help="a directory with an index.html and the app's .py files")
    parser.add_argument("--out", default=None, help="destination (default: build/<app name>)")
    parser.add_argument(
        "--no-pyscript", action="store_true", help="link PyScript from pyscript.net instead of bundling it"
    )
    args = parser.parse_args()
    app = Path(args.app).resolve()
    if not (app / "index.html").exists():
        print(f"error: {app} has no index.html", file=sys.stderr)
        return 2
    out = Path(args.out).resolve() if args.out else ROOT / "build" / app.name
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(app, out, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "frontage", out / "frontage", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    files = {f"./frontage/{p.name}": f"frontage/{p.name}" for p in sorted((ROOT / "frontage").glob("*.py"))}
    config = out / "pyscript.json"
    existing = json.loads(config.read_text()) if config.exists() else {}
    existing["files"] = {**existing.get("files", {}), **files}
    config.write_text(json.dumps(existing, indent=2) + "\n")
    html = (out / "index.html").read_text()
    if args.no_pyscript:
        version = _bundle_version()
        html = (
            html.replace("/pyscript/core.js", f"https://pyscript.net/releases/{version}/core.js")
            .replace("/pyscript/core.css", f"https://pyscript.net/releases/{version}/core.css")
            .replace(" offline>", ">")
        )
    else:
        bundle = _bundle()
        if bundle is None:
            print("error: no local PyScript bundle; run `mk pyscript.fetch` or pass --no-pyscript", file=sys.stderr)
            return 2
        shutil.copytree(bundle, out / "pyscript", ignore=shutil.ignore_patterns("*.map"))
        html = html.replace('"/pyscript/', '"./pyscript/')
    html = html.replace('"../pyscript.json"', '"./pyscript.json"')
    (out / "index.html").write_text(html)
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) // 1024
    print(f"exported {app.name} to {out} ({size} KB); serve it with any static file server")
    return 0


def _bundle():
    bundles = sorted((ROOT / "tools" / "pyscript").glob("*/pyscript"))
    return bundles[-1] if bundles else None


def _bundle_version():
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location("fetch_pyscript", ROOT / "tools" / "fetch_pyscript.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.VERSION


if __name__ == "__main__":
    sys.exit(main())
