"""`python -m frontage runtime`: the MicroPython WebAssembly runtime, and the framework
image the browser imports instead of parsing sixteen `.py` files.

Three jobs, all for maintainers rather than users — a released wheel already carries the
results in `frontage/_runtime/`:

`build`  compiles the interpreter: upstream MicroPython at the pinned tag, the port's
         `webassembly` target, with frontage's own variant (`tools/micropython/variant/`)
         applied out of tree. Runs in Docker (`emscripten/emsdk`, pinned), takes a minute.
         The variant is why a page pays 108 KB of brotli for the interpreter instead of
         170, and why a Python call costs 0.05 µs instead of 0.25: see FASTER.md §2.
`fetch`  the fallback: downloads the upstream npm build — the one PyScript ships — for a
         checkout without Docker. It boots the same apps, bigger and slower.
`image`  cross-compiles the package's browser modules to `.mpy` and packs them in one tar.
         Needs `mpy-cross-v6.3` (dev group, never a runtime dependency).

The tar may hold `.mpy` or `.py` — MicroPython imports either from the filesystem — so a
checkout with no mpy-cross still builds a working app, just one that parses at boot.
"""

import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from . import PROG

# The pin: an upstream git tag, built by `build`. Bumping it is this line, a `build`, and a
# browser run. `v1.28.0` was the first release with PEP 750 t-strings.
UPSTREAM_TAG = "v1.29.0"
UPSTREAM_REPO = "https://github.com/micropython/micropython.git"

# The Emscripten toolchain the interpreter is built with, as a Docker image. Pinned because
# the binary's size and speed are a property of the compiler as much as of the source.
EMSDK_IMAGE = "emscripten/emsdk:6.0.9"

# The npm build `fetch` falls back to: MicroPython's own package, the build PyScript ships.
VERSION = "1.29.0-6"
PACKAGE = "@micropython/micropython-webassembly-pyscript"
URL = f"https://registry.npmjs.org/{PACKAGE}/-/micropython-webassembly-pyscript-{VERSION}.tgz"

# The two files a page loads. The npm tarball carries four wasm builds; the settrace and
# ulab variants are 1.8 MB of things frontage does not use.
WANTED = ("micropython.mjs", "micropython.wasm")

# Where the vendored runtime lives inside the package.
RUNTIME_DIR = Path(__file__).resolve().parent.parent / "_runtime"

# The variant, in the repository (not in the wheel): `mpconfigvariant.h`, `.mk`, `manifest.py`.
VARIANT_DIR = RUNTIME_DIR.parent.parent / "tools" / "micropython" / "variant"

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


def _cache_dir():
    from ._cache import cache_dir

    return cache_dir()


def checkout(tag=UPSTREAM_TAG, quiet=False):
    """Upstream MicroPython at `tag`, with the port's submodules, in the frontage cache.

    A shallow clone of one tag: the build needs the tree, not the history. The checkout is
    never modified beyond one line (see `build`), so a second build reuses it as is.
    """
    root = _cache_dir() / f"micropython-{tag}"
    if not (root / "ports" / "webassembly" / "Makefile").exists():
        if not quiet:
            print(f"cloning {UPSTREAM_REPO} at {tag}")
        shutil.rmtree(root, ignore_errors=True)
        subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", "--branch", tag, UPSTREAM_REPO, str(root)],
            check=True,
        )
    return root


def _patch_longjmp(port):
    """The one line the variant cannot reach: the port appends `SUPPORT_LONGJMP=emscripten`
    to JSFLAGS *after* including the variant, and the last `-s` wins."""
    makefile = port / "Makefile"
    text = makefile.read_text()
    patched = text.replace("-s SUPPORT_LONGJMP=emscripten", "-s SUPPORT_LONGJMP=wasm")
    if patched != text:
        makefile.write_text(patched)


