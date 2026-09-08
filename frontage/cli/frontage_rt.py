"""Frontage's own runtime (`rust/`) on the host: which runtime a build or a server targets,
where its browser files are, and the compiler that turns a module into `.fbc`.

The choice is `--runtime` on `build` and `serve`, or `FRONTAGE_RUNTIME=frontage|micropython`
in the environment (the browser suite sets it). Until the runtime ships in the wheel, its
files come from a checkout's `rust/web/` and the compiler is the `fpy` binary `cargo build`
made there (`FRONTAGE_FPY` names another).
"""

import json
import os
import subprocess
from pathlib import Path

FRONTAGE = "frontage"
MICROPYTHON = "micropython"

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "rust" / "web"
ASSETS = ("frontage.wasm", "glue.js", "boot.js")
MANIFEST = "manifest.json"

_compiled = {}  # path -> (mtime, bytes)


def selected(flag=""):
    """The runtime in force: the flag, else the environment, else MicroPython."""
    name = flag or os.environ.get("FRONTAGE_RUNTIME", "") or MICROPYTHON
    if name in ("rs", "rust"):
        name = FRONTAGE
    if name not in (FRONTAGE, MICROPYTHON):
        raise SystemExit(f"error: unknown runtime {name!r} (frontage or micropython)")
    return name


def available():
    return (WEB / "frontage.wasm").is_file()


def fpy():
    """The compiler binary, or an error that says how to get one."""
    named = os.environ.get("FRONTAGE_FPY")
    candidates = [Path(named)] if named else []
    candidates += [ROOT / "rust" / "target" / profile / "fpy" for profile in ("native", "release", "debug")]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit("error: no fpy binary: run `cargo build --profile native` in rust/, or set FRONTAGE_FPY")


def compile_module(path):
    """`path` as `.fbc` bytes, cached by mtime for a server that answers many reloads."""
    path = Path(path)
    stamp = path.stat().st_mtime_ns
    hit = _compiled.get(path)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / f"frontage-{os.getpid()}-{abs(hash(str(path)))}.fbc"
    run = subprocess.run([str(fpy()), "--compile", str(tmp), str(path)], capture_output=True, text=True)
    if run.returncode != 0:
        raise SystemExit(f"error: {path}: {run.stderr.strip() or 'the compiler failed'}")
    data = tmp.read_bytes()
    tmp.unlink(missing_ok=True)
    _compiled[path] = (stamp, data)
    return data


def closure(app, entry, components=()):
    """The modules a page needs, by dotted name, with the file each comes from: the entry's
    import closure through `cli/graph.py`, over the app, the framework and the components."""
    from .graph import Graph

    graph = Graph(app, components=components)
    names = sorted(graph.closure([entry]))
    return [(name, graph.modules[name]) for name in names]


def manifest(names, entry):
    """`manifest.json`: every module but the entry, which the boot fetches by its own name."""
    return json.dumps({"modules": [n for n in names if n != entry]}).encode()


def module_file(name, app):
    """The source of a dotted module name for a page served from `app`: the app's own, or
    the framework's."""
    if name.startswith("frontage.") or name == "frontage":
        rel = name.split(".")[1:]
        package = ROOT / "frontage"
        return package / "__init__.py" if not rel else package.joinpath(*rel[:-1], rel[-1] + ".py")
    return Path(app) / (name.replace(".", "/") + ".py")
