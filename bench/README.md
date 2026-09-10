# The spike's measurement

`PLAN.md` §6.1 is the gate; this is how to re-run it.

```sh
cargo build --release          # from the repository root
cd bench && uv sync
uv run --no-sync python run.py --duration 10 --connections 64 --workers 1
```

It starts each server in turn on port 8411, warms it for two seconds, runs
[`oha`](https://github.com/hatoo/oha) against a 1 KB `GET /hello` and a 1 KB `POST /echo`,
and prints requests/s and p99 side by side with the gate's ratio at the bottom. A subject
that outlives its own shutdown is killed by port rather than waited on, because Granian's
graceful stop can outlast a benchmark step and `uv run` sits in front of it.

**Four subjects, and the third is the gate.** `frontage-api` on `examples/spike/app.py`;
Granian on `asgi_app.py`, a bare ASGI app with the same two routes, which is the honest
like-for-like while neither side has a framework layer; Granian on `fastapi_app.py`, which is
what §6.1 sets its gate against; and uvicorn on the same FastAPI app for scale.

⚠ **Warm the binary first, or you measure macOS.** `syspolicyd` scans a freshly built
binary the first time it runs, and the scan lands on whichever route is measured first. It
showed up once as a GET slower than the ECHO measured moments later in the same process,
which the server cannot explain. `run.py` warms each subject for two seconds, but the *first*
subject after a rebuild can still carry it: run the binary once by hand after `cargo build`
before trusting a number.

⚠ **Check the ceiling before believing a large number.** This laptop's loopback saturates
near 193,000 requests/s whatever the server does, so a subject at that figure is measuring
the client. The check is two lines: run one server with plenty of workers, and see whether
the figure moves with `-c`.

```sh
./target/release/frontage-api examples/spike/app.py --addr 127.0.0.1:8412 --workers 8 &
for c in 64 128 256; do oha --no-tui -c $c -z 5s --output-format json \
  http://127.0.0.1:8412/hello | grep -o '"requestsPerSec":[0-9.]*'; done
```

Three figures within a percent of each other mean the client is the limit, not the server.
Two `oha` processes at once splitting that same total is the confirmation.
