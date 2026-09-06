"""Fetch PyScript's offline bundle into tools/pyscript/<version>/ for `mk serve`, the browser
suite and `mk site.build`. The version and the fetch live in `frontage.cli.pyscript`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontage.cli.pyscript import VERSION, fetch  # noqa: E402

DEST = Path(__file__).resolve().parents[1] / "tools" / "pyscript" / VERSION

if __name__ == "__main__":
    print(f"pyscript {VERSION} at {fetch(DEST)}")
