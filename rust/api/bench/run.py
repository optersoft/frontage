#!/usr/bin/env python3
"""The spike's measurement (`API.md` §6.1): us against Granian, same box, same load.

    uv run --no-sync python run.py [--duration 10] [--connections 128] [--workers 1]

Starts each server in turn, warms it, runs `oha` at a fixed concurrency against a 1 KB GET
and a 1 KB POST echo, and prints requests/s and p99 side by side. The echo is the one that
matters: it is where Granian's own numbers halve, and where the one-crossing rule of §4.4
has to pay for itself.
"""

import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
CRATE = HERE.parent
PORT = 8411
BODY = HERE / "payload.txt"
TRIP = HERE / "trip.json"


def wait_until_up(url, deadline=20.0):
    end = time.time() + deadline
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=0.5):
                return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.05)
    return False


def oha(url, connections, duration, post=False, body=None):
    cmd = ["oha", "--no-tui", "-c", str(connections), "-z", f"{duration}s",
           "--output-format", "json"]
    if post:
        cmd += ["-m", "POST", "-D", str(body or BODY)]
        if body is TRIP:
            cmd += ["-H", "content-type: application/json"]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    summary, latency = d["summary"], d.get("latencyPercentiles", {})
    codes = d.get("statusCodeDistribution", {})
    return {
        "rps": summary["requestsPerSec"],
        "p99_ms": latency.get("p99", 0.0) * 1000,
        "ok": codes.get("200", 0),
        "other": sum(v for k, v in codes.items() if k != "200"),
    }


def free_port():
    """A previous subject that outlived its kill still holds the port; take it back."""
    for _ in range(20):
        out = subprocess.run(["lsof", "-tnP", f"-iTCP:{PORT}"], capture_output=True, text=True).stdout
        pids = [int(x) for x in out.split()]
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.3)


def measure(name, argv, connections, duration, env=None):
    free_port()
    proc = subprocess.Popen(argv, cwd=HERE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, env={**os.environ, **(env or {})},
                            start_new_session=True)
    try:
        if not wait_until_up(f"http://127.0.0.1:{PORT}/hello"):
            raise RuntimeError(f"{name}: never came up")
        oha(f"http://127.0.0.1:{PORT}/hello", connections, 2)  # warm
        get = oha(f"http://127.0.0.1:{PORT}/hello", connections, duration)
        echo = oha(f"http://127.0.0.1:{PORT}/echo", connections, duration, post=True)
        path = oha(f"http://127.0.0.1:{PORT}/trips/1", connections, duration)
        valid = oha(f"http://127.0.0.1:{PORT}/trips", connections, duration, post=True,
                    body=TRIP)
        return {"name": name, "get": get, "echo": echo, "path": path, "valid": valid}
    finally:
        # Granian's own shutdown can outlast a benchmark step, and `uv run` sits in front of
        # it, so the group gets a term and then a kill rather than a wait that never ends.
        try:
            group = os.getpgid(proc.pid)
            os.killpg(group, signal.SIGTERM)
            try:
                proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(group, signal.SIGKILL)
                proc.wait(timeout=5)
        except ProcessLookupError:
            pass
        free_port()
        time.sleep(0.7)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=10)
    ap.add_argument("--connections", type=int, default=128)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()

    BODY.write_bytes(b"x" * 1024)
    TRIP.write_bytes(b'{"id": 5, "note": "north"}')
    binary = CRATE.parent / "target" / "api" / "frontage-api"
    if not binary.exists():
        sys.exit(f"build it first: cargo build -p frontage-api --profile api ({binary} is missing)")
    w = str(args.workers)
    subjects = [
        ("frontage-api", [str(binary), str(CRATE / "examples" / "spike" / "app.py"),
                          "--addr", f"127.0.0.1:{PORT}", "--workers", w,
                          # The runtime has no site-packages: point it at the checkout that
                          # holds `frontage_api` and `frontage.schema`.
                          "--path", str(CRATE.parent.parent)]),
        ("granian + bare ASGI", ["uv", "run", "--no-sync", "granian", "--interface", "asgi",
                                 "--host", "127.0.0.1", "--port", str(PORT), "--workers", w,
                                 "--runtime-threads", "1", "asgi_app:app"]),
        ("granian + FastAPI", ["uv", "run", "--no-sync", "granian", "--interface", "asgi",
                               "--host", "127.0.0.1", "--port", str(PORT), "--workers", w,
                               "--runtime-threads", "1", "fastapi_app:app"]),
        ("uvicorn + FastAPI", ["uv", "run", "--no-sync", "uvicorn", "--host", "127.0.0.1",
                               "--port", str(PORT), "--workers", w, "fastapi_app:app"]),
    ]
    results = [measure(name, argv, args.connections, args.duration) for name, argv in subjects]

    print(f"\n{args.connections} connections, {args.duration}s, {args.workers} worker(s), "
          f"1 KB bodies both ways\n")
    print(f"{'server':<22} {'GET':>10} {'ECHO':>10} {'PATH PARAM':>11} {'VALIDATED':>10}")
    print("-" * 66)
    for r in results:
        print(f"{r['name']:<22} {r['get']['rps']:>10,.0f} {r['echo']['rps']:>10,.0f} "
              f"{r['path']['rps']:>11,.0f} {r['valid']['rps']:>10,.0f}")
    bad = [(r["name"], k) for r in results for k in ("get", "echo", "path", "valid") if r[k]["other"]]
    if bad:
        print("\nnon-200 responses:", bad)
    base = next(r for r in results if r["name"] == "granian + FastAPI")
    ours = next(r for r in results if r["name"] == "frontage-api")
    ratio = ours["echo"]["rps"] / base["echo"]["rps"]
    print(f"\nthe gate (§6.1): {ratio:.2f}x granian + FastAPI on echo — "
          f"{'MET' if ratio >= 2 else 'NOT MET'} (needs 2.00x)")


if __name__ == "__main__":
    main()
