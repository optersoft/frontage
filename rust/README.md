# frontage's runtime, in Rust

The spike `RUNTIME.md` planned: a Python bytecode VM of our own for the browser, instead of
MicroPython. Written 2026-09-08, clean room from `SPEC.md` and the Python language reference.
`RUNTIME.md` §9 has the results against the gates.

| crate | what |
|---|---|
| `vm/` (`frontage-vm`) | the runtime: NaN-boxed `Value`, an arena heap with a precise mark-sweep collector (`heap.rs`), the interpreter over one shared value stack (`vm.rs`, with the sampling profiler), operators and iteration (`ops.rs`), attributes, classes and the C3 MRO with a direct-mapped method cache (`attr.rs`), dict keys honouring user `__hash__`/`__eq__` (`keys.rs`, `dict.rs`), the builtins and the builtin types' methods (`builtins.rs`), formatting (`format.rs`), the native modules `sys`/`math`/`time`/`random`/`json`/`gc`/`_frontage` and the Python ones under `src/lib/` (`asyncio`, `re` over `RegExp`, `html`, `functools`, `collections`, …) (`modules.rs`), the `.fbc` bytecode format (`fbc.rs`: varints and a string table per module), the JavaScript bridge as a table of function pointers the web crate fills (`jshooks.rs`), and the `Host` trait (`host.rs`). **The framework's native core**: `core.rs` (the reactive graph as VM types: Owner/Signal/Memo/Effect/RenderEffect, tracking, marking, the flush; `_core`), `dom.rs` (the DOM op stream; `_dom`) and `view.rs` (the template path: extract, clone, holes, the hole effects with the insert rules and reconcile; `_view`) |
| `compile/` (`frontage-compile`) | Python source → `Code`, over ruff's parser (`ruff_python_parser`, t-strings included): a symbol table (`symtable.rs`) and the code generator (`codegen.rs`). Runs on the host only; the page never sees source |
| `py/` (`fpy`) | the native runner: `fpy FILE.py`, `fpy --stress FILE.py` (a collection at every safe point, the way GC bugs are found), `fpy --compile OUT.fbc FILE.py`. `FPY_PATH` is the module search path. `tests/differential.rs` runs every `tests/cases/*.py` on `fpy --stress` and on CPython 3.14 (`.venv/bin/python`) and diffs the output byte for byte |
| `web/` (`frontage-web`) | the wasm: `src/lib.rs` exports `init`/`add_module`/`add_js_module`/`run`/`loop_turn`/`py_call`/`collect`, `src/js.rs` is the bridge's wasm side, `src/jsffi.py` the Python side (`create_proxy`, `to_js`, `JsException`, `_await`), `build.rs` precompiles the Python standard modules into the binary. `glue.js` instantiates the wasm, holds the handle table, executes the DOM op stream and delegates events; `boot.js` boots a page from a manifest; `run.mjs` runs bytecode under node. `mk runtime.build` (repo root) builds and vendors both wasms (`frontage.wasm`; `frontage-compiler.wasm` with the `compiler` feature, `exec` and `run_source` for the playground and the runner) and the two scripts into `frontage/_runtime/`, which the wheel ships |

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
`node web/run.mjs main.fbc frontage=…fbc frontage.reactive=…fbc …` (the vendored
`frontage/_runtime/frontage.wasm`; `FRONTAGE_WASM=path` for a fresh build).

An example app in a browser, with the real command (the runtime is the default):

```sh
cd .. && uv run frontage build examples/counter --out dist/counter && python -m http.server -d dist/counter
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

## Where it differs from CPython, on purpose

**`__annotations__` holds the annotation's source text, not its value.** This runtime has
never evaluated an annotation — `def g(x: Undefined)` does not raise, and never did — and
storing the text keeps that exactly, so no code that runs today can start failing. It is the
shape `from __future__ import annotations` gives CPython, so a reader that expects strings is
not surprised; a *string* annotation keeps its quotes, because that is what the source says.
The keys and their order match CPython, which is what `py/tests/cases/annotations.py`
asserts. `frontage_api` is the first consumer: a route's contract is read from it.

**There is no time zone database, so local time *is* UTC.** `datetime.now()` with no `tz`
gives the UTC wall clock where CPython gives the machine's zone, and `timestamp()` reads a
naive datetime as UTC for the same reason; `time.localtime` is simply absent rather than
lying. Everything else in `datetime` matches CPython byte for byte — `repr`, `isoformat`,
`strftime` and the `ValueError` messages included — which is what
`py/tests/cases/datetime_mod.py` asserts. Carrying a zone database would cost more bytes in
every page than the whole reactive core.

**`os` is the environment and nothing else.** There is no file system to wrap, so the module
is `environ`, `getenv`, `name`, `sep`, `linesep`. In the browser the host answers nothing and
`os.environ` is *empty* rather than missing, so the same handler code reads a key on the
server and `None` in a page instead of failing to import.

**`time.strftime` leaves an unknown directive as it was typed** (`%q` stays `%q`), which is
glibc's behaviour and not macOS's. The platforms disagree, so `py/tests/cases/time_calendar.py`
deliberately asserts nothing about it.

**`bytes` is a short list of methods, grown by need.** `decode`, `hex`, `find`,
`startswith`, `endswith`, indexing, slicing and `+` — enough to reassemble a streamed body,
which is what asked for the last three (`py/tests/cases/bytes_search.py`). `split`, `strip`,
`replace` and `join` are not written. ⚠ A `str` argument is a `TypeError`, as it is in
CPython: obliging it would let a `str` needle search a `bytes` haystack, which is the
encoding bug the refusal exists to catch.

## What it is not, yet

`__slots__` is accepted but not enforced (an instance keeps a dict); `eval` is not written
(`exec` and `compile` are, in the compiler build); a class statement's `**kwargs` is
rejected; `re` covers what `RegExp` does (no conditional groups, no `\N{…}`). `match`
statements, metaclasses, class keywords and a generator's `finally` on collection are in
since 2026-09-08, each with a differential case. `time.localtime`, `time.mktime` and
`time.strptime` are not written (no zone database, and `datetime.fromisoformat` is the
parsing that was actually wanted); `datetime.strptime` is not either. Every gap found is a case in
`py/tests/cases/` first.
