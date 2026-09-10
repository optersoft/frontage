# frontage-api: FastAPI's shape, on axum, on frontage's own Python runtime — the 0.1 plan

**Status: unbuilt. This is the plan, written 2026-09-10 from the question "a replacement of
FastAPI using axum instead of starlette — in frontage or a new project?"** The answer to the
second half is *a new project*, for the reasons in §3, and this repository is it. The first
half turned out to be the smaller decision: what makes this worth building is not axum
underneath, it is that the Python above it is **frontage's own runtime** — a Rust VM in the
same address space, with no CPython, no C API and no GIL. Everything else follows from that.

## 0. The decision, in eight sentences

**FastAPI is Starlette plus pydantic plus OpenAPI, and each of those three has a better
answer inside this fleet.** Starlette becomes axum and hyper, which the fleet already
deploys behind `hive-server`. Pydantic becomes `frontage.schema`, which already validates
the same records in the browser, so **one schema checks a form as it is typed and the body
that form posts**. OpenAPI becomes `frontage/schema/jsonschema.py`, which already emits the
JSON Schema a document needs. **The Python that runs the handlers is `frontage-vm`, embedded
as a Rust struct rather than an interpreter process**, so calling a handler is a method call
of about 25 ns and not a trip through the C API holding a global lock. **One `Vm` per worker
thread, sharing nothing**, which is what a GIL-less server looks like when the interpreter
was designed for it. **The standard library is the Rust ecosystem**: polars, turso, reqwest
and chrono as native modules, the way the browser's standard library is the DOM. **The cost
is the ecosystem, and it must be said as plainly as `COMPONENTS.md` §8 says "no pandas"**:
no pydantic, no SQLAlchemy, no boto3, and every IO is a crate someone writes a module for.
**The gate is milestone 1**: if a VM-per-thread axum server does not beat Granian plus
FastAPI on the same box, this stops there and the answer is Granian.

## 1. What FastAPI is, and what of it is actually used

FastAPI's surface is large and its reputation rests on a small part of it. The honest way to
size the job is to list it and mark what the fleet's own FastAPI code uses, because
`frontage.remote` and `frontage.chat` are the two consumers that would move first and they
are the acceptance tests.

| FastAPI feature | `frontage.remote` | `frontage.chat` | here |
|---|---|---|---|
| `APIRouter`, path decorators | yes | yes | **§4.5** |
| path, query and body from annotations | query params, coerced | JSON body | **§4.6** |
| pydantic models in and out | no, hand-rolled | no | `frontage.schema`, **§4.6** |
| `Depends` | no | no | **§4.7**, small version |
| `BackgroundTasks` | no | no | `spawn`, **§4.7** |
| `StreamingResponse` | binary series | SSE token stream | **§4.4** |
| `HTTPException` | 400, 413 | 4xx | **§4.8** |
| CORS middleware | yes, every response | yes | **§4.8** |
| static files | `src.app(static="www")` | no | axum, **§4.8** |
| OpenAPI + `/docs` | unused | unused | **§4.9**, from `jsonschema.py` |
| WebSockets | no, SSE on purpose | no | **§5** |
| `TestClient` | 22 server tests | yes | **§4.10**, the reason the layer is Python |
| security utilities, OAuth2 flows | no | no | **§5**, `axum-oauth` exists |
| `lifespan` | no | key from env at import | **§4.7** |

**Two things stand out.** The fleet uses perhaps a fifth of FastAPI, and the fifth it uses is
almost exactly the fifth that is *cheap* — decorators, annotations, exceptions, a streaming
response and a test client. What it does not use is the part that carries pydantic's weight.
And **the one feature it uses that is not cheap is `TestClient`**, which is why §4.10 makes
the framework layer Python running on CPython under pytest, exactly as `reactive.py` is the
specification for `core.rs`.

## 2. Where we stand, measured

Three sets of numbers decide this, and two of them already exist.

**Frontage's VM, from `RUNTIME.md` §9** (2026-09-08, this laptop):

