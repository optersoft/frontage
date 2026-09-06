"""PyScript's offline bundle (core + Pyodide + MicroPython, no CDN): the pinned version, and a
fetch into a directory. `python -m frontage pyscript [--dest DIR]`."""

import argparse
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import PROG
from ._cache import cache_dir

VERSION = "2026.7.3"
URL = f"https://github.com/pyscript/pyscript/releases/download/{VERSION}/offline_{VERSION}.zip"


def fetch(dest=None, quiet=False):
    """Unpack the bundle into `dest` (default: the cache) unless it is already there. Returns
    the directory that holds `core.js`."""
    dest = Path(dest) if dest is not None else cache_dir("pyscript", VERSION)
    bundle = dest / "pyscript"
    if (bundle / "core.js").exists():
        return bundle
    if not quiet:
        print(f"fetching {URL}")
    data = urllib.request.urlopen(URL, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # The archive has one top-level folder, `offline/`; unpack its contents into dest.
        for member in zf.infolist():
            name = member.filename
            rel = Path(name).relative_to("offline") if name.startswith("offline/") else Path(name)
            target = dest / rel
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))
    if not quiet:
        print(f"pyscript {VERSION} unpacked to {dest}")
    return bundle


def main(argv=None):
    parser = argparse.ArgumentParser(prog=f"{PROG} pyscript", description=__doc__)
    parser.add_argument("--dest", default=None, help="directory to unpack into (default: the frontage cache)")
    args = parser.parse_args(argv)
    bundle = fetch(args.dest)
    print(f"pyscript {VERSION} at {bundle}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
