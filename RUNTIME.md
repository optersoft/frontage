# A Python runtime for the browser, in Rust: the design, and the case for building one

**Status: a design, 2026-09-08, and a proposal for a three-week spike that decides it.
Everything in §2 is measured — on the committed interpreter, on five probes built for this
document (a NaN-boxed bytecode VM, ruff's parser, a delegation harness, all on
`wasm32-unknown-unknown`, stable Rust 1.96), and on the published artefacts of RustPython and
pydantic's Monty. §3 onward is unbuilt. It is written after `FASTER.md` (the interpreter and
the core) and `RUST.md` (where Rust goes), and §4 says what it would change in each.**

The question: *instead of MicroPython, a Python runtime of our own, in Rust, made for the
browser — one that hands the browser what the browser already does well (regular expressions,
Unicode, big integers, the event loop) and keeps for itself only what Python must own.*
RustPython is the obvious reference and the obvious warning: a full Python in Rust is 22.8 MB
of wasm. The answer this document reaches is a *specific* runtime: the Python that frontage and
its apps actually use (measured by a census of the code), no parser in the page, values that
fit in a 64-bit word, a precise collector, errors as values, and the reactive core as native
types of the VM rather than a C module bolted onto someone else's object model.

## 0. The decision, in five sentences

**It is worth a spike, not yet a commitment.** MicroPython is 108 KB of brotli and 49 ns a
call, and the design below has to beat both to justify a second implementation of Python: the
probes say the dispatch floor in Rust is 3× MicroPython's and a `no_std` VM is measured in
kilobytes, so the target is *plausible* and *unproven*. **What a runtime of our own buys is
structural**, not incremental: the reactive core as VM-native types (no C shim, no
`mp_obj_t`), a garbage collector that runs during a render instead of between them, no proxy
objects at all, Python semantics right where MicroPython's are wrong (dict order, stable sort,
generators, `__getattribute__`), exceptions as `Result` so no wasm feature past 2020 is
required, and a build that is `cargo build` in seconds instead of Emscripten in Docker.
**The browser is the standard library**: `re` is `RegExp` (16 ns a call, zero bytes of engine),
Unicode is `String`, big integers are `BigInt`, float printing is `Number`, time and randomness
and the event loop are the host's; only what works on Python's own objects — dicts, lists,
strings, hashing, sorting, JSON — is Rust. **No parser ships**: apps and the framework are
compiled to bytecode on the host, and ruff's parser (1.1 MB raw, 434 KB brotli as wasm) goes
only to the playground. **The gate**: a VM that runs `reactive.py`'s tests under node, under
120 KB of brotli, at least 2× MicroPython on `tools/profile_rows.py`, in three weeks — or
`RUST.md` stands as written.

## 1. Why leave MicroPython, precisely

MicroPython is a good interpreter and the wrong shape for this project, and the reasons are
specific enough to be a requirements list.

**Semantics found wrong in this repository**, each with a workaround somewhere in the code:
dicts do not preserve insertion order (`CLAUDE.md`; every ordered API takes pairs); `sorted`
is quadratic on ordered input and unstable (`RUST.md` §2.3: 269 ms for 10,000 ordered floats,
1,440 ms with a key); a `lambda` inside a t-string's braces is a syntax error; two adjacent
f-strings do not cross-compile; a module object cannot be constructed; no `__getattribute__`,
no `__mro__`, no `co_argcount`, no writable `__name__` or instance `__dict__`; a generator's
`finally` does not run on `throw()`, `close()` after a throw hangs the event loop,
`asyncio.wait_for` rejects a coroutine, `len()` of a JavaScript array raises (the smoke test
of 2026-09-07).

**Structure, which no variant fixes:** the object model is C macros, so a core in Rust needs a
shim and a GC audit (`RUST.md` §3.1); the collector runs only when control returns to
JavaScript, so a 1,000-row create just grows the heap (`FASTER.md` §2); every DOM node Python
holds is a proxy on both sides (`FASTER.md` §4); exceptions are `longjmp`, which on wasm is
either JavaScript trampolines or wasm exception handling with its Safari 15.2 floor; and the
build is Emscripten in Docker, two minutes a turn.

**What it does well, which is the bar:** 265,584 bytes raw, 107,984 brotli; a Python call in
49 ns, a method call in 84 ns, a dict store with a formatted key in 264 ns (§2.2); a full
compiler in the page; twelve years of other people fixing it.

## 2. Measured

### 2.1 The prior art, by size

