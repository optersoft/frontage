"""Where downloaded tools live: `$FRONTAGE_CACHE`, else `$XDG_CACHE_HOME/frontage`, else
`~/.cache/frontage`."""

import os
from pathlib import Path


def cache_dir(*parts):
    root = os.environ.get("FRONTAGE_CACHE")
    if not root:
        root = os.path.join(os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache"), "frontage")
    path = Path(root).joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
