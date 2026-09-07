"""The trips example, built with the real `frontage build` and served by its own server: the
API at /api and the page at /, one process, one port. Playwright drives Chromium against it."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "trips"
sys.path.insert(0, str(ROOT / "tests"))

pytest.importorskip("playwright")


@pytest.fixture(scope="session")
def trips(tmp_path_factory):
    from live import free_port

    out = tmp_path_factory.mktemp("trips")
    subprocess.run([sys.executable, "-m", "frontage", "build", str(EXAMPLE), "--out", str(out), "--quiet"], check=True)
    assert (out / "_frontage" / "components" / "remote" / "index.js").is_file(), "the component was not discovered"
    port = free_port()
    env = dict(os.environ, TRIPS_STATIC=str(out), TRIPS_ROWS="500000")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server:app",
            "--app-dir",
            str(EXAMPLE),
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        env=env,
    )
    import socket

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