| | frontage VM | MicroPython |
|---|---|---|
| `fib(27)`, per call (9 ops + a frame) | **16.2 ns** | 49.3 ns |
| a bytecode operation | **1.55 ns** | ~5 ns |
| a Python call, native, opt 3 | **25 ns** | — |
| a Python call in the wasm | 49 ns | — |

The 25 ns is the number that matters here, because **in a native server that is the whole
cost of entering Python**. There is no boundary to cross: the VM is a Rust struct in the same
address space, `vm.call(handler, &args, &[])` is a method call, and a `Value` is a word.

**Granian, from its own benchmarks** (2026-08-05, Ryzen 7 5700X, 16 CPUs, Python 3.13,
Granian 2.8.1, 128 connections). Granian is the right comparison because it is the same
architecture with CPython in the middle: hyper and tokio underneath, PyO3 embedding, one
interpreter and one asyncio loop per worker *process* because of the GIL.

| server | interface | requests/s |
|---|---|---|
| Granian | RSGI, GET | 143,073 |
| Granian | ASGI, GET | 140,814 |
| Granian | WSGI, GET | 143,939 |
| Granian | ASGI, GET (the *vs* run) | 125,539 |
| Granian | ASGI, ECHO — reads the request body | **63,181** |
| uvicorn (httptools) | ASGI, GET | 51,051 |
| gunicorn | ASGI, GET | 34,532 |
| hypercorn | ASGI, GET | 9,318 |

**Three readings, and they set this design more than anything else does.**

**RSGI is within 2% of ASGI.** Granian's own dict-free interface — a scope object and
`response_str` instead of `send({"type": …})` — buys 1.6%. So the message *format* is not the
cost, and a plan whose pitch is "a leaner protocol" would be measuring noise.

**Reading the body halves throughput**, 125,539 to 63,181. That is the cost, and it is the
cost of extra round trips through the Python event loop for something Rust already has in a
buffer. This is the same finding as `dom.rs`: the browser's DOM op stream made a batch one
crossing because per-operation crossings dominated. **The server rule is the same shape** —
§4.4.

**HTTP/2 costs about 16%** at two runtime threads (238,104 GET on HTTP/1 against 199,991),
which is worth knowing before promising it.

**What is not measured yet, and milestone 1 exists to measure it:** a `Vm` per thread inside
axum, on this laptop and on a fleet VM, against Granian plus FastAPI on the same box. The
gate is in §6.

## 3. Why a new repository, and not `frontage/rust/`

The question asked. Four reasons, in the order they bite.

**The workspace's job is a wasm.** `frontage/rust/` has `default-members = ["vm", "compile",
"py"]` and a `web` crate built only for `wasm32-unknown-unknown`; its gate is
`cargo test --profile native` plus `mk runtime.build`, and its release artefact is 2.5 MB of
committed bytes in a wheel a browser downloads. Adding tokio, hyper, rustls, polars and
turso to that workspace puts tens of megabytes of dependencies and minutes of compile behind
every runtime change, for crates the browser can never link.

**The dependency points the wrong way.** `frontage.remote` and `frontage.chat` declare
`fastapi` in extras today (`polars = [… "fastapi", "uvicorn"]`). They can only move to this
server if it is a thing frontage may depend on — or, better, a thing that depends on
frontage and takes those two server halves over. A server inside `frontage/rust/` cannot be
either.

**The fleet's convention already answers it.** Shared Rust lives in a sibling repo consumed
by path: `hive-server`, `axum-oauth`, `turso-share`, `d2`, `ecdysis`. This is
`frontage-vm = { path = "../frontage/rust/vm" }` and nothing new is invented. The path-dep
rule's consequence applies in full: **a change in the VM reaches this repo with no manifest
diff, and an uncommitted edit in `frontage/rust/` ships with a deploy**, so a provider
commit goes alongside the consumer.

**Starlette is not in FastAPI's repository either**, which is the analogy the question was
built on.

**And one reason not to overstate:** this repo will hold Python of its own (§4.5), and that
Python is a package that must reach PyPI. It is not "the Rust half of frontage"; it is a
project with a wheel, a binary and a version of its own.

## 4. The architecture

### 4.1 The process: axum, tokio, one VM per thread

```
                 tokio multi-thread runtime
   ┌─────────────┬─────────────┬─────────────┐
   │  worker 0   │  worker 1   │  worker N   │   hyper + axum, shared listener
   │  ┌───────┐  │  ┌───────┐  │  ┌───────┐  │
   │  │  Vm   │  │  │  Vm   │  │  │  Vm   │  │   one interpreter per thread,
   │  └───────┘  │  └───────┘  │  └───────┘  │   sharing nothing at all
   └─────────────┴─────────────┴─────────────┘
