# frontage's runtime, in Rust

The spike `RUNTIME.md` planned: a Python bytecode VM of our own for the browser, instead of
MicroPython. Written 2026-09-08, clean room from `SPEC.md` and the Python language reference.
`RUNTIME.md` §9 has the results against the gates.

| crate | what |
|---|---|
| `vm/` (`frontage-vm`) | the runtime: NaN-boxed `Value`, an arena heap with a precise mark-sweep collector (`heap.rs`), the interpreter over one shared value stack (`vm.rs`, with the sampling profiler), operators and iteration (`ops.rs`), attributes, classes and the C3 MRO with a direct-mapped method cache (`attr.rs`), dict keys honouring user `__hash__`/`__eq__` (`keys.rs`, `dict.rs`), the builtins and the builtin types' methods (`builtins.rs`), formatting (`format.rs`), the native modules `sys`/`math`/`time`/`random`/`json`/`gc`/`_frontage` and the Python ones under `src/lib/` (`asyncio`, `re` over `RegExp`, `html`, `functools`, `collections`, …) (`modules.rs`), the `.fbc` bytecode format (`fbc.rs`: varints and a string table per module), the JavaScript bridge as a table of function pointers the web crate fills (`jshooks.rs`), and the `Host` trait (`host.rs`). **The framework's native core**: `core.rs` (the reactive graph as VM types: Owner/Signal/Memo/Effect/RenderEffect, tracking, marking, the flush; `_core`), `dom.rs` (the DOM op stream; `_dom`) and `view.rs` (the template path: extract, clone, holes, the hole effects with the insert rules and reconcile; `_view`) |
| `compile/` (`frontage-compile`) | Python source → `Code`, over ruff's parser (`ruff_python_parser`, t-strings included): a symbol table (`symtable.rs`) and the code generator (`codegen.rs`). Runs on the host only; the page never sees source |
| `py/` (`fpy`) | the native runner: `fpy FILE.py`, `fpy --stress FILE.py` (a collection at every safe point, the way GC bugs are found), `fpy --compile OUT.fbc FILE.py`. `FPY_PATH` is the module search path. `tests/differential.rs` runs every `tests/cases/*.py` on `fpy --stress` and on CPython 3.14 (`.venv/bin/python`) and diffs the output byte for byte |
| `web/` (`frontage-web`) | the wasm: `src/lib.rs` exports `init`/`add_module`/`run`/`loop_turn`/`py_call`/`collect`, `src/js.rs` is the bridge's wasm side, `src/jsffi.py` the Python side (`create_proxy`, `to_js`, `JsException`, `_await`), `build.rs` precompiles the Python standard modules into the binary. `glue.js` instantiates the wasm and holds the handle table; `boot.js` boots a page from a manifest; `run.mjs` runs bytecode under node; `build_app.py` is the stand-in for `frontage build` |

## Build and test

```sh
cargo build --profile native                     # fpy, optimised
cargo test  --profile native                     # the differential cases
rustup target add wasm32-unknown-unknown         # once
cargo build -p frontage-web --profile wasms --target wasm32-unknown-unknown
wasm-opt -Os --all-features target/wasm32-unknown-unknown/wasms/frontage_web.wasm -o web/frontage.wasm
```

`wasm-opt` needs `--all-features`: Rust 1.96 emits bulk memory and non-trapping float
conversions. `--profile release` + `wasm-opt -Oz` is the small build (`RUNTIME.md` §9 has both
sizes and what -Oz costs).

The framework's own tests run on the runtime with a pytest shim (`raises`, `mark`, `fixture`,
`approx`, `monkeypatch`, `capsys`) and a runner that collects `test_*` and resolves fixtures by
parameter name; both live in the session's scratchpad for now (`shim/pytest.py`,
`shim/runtests.py`) and belong under `rust/py/tests/` when this leaves spike status:

```sh
FPY_PATH=..:shim target/native/fpy --stress shim/runtests.py tests.test_reactive tests.test_store
```

and the same on the wasm, compiled module by module with `fpy --compile` and passed to
`node web/run.mjs main.fbc frontage=…fbc frontage.reactive=…fbc …`.

An example app in a browser:

```sh
python web/build_app.py ../examples/counter dist/counter    # .fbc per module + manifest + runtime
python -m http.server -d dist/counter                        # then open /
```

## The profiler

```python
import _frontage
_frontage.profile_start()
...                      # the code to measure
for name, file, line, exclusive_ms, inclusive_ms in _frontage.profile_stop()[:30]:
    print(name, file, line, exclusive_ms, inclusive_ms)
```

A sample every 64 instructions: the time since the last one goes to the running code object
(exclusive) and to every code object on the frame stack (inclusive). About 30% overhead. The
native core was built by it: `RUNTIME.md` §9's addendum has each step's number.

## What it is not, yet

No `match` statement, no metaclasses or class keywords, `__slots__` is a plain dict, a
generator's `finally` does not run when it is collected, no `re` (it delegates to `RegExp`
by design, §3.6, not written), no `exec`/`eval` of source in the page (no parser there), and
`.fbc` files are read from a manifest rather than found by `build`'s import walk. Every one is
listed in `RUNTIME.md` §9 with its cost.