| runtime | wasm raw | brotli | Python | note |
|---|---|---|---|---|
| RustPython (demo, with stdlib) | ~22.8 MB | | full | `Rc` objects, no cycle collection by default; issues #4203, #5403 |
| **Monty** 0.0.23 (pydantic, 2026-02), `@pydantic/monty` | 18,980,772 | 3,694,491 | a subset: no inheritance, no `@property`/`super`, no generators, no t-strings, no user exceptions | ruff's parser + `ty`'s semantic model + `regex` + `num-bigint` on `wasm32-wasip1`; sandbox for agents, not a browser runtime |
| Edge Python (2026, discuss.python.org) | ~160 KB | | no classes, no exceptions, no generators | hand-written parser, inline caches; `fib(45)` in 11 ms |
| **MicroPython**, frontage's variant | 265,584 | 107,984 | nearly full | the incumbent |
| **the VM probe** (§2.2), NaN-boxed, frames, `Result` per op | 3,469 | 1,429 | none | the dispatch floor |
| **ruff's parser + AST** alone, as wasm | 1,119,254 | 434,158 | — | parses `reactive.py` in 4 ms, t-strings included |

Two lessons. A Python in Rust is not small by default: Monty's is 3.7 MB of brotli with a
subset MicroPython exceeds, because the general crates (`regex`, `num-bigint`, `serde`, the
type checker) come whole. And a parser is a third of a megabyte before a single Python object
exists — which is why the runtime described here carries none.

### 2.2 The dispatch floor, against MicroPython, same loops, node 26

A 300-line `no_std` VM: 64-bit NaN-boxed values (a float is itself; ints, bools, `None` and
pointers in the quiet-NaN space with a 3-bit tag), a stack of values, frames with a base
index, every op returning `Result`, `fib` as a real call with a real frame.

| | Rust VM probe | MicroPython (frontage variant) | ratio |
|---|---|---|---|
| `fib(27)`, per call (9 ops + a frame) | **16.2 ns** | 49.3 ns | 3.0× |
| `while i < n: s = s + i; i = i + 1`, per iteration (10 ops) | **15.5 ns** (1.55 ns an op) | 49.8 ns | 3.2× |
| a method call in a loop | not probed | 84 ns | |
| a dict store with a `%`-formatted key | not probed | 264 ns | |

The probe has no attribute lookup, no dict, no allocation — it is the cost of *being a bytecode
interpreter on wasm*, and it says Rust with values in a word pays a third of what MicroPython
pays for the same work. A real page is attribute lookups and allocation; §3.3's inline caches
and §3.2's allocator are what turns the floor into a number on `profile_rows`, and that is what
the spike measures.

### 2.3 What delegation costs: a wasm → JavaScript import call

| | ns per call |
|---|---|
| `Math.sin` through an import | **11.6** |
| `RegExp.prototype.test` on an e-mail pattern | **16.3** |
| `String.prototype.toUpperCase` on a 19-char string | **22.2** |
| a native f64 multiply-add in wasm, for scale | 0.59 |

A delegated call is cheaper than a MicroPython method call today (84 ns), and the things
delegated are exactly the ones whose Rust implementation is measured in hundreds of kilobytes:
`regex` (Monty carries it), Unicode tables, arbitrary-precision integers, float formatting.

### 2.4 The census: what Python the browser side actually uses

`ast` over 55 files, 10,839 lines — the framework's browser modules, the seven components,
every example:

| | |
|---|---|
| calls to builtins | `len` 111, `str` 84, `isinstance` 64, `type` 48, `list` 46, `getattr` 44, `callable` 39, `range` 33, `int` 33, `hasattr` 28, `dict` 20, `bool` 19, `id` 16, `sorted` 12, `repr` 10, `sum` 9, `set` 7, `enumerate` 7, `any` 6, `max` 6, `iter` 4, `setattr` 4, `float` 4, `super` 3, `chr` 3, `min` 3, `abs` 3, `round` 3, `reversed` 2, `tuple` 2, `zip` 2, `hash`, `format`, `next`, `delattr`, `print` |
| dunders defined | `__init__` 74, `__repr__` 32, `__call__` 13, `__getattr__` 7, `__len__` 4, `__getitem__` 3, `__iter__` 3, `__setattr__` 3, `__enter__`/`__exit__` 3, `__bool__` 2, `__eq__` 2, `__contains__`, `__setitem__`, `__delitem__`, `__str__`; one `__slots__`, one `__getattribute__`; `@property` 3, `@staticmethod` 2, `super()` 1 |
| syntax | `Lambda` 248, `ListComp` 74, `GeneratorExp` 25, `DictComp` 7, `Await` 46, `AsyncFunctionDef` 42, `Try` 56, `Raise` 91, `With` 9, `Global` 19, `Starred` 40, `JoinedStr` 146, `Interpolation` (t-strings) 6, `NamedExpr` 1, **`Yield` 2**, no `match`, no `async with`/`async for` |
| stdlib imported | `asyncio` 9, `sys` 5, `json` 5, `math` 2, `re` 1, `struct` 1, `time` 1, `random` 1, `io` 1; `html` and `traceback` on CPython only |
| `str` methods called | `join` 30, `startswith` 25, `replace` 15, `strip` 12, `split` 10, `lower` 9, `find` 8, `rstrip` 6, `index` 6, `format` 4, `endswith` 3, `partition` 3, `encode` 2, `isdigit` 2, `rfind` 2, `upper`, `count`, `decode`, `rpartition` |
| the DOM surface `dom.py` touches | `createElement`, `createTextNode`, `querySelector`, `createTreeWalker`, `appendChild`/`insertBefore`/`removeChild`/`replaceChild`, `setAttribute`/`getAttribute`/`removeAttribute`/`hasAttribute`, `classList`, `style`, `data`, `nodeType`, `nextSibling`/`previousSibling`/`parentNode`/`firstChild`/`lastChild`, `isSameNode`, `addEventListener`/`removeEventListener`/`dispatchEvent`, `CustomEvent` — thirty names |