```

`Vm` holds `Rc` and a `Box<dyn Host>`, so it is not `Send` and not `Sync` — which is not a
limitation here, it is the design. **N cores are N interpreters, each with its own heap, its
own collector and its own asyncio loop**, in one process and one address space. A request is
handled entirely on the thread it arrived on; nothing is sent between VMs, so nothing needs
to be `Send`.

Two consequences worth stating because they are the opposite of CPython's.

**There is no GIL, so there is nothing to release.** Granian pays processes per worker
because a CPython interpreter cannot share a process usefully; its free-threaded mode is
experimental as of its 2.0. A CPU-bound frontage handler stalls its own thread and no other.

**Global state must be explicit.** Anything genuinely shared — a connection pool, a cache, a
polars `LazyFrame` scanned once — lives in Rust behind an `Arc`, and each VM sees it through
a native module. A module-level Python dict is per-thread, and that is a documented property
of the server, not a bug. `frontage.remote`'s per-query result cache is exactly this case and
becomes a Rust cache behind `_polars`.

**Where a handler blocks.** A native module that blocks (a file read, a synchronous query)
must go through `tokio::task::spawn_blocking` and return to the VM's thread, because a
blocked worker thread is a blocked interpreter. That is the same rule Granian states with
`--blocking-threads` and it needs saying in the module-author documentation.

### 4.2 The seam: an RSGI-shaped protocol object

RSGI's real contribution is not speed, it is the *shape*: a connection-level `scope` and a
`protocol` object with awaitable methods, instead of a stream of event dicts. That shape is
the right internal seam here, for a reason specific to this repo rather than to performance.

```python
async def app(scope, protocol):        # the seam, not the user's surface
    body = await protocol()            # the whole body, one crossing
    protocol.response_str(200, [("content-type", "application/json")], out)
```

`scope` carries `proto`, `http_version`, `method`, `path`, `query_string`, `headers` (with
`get_all`), `client`, `server`, `scheme`, `authority`. `protocol` answers `__call__` for the
whole body, `__aiter__` for chunks, and `response_empty` / `response_str` / `response_bytes`
/ `response_file` / `response_stream` / `client_disconnect`.

**Why this seam and not axum's own types straight into the handler:** because it can be
implemented twice. Natively it is a Rust object over `http::Request`. On CPython it is a few
dozen lines over anything — including Granian itself, which speaks RSGI. So **the framework
layer is Python written against the seam, tested with pytest on CPython, and ported to
nothing**: it *is* the shipped code, running on the VM. That is the repo's own rule — Python
first, tested on CPython, then the hot parts ported — applied one level up, and it is what
gives §4.10 a real test client for free.

The names above are RSGI's, from its specification. The shape is copied; no code is read from
it, and nothing in this repository is written with Granian's or FastAPI's source open. The
clean-room rule of `frontage/CLAUDE.md` holds here too: docs and specifications yes, source
no.

### 4.3 The loop: driving asyncio from tokio

The VM's `asyncio` is already written for exactly this (`rust/vm/src/lib/asyncio.py`): "in
the browser the loop is driven by JavaScript (`setTimeout` for timers, a microtask for the
ready queue), so nothing here blocks", and `loop_turn()` returns the delay until the next
timer. **The server wants the browser's shape with tokio in JavaScript's place**, not the
native runner's blocking `sleep_ms`.

```
a request arrives  →  vm.call(handler)  →  the coroutine runs to its first await
                                        →  loop_turn() drains the ready queue
