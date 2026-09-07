"""`frontage serve`: static files with the reload script injected, a watcher that sees a
change, and the event stream that carries it to the page."""

import http.client
import http.server
import json
import os
import threading

from frontage.cli.serve import RELOAD_PATH, Handler, Watcher, inject, make_server


def test_inject_puts_the_script_in_the_head_once():
    page = "<html><head><title>t</title></head><body></body></html>"
    out = inject(page)
    assert out.count("data-fr-reload") == 1 and out.index("data-fr-reload") < out.index("</head>")
    assert inject(out) == out
    assert inject("<p>bare</p>").endswith("</script>")


def test_watcher_sees_a_changed_new_and_deleted_file(tmp_path):
    f = tmp_path / "app.py"
    f.write_text("a")
    (tmp_path / "__pycache__").mkdir()
    w = Watcher([tmp_path])
    assert w.check() is False  # the first poll only takes the snapshot
    assert w.check() is False
    os.utime(f, ns=(1, f.stat().st_mtime_ns + 1_000_000))
    assert w.check() is True
    (tmp_path / "__pycache__" / "x.pyc").write_text("ignored")
    assert w.check() is False
    (tmp_path / "new.css").write_text("")
    assert w.check() is True
    f.unlink()
    assert w.check() is True and w.changes == 3


def test_server_injects_the_script_and_streams_a_reload(tmp_path):
    (tmp_path / "index.html").write_text("<html><head></head><body><h1>hi</h1></body></html>")
    (tmp_path / "app.py").write_text("print(1)")
    server = make_server(tmp_path, port=0, quiet=True)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/")
        r = c.getresponse()
        body = r.read().decode()
        assert r.status == 200 and "data-fr-reload" in body and "<h1>hi</h1>" in body
        assert r.getheader("Cache-Control") == "no-store"
        c.request("GET", "/app.py")
        r = c.getresponse()
        assert r.status == 200 and r.read() == b"print(1)"
        c.close()
        # The event stream: connected, then a reload when the watcher sees a change.
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", RELOAD_PATH)
        r = c.getresponse()
        assert r.status == 200 and r.getheader("Content-Type") == "text/event-stream"
        assert r.fp.readline() == b": connected\n"
        r.fp.readline()
        server.watcher.notify()
        assert r.fp.readline() == b'data: {"type":"reload"}\n'
        c.close()
    finally:
        server.shutdown()
        server.server_close()


def test_serve_command_rejects_a_missing_directory(tmp_path, capsys):
    from frontage.cli import main

    assert main(["serve", str(tmp_path / "nope")]) == 2
    assert "not a directory" in capsys.readouterr().err
    assert Handler.watcher is None  # the base class is never bound to a watcher


def test_a_changed_app_module_is_a_swap_and_anything_else_is_a_reload(tmp_path):
    """What the dev stream says. A swap keeps the interpreter; only the app's modules move."""
    from frontage.cli.serve import Handler

    class Bound(Handler):
        app_root = str(tmp_path)
        entry = "app"

    assert Bound.change_message([str(tmp_path / "app.py")]) == {
        "type": "swap",
        "modules": ["app"],
        "entry": "app",
    }
    assert Bound.change_message([str(tmp_path / "a.py"), str(tmp_path / "b.py")])["modules"] == ["a", "b"]
    # The page, a stylesheet, a nested module, and the framework itself: all reload.
    for path in ("index.html", "style.css", "pkg/mod.py"):
        assert Bound.change_message([str(tmp_path / path)]) == {"type": "reload"}
    assert Bound.change_message(["/elsewhere/frontage/view.py"]) == {"type": "reload"}
    # One unswappable file among several is enough to reload.
    assert Bound.change_message([str(tmp_path / "app.py"), str(tmp_path / "index.html")]) == {"type": "reload"}
    assert Bound.change_message([]) == {"type": "reload"}


def test_the_dev_script_swaps_only_when_the_page_boots_from_wasm():
    from frontage.cli.serve import dev_script

    wasm = dev_script('<script data-fr-boot src="./_frontage/boot.js" data-fr-entry="app"></script>')
    assert "import { ready }" in wasm and './_frontage/boot.js"' in wasm and "frontage.dev" in wasm
    # A PyScript page has no boot tag and can only reload.
    plain = dev_script("<p>hi</p>")
    assert "location.reload()" in plain and "import" not in plain


