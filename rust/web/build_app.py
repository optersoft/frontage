"""Build an example app for frontage's runtime: `python build_app.py examples/counter dist/counter [entry]`.

Compiles the modules the entry reaches (the framework's and the app's, by the import walk) to `.fbc` with `fpy --compile`, writes the
manifest, copies the runtime (`frontage.wasm`, `glue.js`, `boot.js`) and the page. The spike's
stand-in for `frontage build`; the real one folds this into `cli/build.py`.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FPY = HERE.parent / "target" / "debug" / "fpy"


def compile_to(out: Path, name: str, source: Path) -> None:
    subprocess.run([str(FPY), "--compile", str(out / f"{name}.fbc"), str(source)], check=True)


def main() -> None:
    app = Path(sys.argv[1]).resolve()
    dist = Path(sys.argv[2]).resolve()
    entry = sys.argv[3] if len(sys.argv) > 3 else _entry_of(app)
    shutil.rmtree(dist, ignore_errors=True)
    runtime = dist / "_frontage"
    runtime.mkdir(parents=True)
    # The closure the entry reaches, read with `ast` on CPython: what `frontage build` packs
    # (`frontage/cli/graph.py`), rather than the whole framework.
    sys.path.insert(0, str(ROOT))
    from frontage.cli.graph import Graph

    graph = Graph(app)
    modules = sorted(graph.closure([entry]))
    for name in modules:
        compile_to(runtime, name, graph.modules[name])
    (runtime / "manifest.json").write_text(json.dumps({"modules": [m for m in modules if m != entry]}))
    for name in ("frontage.wasm", "glue.js", "boot.js"):
        shutil.copy2(HERE / name, runtime / name)
    for extra in app.iterdir():
        if extra.suffix in (".html", ".css", ".js") and extra.is_file():
            shutil.copy2(extra, dist / extra.name)
    total = sum(p.stat().st_size for p in runtime.glob("*.fbc"))
    skipped = sorted(graph.framework_modules - set(modules))
    print(f"{dist}: {len(modules)} modules, {total:,} bytes of bytecode; not reached: {', '.join(skipped) or 'nothing'}")


def _entry_of(app: Path) -> str:
    """The `data-fr-entry` of the page's boot tag, else `app`."""
    page = app / "index.html"
    if page.exists():
        m = re.search(r'data-fr-entry="([^"]+)"', page.read_text())
        if m:
            return m.group(1)
    return "app"


if __name__ == "__main__":
    main()