a Rust future ends →  set_result on the pending future  →  loop_turn() again
                                        →  the coroutine finishes  →  response
```

**The one piece the VM does not have is the host future hook**: a way for a Rust future to
complete into a Python awaitable. The browser has it as `jsffi._await` over a JavaScript
promise; the server needs the same over a `tokio` future, on the VM's own thread, so no lock
is involved. Granian's mechanism is the reference for the *shape* — a native awaitable whose
`set_result` raises StopIteration into the loop, and a scheduler stepping the coroutine —
and it is worth noting how much of Granian's version is GIL bookkeeping we simply do not
have: no `call_soon_threadsafe`, no context copy across a lock, no `Python` token.

This hook is **a commit in `frontage/rust/`**, made alongside the consumer per the path-dep
rule, and it is the first item of milestone 1 because nothing else can be measured without
it.

### 4.4 One crossing per request

Granian's 125,539 → 63,181 on a body read is the budget-setting measurement, and the rule it
implies is the one `frontage/CLAUDE.md` already states for the DOM: *count the crossings, and
count the Python calls*.

- **Parse, route and match in Rust.** Python sees a resolved handler and its arguments, never
  a URL to split or a header list to scan.
- **The body arrives whole, decoded, as one value.** JSON is parsed in Rust into VM values
  directly — the VM's `json` is native already — so a handler taking a record gets a dict and
  never sees bytes.
- **The response leaves in one call.** `response_str` and friends take status, headers and
  body together, which is the whole reason RSGI's methods are shaped that way.
- **A handler that never awaits costs exactly one `vm.call`.** No loop turn, no future, no
  scheduler.
- **A `RecordingHost` counts them**, the way `RecordingRenderer` counts DOM operations, and a
  test asserts the count per request shape. A change that adds a crossing to a hot path
  brings its number.

### 4.5 The surface: what the user writes

```python
from frontage.api import App, HTTPError
from frontage.schema import record, text, integer, optional

App.title = "trips"
app = App()

Trip = record(("id", integer(ge=0)), ("borough", text()), ("note", optional(text()), None))


@app.get("/trips/{trip_id}")
async def trip(trip_id: int, verbose: bool = False):
    row = await db.one("select * from trips where id = ?", trip_id)
    if row is None:
        raise HTTPError(404, "no such trip")
    return row


@app.post("/trips")
async def create(body: Trip):        # validated by the schema, coerced, errors as 422
    return {"id": await db.insert(body)}
