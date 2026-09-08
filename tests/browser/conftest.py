"""The local server every browser test needs: examples at /examples/, the package at
/frontage/, and the runtime under every directory at `<dir>/_frontage/`. Session-scoped and
autouse, so any single test can run alone. Skips the whole directory when the runtime is not
vendored or its compiler cannot be found."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "frontage" / "_runtime"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session", autouse=True)
def server():

    from frontage.cli import frontage_rt

    if not frontage_rt.available():
        pytest.skip("the runtime is missing from frontage/_runtime: run `mk runtime.build`")
    frontage_rt.fpy(quiet=True)  # the compiler, or a message that says how to get one
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "tools" / "serve.py"), "--port", str(port), "--quiet"],
        cwd=ROOT,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("tools/serve.py did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait()


@pytest.fixture(scope="session")
def trips(tmp_path_factory):
    """`examples/trips`, built with the real `frontage build` and served by its own uvicorn:
    the API at /api and the page at /, one process, one port."""
    import os

    pytest.importorskip("polars")
    example = ROOT / "examples" / "trips"
    out = tmp_path_factory.mktemp("trips")
    subprocess.run([sys.executable, "-m", "frontage", "build", str(example), "--out", str(out), "--quiet"], check=True)
    assert (out / "_frontage" / "components" / "remote" / "index.js").is_file(), "the component was not discovered"
    port = _free_port()
    env = dict(os.environ, TRIPS_STATIC=str(out), TRIPS_ROWS="500000")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server:app",
            "--app-dir",
            str(example),
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=env,
    )
    deadline = time.time() + 60  # half a million rows are generated on import
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("the trips server did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait()


@pytest.fixture(scope="session")
def lazy(tmp_path_factory):
    """`examples/lazy`, built with the real `frontage build` and served as static files: a
    chunk only exists in a build, so the dev server (one archive per directory) cannot show
    one."""
    import functools
    import http.server
    import socketserver
    import threading

    out = tmp_path_factory.mktemp("lazy")
    subprocess.run(
        [sys.executable, "-m", "frontage", "build", str(ROOT / "examples" / "lazy"), "--out", str(out), "--quiet"],
        check=True,
    )

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            # `?slow` on the page makes the chunk take a second, so the state while it is in
            # flight is observable; `?gone` makes it 404, so the failure is too.
            if "pages.report" in self.path:
                shape = getattr(self.server, "chunk", "")
                if shape == "slow":
                    time.sleep(1.0)
                elif shape == "gone":
                    self.send_error(404)
                    return
            super().do_GET()

    class Threaded(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True
        chunk = ""  # a test sets "slow" or "gone" to shape the chunk's response

    server = Threaded(("127.0.0.1", 0), functools.partial(Quiet, directory=str(out)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", out, server
    server.shutdown()
