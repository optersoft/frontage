"""`frontage serve [DIR]`: a development server that reloads the page when a file changes.

Serves `DIR` (the current directory by default) with nothing cached, and every HTML page it
sends carries a few lines of script that listen on `/__frontage/reload`. A thread polls the
files under `DIR` (and any `--watch` directory); when one changes, every open page reloads.
That is what Vite does for a JavaScript app, minus the module swap: a PyScript page is one
interpreter that has to boot again, so the page reloads whole, and the browser keeps its
scroll position. Stdlib only; `python -m http.server` with a watcher."""

import argparse
import functools
import http.server
import os
import queue
import sys
import threading
import time
from pathlib import Path

from . import PROG

RELOAD_PATH = "/__frontage/reload"
RELOAD_SCRIPT = (
    '<script data-fr-reload>(function(){var s=new EventSource("'
    + RELOAD_PATH
    + '");s.onmessage=function(e){if(e.data==="reload")location.reload()}})();</script>'
)
SKIP_DIRS = {"__pycache__", ".git", ".hg", ".venv", "node_modules", ".mypy_cache", ".ruff_cache", ".pytest_cache"}


class Watcher(threading.Thread):
    """Polls the files under `roots`; a change (content, a new file, a deleted one) wakes
    every subscriber. Polling, not inotify/FSEvents: the stdlib has neither, and a scan of
    an app directory every third of a second is nothing."""

    def __init__(self, roots, interval=0.3):
        threading.Thread.__init__(self, daemon=True)
        self.roots = [Path(r) for r in roots]
        self.interval = interval
        self._subscribers = set()
        self._lock = threading.Lock()
        self._snapshot = None
        self.changes = 0  # how many times a change was seen (tests)

    def snapshot(self):
        seen = {}
        for root in self.roots:
            if root.is_file():
                try:
                    seen[str(root)] = root.stat().st_mtime_ns
                except OSError:
                    pass
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
                for name in filenames:
                    if name.endswith((".pyc", ".swp", ".tmp")) or name.startswith(".#"):
                        continue
                    path = os.path.join(dirpath, name)
                    try:
                        seen[path] = os.stat(path).st_mtime_ns
                    except OSError:
                        pass
        return seen

    def subscribe(self):
        q = queue.Queue()
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subscribers.discard(q)

    def notify(self):
        self.changes += 1
        with self._lock:
            for q in self._subscribers:
                q.put("reload")

    def check(self):
        """One poll: True when something changed since the last one."""
        now = self.snapshot()
        changed = self._snapshot is not None and now != self._snapshot
        self._snapshot = now
        if changed:
            self.notify()
        return changed

    def run(self):
        self._snapshot = self.snapshot()
        while True:
            time.sleep(self.interval)
            try:
                self.check()
            except Exception:
                pass


def inject(html):
    """`html` with the reload script before `</head>` (or `</body>`, or at the end)."""
    if "data-fr-reload" in html:
        return html
    for tag in ("</head>", "</body>"):
        i = html.find(tag)
        if i >= 0:
            return html[:i] + RELOAD_SCRIPT + html[i:]
    return html + RELOAD_SCRIPT


class Handler(http.server.SimpleHTTPRequestHandler):
    """Static files, uncached, with the reload script in every HTML page and the event stream
    the script listens on. Subclasses (`tools/serve.py`) override `translate_path`."""

    watcher = None
    quiet = False

    def do_GET(self):
        if self.path.split("?", 1)[0] == RELOAD_PATH:
            self._stream()
            return
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            index = os.path.join(path, "index.html")
            if os.path.isfile(index) and self.path.split("?", 1)[0].endswith("/"):
                path = index
        if path.endswith((".html", ".htm")) and os.path.isfile(path):
            self._send_html(path)
            return
        http.server.SimpleHTTPRequestHandler.do_GET(self)

    def _send_html(self, path):
        try:
            with open(path, encoding="utf-8") as f:
                body = inject(f.read()).encode("utf-8")
        except (OSError, UnicodeDecodeError):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        watcher = self.watcher
        if watcher is None:
            self.wfile.write(b"data: reload\n\n")  # no watcher: nothing will ever change
            return
        q = watcher.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    message = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                else:
                    self.wfile.write(f"data: {message}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            watcher.unsubscribe(q)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        # Workers with SharedArrayBuffer need cross-origin isolation; harmless otherwise.
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        http.server.SimpleHTTPRequestHandler.end_headers(self)

    def log_message(self, format, *args):
        if not self.quiet:
            http.server.SimpleHTTPRequestHandler.log_message(self, format, *args)


Handler.extensions_map.update({".wasm": "application/wasm", ".mjs": "text/javascript", ".js": "text/javascript"})


def make_server(directory, host="127.0.0.1", port=8000, watch=(), handler=Handler, quiet=False):
    """A `ThreadingHTTPServer` serving `directory` with live reload; its watcher is started.
    `watch` names the directories to poll; the served one when it is empty."""
    directory = Path(directory).resolve()
    watcher = Watcher(list(watch) or [directory])
    watcher.start()

    class Bound(handler):
        pass

    Bound.watcher = watcher
    Bound.quiet = quiet
    # The plain handler serves `directory`; a subclass with its own `translate_path` needs none.
    factory = functools.partial(Bound, directory=str(directory)) if handler is Handler else Bound
    server = http.server.ThreadingHTTPServer((host, port), factory)  # ty: ignore[invalid-argument-type]
    server.daemon_threads = True
    server.watcher = watcher  # ty: ignore[unresolved-attribute]
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(prog=f"{PROG} serve", description=__doc__)
    parser.add_argument("dir", nargs="?", default=".", help="the directory to serve (default: .)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to reach it from a phone on the same network")
    parser.add_argument("--watch", action="append", default=[], help="another directory to watch (repeatable)")
    parser.add_argument("--open", action="store_true", help="open the page in the browser")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"error: {directory} is not a directory", file=sys.stderr)
        return 2
    for extra in args.watch:
        if not Path(extra).exists():
            print(f"error: --watch {extra} does not exist", file=sys.stderr)
            return 2
    try:
        server = make_server(directory, args.host, args.port, watch=args.watch, quiet=args.quiet)
    except OSError as exc:
        print(f"error: cannot listen on {args.host}:{args.port} ({exc})", file=sys.stderr)
        return 2
    url = f"http://{args.host}:{args.port}/"
    if not args.quiet:
        print(f"serving {directory.resolve()} on {url}  (reloads the page when a file changes)")
        sys.stdout.flush()
    if args.open:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
