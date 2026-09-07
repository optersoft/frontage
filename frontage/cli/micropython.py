"""`python -m frontage runtime`: the MicroPython WebAssembly runtime, and the framework
image the browser imports instead of parsing sixteen `.py` files.

Two jobs, both for maintainers rather than users — a released wheel already carries the
results in `frontage/_runtime/`:

`fetch`  downloads the pinned upstream build from npm and keeps `micropython.mjs` and
         `micropython.wasm`. It is the *same* build PyScript shipped, byte for byte, which is
         why 0.9.0 changed the delivery without changing the interpreter under it.
`image`  cross-compiles the package's browser modules to `.mpy` and packs them in one tar.
         Needs `mpy-cross-v6.3` (dev group, never a runtime dependency).

The tar may hold `.mpy` or `.py` — MicroPython imports either from the filesystem — so a
checkout with no mpy-cross still builds a working app, just one that parses at boot.
"""

import argparse
import io
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from . import PROG

# The pin. Bumping it is this line plus a browser run, the way the PyScript pin worked.
# `1.28.0-6` is MicroPython v1.28.0-6.g974b56afa6: the first release with PEP 750 t-strings,
# and the build PyScript 2026.7.3 shipped.
VERSION = "1.28.0-6"
PACKAGE = "@micropython/micropython-webassembly-pyscript"
URL = f"https://registry.npmjs.org/{PACKAGE}/-/micropython-webassembly-pyscript-{VERSION}.tgz"

# The npm tarball carries four wasm builds; these two are the ones we want. The settrace and
# ulab variants are 1.8 MB of things frontage does not use.
WANTED = ("micropython.mjs", "micropython.wasm")

# Where the vendored runtime lives inside the package.
RUNTIME_DIR = Path(__file__).resolve().parent.parent / "_runtime"

IMAGE_NAME = "frontage.tar"


def fetch(dest=None, quiet=False):
    """The pinned `micropython.mjs` + `.wasm` in `dest`, downloaded on first use."""
    dest = Path(dest) if dest else RUNTIME_DIR
    dest.mkdir(parents=True, exist_ok=True)
    if all((dest / name).exists() for name in WANTED):
        return dest
    if not quiet:
        print(f"fetching {URL}")
    blob = urllib.request.urlopen(URL, timeout=300).read()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for name in WANTED:
            member = tf.extractfile(f"package/{name}")
            if member is None:
                raise RuntimeError(f"{name} missing from {URL}")
            (dest / name).write_bytes(member.read())
    return dest


def browser_modules(package=None):
    """The package files the browser imports: the top-level modules, minus `__main__.py`.

    `cli/` and `lsp/` are CPython-only and never ship. `debug.py` does ship — it is imported
    lazily, by an app that wants the hydration report.
    """
    package = Path(package) if package else Path(__file__).resolve().parent.parent
    return sorted(p for p in package.glob("*.py") if p.name != "__main__.py")


def _mpy_cross():
    """The cross-compiler, or None if it is not installed (a checkout without the dev group)."""
    try:
        import mpy_cross_v6_3
    except ImportError:
        return None
    return str(mpy_cross_v6_3.MPY_CROSS_PATH)


def image(dest=None, package=None, quiet=False):
    """Write `frontage.tar`: the browser modules, compiled if mpy-cross is here.

    Returns `(path, compiled)`. `compiled` is False when the tar holds sources, which boots
    correctly and about 35 ms slower — the difference the whole 0.9.0 change is about.
    """
    dest = Path(dest) if dest else RUNTIME_DIR
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / IMAGE_NAME
    modules = browser_modules(package)
    mpy = _mpy_cross()

    with tempfile.TemporaryDirectory() as tmp:
        members = []
        for src in modules:
            if mpy is None:
                members.append((f"frontage/{src.name}", src))
                continue
            built = Path(tmp) / (src.stem + ".mpy")
            # -O2 drops asserts and __debug__ blocks; -s gives a traceback the real file name
            # instead of the temporary path, which `format_exception` then shows the user.
            run = subprocess.run(
                [mpy, "-O2", "-s", f"frontage/{src.name}", "-o", str(built), str(src)],
                capture_output=True,
                text=True,
            )
            if run.returncode:
                detail = (run.stderr or run.stdout).strip().splitlines()
                raise RuntimeError(f"mpy-cross failed on {src.name}: {detail[-1] if detail else '?'}")
            members.append((f"frontage/{built.name}", built))

        with tarfile.open(out, "w", format=tarfile.USTAR_FORMAT) as tf:
            for name, path in members:
                info = tarfile.TarInfo(name)
                info.size = path.stat().st_size
                info.mtime = 0  # reproducible: the same sources give the same bytes
                with path.open("rb") as fh:
                    tf.addfile(info, fh)

    if not quiet:
        kind = "bytecode" if mpy else "sources (no mpy-cross: pip install mpy-cross-v6.3)"
        raw = sum(p.stat().st_size for p in modules)
        print(f"{out}: {len(modules)} modules, {out.stat().st_size:,} bytes of {kind} (source {raw:,})")
    return out, mpy is not None


def main(argv=None):
    parser = argparse.ArgumentParser(prog=f"{PROG} runtime", description=__doc__)
    parser.add_argument("action", choices=("fetch", "image", "all"), help="what to do")
    parser.add_argument("--dest", default="", help=f"where to write (default: {RUNTIME_DIR})")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    dest = Path(args.dest) if args.dest else RUNTIME_DIR
    if args.action in ("fetch", "all"):
        where = fetch(dest, quiet=args.quiet)
        if not args.quiet:
            print(f"{where}: micropython {VERSION}")
    if args.action in ("image", "all"):
        _, compiled = image(dest, quiet=args.quiet)
        if not compiled:
            print("warning: the image holds sources, not bytecode", file=sys.stderr)
    return 0
