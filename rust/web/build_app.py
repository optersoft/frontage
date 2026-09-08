"""Build an example app for frontage's runtime: `python build_app.py examples/counter dist/counter`.

Compiles the framework and the app's modules to `.fbc` with `fpy --compile`, writes the
manifest, copies the runtime (`frontage.wasm`, `glue.js`, `boot.js`) and the page. The spike's
stand-in for `frontage build`; the real one folds this into `cli/build.py`.
"""

import json
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
    shutil.rmtree(dist, ignore_errors=True)
    runtime = dist / "_frontage"
    runtime.mkdir(parents=True)
    modules = []
    package = ROOT / "frontage"
    compile_to(runtime, "frontage", package / "__init__.py")
    modules.append("frontage")
    for src in sorted(package.glob("*.py")):
        if src.name in ("__init__.py", "__main__.py"):
            continue
        compile_to(runtime, f"frontage.{src.stem}", src)
        modules.append(f"frontage.{src.stem}")
    for src in sorted(app.glob("*.py")):
        compile_to(runtime, src.stem, src)
        modules.append(src.stem)
    (runtime / "manifest.json").write_text(json.dumps({"modules": modules}))
    for name in ("frontage.wasm", "glue.js", "boot.js"):
        shutil.copy2(HERE / name, runtime / name)
    for extra in app.iterdir():
        if extra.suffix in (".html", ".css", ".js") and extra.is_file():
            shutil.copy2(extra, dist / extra.name)
    total = sum(p.stat().st_size for p in runtime.glob("*.fbc"))
    print(f"{dist}: {len(modules)} modules, {total:,} bytes of bytecode")


if __name__ == "__main__":
    main()
