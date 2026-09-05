"""The local server every browser test needs: examples at /examples/, the package at
/frontage/ and the offline PyScript bundle at /pyscript/. Session-scoped and autouse, so
any single test can run alone. Skips the whole directory when the bundle is not fetched."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PYSCRIPT = ROOT / "tools" / "pyscript"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session", autouse=True)
def server():
    if not any(PYSCRIPT.glob("*/pyscript/core.js")):
        pytest.skip("no local PyScript: run `mk pyscript.fetch`")
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
