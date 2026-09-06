"""Run tools/profile/ under both interpreters and print each phase's median time.

Usage: uv run python tools/profile_rows.py [--interpreters mpy,py]. Starts tools/serve.py itself."""

import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interpreters", default="mpy,py")
    args = parser.parse_args()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = subprocess.Popen([sys.executable, str(ROOT / "tools/serve.py"), "--port", str(port), "--quiet"], cwd=ROOT)
    time.sleep(1)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for interp in args.interpreters.split(","):
                page = browser.new_page()
                page.on(
                    "console",
                    lambda m: print("  console:", m.type, m.text[:1500]) if m.type in ("error", "warning") else None,
                )
                page.on("pageerror", lambda e: print("  pageerror:", str(e)[:300]))
                page.goto(f"http://127.0.0.1:{port}/profile/?type={interp}")
                try:
                    page.wait_for_function("!document.querySelector('#done').hidden", timeout=120_000)
                except Exception as exc:
                    print(f"\n== {interp}: did not finish ({type(exc).__name__})")
                    print(page.locator("#out").text_content())
                    page.close()
                    continue
                print(f"\n== {interp}")
                print(page.locator("#out").text_content())
                page.close()
            browser.close()
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