This is a bounded Python: classes with a dozen dunders, closures everywhere, comprehensions,
exceptions with a hierarchy, coroutines, t-strings — and two `yield`s in eleven thousand lines.
Generators still ship (an app may use one), but they need not be fast.

## 3. The runtime

### 3.1 Values and objects

A `Value` is 64 bits, NaN-boxed as in the probe: an `f64` is itself; a small `int` (31 bits),
`bool`, `None` and a heap pointer sit in the quiet-NaN space under a tag. No allocation for
arithmetic, no boxing for floats, one word on the stack. A heap object is a header — type
pointer, GC mark bits, a 32-bit hash cache for strings — followed by the payload:
`str` (UTF-8, byte length, char length, `is_ascii`), `list` (a `Vec`), `tuple` (inline),
`dict` (compact and ordered: an index table plus an entries array, CPython's layout, so
insertion order is a property of the layout and not a feature), `set`, `bigint` (a JavaScript
`BigInt` behind a handle, §3.6), `function`, `bound method`, `cell`, `class`, `instance` (a
slot array for `__slots__` and declared attributes, a dict otherwise), `frame`, `generator`
and `coroutine` (a suspended frame), `exception`, `JsObject` (a handle), and the framework's
own types (§3.8). Attribute names are interned at load, so a lookup compares pointers.

### 3.2 The collector

Precise, tracing, mark-sweep, non-moving, in Rust, over a bump-and-free-list allocator in
linear memory. The roots are known exactly — the value stacks of every live task, module
dicts, the interned table, and the handle table of Python objects JavaScript holds (event
handlers, `create_proxy`'s successors) — so there is no conservative scan of anything and no
`MP_REGISTER_ROOT_POINTER`. Collection runs on an allocation threshold *during* a run, which
is what MicroPython's port cannot do (it collects only when control returns to JavaScript, so a
construction simply grows the heap), and it collects cycles, which a UI framework makes by
the thousand: signal ↔ effect ↔ owner. No `__del__`; `weakref` as a later feature; a
`FinalizationRegistry` on the JavaScript side releases handles a JavaScript object dropped.
Later, when a measurement asks: generations, or incremental marking sliced between frames.

### 3.3 The VM

A stack bytecode of our own, executed by a loop that returns `Result<Value, Exception>` from
every operation — a branch a few cycles wide, and no `setjmp`, no `longjmp`, no wasm
exception handling, no trampolines. `try`/`except`/`finally` are handler tables on the code
object, as in CPython 3.11; a raise unwinds frames in Rust, building the traceback as it goes.
Frames live on the heap, so a generator or a coroutine is a frame kept, and resuming one is
re-entering the loop at its saved `pc` — no stack switching, no JSPI, nothing beyond wasm
MVP plus bulk memory. Calls push a frame with the arguments already in place; keyword and
starred arguments take the slow path. **Inline caches** at every attribute-load, global-load
and call site, keyed on the type's version tag, are the whole difference between the probe's
floor and a page's number: an instance attribute becomes a slot index compare-and-load, a
method call skips the MRO walk, a global skips the dict. The attribute-set path bumps the
version; the framework's own hot paths (`_children`, holes, `For`) do not go through Python
attribute access at all (§3.8).

### 3.4 The Python it runs

