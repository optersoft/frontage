"""Run the rows example under both interpreters and print the numbers DESIGN.md §12 asks for.

Usage: uv run python tools/bench.py [--runs 3]. Needs the server (started here) and Chromium
from `uv run playwright install chromium`. Wall time comes from performance.now() around
each operation inside the page; ops is the count of renderer calls (bridge crossings)."""

import argparse
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OPS = [
    ("run", "create 1,000"),
    ("update", "update every 10th"),
    ("swaprows", "swap"),
    ("add", "append 1,000"),
    ("clear", "clear"),
]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--interpreters", default="mpy,py")
    args = parser.parse_args()
    port = free_port()
    server = subprocess.Popen([sys.executable, str(ROOT / "tools/serve.py"), "--port", str(port), "--quiet"], cwd=ROOT)
    time.sleep(1)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for interp in args.interpreters.split(","):
                page = browser.new_page()
                t0 = time.time()
                page.goto(f"http://127.0.0.1:{port}/examples/rows/index.html?type={interp}")
                page.wait_for_selector("#run", timeout=120_000)
                startup = time.time() - t0
                print(f"\n== {interp}  (page ready in {startup:.1f}s)")
                print(f"{'operation':<20}{'ms (median)':>14}{'ops':>10}{'rows after':>12}")
                for button, label in OPS:
                    times, ops = [], None
                    for _ in range(args.runs):
                        # Every operation is measured against a table of exactly 1,000 rows.
                        if button != "run" and page.locator("#tbody tr").count() != 1000:
                            if page.locator("#tbody tr").count():
                                page.click("#clear")
                                page.wait_for_function("document.querySelectorAll('#tbody tr').length === 0")
                            page.click("#run")
                            page.wait_for_function("document.querySelectorAll('#tbody tr').length === 1000")
                        elif button == "run" and page.locator("#tbody tr").count():
                            page.click("#clear")
                            page.wait_for_function("document.querySelectorAll('#tbody tr').length === 0")
                        page.click(f"#{button}")
                        page.wait_for_function(f"document.querySelector('#stats').textContent.startsWith({label!r})")
                        m = re.match(r".*: ([\d.]+) ms, (\d+) ops", page.locator("#stats").text_content())
                        times.append(float(m.group(1)))
                        ops = int(m.group(2))
                    times.sort()
                    rows = page.locator("#tbody tr").count()
                    print(f"{label:<20}{times[len(times) // 2]:>14.1f}{ops:>10}{rows:>12}")
                page.close()
            browser.close()
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
