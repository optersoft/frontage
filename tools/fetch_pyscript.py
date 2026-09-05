"""Fetch PyScript's offline bundle (core + Pyodide + MicroPython, no CDN) into
tools/pyscript/<version>/. Used by `mk pyscript.fetch` and by CI. Stdlib only."""

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "2026.7.3"
URL = f"https://github.com/pyscript/pyscript/releases/download/{VERSION}/offline_{VERSION}.zip"
DEST = Path(__file__).resolve().parents[1] / "tools" / "pyscript" / VERSION


def main():
    if (DEST / "pyscript" / "core.js").exists():
        print(f"pyscript {VERSION} already at {DEST}")
        return 0
    print(f"fetching {URL}")
    data = urllib.request.urlopen(URL, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # The archive has one top-level folder, `offline/`; unpack its contents into DEST.
        for member in zf.infolist():
            rel = (
                Path(member.filename).relative_to("offline")
                if member.filename.startswith("offline/")
                else Path(member.filename)
            )
            target = DEST / rel
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))
    print(f"pyscript {VERSION} unpacked to {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