**In**: everything in §2.4, plus what an app plausibly reaches: classes with single and
multiple inheritance and a C3 MRO, `super()`, `@property`, `@staticmethod`, `@classmethod`,
`__slots__`, descriptors as far as `property` and functions need them, `__getattr__` and
`__getattribute__`, every operator dunder the census shows plus `__lt__`/`__hash__` for
sorting and dict keys, closures with `nonlocal` cells, `global`, comprehensions of all four
kinds, generator expressions as real (lazy) generators, `yield`/`yield from`, `async def`,
`await`, `async for`/`async with`, exceptions with a hierarchy and user subclasses, chained
`raise … from`, `try`/`except`/`else`/`finally`, `with`, f-strings and t-strings with format
specs and conversions, `%` formatting, `str.format`, slicing with steps, unpacking, `del`,
`assert`, `match` (last, it is syntax the compiler lowers), `int` beyond 31 bits (§3.6),
`float` with Python's repr, `bytes`/`bytearray`/`memoryview` enough for `struct` and a
`data-fr-js` buffer, `array('d')`.

**Out, and said so**: `eval`/`exec` of *source* (there is no parser; `exec` of bytecode
exists for the playground), metaclasses beyond `type`, `__init_subclass__`/`__set_name__` until
asked for, `__del__`, threads, `locals()` as a writable dict, `sys.settrace`, complex numbers,
`decimal`, `fractions`. **Documented differences**, the way MicroPython documents its own: `str`
indexes by code point with an O(1) path for ASCII and O(n) otherwise (the same trade
MicroPython makes); integers are exact at every size but a `BigInt` beyond 31 bits (§3.6);
`id()` is the handle, not an address.

### 3.5 Strings

UTF-8 in linear memory, with the byte length, the code-point length and an ASCII flag in the
header, hash cached, identifiers interned. Concatenation, slicing, `find`, `split`, `join`,
`replace`, `strip`, `startswith`, `format` and `%` are Rust over bytes; equality is a
length-then-`memcmp`. What Rust `core` does *not* have — case mapping beyond ASCII,
`casefold`, `isalpha` over Unicode, normalisation — is a delegated call on the non-ASCII path
only (§3.6). The alternative — `str` as a JavaScript string behind a handle, with the JS String
Builtins for `length`/`concat`/`equals` — was weighed: it would make `textContent` free of
encoding, but every `==` and hash would be an import, the builtins reached Safari only in
26.2, and the DOM path already crosses once per flush with a byte buffer (`FASTER.md` §4).
Revisit if a profile ever shows string traffic to the DOM as the bottleneck.

### 3.6 The browser is the standard library

The rule: **delegate what the engine owns or what needs tables; keep what works on Python's
objects.** Monty ships `regex` and `num-bigint` and pays megabytes for it; a browser has both
built in, JIT-compiled, tested, and 16 ns away.

| Python | implementation | why |
|---|---|---|
| `re` | `RegExp`, behind a translator: `(?P<n>…)` → `(?<n>…)`, `(?P=n)` → `\k<n>`, `\A`/`\Z` → anchors, `(?x)` stripped at compile, `re.sub` callbacks through a handle, Python flag letters → JS flags; `match`/`search`/`fullmatch`/`findall`/`finditer`/`split`/`sub`/`groupdict` over `exec` with `d` (indices) | a backtracking engine for zero bytes; the translator is small and the differences are finite and known |
| Unicode `upper`/`lower`/`casefold`/`isalpha`/…, `unicodedata.normalize` | `String` methods, on the non-ASCII path | Rust `core` has no tables; the ASCII path stays in Rust |
| `int` beyond 31 bits | a `BigInt` handle; `+`, `*`, `//`, `%`, `**`, comparisons and `str()` through imports; results that fit come back as small ints | arbitrary precision for zero bytes, on a path apps almost never take |
| `float.__repr__`, `format(x, ".3f")`, `%g` | `Number.prototype.toString`/`toFixed`/`toPrecision`/`toExponential`, with Python's spelling applied in Rust (`1e+16`, `.0`, `inf`, `nan`, `-0.0`) | shortest round-trip printing without `core::fmt`'s tables |
| `math` | `Math.*` through imports; `floor`/`ceil`/`trunc`/`isnan` in Rust | `core` has no `sin` on `wasm32-unknown-unknown`; 12 ns a call |
| `time`, `random` | `performance.now`, `Date.now`, `crypto.getRandomValues`, `Math.random` | the host's clock and entropy |
| `datetime` | a thin type over `Date` and `Intl.DateTimeFormat`; ISO parse/format in Rust | the Python module is thousands of lines the census never reaches |
| `asyncio` | **the event loop is the browser's**: a task is a heap frame chain, `await <coroutine>` is a VM operation, `await <promise>` parks the task and resumes it from the promise's microtask, `sleep` is `setTimeout`, `gather`/`wait_for`/`Event`/`create_task` in Rust over that | no scheduler to write, and `wait_for` finally accepts a coroutine |
| fetch, the DOM, events, `js.*` | the handle table (§3.7) | |
| `json` | **Rust**: a parser straight into Python objects | `JSON.parse` would build JavaScript objects that then cross node by node; the Rust parser is ~3 KB and touches nothing outside linear memory |
| `sorted`, `list.sort` | **Rust**: stable merge sort, key called once per element | a comparator crossing per comparison would cost more than the sort |
| `dict`, `list`, `set`, `str` operations, hashing, `struct`, `%`/`format` | **Rust** | Python's objects |

