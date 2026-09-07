"""`frontage serve [DIR]`: a development server that reloads the page when a file changes,
and forwards `--proxy PREFIX=URL` requests to a server half on another port.

Serves `DIR` (the current directory by default) with nothing cached, and every HTML page it
sends carries a few lines of script that listen on `/__frontage/reload`. A thread polls the
files under `DIR` (and any `--watch` directory); when one changes, every open page reloads.
That is what Vite does for a JavaScript app, minus the module swap: a PyScript page is one
interpreter that has to boot again, so the page reloads whole, and the browser keeps its
scroll position. Stdlib only; `python -m http.server` with a watcher."""

import argparse
import functools
import http.server
import io
import json
import os
import queue
import re
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import PROG

RELOAD_PATH = "/__frontage/reload"
MODULE_PATH = "/__frontage/module/"
RUNTIME_PREFIX = "/_frontage/"

# A page with no boot tag (a PyScript page, 0.9.x) can only reload.
RELOAD_SCRIPT = (
    '<script data-fr-reload>(function(){var s=new EventSource("'
    + RELOAD_PATH
    + '");s.onmessage=function(e){location.reload()}})();</script>'
)

# A wasm page can do better: keep the interpreter, replace the app's modules, mount again.
# It imports the *same* module URL the page booted from, so it gets that live instance.
SWAP_SCRIPT = """<script type="module" data-fr-reload>
import {{ ready }} from "{boot}";
const stream = new EventSource("{reload}");
stream.onmessage = async (event) => {{
  let message;
  try {{ message = JSON.parse(event.data); }} catch {{ return location.reload(); }}
  if (message.type !== "swap") return location.reload();
  try {{
    const mp = await ready;
    for (const name of message.modules) {{
      const source = await (await fetch("{module}" + name + ".py")).text();
      mp.FS.writeFile("/lib/" + name + ".py", source);
    }}
    mp.globals.set("__fr_entry", message.entry);
    mp.globals.set("__fr_names", message.modules.join(","));
    // One line, semicolons rather than newlines: this string travels through a Python
    // formatter into an HTML page into a JavaScript literal, and every newline in it is one
    // more chance for a layer to eat a backslash. One of them already did.
    mp.runPython("import frontage.dev as _d; _d.swap(__fr_entry, __fr_names.split(','))");
  }} catch (error) {{
    // Deliberately no reload. The usual failure here is a half-typed file, and `dev.swap`
    // compiles before it tears anything down, so the page on screen is still the last one
    // that worked. Reloading would replace it with the broken source and a blank page.
    console.error("frontage: swap failed, page left as it was", error);
  }}
}};
</script>"""

_BOOT_SRC = re.compile(r"""<script[^>]*\bdata-fr-boot\b[^>]*>""", re.I)
_SRC = re.compile(r"""\bsrc\s*=\s*["\']([^"\']+)["\']""", re.I)
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

    def notify(self, paths=()):
        """Wake every subscriber with the paths that changed (empty means "something did")."""
        self.changes += 1
        with self._lock:
            for q in self._subscribers:
                q.put(list(paths))

    def check(self):
        """One poll: True when something changed since the last one."""
        now = self.snapshot()
        changed = self._snapshot is not None and now != self._snapshot
        if changed:
            before = self._snapshot or {}
            touched = [p for p in now if before.get(p) != now[p]]
            touched += [p for p in before if p not in now]
        self._snapshot = now
        if changed:
            self.notify(sorted(touched))
        return changed

    def run(self):
        self._snapshot = self.snapshot()
        while True:
            time.sleep(self.interval)
            try:
                self.check()
            except Exception:
                pass


def dev_script(html):
    """The script this page needs: a module swap if it boots from wasm, else a page reload."""
    tag = _BOOT_SRC.search(html)
    src = _SRC.search(tag.group(0)) if tag else None
    if src is None:
        return RELOAD_SCRIPT
    return SWAP_SCRIPT.format(boot=src.group(1), reload=RELOAD_PATH, module=MODULE_PATH)


def inject(html):
    """`html` with the dev script before `</head>` (or `</body>`, or at the end)."""
    if "data-fr-reload" in html:
        return html
    script = dev_script(html)
    for tag in ("</head>", "</body>"):
        i = html.find(tag)
        if i >= 0:
            return html[:i] + script + html[i:]
    return html + script


def _tar(members):
    """`[(name, bytes)]` as an uncompressed USTAR archive, the shape `boot.js` unpacks."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def app_archive(root):
    """The app's modules, straight off disk. Nothing is built in dev: an edit is live."""
    return _tar([(p.name, p.read_bytes()) for p in sorted(Path(root).glob("*.py"))])


def framework_archive():
    """The framework as *source*, so a checkout's edits reach the page on the next reload.

    A built site gets the precompiled `frontage.tar` instead; here the loop matters more than
    the 35 ms, and this is what `tools/serve.py` has always done with `/frontage/*.py`.
    """
    from . import micropython as mp

    return _tar([("frontage/" + p.name, p.read_bytes()) for p in mp.browser_modules()])


