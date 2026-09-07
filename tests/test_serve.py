"""`frontage serve`: static files with the reload script injected, a watcher that sees a
change, and the event stream that carries it to the page."""

import http.client
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