### 3.7 Interop: the handle table

JavaScript keeps an array of objects; Python holds `u32` indices in a `JsObject`. No
`externref` is needed (the array is what `wasm-bindgen` used before reference types existed)
and no JavaScript proxy object exists per Python-held value. `js.document`, attribute access,
calls, `await` on a promise, `new`, indexing, `len` (`length`), iteration (`Symbol.iterator`),
`bool`, `str` — the surface `jsffi` offers, with the gaps the smoke test found closed. Python
callables given to JavaScript are entries in a second table on the Python side, GC roots until
released; `on_cleanup` releases them today and keeps doing so. A `registerJsModule` equivalent
makes a JavaScript namespace importable, so `data-fr-js` and every component's glue are
unchanged. Conversions cross by iteration (65 ns an element, `RUST.md` §2.2) or, for
`bytes`/`array`, by a `(ptr, len)` the glue reads from linear memory directly — the zero-copy
path `RUST.md` had to ask a shim for is a native property here.

### 3.8 The framework core, native

This is the part that no amount of work on MicroPython gives. `Signal`, `Memo`, `Effect`,
`RenderEffect`, `Owner`, the two-phase graph, `_mark`/`_flush`, `batch`, template holes,
`_reconcile` and `_lis`, `For` rows, `Store` proxies — `FASTER.md` §3's table — are Rust types
*of the VM*: they read a `Value` field directly, call a Python closure by pushing a frame, and
never go through attribute lookup, `mp_call_function_n_kw` or a shim. `RUST.md` §3.1's four
rules (GC-heap allocation, no `Drop` across a call into Python, the `fr_try` shim) shrink to
one: a core type is a heap object like any other, traced by the collector like any other,
and a Python error is a `Result` it returns like any other. The DOM op stream of `FASTER.md`
§4 is written by the VM into a byte buffer the glue drains once per flush; nodes are integers
in the glue's array; delegated events hand the VM an id and an event handle. The Python
implementation of the same behaviour stays, for CPython (tests, prerender, the language
server) and behind `FRONTAGE_PURE=1` in the browser, exactly as `FASTER.md` §12 keeps it.

### 3.9 Bytecode and the compiler

**The page gets bytecode, never source.** `frontage build` compiles the app, the framework
and the components on the host into `.fbc` modules — marshalled constants, interned names,
handler tables — packed as today's archives (`FASTER.md` §7 unchanged: two content-hashed
archives, chunks, the manifest). The format is ours and versioned with the runtime; a wheel
carries a runtime and the framework compiled for it, and `serve` compiles on save in
milliseconds.

**The compiler is Rust over ruff's parser** — `ruff_python_parser` 0.0.9 on crates.io, which
parses PEP 750 t-strings since ruff 0.11.13 (2025-05-30), `async`, `match`, everything — with
a codegen crate of ours: symbol tables (locals, cells, globals), the handler tables, the
lowering of comprehensions, `with`, f-strings and t-strings, `match`. One implementation, run
in two places: **on the host** as a native extension in the wheel (`maturin`, `abi3`, one
wheel per platform — the shape `pydantic-core` and `ruff` ship in; `uvx frontage` resolves
it), and **in the playground** as the same crate compiled to wasm — 434 KB of brotli for the
parser plus the codegen, loaded by the playground and the academy's runner pages only, never
by an app. The alternative weighed: a compiler written in Python over CPython's `ast` on the
host (exact front end, no native wheel) with a self-hosted parser for the playground (a
`pegen`-generated Python parser running on the VM) — two front ends that must agree, against
one crate that runs everywhere. If the native wheel ever proves a burden, the wasm build of
the same crate runs on the host under `wasmtime`; the code does not change.

**Bytecode is an API for the LSP too**: `frontage check`'s three rules already read templates
statically; a compile pass that emits the same diagnostics is a fourth reader of one grammar.

### 3.10 What a page loads, and where it runs

