"""Serve the repo for the browser tests and `mk serve`: examples at /examples/, the
package at /frontage/ (read live, so an edit shows on reload), and the local PyScript
bundle at /pyscript/. Everything else 404s. Nothing is cached."""

import argparse
import http.server
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pyscript_dir():
    versions = sorted(ROOT.glob("tools/pyscript/*/pyscript"))
    return versions[-1] if versions else None


class Handler(http.server.SimpleHTTPRequestHandler):
    routes = {
        "/examples/": ROOT / "examples",
        "/frontage/": ROOT / "frontage",
        "/playground/": ROOT / "web" / "playground",
        "/build/": ROOT / "build",  # `python -m frontage prerender` output, for the browser tests
    }
    quiet = False

    def translate_path(self, path):
        path = path.split("?", 1)[0].split("#", 1)[0]
        # PyScript's offline mode resolves its interpreters as ./pyscript/<name>/… relative to
        # the *page*, so the bundle must answer at that path under every example directory
        # too. The site does the same with a _redirects rule (see Makefile.py site_build).
        if "/pyscript/" in path:
            base = pyscript_dir()
            return str(base / path.split("/pyscript/", 1)[1]) if base else "/nonexistent"
        for prefix, base in self.routes.items():
            if path.startswith(prefix):
                return str(base / path[len(prefix) :])
        return "/nonexistent"

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        # Workers with SharedArrayBuffer need cross-origin isolation; harmless otherwise.
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        super().end_headers()

    def log_message(self, fmt, *args):
        if not self.quiet:
            super().log_message(fmt, *args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    Handler.quiet = args.quiet
    Handler.extensions_map.update({".wasm": "application/wasm", ".mjs": "text/javascript", ".js": "text/javascript"})
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as httpd:
        if not args.quiet:
            print(f"serving on http://127.0.0.1:{args.port}/examples/  (pyscript: {pyscript_dir() or 'NOT FETCHED'})")
        sys.stdout.flush()
        httpd.serve_forever()
