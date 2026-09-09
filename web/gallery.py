"""The measured gallery, as `tools/gallery.py` writes it.

`mk gallery` builds every app with the real command, loads each cold in Chromium and writes
`web/data/gallery.json` (gitignored) beside the apps it put in `www/gallery/`. This module
reads it; the page renders it. Absent — `frontage site` before `mk gallery` has run — the
page says so rather than failing the build.
"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "gallery.json"


def gallery():
    if not DATA.is_file():
        return None
    return json.loads(DATA.read_text())