def build(dest=None, quiet=False, tag=UPSTREAM_TAG, image=EMSDK_IMAGE, c_modules=None):
    """Compile `micropython.mjs` + `.wasm` with the frontage variant, into `dest`.

    `c_modules` is a directory of MicroPython user C modules to compile in (the framework's
    C core, when it exists). Docker is the only requirement; the toolchain lives in the
    image, so the build is the same on every machine that has it.
    """
    dest = Path(dest) if dest else RUNTIME_DIR
    dest.mkdir(parents=True, exist_ok=True)
    if shutil.which("docker") is None:
        raise RuntimeError("docker is needed to build the interpreter (or use `runtime fetch` for the upstream build)")
    root = checkout(tag, quiet=quiet)
    port = root / "ports" / "webassembly"
    _patch_longjmp(port)

    mounts = ["-v", f"{root}:/src", "-v", f"{VARIANT_DIR}:/variant"]
    make = "make -C ports/webassembly VARIANT_DIR=/variant"
    if c_modules:
        mounts += ["-v", f"{Path(c_modules).resolve()}:/cmodules"]
        make += " USER_C_MODULES=/cmodules"
    jobs = os.cpu_count() or 4
    script = (
        # The clone is owned by the host user; git inside the container refuses it otherwise.
        "git config --global --add safe.directory '*' && "
        "make -C ports/webassembly submodules >/dev/null && "
        "make -C mpy-cross >/dev/null && "
        f"{make} -j{jobs}"
    )
    if not quiet:
        print(f"building micropython {tag} in {image}")
    run = subprocess.run(
        ["docker", "run", "--rm", *mounts, "-w", "/src", image, "bash", "-c", script],
        capture_output=quiet,
        text=True,
    )
    if run.returncode:
        detail = (run.stderr or "").strip().splitlines()
        raise RuntimeError(f"the interpreter build failed: {detail[-1] if detail else 'see the output above'}")
    out = port / "build-variant"
    for name in WANTED:
        shutil.copy2(out / name, dest / name)
    if not quiet:
        sizes = ", ".join(f"{name} {(dest / name).stat().st_size:,}" for name in WANTED)
        print(f"{dest}: {sizes} bytes")
    return dest


def browser_modules(package=None):
    """The package files the browser imports: the top-level modules, minus `__main__.py`.

    `cli/` and `lsp/` are CPython-only and never ship. `debug.py` does ship — it is
    imported lazily, by an app that wants the hydration report.
    """
    package = Path(package) if package else Path(__file__).resolve().parent.parent
    return sorted(p for p in package.glob("*.py") if p.name != "__main__.py")


def _is_compiled(archive):
    """True when the image holds `.mpy`, not `.py`."""
    try:
        with tarfile.open(archive) as tf:
            return any(name.endswith(".mpy") for name in tf.getnames())
    except (OSError, tarfile.TarError):
        return False


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

    if mpy is None and out.exists() and _is_compiled(out):
        # A host without mpy-cross must not replace a committed bytecode image with sources.
        # It would still work, and it would silently ship a slower framework than the one in
        # the repository — the worst kind of regression, because nothing fails.
        if not quiet:
            print(f"{out}: kept (no mpy-cross here, and the existing image is bytecode)")
        return out, True

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
    parser.add_argument("action", choices=("build", "fetch", "image", "all"), help="what to do")
    parser.add_argument("--dest", default="", help=f"where to write (default: {RUNTIME_DIR})")
    parser.add_argument("--c-modules", default="", help="a directory of user C modules to compile in")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    dest = Path(args.dest) if args.dest else RUNTIME_DIR
    try:
        if args.action == "build":
            build(dest, quiet=args.quiet, c_modules=args.c_modules or None)
        if args.action in ("fetch", "all"):
            where = fetch(dest, quiet=args.quiet)
            if not args.quiet:
                print(f"{where}: micropython {VERSION}")
        if args.action in ("image", "all"):
            _, compiled = image(dest, quiet=args.quiet)
            if not compiled:
                print("warning: the image holds sources, not bytecode", file=sys.stderr)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0