class Handler(http.server.SimpleHTTPRequestHandler):
    """Static files, uncached, with the reload script in every HTML page and the event stream
    the script listens on. Subclasses (`tools/serve.py`) override `translate_path`."""

    watcher = None
    quiet = False
    app_root = None  # where the app's .py files live; set by `make_server`
    entry = None  # the module that mounts, so a swap knows what to re-run
    proxies = ()  # (prefix, upstream) pairs: `--proxy /api=http://127.0.0.1:8000`

    def _upstream(self):
        route = self.path.split("?", 1)[0]
        for prefix, upstream in self.proxies:
            if route == prefix or route.startswith(prefix.rstrip("/") + "/"):
                return upstream
        return None

    def do_POST(self):
        self._proxy_or(405)

    def do_PUT(self):
        self._proxy_or(405)

    def do_PATCH(self):
        self._proxy_or(405)

    def do_DELETE(self):
        self._proxy_or(405)

    def _proxy_or(self, status):
        if self._upstream() is not None:
            self._proxy()
        else:
            self.send_error(status)

    def _proxy(self):
        """Forward this request to the upstream that owns its prefix, path and query intact,
        and stream the answer back — line by line for an event stream, so a server's push
        reaches the page through the dev server the way it will through a production proxy.

        This is the dev loop for an app with a server half (`frontage-polars`): the page comes
        from here, with its module swap, and `/api` goes to uvicorn on another port, from the
        same origin, so there is no CORS to get wrong in development and not in production."""
        upstream = self._upstream()
        url = upstream.rstrip("/") + self.path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in ("host", "connection", "accept-encoding", "content-length")
        }
        request = urllib.request.Request(url, data=body, method=self.command, headers=headers)
        try:
            response = urllib.request.urlopen(request)  # noqa: S310  (the URL is the developer's own flag)
        except urllib.error.HTTPError as exc:
            response = exc  # a 4xx/5xx from the upstream is still its answer; relay it as-is
        except (urllib.error.URLError, OSError) as exc:
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                f"frontage serve: cannot reach {upstream} for {self.path} ({exc.reason if hasattr(exc, 'reason') else exc})\n".encode()
            )
            return
        with response:
            self.send_response(response.status)
            streaming = (response.headers.get("Content-Type") or "").startswith("text/event-stream")
            for key, value in response.headers.items():
                if key.lower() in ("connection", "transfer-encoding", "keep-alive", "content-encoding"):
                    continue
                if streaming and key.lower() == "content-length":
                    continue
                self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                if streaming:
                    for line in response:
                        self.wfile.write(line)
                        self.wfile.flush()
                else:
                    while chunk := response.read(65536):
                        self.wfile.write(chunk)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if self._upstream() is not None:
            self._proxy()
            return
        if route == RELOAD_PATH:
            self._stream()
            return
        if route.startswith(MODULE_PATH):
            self._send_module(route[len(MODULE_PATH) :])
            return
        at = route.find(RUNTIME_PREFIX)
        if at >= 0:
            # `_frontage/` anywhere, not only at the root: the app it belongs to is whatever
            # directory holds it, so one server can carry many apps (the examples tree) with
            # the same relative boot tag a built app uses.
            self._send_runtime(route[at + len(RUNTIME_PREFIX) :], route[: at + 1])
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

    def _send_bytes(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_module(self, name):
        """One app module's source, by module name, for a swap."""
        root = Path(self.app_root or self.translate_path("/"))  # a swap only runs on a single-app server
        candidate = root / name
        if candidate.suffix != ".py" or candidate.parent != root or not candidate.is_file():
            self.send_error(404)
            return
        self._send_bytes(candidate.read_bytes(), "text/x-python; charset=utf-8")

    def _send_runtime(self, name, prefix="/"):
        """`_frontage/*`, in one order: what is on disk, then what we can build, then the
        package's copy.

        Disk first, because a *built* directory already holds everything — including a
        component's assets and an `app.tar` that carries its Python. Synthesising over the top
        would silently serve a different app than the one `build` produced, which is how the
        first component ever built here failed to import.

        With nothing on disk we are serving sources, so the archives are made on the spot from
        whatever is there: that is the dev loop, where an edit needs no build step.
        """
        from . import micropython as mp

        try:
            on_disk = Path(self.translate_path(f"{prefix}{RUNTIME_PREFIX.strip('/')}/{name}"))
            if on_disk.is_file():
                self._send_bytes(on_disk.read_bytes(), self.guess_type(str(on_disk)))
                return
            if name == "app.tar":
                # The directory the request came from, never a configured root: one server can
                # carry several apps, and `/examples/todo/_frontage/app.tar` must be the todo one.
                self._send_bytes(app_archive(self.translate_path(prefix)), "application/x-tar")
                return
            if name == mp.IMAGE_NAME:
                self._send_bytes(framework_archive(), "application/x-tar")
                return
            asset = mp.RUNTIME_DIR / name
            if "/" in name or not asset.is_file():
                self.send_error(404)
                return
            # `guess_type`, not `extensions_map.get`: that dict is a few overrides, not a mime
            # database, and a `.css` served as octet-stream is silently refused by the browser.
            self._send_bytes(asset.read_bytes(), self.guess_type(str(asset)))
        except OSError:
            self.send_error(404)

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        watcher = self.watcher
        if watcher is None:
            self.wfile.write(b'data: {"type":"reload"}\n\n')  # no watcher: nothing will ever change
            return
        q = watcher.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    paths = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                else:
                    message = self.change_message(paths)
                    self.wfile.write(f"data: {json.dumps(message, separators=(',', ':'))}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            watcher.unsubscribe(q)

    @classmethod
    def change_message(cls, paths):
        """What to tell the page about `paths`.

        An app module swaps. Anything else -- the page itself, a stylesheet, a file under
        `frontage/` -- reloads, because the framework's own module objects are what the live
        page is holding, and replacing those under it means two frameworks at once.
        """
        # A swap needs to know which module to re-run. Without an entry -- a server carrying
        # many apps, like the examples tree -- the honest answer is a reload.
        root = Path(cls.app_root) if cls.app_root and cls.entry else None
        if root is None or not paths:
            return {"type": "reload"}
        modules = []
        for path in paths:
            candidate = Path(path)
            if candidate.suffix == ".py" and candidate.parent == root:
                modules.append(candidate.stem)
            else:
                return {"type": "reload"}
        if not modules:
            return {"type": "reload"}
        return {"type": "swap", "modules": sorted(set(modules)), "entry": cls.entry}

    def handle(self):
        try:
            http.server.SimpleHTTPRequestHandler.handle(self)
        except (ConnectionResetError, BrokenPipeError):
            pass  # a page closed its event stream; nothing to report

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        # What `web/_headers` says in production. A sandboxed frame runs in an opaque origin,
        # so even its own-origin fetches arrive as `Origin: null`; without this, `runner.html`
        # works when served by Pages and not when served here, which is the worst way round.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        # Workers with SharedArrayBuffer need cross-origin isolation; harmless otherwise.
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        http.server.SimpleHTTPRequestHandler.end_headers(self)

    def log_message(self, format, *args):
        if not self.quiet:
            http.server.SimpleHTTPRequestHandler.log_message(self, format, *args)


Handler.extensions_map.update({".wasm": "application/wasm", ".mjs": "text/javascript", ".js": "text/javascript"})


def make_server(
    directory, host="127.0.0.1", port=8000, watch=(), handler=Handler, quiet=False, app_root=None, entry=None, proxy=()
):
    """A `ThreadingHTTPServer` serving `directory` with live reload; its watcher is started.
    `watch` names the directories to poll; the served one when it is empty. `proxy` is a list
    of `(prefix, upstream)` pairs: requests under `prefix` are forwarded to `upstream`.

    `app_root` is where the app's modules live (the served directory by default) and `entry`
    is the one that mounts. Together they are what lets a change become a module swap rather
    than a page reload."""
    directory = Path(directory).resolve()
    watcher = Watcher(list(watch) or [directory])
    watcher.start()

    class Bound(handler):
        pass

    Bound.watcher = watcher
    Bound.quiet = quiet
    Bound.app_root = str(Path(app_root).resolve()) if app_root else str(directory)
    Bound.entry = entry
    Bound.proxies = tuple(proxy)
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
    parser.add_argument("--entry", default="", help="the module that mounts (default: inferred)")
    parser.add_argument(
        "--proxy",
        action="append",
        default=[],
        metavar="PREFIX=URL",
        help="forward requests under PREFIX to URL, e.g. /api=http://127.0.0.1:8000 (repeatable)",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    proxies = []
    for spec in args.proxy:
        prefix, sep, upstream = spec.partition("=")
        if not sep or not prefix.startswith("/") or not upstream.startswith(("http://", "https://")):
            print(f"error: --proxy wants PREFIX=URL, like /api=http://127.0.0.1:8000, not {spec!r}", file=sys.stderr)
            return 2
        proxies.append((prefix, upstream))
    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"error: {directory} is not a directory", file=sys.stderr)
        return 2
    for extra in args.watch:
        if not Path(extra).exists():
            print(f"error: --watch {extra} does not exist", file=sys.stderr)
            return 2
    # Knowing which module mounts is what turns a save into a swap instead of a reload. It is
    # inferred the same way `build` infers it, and a directory it cannot read is not an error
    # here: the page simply reloads, as it always did.
    entry = args.entry
    if not entry:
        from .build import find_entry

        try:
            entry = find_entry(directory)
        except SystemExit:
            entry = ""
    try:
        server = make_server(
            directory, args.host, args.port, watch=args.watch, quiet=args.quiet, entry=entry or None, proxy=proxies
        )
    except OSError as exc:
        print(f"error: cannot listen on {args.host}:{args.port} ({exc})", file=sys.stderr)
        return 2
    url = f"http://{args.host}:{args.port}/"
    if not args.quiet:
        how = f"swaps {entry}.py in place" if entry else "reloads the page"
        print(f"serving {directory.resolve()} on {url}  ({how} when a file changes)")
        for prefix, upstream in proxies:
            print(f"  {prefix} -> {upstream}")
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
