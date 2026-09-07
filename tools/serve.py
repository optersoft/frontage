"""Serve the repo for the browser tests and `mk serve`: examples at /examples/, the playground
at /playground/, prerendered output at /build/. Everything else 404s. Nothing is cached, and
the page reloads by itself when a file under examples/, frontage/ or web/ changes.

The WebAssembly runtime answers under every directory, at `<dir>/_frontage/…`, which is where
a built app's boot tag points too. `frontage.cli.serve` builds both archives on the spot from
whatever is on disk — the framework from `frontage/*.py`, the app from that directory — so an
edit to either shows on the next reload with nothing to rebuild.

One server carries many apps here, so a change reloads the page rather than swapping a module:
a swap has to know which module mounts, and on this tree that depends on the page you happen
to be looking at. `frontage serve <one app>` swaps."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from frontage.cli.serve import Handler as LiveHandler  # noqa: E402
from frontage.cli.serve import make_server  # noqa: E402


class Handler(LiveHandler):
    routes = {
        "/examples/": ROOT / "examples",
        "/frontage/": ROOT / "frontage",
        "/playground/": ROOT / "web" / "playground",
        "/web/": ROOT / "web",  # `runner.html`, which the browser suite embeds as a frame
        "/build/": ROOT / "build",  # `python -m frontage prerender` output, for the browser tests
        "/profile/": ROOT / "tools" / "profile",  # the rows profile page (tools/profile_rows.py)
    }

    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        for prefix, base in self.routes.items():
            if path.startswith(prefix):
                return str(base / path[len(prefix) :])
        return "/nonexistent"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    watch = [ROOT / "examples", ROOT / "frontage", ROOT / "web" / "playground"]
    with make_server(ROOT, port=args.port, watch=watch, handler=Handler, quiet=args.quiet) as httpd:
        if not args.quiet:
            print(f"serving on http://127.0.0.1:{args.port}/examples/")
        sys.stdout.flush()
        httpd.serve_forever()