def test_the_archives_the_dev_server_synthesises(tmp_path):
    """Nothing is built in dev: both archives come off disk on request, so an edit is live."""
    import tarfile

    from frontage.cli.serve import app_archive, framework_archive

    (tmp_path / "app.py").write_text("x = 1\n")
    (tmp_path / "helpers.py").write_text("y = 2\n")
    (tmp_path / "index.html").write_text("<p>ignored</p>")
    with tarfile.open(fileobj=__import__("io").BytesIO(app_archive(tmp_path))) as tf:
        assert sorted(tf.getnames()) == ["app.py", "helpers.py"]
    with tarfile.open(fileobj=__import__("io").BytesIO(framework_archive())) as tf:
        names = tf.getnames()
    assert "frontage/view.py" in names and "frontage/dev.py" in names
    assert all(n.startswith("frontage/") for n in names)


# --- --proxy --------------------------------------------------------------------------------


class _Upstream(http.server.BaseHTTPRequestHandler):
    """A stand-in for uvicorn: JSON at /api/hello, a POST echo, a 404, and an event stream that
    sends one event, then waits for the test to release it — so a test can prove the first
    event came through *before* the upstream finished."""

    release = threading.Event()

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/api/hello"):
            body = json.dumps({"path": self.path, "accept": self.headers.get("Accept")}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Upstream", "yes")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b"data: first\n\n")
            self.wfile.flush()
            self.release.wait(5)
            self.wfile.write(b"data: second\n\n")
        else:
            self.send_error(404, "no such thing upstream")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(201)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _serve(tmp_path, proxy):
    (tmp_path / "index.html").write_text("<html><head></head><body>page</body></html>")
    server = make_server(tmp_path, port=0, quiet=True, proxy=proxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_proxy_forwards_a_prefix_with_path_query_headers_and_status(tmp_path):
    import json as _json

    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    server, port = _serve(tmp_path, [("/api", f"http://127.0.0.1:{upstream.server_address[1]}")])
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/api/hello?x=1&y=two%20words", headers={"Accept": "application/json"})
        r = c.getresponse()
        assert r.status == 200 and r.getheader("X-Upstream") == "yes"
        assert _json.loads(r.read()) == {"path": "/api/hello?x=1&y=two%20words", "accept": "application/json"}
        c.close()
        # The page itself is still the dev server's, script and all.
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/")
        r = c.getresponse()
        assert r.status == 200 and b"data-fr-reload" in r.read()
        c.close()
        # A POST with a body goes through, and so does a 404 from the upstream, as itself.
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("POST", "/api/things", body=b"payload", headers={"Content-Type": "text/plain"})
        r = c.getresponse()
        assert r.status == 201 and r.read() == b"payload"
        c.close()
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/api/missing")
        r = c.getresponse()
        assert r.status == 404 and b"no such thing upstream" in r.read()
        c.close()
        # `/apix` is not under `/api`; a POST anywhere else is still a 405.
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("POST", "/apix")
        assert c.getresponse().status == 405
        c.close()
    finally:
        server.shutdown()
        server.server_close()
        upstream.shutdown()
        upstream.server_close()


def test_proxy_streams_an_event_stream_line_by_line(tmp_path):
    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    _Upstream.release.clear()
    server, port = _serve(tmp_path, [("/api", f"http://127.0.0.1:{upstream.server_address[1]}")])
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/api/events")
        r = c.getresponse()
        assert r.status == 200 and r.getheader("Content-Type") == "text/event-stream"
        assert r.fp.readline() == b"data: first\n"  # before the upstream is done: streamed, not buffered
        _Upstream.release.set()
        r.fp.readline()
        assert r.fp.readline() == b"data: second\n"
        c.close()
    finally:
        _Upstream.release.set()
        server.shutdown()
        server.server_close()
        upstream.shutdown()
        upstream.server_close()


def test_an_unreachable_upstream_is_a_502_that_names_it(tmp_path):
    server, port = _serve(tmp_path, [("/api", "http://127.0.0.1:9")])
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", "/api/hello")
        r = c.getresponse()
        assert r.status == 502 and b"cannot reach http://127.0.0.1:9" in r.read()
        c.close()
    finally:
        server.shutdown()
        server.server_close()


def test_serve_command_rejects_a_malformed_proxy(tmp_path, capsys):
    from frontage.cli.serve import main

    assert main([str(tmp_path), "--proxy", "api=localhost:8000"]) == 2
    assert "PREFIX=URL" in capsys.readouterr().err
