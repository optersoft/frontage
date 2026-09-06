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
        assert r.fp.readline() == b"data: reload\n"
        c.close()
    finally:
        server.shutdown()
        server.server_close()


def test_serve_command_rejects_a_missing_directory(tmp_path, capsys):
    from frontage.cli import main

    assert main(["serve", str(tmp_path / "nope")]) == 2
    assert "not a directory" in capsys.readouterr().err
    assert Handler.watcher is None  # the base class is never bound to a watcher
