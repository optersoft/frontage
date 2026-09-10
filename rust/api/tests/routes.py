#!/usr/bin/env python3
"""What the spike must do, as assertions (`API.md` §6.1 and §4.3).

    cargo build -p frontage-api --profile api      # in rust/
    python3 rust/api/tests/routes.py               # from the repository root, or anywhere

No dependencies: the standard library starts the binary, hits every route in
`rust/api/examples/spike/app.py`, and checks the answers. The four that matter are the last four —
a coroutine that suspends on a tokio deadline, one that suspends on the event loop's own
timer, one that does both in a row, and one that awaits something nothing will ever settle
and must answer 500 promptly rather than hang.
"""

import concurrent.futures
import os
import pathlib
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

# rust/api/tests/routes.py -> rust/api
CRATE = pathlib.Path(__file__).resolve().parent.parent
PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"
failures = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{'' if ok else '  ' + detail}")
    if not ok:
        failures.append(name)


def get(path, data=None, timeout=10):
    request = urllib.request.Request(BASE + path, data=data, method="POST" if data else "GET")
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            return r.status, r.read(), time.time() - started
    except urllib.error.HTTPError as e:
        return e.code, e.read(), time.time() - started


def main():
    binary = CRATE.parent / "target" / "api" / "frontage-api"
    if not binary.exists():
        sys.exit(f"build it first: cargo build -p frontage-api --profile api ({binary} is missing)")
    app = CRATE / "examples" / "spike" / "app.py"
    extra = ["--stress"] if "--stress" in sys.argv else []
    if extra:
        print("  (GC stress: collecting at every safe point)")
    proc = subprocess.Popen([str(binary), str(app), "--addr", f"127.0.0.1:{PORT}", "--workers", "2", *extra],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                urllib.request.urlopen(BASE + "/hello", timeout=0.5).read()
                break
            except OSError:
                time.sleep(0.05)
        else:
            sys.exit("the server never came up")

        status, body, _ = get("/hello")
        check("GET /hello is 1 KB", status == 200 and len(body) == 1024, f"{status} {len(body)}")

        payload = b"a body, and back again"
        status, body, _ = get("/echo", payload)
        check("POST /echo returns the body", body == payload, repr(body[:40]))

        status, body, _ = get("/echo", b"z" * 65536)
        check("POST /echo survives 64 KB", len(body) == 65536, str(len(body)))

        status, _, _ = get("/nope")
        check("an unknown path is 404", status == 404, str(status))

        # §4.3: a Rust deadline settling a Python future.
        status, body, took = get("/sleeps")
        check("await _host.sleep resumes", body == b"slept on a tokio deadline", repr(body[:40]))
        check("and it really waited", 0.008 <= took < 0.5, f"{took:.3f}s")

        status, body, _ = get("/loops")
        check("await asyncio.sleep resumes", body == b"slept on the event loop", repr(body[:40]))

        status, body, took = get("/both")
        check("two awaits in a row resume", body == b"both", repr(body[:40]))
        check("and both waits happened", took >= 0.008, f"{took:.3f}s")

        # A stale delay measured before a poll used to declare this one stuck between its
        # two awaits, which is why the case above exists at all.
        status, body, took = get("/stuck", timeout=6)
        check("an unsettleable await is 500", status == 500, str(status))
        check("and it does not hang", took < 1.0, f"{took:.3f}s")

        # One worker, many suspended requests: they must interleave, not queue.
        with subprocess.Popen([str(binary), str(app), "--addr", f"127.0.0.1:{PORT + 1}",
                               "--workers", "1", *extra], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, start_new_session=True) as single:
            try:
                one = f"http://127.0.0.1:{PORT + 1}/sleeps"
                deadline = time.time() + 20
                while time.time() < deadline:
                    try:
                        urllib.request.urlopen(one, timeout=0.5).read()
                        break
                    except OSError:
                        time.sleep(0.05)
                started = time.time()
                with concurrent.futures.ThreadPoolExecutor(40) as pool:
                    bodies = list(pool.map(lambda _: urllib.request.urlopen(one, timeout=10).read(),
                                           range(40)))
                took = time.time() - started
                budget = 2.0 if extra else 0.20
                check("40 suspended requests interleave on one worker", took < budget,
                      f"{took:.3f}s, serialized would be ~0.40s")
                check("and every one of them is right",
                      all(b == b"slept on a tokio deadline" for b in bodies))
            finally:
                os.killpg(os.getpgid(single.pid), signal.SIGKILL)
    finally:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

    print()
    if failures:
        sys.exit(f"{len(failures)} failed: {', '.join(failures)}")
    print("all good")


if __name__ == "__main__":
    main()