`frontage.wasm` (the runtime, one file per version, app-independent, cached across a site —
`RUST.md` §1's principle), `glue.js` (the handle table, the DOM buffer drain, the promise
bridge, the loader; a few kilobytes), `frontage.<hash>.fbc` (the framework's reached modules,
compiled), `app.<hash>.fbc`, and a component's `_browser/` when reached. Four requests, as
now. **The floor is wasm MVP with bulk memory**: no exception handling, no reference types,
no GC, no JSPI, no string builtins — every browser released since 2020, lower than the 0.10
interpreter's Safari 15.2. The runtime also runs **natively**: it is plain Rust with a host
trait for the browser's services, so `cargo test` executes the SPEC suite at native speed with
a mock host, and a fuzzer runs the VM without a browser or node in the room.

### 3.11 Tests, and the two Pythons

The tests in `tests/` run under pytest on CPython today. Under this design they run **three
ways**: pytest on CPython (the reference), the same files compiled and executed on the VM
natively under `cargo test` (differential: every assertion that CPython passes, the VM must),
and the browser suite through the real build. `SPEC.md`'s lines stay the specification; the
census (§2.4) becomes a conformance list, one test per builtin, dunder and method it names.
Where CPython and the VM must differ (§3.4), the difference is a test that asserts the VM's
behaviour and a line in the chapter.

## 4. What it changes in the documents that came before

- **`FASTER.md` §2 (the interpreter)**: stands for 0.10 as shipped. The variant, the Docker
  build and the pin become the fallback path once the runtime passes parity, and go at 1.0.
- **`FASTER.md` §3 (the core in C) and `RUST.md` §3.1 (Home A)**: replaced. There is no shim,
  no `USER_C_MODULES`, no GC audit against a conservative collector; the core is §3.8.
  `RUST.md`'s step 1 (`_core.sort`, a kilobyte, days) is still worth doing on MicroPython
  *now*, because it ships a fix this year and the spike may say no.
- **`FASTER.md` §4 (the DOM stream)**: unchanged in design, native in implementation.
- **`RUST.md` §3.2 (Home B, modules of their own) and §4 (the analysis)**: unchanged; the
  runtime's interop (§3.7) is the same contract with a cheaper handoff.
- **`FASTER.md` §6–§8 (closure, chunks, swap)**: unchanged; `.fbc` where it says `.mpy`;
  `dev.swap` drops modules from the VM's module table instead of `sys.modules`; a swap that
  keeps module-level signals by name is a VM operation.
- **`CLAUDE.md`'s MicroPython rules** — no `typing`, no dataclasses, `type(x) is T` over
  `isinstance` — stay while MicroPython is a target, and the census says the code already
  fits the subset either way.

## 5. Budget and gates

| | MicroPython, the bar | target | gate |
|---|---|---|---|
| runtime over the wire, brotli | 107,984 | ≤ 90,000 (no parser; §3.6 delegation) | **≤ 120,000** at the spike, ≤ 100,000 at parity |
| a Python call | 49 ns | ~20 ns (§2.2 floor 16) | **≤ 25 ns** |
| a method call with attribute lookup | 84 ns | ~30 ns (inline cache) | ≤ 40 ns |
| `profile_rows`: create 1,000 rows, DOM, templates | 71 ms (139 upstream) | ≤ 20 ms with the native core | **≥ 2× MicroPython** at the spike with the *Python* core; the 20 ms is `FASTER.md`'s gate for the native one |
| boot to first paint, `counter` | 52 ms | ≤ 40 ms (no framework parse, smaller wasm) | no slower |
| browser floor | Safari 15.2 / Chrome 95 / Firefox 100 | any 2020 browser | |

Size discipline is the risk Rust brings: `core::fmt` (never in the hot path; a hand formatter),
generics (a `Value` API that is not generic over types), `panic = "abort"`, `opt-level = "z"`,
`wasm-opt -Oz`, and a size test in CI that fails the build past the budget, the way
`tests/test_build.py` refuses the upstream interpreter today.

## 6. The roads not taken, with the number that closed each

- **RustPython** — 22.8 MB; `Rc` objects without a cycle collector; a full CPython
  compatibility target that this project does not have. Its bytecode and compiler design are
  worth reading (`rustpython-compiler-core`); its code is not the base.
- **Monty** — 3.7 MB of brotli for a subset without inheritance, properties, `super`,
  generators, t-strings or user exceptions, on `wasm32-wasip1` behind a WASI shim; built to
  sandbox an agent's code for milliseconds, which is a different problem. The right thing to
  take from it is the *shape* — ruff's parser, an own bytecode VM, external functions as the
  only door — and the confirmation that ruff's crates are on crates.io and build to wasm.
- **Edge Python** — 160 KB with no classes and no exceptions; a data point that a Rust
  subset-VM can be small, and a warning about what "97 % of the grammar" leaves out.
