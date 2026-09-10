# CLAUDE.md

**[`API.md`](../../API.md) at the repository root is authoritative** — the design, the
measurements, and the plan with its gates. Read it before proposing anything here, including
where code should go.

`frontage-api`: FastAPI's shape on axum, with handlers on this repository's own Python runtime
(`../vm`). §6.1 is built; §6.2, the surface, is next.

## Rules that bite

- **It is a workspace member but not a *default* member.** It pulls tokio, hyper and axum, and
  the runtime's gate (`cargo test --profile native` in `rust/`) must not compile a web server
  to check a bytecode change. Build it by name: `cargo build -p frontage-api --profile api`.
- **The `api` profile exists for `panic = "unwind"`.** `[profile.release]` sets
  `panic = "abort"` for the wasm, and under that a panic in one request handler takes the whole
  process down instead of failing one connection.
- **`axum` follows the fleet pin.** `hive-server` is `axum = "0.8"` and `axum-oauth` is
  `=0.8.9`, because that is what dioxus 0.7 re-exports; a split minor breaks type unification
  at compile time. `API.md` §4.8.
- **Never hold a `Value` in a Rust local across a call into Python.** The collector is precise
  and cannot see it. Use `vm.roots` with a mark and a truncate, or a Python dict that is itself
  rooted, which is what `coros` and `waits` are. `python3 tests/routes.py --stress` is what
  proves it: collection at every safe point.
- **The VM is never borrowed across an `.await`.** Every access goes through a synchronous
  closure, so only `Send` values cross a suspension point and the router stays a plain
  `axum::Router` — which is what `hive-server` takes.
- **Thread-per-core is load-bearing, not a performance choice.** A suspended coroutine belongs
  to the `Vm` it started on; a task on a `current_thread` runtime never migrates.
- **Count the crossings.** §4.4 is a budget: a handler that never suspends costs one
  `vm.call` and never touches the event loop. Granian's own numbers (125,539 → 63,181
  requests/s on a body read) are why.
- **Clean room, as everywhere here.** Granian's and FastAPI's docs and specifications are fine;
  their source is not opened. The RSGI *shape* is copied from its specification, nothing else.
