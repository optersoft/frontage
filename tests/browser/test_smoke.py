"""The package imports under both browser interpreters, served from a local PyScript.

Needs `tools/pyscript/<version>/` (run `mk pyscript.fetch`) and a Chromium from
`uv run playwright install chromium`. Every test here starts its own server, so any one
of them can run alone.
"""

import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

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


@pytest.mark.parametrize("interpreter", ["mpy", "py"])
def test_package_imports_in_the_browser(server, page: Page, interpreter):
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/examples/hello/index.html?type={interpreter}")
    expected = "micropython" if interpreter == "mpy" else "pyodide"
    expect(page.locator("#app")).to_contain_text(re.compile(rf"Frontage \S+ on {expected}"), timeout=60_000)
    expect(page.locator("#app")).to_contain_text("<p>Hello from the string renderer</p>")
    expect(page.locator("#app")).to_contain_text("reactive: [2, 42] store: ['Ann', 'Bob']")
    assert errors == []
