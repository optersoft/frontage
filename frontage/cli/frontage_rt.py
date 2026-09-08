"""Frontage's runtime (`rust/`) on the host: where its browser files are, and the compiler
that turns a module into `.fbc`.

The browser files ride in the wheel under `frontage/_runtime/`: `frontage.wasm` (no parser
in the page), `frontage-compiler.wasm` (the same with the compiler, for the playground and
the runner, which run a program someone types), `glue.js` and `boot.js`. The compiler on the
host is the `fpy` binary — one on PATH, `FRONTAGE_FPY`, a checkout's `cargo build`, or the
release asset for this platform, fetched once into `~/.cache/frontage` the way the Tailwind
CLI is.
"""

import json
import os
import platform
import shutil
import stat
import subprocess
import urllib.request
from pathlib import Path

from .. import __version__
from .tailwind import cache_dir

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = Path(__file__).resolve().parent.parent / "_runtime"
ASSETS = ("frontage.wasm", "frontage-compiler.wasm", "glue.js", "boot.js")
MANIFEST = "manifest.json"
FRAMEWORK = "framework.json"  # every framework module, for a page that runs a typed program
RELEASES = "https://github.com/optersoft/frontage/releases/download"

_compiled = {}  # path -> (mtime, bytes)


def available():
    return all((RUNTIME_DIR / name).is_file() for name in ASSETS)


def browser_modules(package=None):
    """The package files the browser can import: the top-level modules, minus `__main__.py`.

    `cli/` and `lsp/` are CPython-only and never ship. `debug.py` does ship — it is imported
    lazily, by an app that wants the hydration report.
    """
    package = Path(package) if package else Path(__file__).resolve().parent.parent
    return sorted(p for p in package.glob("*.py") if p.name != "__main__.py")


def main(argv=None):
    """`frontage runtime`: where the compiler and the browser files are, fetching the compiler."""
    import argparse

    from . import PROG

    parser = argparse.ArgumentParser(prog=f"{PROG} runtime", description=main.__doc__)
    parser.parse_args(argv)
    print(f"browser files: {RUNTIME_DIR}" + ("" if available() else " (incomplete: run `mk runtime.build`)"))
    print(f"compiler: {fpy()}")
    return 0


def asset_name(system=None, machine=None):
    """The compiler's release asset for this platform, e.g. `fpy-macos-arm64`."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if system == "darwin":
        return f"fpy-macos-{arch}"
    if system == "windows":
        return f"fpy-windows-{arch}.exe"
    return f"fpy-linux-{arch}"


def fpy(quiet=False):
    """The compiler binary: PATH, `FRONTAGE_FPY`, a checkout's build, else the release asset
    for this version, downloaded on first use."""
    named = os.environ.get("FRONTAGE_FPY")
    if named:
        return Path(named)
    found = shutil.which("fpy")
    if found:
        return Path(found)
    for profile in ("native", "release", "debug"):
        candidate = ROOT / "rust" / "target" / profile / "fpy"
        if candidate.is_file():
            return candidate
    name = asset_name()
    path = cache_dir("fpy", __version__) / name
    if path.exists():
        return path
    url = f"{RELEASES}/v{__version__}/{name}"
    if not quiet:
        print(f"fetching {url}")
    try:
        data = urllib.request.urlopen(url, timeout=300).read()
    except OSError as exc:
        raise SystemExit(
            f"error: no fpy compiler for this platform ({exc}); in a checkout run "
            "`cargo build --profile native -p fpy` in rust/, or set FRONTAGE_FPY"
        ) from None
    partial = path.with_suffix(".part")
    partial.write_bytes(data)
    partial.chmod(partial.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.replace(partial, path)
    return path


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


def framework_names():
    """Every top-level framework module by dotted name: what the compiler build loads, since a
    program typed into the playground or the runner may import any of them."""
    return ["frontage"] + sorted(f"frontage.{p.stem}" for p in browser_modules() if p.name != "__init__.py")


def framework_files(dest, quiet=True):
    """Write `framework.json` and every framework module as `.fbc` into `dest` (a static site's
    `_frontage/` for the playground and the runner)."""
    dest = Path(dest)
    names = framework_names()
    for name in names:
        (dest / f"{name}.fbc").write_bytes(compile_module(module_file(name, dest)))
    (dest / FRAMEWORK).write_bytes(json.dumps({"modules": names}).encode())
    if not quiet:
        print(f"{dest}: {len(names)} framework modules")
    return names


def site_files(dest, quiet=True):
    """A static site's `_frontage/` for a page that runs a typed program (the playground, the
    runner): the runtime's four files and every framework module as bytecode."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name in ASSETS:
        shutil.copy2(RUNTIME_DIR / name, dest / name)
    return framework_files(dest, quiet=quiet)


def manifest(names, entry, files=None, wasm=None):
    """`manifest.json`: every module but the entry (which the boot fetches by its own name),
    and, for a built app, the content-hashed file of each module and of the wasm, so the
    files can be cached forever and a rebuild changes only what changed."""
    out = {"modules": [n for n in names if n != entry]}
    if files:
        out["files"] = files
        out["entry"] = files[entry]
    if wasm:
        out["wasm"] = wasm
    return json.dumps(out).encode()


def hashed(name, data, suffix):
    """`<name>.<8 hex digits of the content>.<suffix>`."""
    import hashlib

    return f"{name}.{hashlib.sha256(data).hexdigest()[:8]}.{suffix}"


# Cloudflare Pages / Netlify `_headers`: the hashed files never change at their URL.
HEADERS = """/_frontage/*.fbc
  Cache-Control: public, max-age=31536000, immutable
/_frontage/*.wasm
  Cache-Control: public, max-age=31536000, immutable
"""


def module_file(name, app):
    """The source of a dotted module name for a page served from `app`: the app's own, or
    the framework's."""
    if name.startswith("frontage.") or name == "frontage":
        rel = name.split(".")[1:]
        package = ROOT / "frontage"
        return package / "__init__.py" if not rel else package.joinpath(*rel[:-1], rel[-1] + ".py")
    return Path(app) / (name.replace(".", "/") + ".py")