- **Python compiled to JavaScript** (Transcrypt, Brython, or our own) — V8's JIT for free,
  and every semantic corner (`//`, `%`, big ints, exceptions across generators, `await`) as a
  helper call or a deviation; no wasm, no linear memory for the frame, and the framework's core
  would be JavaScript with Python syntax. `FASTER.md` §10's objection stands. The one honest
  point in its favour — that a JIT beats an interpreter — is answered by asking how much
  Python a page runs after the core is native: under a millisecond per 1,000 rows.
- **A WasmGC target** (a compiler emitting GC types, `externref` fields, JS string builtins,
  the host's collector) — the best long-term shape for a dynamic language in a browser, and
  a compiler project rather than a runtime project: Rust cannot emit it, the runtime library
  would have to be written in the compiled language, and the floor is Safari 18.2 for GC and
  26.2 for strings. Revisit in 2028 with a probe of `Signal` compiled that way.
- **Pyodide** — `DESIGN.md` §12; 1.5 MB, 844 ms.
- **Keeping MicroPython and doing `RUST.md`** — the incumbent, and the answer if the spike
  misses its gate: a Rust core behind a shim, at 108 KB, with the semantic list of §1 carried
  as documented differences.

## 7. The plan

**The spike, three weeks, one person, go/no-go at the end.**

1. Week 1 — the VM: values, the collector, `str`/`list`/`dict`/`tuple`/`set`, functions,
   closures, classes with MRO and `property`, exceptions as `Result`, the compiler crate over
   ruff's parser emitting `.fbc`, `cargo test` against a first hundred conformance cases.
2. Week 2 — coroutines and generators as heap frames, the handle table and `js`, the
   promise bridge, `asyncio` over the host loop, `re` over `RegExp`, `json`, formatting, the
   glue and a boot; `reactive.py` and `store.py` compiled and their tests passing under node.
3. Week 3 — `view.py`, `dom.py`, `flow.py`, `template.py`, `router.py` compiled; the
   `counter`, `todo` and `rows` examples booting from `frontage.wasm`; `profile_rows` on it;
   the size and speed numbers against §5's gates.

**If go**, in dependency order, each with the browser suite as the gate: the rest of the
framework and the components (parity with the 21-test browser suite and `tests/` under the
differential runner); `serve`, `build`, `prerender`+hydration, the chunks on `.fbc`; the
native core (§3.8) — `FASTER.md` step 2 landing here instead of in C; the playground on the
wasm compiler; the chapters; the release, with MicroPython kept as `--runtime micropython`
for one minor version and the `_runtime/` variant retired at 1.0. Realistically three to four
months to parity, and a long tail of "this Python thing does not work" afterwards, the way
MicroPython's list in `CLAUDE.md` grew — which is the cost to say out loud before starting.

**If no-go**: `RUST.md` as written, and this document stays as the measured reason.

## 8. Risks, and the decisions to take

The risks: **the long tail of Python** (every builtin has ten corners; the census bounds it
and the differential suite finds it, but it is months, not weeks); **size in Rust** (Monty is
the cautionary number; the budget test is the guard); **the floor is not the page** (3× on
dispatch may be 1.5× on `profile_rows` until the inline caches and the native core land —
which is exactly what the spike's third week measures); **two runtimes in flight** for a
release; and **a native wheel** in the release path.

1. **Run the spike, or stay with `RUST.md`?** Recommendation: run it — three weeks buys a
   measured answer to the largest architectural question the project has, and `RUST.md`
   step 1 (the sort) ships meanwhile either way.
2. **Sequencing against `FASTER.md` step 2.** Recommendation: the spike *before* the core in
   C or in a MicroPython shim; that is the work a runtime of our own would throw away.
3. **The compiler's home**: a Rust crate over ruff's parser shipped as a native wheel (§3.9,
   recommended), or a Python compiler over CPython's `ast` with a self-hosted parser for the
   playground.
4. **`str` as UTF-8 in Rust (recommended) or as JavaScript strings** — §3.5.
5. **The subset's documented differences** (§3.4) — which ones an app may rely on, and the
   chapter that says so.

## 9. The spike, run (2026-09-08)

Decisions taken before it started: run it; the compiler is a Rust crate over ruff's parser;
`str` is UTF-8 in Rust. The code is `rust/` (`rust/README.md` is the map). Nothing of it is
committed.

**What runs.** Ten differential cases (`rust/py/tests/cases/`) match CPython 3.14 byte for
byte under `--stress`, a collection at every safe point. The framework's own unit tests run
unchanged on the runtime, natively and inside `frontage.wasm` under node: `reactive` 32,
`store` 17, `view` 9, `reactive_view` 32, `renderer` 7, `router` 17, `m2` 23, `m5` 14, `m6`
6 — 157 passing, the whole set in 1.4 s on the wasm. The JavaScript bridge (globals, arrays,
objects, callbacks, promises, timers, `JsException`) passes its own test. `counter`, `todo`
and `tools/profile` boot from `frontage.wasm` in Chromium and work; `frontage/runtime.py`
knows the platform as `FRONTAGE`.

**Against the gates of §5.**

| | MicroPython, frontage's build | this runtime | gate | |
|---|---|---|---|---|
| runtime over the wire, brotli | 107,984 | **178,994** (`-Os`); 164,327 at `-Oz`, which is 27% slower | ≤ 120,000 | **not met** |
| framework bytecode, 19 modules, raw / brotli | 64 KB / 37 KB (`.mpy`) | 114 KB / 50.6 KB (`.fbc`, varints + a string table per module; the first format was 343 KB) | — | close |
| a Python call, native, opt 3 | 49 ns (wasm) | 25 ns native; a method call 80 ns in the wasm | ≤ 25 ns | met natively, parity in wasm |
| `profile_rows`, create 1,000 rows, DOM, templates | 71.1 ms | **70.1 ms** (first build: 212) | ≥ 2× | **not met: parity** |
| `For`, null renderer | 44.0 | 42.8 | | parity |
| swap two rows / update every 10th | 4.4 / 1.4 | 4.5 / 1.1 | | parity |
| effects create+dispose 1,000 / 1,000 text holes | 4.8 / 6.6 | 6.3 / 7.4 | | slightly behind |
| boot to first paint, `counter` | 52 ms | 62–82 ms, four requests | no slower | behind, noisy |

**Where the speed went.** The dispatch floor of §2.2 (3× MicroPython on `fib`) did not carry
to the page, exactly the risk §8 named. It took the in-place call convention (arguments
already on the shared stack, no argument copy), the direct-mapped class-attribute cache, a
per-site global cache keyed on dict versions, `LoadMethod`/`CallMethod`, inline `ForIter`
for ranges and lists and int fast paths to get from 212 ms to 70 — and that is MicroPython's
number, not half of it. What is left is what a *Python* core costs: the framework's own
`_children`/`_build_nodes`/holes are Python method calls and allocations on both runtimes,
and neither interpreter makes those free. The 2× the gate wanted is the native core of §3.8
(`FASTER.md` step 2), not the interpreter — on either runtime. CPython 3.14 is still about 2×
faster than this VM natively; the gap is its specialising interpreter, which is months of
work and lands on the same wall.

**Where the size went.** By function, the wasm is 80% this runtime's own code — the
interpreter loop 26% (one function, everything inlined into it), the builtins 16%, operators
10%, formatting 5%, attributes 4%, modules 4% — and 15% Rust's standard pieces (float
printing and parsing 4%, sorting 3%, `libm` 2.5%, `core::fmt` 1.7%, `hashbrown` and
`dlmalloc` 1% each; Unicode case tables 1.5%). The precompiled Python standard modules are
12.5 KB of the brotli. Delegating floats and Unicode case to JavaScript as §3.6 planned would
buy about 7%, and `-Oz` buys 8% for 27% of the speed: **the gate is 60 KB away and the
runtime is not made of anything removable at that scale**. The honest floor for a Rust
interpreter with these semantics looks like 150–160 KB brotli, against MicroPython's 108.

**What is not written.** `match`, metaclasses and class keywords, generator finalisation on
collection, `re` over `RegExp` (§3.6, designed, not built), `exec`/`eval` of source in the
page, `__slots__` as anything but a dict, `build`'s import walk (the page reads a manifest),
and the long tail §8 predicted: `round`, `%`-formatting alignment, `str.center`'s odd
padding, `math.fsum`, cross-type numeric equality, dict keys with user `__hash__`, `Counter`
reads that must not insert — each found by a differential case or a framework test and
fixed the same day, and each a reminder that the tail is long.

**Reading.** The speed gate failed at parity and the size gate failed by half again; the
correctness gate passed with room. So the runtime is real and works, and it does not by
itself buy what it was meant to buy: the page is no faster and 70 KB heavier. What it does
buy is the platform the rest of §3 assumed — a runtime we can put a native reactive core
into as VM types (§3.8) rather than through MicroPython's C API and `mp_obj_t`, errors as
`Result` all the way down, one bytecode from one compiler, a bridge whose cost we set. The
recommendation of §8.1 stands corrected by the numbers: **the interpreter alone is not the
win; the native core is, and it can be built on either runtime.** The decision that remains
is whether to build it here (a runtime of our own to maintain, 60 KB heavier, everything
else in hand) or in MicroPython (`RUST.md` §3.1, the C shim, the upstream tail). That is
`TODO.md`'s item.