```

Path parameters, query parameters and the body come from the annotations, exactly FastAPI's
idea, and the conversion is `frontage.schema` with `coerce=True` — which is what that switch
was written for: *"a query parameter is always a string"*. A schema failure is a 422 whose
body is the `(path, message)` pairs `validate` already returns.

**The package is `frontage_api`, its own wheel** (§7 has the reasoning): a top-level import
name, not a `frontage.api` subpackage, so a shared record is a two-package install and a
server never carries the browser's runtime. `from frontage.schema import record` still reads
the same on both sides, which is all §4.6 needs.

### 4.6 Validation is `frontage.schema`, and it is the strongest single argument

This is the part with no equivalent anywhere, and it deserves to be the pitch.

```python
# shared.py — imported by the page and by the server
Booking = record(("email", email()), ("nights", integer(ge=1, le=30)), ("notes", optional(text())))
```

In the browser that record renders a form and checks it as it is typed (`frontage/schema/form.py`).
On the server the same record validates the body that form posts. **Not a generated copy, not
a shared JSON Schema document, not two libraries kept in step — the same Python object, on the
same runtime, in one file.** FastAPI cannot do this because pydantic does not run in a
browser. Full-stack TypeScript does it, and it is the main thing TypeScript has that Python
has not; this closes it.

`frontage/schema/jsonschema.py` already renders a record as JSON Schema, so §4.9's OpenAPI
document is nearly free, and `repr` of a schema is the code that builds it, which makes an
error message and a document readable by the same means.

### 4.7 Dependencies, lifespan, background work

Small versions of three FastAPI ideas, and no more.

**`Depends`** becomes a callable resolved once per request and cached per request, with
`yield` for teardown. It is thirty lines and the one FastAPI feature whose absence is
immediately felt (an authenticated user, a database handle).

**Lifespan** is an `async` context manager per *worker*, which is the point worth documenting:
it runs once per thread, N times per process. Anything that must happen once for the process
is Rust, before the workers start.

**Background work** is `spawn` from `frontage.reactive`, which already exists and already
names its tasks for the read-after-await warning. A task outlives its request and dies with
its worker.

### 4.8 What axum and `hive-server` bring, so we do not write it

`hive-server` is the fleet's front door and this server should sit behind it exactly as
broker, drive, alma, academy and code do: in-process ACME TLS, the `:80` → `:443` redirect,
security headers, brotli and gzip compression, `/healthz` and `/version`, app-layer
DoS-resilience, graceful drain, and the ecdysis fork/exec **zero-downtime hot swap**. That
last one is a thing Granian only approximates with process respawn, and the fleet has it in
production. The app hands `hive_server::Host` a plain `axum::Router`, which is precisely the
shape this server produces.

⚠ **`axum` must stay at the version the fleet unifies on** — `hive-server` pins `axum = "0.8"`
and `axum-oauth` pins `=0.8.9` because that is what dioxus 0.7 re-exports. A split minor
breaks type unification at compile time, not at link time. This repo follows the same pin.

Static files, CORS and request limits are `tower-http`, already in `hive-server`'s graph.
Authentication, when it is wanted, is `axum-oauth`, which is why §5 says this repo writes no
security utilities.

### 4.9 OpenAPI

The document is generated from the routes and their schemas through `jsonschema.py`, and
served with a docs page. It is a milestone of its own (§6.3) rather than a footnote because
it is the reason many people pick FastAPI, and because it is the natural test of §4.6's
claim: if the shared record cannot produce a correct schema for both a form and a document,
the claim is weaker than it sounds.

### 4.10 Testing

Three ways, matching how frontage tests itself.

**pytest on CPython over the seam.** The framework layer is Python, the protocol object has a
CPython implementation, and a test client is a function that builds a scope and collects the
response. This is where routing, coercion, dependencies and OpenAPI are specified — and it is
the reason `TestClient`, the one expensive thing the fleet's FastAPI code actually uses, comes
free.

**`cargo test` natively.** The differential cases of `rust/py/tests/cases/` grow with whatever
Python the server needs; the native modules get their own tests.

**End to end against the real binary.** `hurl` or plain `reqwest` against a running server,
including TLS through `hive-server`, plus the throughput runs of §6.

## 5. What this will not do, deliberately

Naming these is worth more than pretending they are coming, the way `COMPONENTS.md` §8 does.

- **CPython compatibility.** No pydantic, no SQLAlchemy, no boto3, no `requests`, no
  `pandas`. This is not a server for existing FastAPI applications and must never be
  described as one — a *migration* story would be a lie, since the handler bodies are the
  part that does not port. **If an app needs the ecosystem, the answer is Granian plus
  FastAPI, and this repository's README should say so in its first paragraph.**
- **The full polars expression API on day one.** §6.4 takes the subset `frontage.remote`
  uses and grows it by case.
- **Security utilities.** `axum-oauth` is the fleet's OIDC stack and it is Rust; a second
  implementation in Python would be a liability, not a feature.
- **WebSockets, at first.** `frontage.remote` chose Server-Sent Events on purpose — *"a
  session per client is Streamlit's model and the reason to avoid one has not changed"* — so
  SSE is milestone 2 and WebSockets wait for an app that needs them.
- **HTTP/3, and HTTP/2 as a headline.** HTTP/2 comes from hyper when it is wanted, at the 16%
  its own benchmark shows.
- **A plugin ecosystem, an admin, an ORM.** A `_turso` module and `frontage.schema` are the
  data story.

## 6. The plan, in order, with its gates

### 6.1 The spike, and the gate that decides everything

The host future hook in `frontage/rust/` (§4.3), an axum server with a `Vm` per worker
thread, the protocol object in Rust, and exactly two routes: a static `GET` returning JSON,
and an echo that reads and re-encodes a JSON body. No routing table, no schemas, no
decorators.

**Measured on this laptop and on a fleet VM, against Granian 2.8.1 + FastAPI and uvicorn +
FastAPI on the same box, at the same concurrency**, reporting requests/s and p99 for both
routes.

**The gate: ≥ 2× Granian + FastAPI on the echo route.** The echo is the honest one, because
it is where Granian loses half its throughput and where the one-crossing rule should pay.
A static GET flatters any Rust server and proves little. **If the gate is missed and the
profile does not name a fixable cause, this stops here** and the recommendation becomes
Granian, in a paragraph in this file. `RUNTIME.md` §9 is the precedent: a gate was missed,
it was written down as missed, and the reading changed.

### 6.2 The surface

The Python framework layer against the seam: `App`, the method decorators, path and query and
body from annotations through `frontage.schema`, `HTTPError` and a problem-JSON body,
`Depends`, lifespan, `spawn`, `StreamingResponse` and SSE, static files, CORS. pytest on
CPython throughout, and the `RecordingHost` crossing budget of §4.4 with a test per request
shape.

**Gate:** `frontage.chat`'s server half runs on it unchanged in behaviour, with its tests
passing, and the one-crossing budget holds for a no-await handler.

### 6.3 OpenAPI and the docs page

From the routes and `jsonschema.py`. **Gate:** the shared-record example of §4.6 produces a
schema that validates the same values the form accepts, asserted as a test rather than by
eye.

### 6.4 The standard library, as native modules

One crate each, behind cargo features so a server pays only for what it imports:

| module | crate | first consumer |
|---|---|---|
| `_http` | `reqwest` | `frontage.chat` — hold the key, stream the answer |
| `_polars` | `polars` (lazy, parquet, csv) | `frontage.remote` — **polars is Rust, so it is no exception** |
| `_turso` | `turso` | the fleet's own data story |
| `_datetime`, `_env`, `_log`, `_fs` | `chrono`, `std`, `tracing`, `tokio::fs` | everything |

**`_polars` is the interesting one and the reason this section is not an afterthought.**
Polars' Python package is a PyO3 wrapper over the `polars` crate, so a native module exposes
*the same crate* under the same spelling, with no CPython anywhere. `frontage.remote`'s
server half then moves like `chat`'s does, and the whole stack under the Python is one
language.

Three cautions to carry in rather than discover: the surface is a **subset grown by case**
(`scan_parquet`, `col`, `filter`, `group_by`, `len`, `sort`, and the comparison dunders on an
`Expr` type — that is what `remote`'s queries use); polars with lazy, parquet and csv is tens
of megabytes and minutes of compile, hence the feature; and **method chains must stay cheap**,
because polars' Python returns new lazy frames over an `Arc` and a module that copies instead
turns `frame.filter(…).sort(…)` into a data copy. That last one is measured in the spike,
beside the requests/s.

**Gate:** `frontage.remote`'s 22 server tests pass against `_polars`, and its
`/series/{name}` answer is byte-identical to the FastAPI version's.

### 6.5 Ship

A binary per platform built by Actions on a tag, the way `fpy` is a release asset, and a
wheel that finds it — `cli/frontage_rt.py`'s `_asset_urls` is the pattern, ⚠ **including its
lesson: `releases/latest` is not safe during a release**, because a release exists from the
moment its tag is pushed and its assets arrive minutes later. `hive-server` as the front
door, `mk server.deploy` like every other fleet app, and the two consumers' extras changed
from `fastapi` + `uvicorn` to this.

**Gate:** one of the two consumers deployed on a fleet VM behind the gateway, with the
throughput of §6.1 re-measured there.

## 7. Decisions taken, and the risks that remain

**The name is `frontage-api`, and the objection against it did not survive being written
out.** The objection was that the name reads as a subpackage of frontage, which §3 argues it
is not. But §3 argues about repositories and wheels, not about product identity, and those
are different things: `pytest-cov` is a separate repository with its own version and its own
release path, is genuinely an extension of pytest, and is correctly named for it. **This is
family by its own pitch.** §4.6 only pays off with a frontage page in front of it, validation
is `frontage.schema`, background work is `frontage.reactive`'s `spawn`, the language subset
is documented in frontage's own `rust/README.md`, and §5 says outright that this is not for
existing FastAPI applications. Someone who finds the server first is not the target reader;
someone who arrives from frontage wanting a server is, and the prefix is what that person
searches for. So the prefix earns its place.

**What is genuinely weak is the suffix, and the alternatives are worse.** "The frontage API"
already means something in this project's vocabulary — `Signal`, `Memo`, `mount`, the names
`_exports.py` tabulates — so `frontage-api` collides with a phrase in use, and it names the
wrong half: the artifact is a server, and what it serves is not only an API. The fleet
convention (`hive-server`, `staff-store`) would say **`frontage-server`**, which is worse:
**`frontage serve` is already the dev server command**, so the production server and the
static dev server would differ by one character. **`frontage-http`** is the clean option, no
collision anywhere, slightly colder to read. `frontage-api` is kept because a reader arriving
from FastAPI understands it instantly, and that beats a mild clash with an internal phrase.
**Decided, and reversible for the cost of a rename until §6.5 puts a wheel on PyPI.**

**Two wheels, decided, and not for the reason first given.** The first draft of this section
said a single wheel would drag the browser runtime's 2.5 MB onto every server, which is a weak
argument: 2.5 MB is nothing by server standards. **The real reason is the wheel tag.** Frontage
builds one pure-Python `py3-none-any` wheel from hatchling. A server binary with polars in it
needs a platform matrix — `manylinux_x86_64`, `macosx_arm64`, and every other target §6.5
builds. Merging them would turn every browser user's install into a platform wheel for a
server they are not running.

**And the import is a top-level `frontage_api`, not `frontage.api`.** A second wheel writing
into frontage's package directory would technically resolve — `frontage/__init__.py`'s
`__getattr__` falls through to a submodule import, deliberately, for `from . import reactive`
— but it is an overlapping install with an uninstall hazard, hatchling's
`packages = ["frontage"]` claims that directory, and the generated `__init__.pyi` static view
would not know the subpackage exists, so an editor and `ty` would disagree with the runtime.
A separate top-level name is also a different spelling from a real subpackage, which is what
makes the name in the paragraph above mislead less than it appears to.

**The ecosystem is the whole risk, and it is not mitigable.** Every argument above is true and
none of it matters to someone whose handler needs SQLAlchemy. The mitigation is honesty in the
README (§5) and picking first consumers that are ours.

**The gate may fail.** §6.1 says what happens then, and it is a real possibility: Granian is
mature, well engineered and fast, and its authors have solved problems this plan has not met
yet. Being second to a good answer is a fine outcome as long as it is written down.

**The VM is young.** `rust/README.md`'s list of gaps is short but real, and a server will find
its own: `__slots__` is not enforced, `eval` is unwritten, `re` is what `RegExp` does. Each
gap is a differential case first, which is the established rule.

**Two consumers is a thin acceptance test.** `remote` and `chat` are both ours and both
small. A third — something with authentication, a database and a form, end to end with a
frontage page in front of it — is what would actually prove §4.6, and it should be built
before 1.0 rather than assumed.
