"""The site's stylesheet: Tailwind, compiled by frontage's own command.

`web/site.tailwind.css` is the input and `web/site.css` the output, and the output is
COMMITTED. Tailwind's standalone CLI is a 100 MB download and the site is assembled on
Cloudflare's builder as well as here; a deploy that has to fetch a binary is a deploy that
breaks the first day GitHub is slow. So the normal path is a copy, and compiling is the
exception.

Staleness is not left to whoever remembers. The first line of `site.css` stamps the digest of
everything it was compiled from — the input, the two static pages, and the page template
inside `gallery.py` — so a change to any of them rebuilds it here, and a host that cannot run
Tailwind ships the committed file with a warning rather than a page with no stylesheet.

    mk site.css [--force]
"""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "web" / "site.tailwind.css"
OUTPUT = ROOT / "web" / "site.css"
PAGES = [ROOT / "web" / "index.html", ROOT / "web" / "404.html"]


def material():
    """Every text a class name can come from. The gallery contributes its template, not its
    code: a refactor there must not invalidate a stylesheet it cannot have changed."""
    from gallery import CARD, PAGE, TIMING  # local: gallery imports this module

    return "".join([INPUT.read_text(), PAGE, CARD, TIMING, *(p.read_text() for p in PAGES)])


def stamp():
    return f"/* built by mk site.css from {hashlib.sha256(material().encode()).hexdigest()[:12]} */"


def build(force=False, quiet=False):
    """Compile `web/site.css` if it is missing or stale. Returns whether it is now current."""
    mark = stamp()
    if not force and OUTPUT.exists() and OUTPUT.read_text(errors="replace").startswith(mark):
        return True
    if not force and not quiet:
        print("site.css is stale: rebuilding it", file=sys.stderr)
    code = subprocess.call(
        [sys.executable, "-m", "frontage", "tailwind", "--input", str(INPUT), "--output", str(OUTPUT), "--minify"],
        cwd=ROOT,
    )
    if code == 0:
        OUTPUT.write_text(f"{mark}\n{OUTPUT.read_text()}")
        return True
    if OUTPUT.exists():
        print("tailwind failed: keeping the committed site.css, which may be stale", file=sys.stderr)
        return False
    raise SystemExit("tailwind failed and there is no committed web/site.css")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mk site.css", description=__doc__)
    parser.add_argument("--force", action="store_true", help="recompile even when the stamp matches")
    args = parser.parse_args(argv)
    build(force=args.force)
    print(f"{OUTPUT.relative_to(ROOT)}: {OUTPUT.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
