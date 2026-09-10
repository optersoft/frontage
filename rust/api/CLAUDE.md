# CLAUDE.md

**Nothing is implemented. [`PLAN.md`](./PLAN.md) is authoritative and is the only content
here** — read it before proposing anything, including where the code should go, because §3
answers that and §6.1 defines a gate that may end the project.

`frontage-api`: FastAPI's shape on axum, with handlers on frontage's own Python runtime
(`frontage-vm`, a Rust VM per worker thread, no CPython and no GIL). Sibling of
`~/optersoft/frontage`, consumed by **path**, per the fleet convention:

```toml
frontage-vm = { path = "../frontage/rust/vm" }
```

## Rules that bite, before any code exists

- **`axum` follows the fleet pin.** `hive-server` is `axum = "0.8"` and `axum-oauth` is
  `=0.8.9`, because that is what dioxus 0.7 re-exports; a split minor breaks type
  unification at compile time. `PLAN.md` §4.8.
- **The path-dep rule applies in full.** A change in `frontage/rust/` reaches here with no
  manifest diff and an uncommitted edit there ships with a deploy, so commit the provider
  alongside the consumer. The first such change is the host future hook of §4.3.
- **Clean room, as in frontage.** Granian's and FastAPI's docs and specifications are fine;
  their source is not opened while writing code here. The RSGI *shape* is copied from its
  specification (§4.2) and nothing else is.
- **Python is the specification.** The framework layer is Python against the protocol seam,
  tested with pytest on CPython, and it is also the shipped code running on the VM — the same
  discipline `reactive.py` has with `core.rs`.
- **Count the crossings.** §4.4 is a budget with a test, not an aspiration: a handler that
  never awaits costs one `vm.call`. Granian's own numbers (125,539 → 63,181 requests/s on a
  body read) are why.
