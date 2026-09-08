"""The local server every browser test needs: examples at /examples/, the package at
/frontage/, and the WebAssembly runtime under every directory at `<dir>/_frontage/`.
Session-scoped and autouse, so any single test can run alone. Skips the whole directory when
the runtime has not been fetched."""

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
    import os

    if os.environ.get("FRONTAGE_RUNTIME") in ("frontage", "rs", "rust"):
        if not (ROOT / "rust" / "web" / "frontage.wasm").exists():
            pytest.skip("frontage's runtime is not built: see rust/README.md")
    elif not (RUNTIME / "micropython.wasm").exists():
        pytest.skip("no MicroPython runtime: run `mk runtime.fetch`")
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
