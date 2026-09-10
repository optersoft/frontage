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

## 3. Where it lives: `rust/api/`, in this repository

**Decided 2026-09-10, against what this section first said.** It argued for a separate
repository beside `frontage/`, consumed by path the way `hive-server` is; it was built that
way, and then merged here with its history under `rust/api/`. The four arguments it made are
worth keeping, because two of them were answered by the move and two were answered by
configuration.

**"The workspace's job is a wasm."** Still true, and the reason `api` is a workspace member
but **not a default member**: `cargo test --profile native` and `mk runtime.build` never
compile tokio, hyper or axum, because the runtime's gate must not slow down to check a
bytecode change. `cargo build -p frontage-api --profile api` is the server's own line, and
`[profile.api]` exists for one word — `panic = "unwind"`, because `[profile.release]` sets
`abort` for the wasm and under that a panic in one request handler takes the process down
instead of failing one connection.

**"The dependency points the wrong way."** This one *reverses*. `frontage.remote` and
`frontage.chat` declare `fastapi` and `uvicorn` in extras today, and in one repository they
can simply use the server that is already here. As a sibling repo they could not, unless
frontage took a dependency on it or it took over both server halves.

**"The fleet's convention already answers it."** It did, for a sibling. Inside one repository
the convention that applies is the *other* one this repo already follows: the runtime is
`rust/`, the Python package is `frontage/`, and a Rust crate belongs beside the crates it
links against. `frontage-vm = { path = "../vm" }` is shorter than the sibling form and cannot
go stale.

**"Starlette is not in FastAPI's repository."** An analogy, and analogies do not survive
contact with a wheel tag — see below.

**What does not change is the distribution, and it is the one thing worth holding on to.**
Frontage builds a single pure-Python `py3-none-any` wheel. A server binary with polars in it
needs a platform matrix — `manylinux_x86_64`, `macosx_arm64`, and every other target §6.5
builds. So this is **one repository and two wheels**: merging the repos did not merge the
distributions, and the browser user who never runs a server must not be handed a platform
wheel. The Python package of §4.5 is therefore a top-level `frontage_api` with a pyproject of
its own, not a `frontage.api` subpackage — §7 has the rest of that reasoning, which the merge
leaves standing.

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
async def app(scope, protocol):  # the seam, not the user's surface
    body = await protocol()  # the whole body, one crossing
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

⚠ **Written 2026-09-10, and it needed no change to the runtime at all** — this paragraph
used to say the hook was "a commit in `frontage/rust/`, made alongside the consumer per the
path-dep rule". It is not: `_host` is a native module registered from *this* repository
through `vm.builtin_modules`, and it builds its future by calling
`asyncio.get_event_loop().create_future()` and settles it by calling `set_result`, all
through the VM's public surface. The provider's working tree is untouched.

That is worth more than the commit it saved. **The VM's embedding surface was already
sufficient for a server**, which is not something the spike could assume: `roots` for
temporary native roots, `builtin_modules` for a native module, `gen_resume` for the coroutine
protocol, and an `asyncio` whose loop already expects to be driven from outside because the
browser drives it from `setTimeout`. The one thing the server does differently from the
browser is *what* it waits on, and that was never the VM's business.

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
async def create(body: Trip):  # validated by the schema, coerced, errors as 422
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
- **Security utilities *in Python*.** A validator, a session, a token check written in the
  handler language would be a liability, not a feature. ⚠ **The sign-in gate is not an
  exception to this and §5a says why** — it is Rust, it is the server's, and an app declares
  nothing.
- **WebSockets, at first.** `frontage.remote` chose Server-Sent Events on purpose — *"a
  session per client is Streamlit's model and the reason to avoid one has not changed"* — so
  SSE is milestone 2 and WebSockets wait for an app that needs them.
- **HTTP/3, and HTTP/2 as a headline.** HTTP/2 comes from hyper when it is wanted, at the 16%
  its own benchmark shows.
- **A plugin ecosystem, an admin, an ORM.** A `_turso` module and `frontage.schema` are the
  data story.

## 5a. The sign-in gate, and a rule this repository broke on purpose

**Built 2026-09-10.** `frontage-api APP.py --auth google` puts Google sign-in in front of an
app: `/login`, `/logout`, `/auth/google/start`, `/auth/google/callback`, and a middleware over
everything else — a valid session passes, `/api/*` without one gets a bare `401`, and any other
path gets a `303` to the login page carrying where it was going. The gate sits **above the
static files**, which is the point of the whole exercise: a private site is a directory of
prerendered HTML, and `ServeDir` would otherwise hand it to anyone with the URL.

**What asked for it.** `governor`, the company's private strategy folder, is 25 prose pages
built by `frontage site` and it has been readable only on a laptop, because the fleet's gateway
has no browser-facing sign-in: `require_secret` is a header a fronting proxy presents, which a
browser cannot. The commented `[apps.governor]` block in `hive-deploy/fleet.toml` has been
waiting on exactly this, and its smoke asserts the gate rather than the pages — an anonymous
`GET /` answering `200` is the failure, not the success.

**Why it is here and not in `axum-oauth`, which already has it.** It should have been. That
crate is the fleet's one OIDC stack, and §5 named it as the reason this repository writes no
security utilities. What blocks it is not design, it is distribution: **this repository is
public and its CI resolves the whole cargo workspace**, and cargo reads every member's
manifest — a path dependency on a private sibling is a broken checkout on every Actions run,
optional or not. The alternatives were a git dependency needing forge credentials in a public
repo's CI, or moving the gated binary out to the private side, which trades one file here for a
Rust toolchain and a deploy pipeline in a repository of Markdown. So the flow is here, and
`rust/api/src/auth/` says at the top of every file that it is the second copy.

**It is a copy on purpose, decision for decision.** The state cookie scoped to `/auth/google`;
`leeway = 0` on cookies this process signed and the provider's default on the `id_token`; the
forced JWKS refetch on a `kid` miss; `email_verified` accepted as a bool or the string Google
used to send; the client secret read from `$CREDENTIALS_DIRECTORY` before the environment; the
signing secret persisted `0600` so a deploy does not sign everyone out. Where one of those
turns out to be wrong, **both files change** — that is the standing cost this section is the
receipt for.

**What it deliberately is not.** No users, no roles, no per-path rules, and no Python API: an
allow-list of addresses either contains you or does not, the session claims are `{sub, exp}`,
and an app that wants more than "everyone I named may read everything" wants a different tool.
The gate re-checks nothing per request, so a session's lifetime is the revocation window —
30 days by default, and that is a knob (`…_SESSION_TTL_SECS`), not a promise.

**Configuration** is env, read under `FRONTAGE_AUTH_*` first and `AXUM_OAUTH_*` second,
first-found-wins and never a union: `…_GOOGLE_CLIENT_ID`, `…_GOOGLE_CLIENT_SECRET`,
`…_BASE_URL` (which settles both the callback URL and whether cookies carry `Secure`, so the
two cannot drift apart — unset reads as production), `…_ALLOWED_EMAILS`, and the two optional
ones above. **Every missing piece is fatal at startup**, including an empty allow-list: a
private site nobody can open is a better failure than one anybody can.

**What a fleet deploy needed, and it was not the flow.** Three things, found by reading
`hive-deploy` rather than by running it: a `binary` app's unit is **`Type=notify`**, so the
process must send `READY=1` on `$NOTIFY_SOCKET` or systemd kills it at `TimeoutStartSec`
believing it never started; that unit's **`ExecStart=` carries no arguments** — it is the
release's binary path and nothing else — so every option is now also `FRONTAGE_API_*` in the
environment, which is what `EnvironmentFile=` supplies; and the smoke **requires 200**, so a
`liveness_path` behind the gate answering `303` fails every deploy. That last one is why
`/healthz` and `/version` are public and why the fleet.toml block's original plan — smoke `/`
and assert the redirect — cannot work as written.

**`--serve DIR` is the fourth**, and it is the one that made the deploy small: a private site
is a directory of prerendered pages, so the server takes the directory and runs **no
interpreter at all** — no app module, no `frontage_api` package tree to ship beside it, no VM
per worker. `governor` deploys as this binary plus its `www/`, and that is the whole artifact.

⚠ **The signing secret must not live inside the tree being served, and `--serve` is where
that is easy to get wrong.** Two silent failures, not one: the file server hands the secret to
anyone with a session, who can then mint one for anybody; and a deploy rsyncs that tree with
`--delete`, so the secret changes under the running process and everyone is signed out. In
`--serve` mode the default therefore sits one directory *above* what is served
(`/home/<app>/.auth_secret` in the fleet's layout, beside the `public/` a deploy replaces),
and a configured path inside it stops the server before it binds. Found by reading a
`bootstrap --dry-run`, not by a leak.

⚠ **An empty `--serve` directory is refused too, and for a reason the gate creates.** A
gated site answers every anonymous request with a redirect *whether or not there is anything
behind it*: the fleet smoke passes, `/healthz` passes, `mk gate.check` passes, and the first
person to see the truth is a reader who has signed in and got a 404. `governor` spent its
first deploy exactly there — pointed at the workdir's `public/` while a **packaged** app's
assets install into the release root — so an empty tree now stops the server at startup.

**Gate:** `python3 rust/api/tests/gate.py` — 22 assertions against the real binary with no
network in them, because everything up to the consent screen is ours (the redirect, the PKCE
challenge, the state cookie) and the authenticated half is minted from the secret the server
persisted, which is the only honest way to assert that a signed-in visitor gets the page. The
last six run the server the way a box does: `--serve`, no arguments, everything from env.

## 6. The plan, in order, with its gates

### 6.1 The spike, and the gate that decides everything

The host future hook in `frontage/rust/` (§4.3), an axum server with a `Vm` per worker
thread, the protocol object in Rust, and exactly two routes: a static `GET` returning JSON,
and an echo that reads and re-encodes a JSON body. No routing table, no schemas, no
decorators.

**Measured on this laptop and on a fleet VM, against Granian 2.8.1 + FastAPI and uvicorn +
FastAPI on the same box, at the same concurrency**, reporting requests/s and p99 for both
routes.

**Status: the gate is met, on this laptop, 2026-09-10, and §4.3 is written.** What exists is
`server/`, `examples/spike/app.py` and `tests/routes.py`: axum 0.8.9, one OS thread per worker
with a `current_thread` runtime and a `Vm` of its own, the app's `ROUTES` dict read once at
load, the body handed to the handler whole as `bytes`, and `str` or `bytes` back.

**A handler can await.** `_host.sleep` is the hook of §4.3 — a tokio deadline settling a
Python future, the shape every native module in §6.4 will use. A coroutine is driven in Rust
rather than by an asyncio `Task`: `send(None)`, a `StopIteration` is the answer, a yielded
`Future` means suspend. That costs no Task object and no callback per step, and **an
`async def` that never suspends never touches the event loop at all**, which is what keeps
the budget below. Thread-per-core is what makes a suspended handler correct: a task on a
`current_thread` runtime never migrates, so a coroutine resumes on the VM it started on. The
VM is never borrowed across an `.await`, so only `Send` values cross one and the router stays
a plain `axum::Router` — which is what `hive-server` takes in §4.8.

**`tests/routes.py` is thirteen assertions over the real binary**, and the one that matters
most is the last: **40 suspended requests on a single worker interleave in 88 ms** rather than
queueing for 400. Two ordering bugs it caught are worth naming, because both look like a
deadlock and neither is. Polling before pumping declares every awaiting handler stuck, since
a turn of the loop settles the last future and reports "nothing scheduled" in the same breath.
And a delay measured before a poll is stale the moment that poll advances the coroutine into
a *new* await, which declared a two-await handler stuck between its two sleeps.

M4 MacBook, 10 cores, macOS 25.6, one worker, 64 connections, 1 KB bodies both ways, `oha`
as the client. Medians of three; every row reproduces within about 2% across runs, and these
figures are **after** the coroutine driver of §4.3, not before it.

| server | GET rps | ECHO rps | ECHO p99 |
|---|---|---|---|
| **frontage-api** | **180,276** | **171,252** | 0.74 ms |
| granian 2.8.2 + bare ASGI | 119,141 | 62,515 | 1.56 ms |
| granian 2.8.2 + FastAPI 0.141 | 55,077 | 28,676 | 4.33 ms |
| uvicorn + FastAPI | 13,451 | 11,928 | 5.53 ms |

**5.97× Granian + FastAPI on echo, against a gate of 2×.** The like-for-like is the bare ASGI
row, since neither side has a framework layer yet, and that is **2.74×**.

**Awaiting costs nothing when nobody awaits.** The figures above are within 2% of the ones
measured before the driver existed (177,031 and 169,293), which is the point of driving a
coroutine in Rust: an `async def` that returns without suspending takes one `gen_resume` and
never reaches the event loop, so the route that *can* await is not slower for the requests
that do not.

**The prediction of §4.4 is the finding, and it is the part worth keeping.** Reading the
request body costs us **4.4%** (177,031 → 169,293) and costs Granian **48%** (125,864 →
65,428), on the same box against the same client. That is the whole argument for one crossing
per request, measured rather than asserted: the body is already in a buffer in Rust, and
Granian's cost is the trips through the Python event loop to fetch it, not the parsing.

⚠ **Measure a warm binary, or measure Gatekeeper.** The first execution of a
freshly built binary on macOS is scanned by `syspolicyd`, and that scan lands on whichever
route runs first: one run read 151,512 on GET while ECHO, measured moments later in the same
process, read a normal 167,417. Nothing in the server explains a GET slower than an ECHO.
Run the binary once before believing anything it reports, and treat a figure that contradicts
the route ordering as a machine artefact rather than a finding.

⚠ **Our figures are floors, and Granian's are not.** This laptop's loopback tops out near
**193,000 requests/s**: an 8-worker server answers 190,415 / 192,645 / 193,132 at 64 / 128 /
256 connections, and two `oha` processes at once split it (95,394 + 95,581 = 190,974). So the
frontage-api rows are pressed against the harness and the true number is higher, while the
Granian rows sit well below it and are real. **The ratios above are lower bounds**, and the
4-worker run says the same thing more loudly: 193,123 against 59,415, which is 3.25× and is
our ceiling divided by their genuine number. Measuring our own limit needs a client off this
machine, which is the fleet-VM half of this milestone and is not done.

⚠ **What is not yet in the number.** No routing table (two paths, a linear scan), no schema
validation, no dependency resolution, no OpenAPI — §6.2 and §6.3 add all of it and each costs
something. And this is macOS on Apple Silicon with four performance cores and six efficiency
ones, not the Linux box Granian's own published figures come from; nothing here should be
compared against those numbers, only against the rows measured beside it.

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

**Status: partly built, 2026-09-10.** `frontage_api/` is the package: `App` with the seven
method decorators, a router, arguments built from a route's spec, `HTTPError`, the response
rules, and `frontage_api.testing.Client` — a client with no server under it, because
`App.handle` is the whole of what the server calls, so a test calls the same thing and a test
run has no socket in it. 21 tests on CPython, and `rust/api/tests/routes.py` runs the same
surface on the real runtime, 20 assertions, all of them also under `--stress`.

**Built since**: `Depends` (resolved once per request, generator dependencies closing after
the response), lifespan (`on_startup`/`on_shutdown`, per *worker* — one interpreter per thread
means N times per process), `Stream` with Server-Sent Events, static files served by Rust, and
CORS as a constructor argument rather than a middleware to remember.

✅ **The gate is met.** `frontage.chat`'s server half runs on this, its 28 tests pass, and the
real binary streams a conversation token by token — 35 ms, 58 ms, 79 ms for three tokens a
model "thinks" about for 20 ms each. `Conversation.stream` is **unchanged**: an async
generator is an async generator on either transport. What it needed was async generators in
the runtime, which is the provider commit below.

✅ **A route reads its types from the signature, and §4.5's example is real.** It was not:
this runtime parsed annotations and *discarded* them, so there was no `__annotations__` to
read and the spec had to be spelled out in the decorator. The provider commit that fixed it
took the shape this section predicted — **annotations as source text** — because the runtime
already never evaluated them, so storing the spelling changes nothing that runs today and
`def g(x: Undefined)` stays legal. It needed no bytecode format change either: the dict is
built from string constants at function-definition time, the way defaults already are.

The decorator still works and **wins where both speak**, so a route can override what a
signature says without editing the signature. Two details worth stating: `_resolve` handles
**both shapes**, because on CPython an annotation is the object itself and that is where
handlers get written and tested; and an annotation nothing can resolve is **ignored, not an
error**, so a parameter typed for a reader rather than for the router costs nothing.

**What the surface costs, measured.** Same box and client as §6.1, one worker, 64 connections.
`GET` is the 1 KB constant, `ECHO` reads a 1 KB body, `PATH PARAM` converts an integer out of
the path and looks a row up, `VALIDATED` posts JSON through a schema. The bare-ASGI column
hand-writes all four, because that is what "no framework" has to mean if the columns compare.

| server | GET | ECHO | PATH PARAM | VALIDATED |
|---|---|---|---|---|
| **frontage-api** | **135,852** | **128,717** | **118,612** | **100,161** |
| granian + bare ASGI, hand-written | 124,034 | 61,762 | 117,998 | 56,113 |
| granian + FastAPI + pydantic | 55,687 | 28,902 | 33,941 | 21,452 |
| uvicorn + FastAPI + pydantic | 13,024 | 12,090 | 11,009 | 9,916 |

**The surface costs 25%**, against §6.1's hand-rolled dispatch on the same two routes
(180,276 and 171,252). That is the price of matching, binding, conversion, validation and the
response rules, and it is worth naming rather than hiding: everything below is measured *with*
it paid.

**The number to keep is the last column: 100,161 against 21,452, or 4.7×.** Pydantic's
validator is compiled Rust and `frontage.schema` is pure Python interpreted on our own VM, so
that axis favours FastAPI and this is still not close — because **the validator is not what
costs**, the server around it is. The same reading in the other direction: on `PATH PARAM` we
are within half a percent of hand-written ASGI with no framework at all (118,612 against
117,998), so the framework is costing about what having no framework costs.

⚠ **Async generators were missing from the runtime, and the gate could not be met without
them.** `async def` with a `yield` produced a plain generator, so `async for` refused it —
and `frontage.chat`'s reply function is exactly that shape, as is every streaming model
client. The fix needed no compiler change at all, which is the part worth keeping: both
`await` and `yield` suspend the same frame, so a driver has to tell them apart, and CPython
wraps the yielded value to mark it. Here the two spellings are *already different opcodes*
(`Yield` against `GetAwaitable` + `YieldFrom`), so the VM records which one suspended the
frame and that is the whole discriminator. `__anext__` returns `_asyncgen.ANext`, which is
Python rather than Rust for one reason: propagating an inner `await` means `yield`ing it, and
only a generator function can do that. A differential case matches CPython 3.14 byte for byte, and it costs the browser
**2,398 raw bytes** of runtime (673,967 raw, 214,784 brotli), which is what a language feature
this central should cost. 61 browser tests pass on the rebuilt wasm.

⚠ **Two things this cost, and both are the kind that only appear when code runs.**
`frontage.schema` imported `re` at module scope, and this runtime's `re` is implemented over
the browser's `RegExp` and *raises on import* off the browser — so the one module §4.6 needs
on both sides was unimportable on a server. It uses a regex for exactly one thing,
`text(pattern=…)`; every other format there is hand-written string code. The import is now
inside that branch, and `ast.walk` in `cli/graph.py` still finds it, so a page still packs it.
And `--stress` earned its keep: the first version of the loader left a freshly bound
`App.handle` in a Rust local across two further calls into Python, which collected it and
reused the slot — `TypeError: 'list' object is not callable`, from a `handle` that had become
a list. Root a value on the line after it exists, not at the end of the function.

**Gate:** `frontage.chat`'s server half runs on it unchanged in behaviour, with its tests
passing, and the one-crossing budget holds for a no-await handler.

### 6.2b The validator, compiled once instead of walked every time

**Done 2026-09-10, and it was the cheap half of a question worth asking.** The question was
whether `frontage.schema` should get a native half in Rust the way `reactive.py` has
`core.rs` — and the framing that came with it needed one correction first: **the browser runs
the same VM**, so a native `_schema` would not be a server-only thing, it would be bytes in
every page's download. The cheap move was available first, and it is the one pydantic made
for its version two: stop walking the schema tree per value, decide what can be decided at
construction, and execute a plan.

The profiler said where to look, and it was not where the argument would have put it. **The
record dispatcher was the single largest cost — 35% of the walk, more than any field type.**
Per field it unpacked a three-tuple, looked the key up *twice* (`in` then `[]`), built
`path + "." + name` for an error that will not happen, and resolved `t.check` through the
instance. All of that is decided in `Record._compile` now. Two more: a bare `text()` answers
after its type check instead of testing four constraints it does not have, and an unbounded
`integer()` never calls `_bounds` at all.

| | before | after |
|---|---|---|
| `Big.validate`, 8 fields, isolated | 3.18 µs | **2.51 µs** |
| per field | 0.398 µs | **0.314 µs** |
| the same record through a POST | 4.07 µs | **3.31 µs** |
| that route, end to end | 72,659 rps | **76,630 rps** |

**21% off the validator, 5.5% off the request**, for no WebAssembly bytes and no second
implementation — and the page gets it too, because it is the same code. Medians of three,
measured back to back against the stashed original on a quiet machine, which is the only way
these numbers mean anything.

⚠ **One finding is worth more than the speed, because it inverts a habit.** `d.get(name,
MISSING)` reads like the faster choice and is the slower one here: **two dict lookups are two
opcodes, while `.get` is an attribute resolution and a call** — 0.52 µs against 0.61 for eight
fields on this runtime. The CPython instinct is exactly backwards. Measure on the runtime that
will run it.

**And the answer on the Rust half: not yet, with the number to revisit it by.** Validation is
now 3.31 µs of a 13.05 µs request, so a native validator that made it free would buy **+34% on
a validated route** — real, but the cost is bytes in every page, a second implementation to
keep in step, and the "Python is the specification" rule that has served this repo well. The
bigger target is now the **8.44 µs floor every route pays** before any user code runs, and
§6.3 and §6.4 are each worth more than 34% on one route. Revisit when a profile says the floor
is dealt with and validation is still the top line.

### 6.3 OpenAPI and the docs page

From the routes and `jsonschema.py`. **Gate:** the shared-record example of §4.6 produces a
schema that validates the same values the form accepts, asserted as a test rather than by
eye.

### 6.4 The standard library, as native modules

One crate each, behind cargo features so a server pays only for what it imports:

| module | crate | first consumer |
|---|---|---|
| `_http` ✅ | `reqwest` | `frontage.chat` — hold the key, stream the answer |
| `_polars` | `polars` (lazy, parquet, csv) | `frontage.remote` — **polars is Rust, so it is no exception** |
| `_turso` | `turso` | the fleet's own data story |
| `_datetime`, `_env`, `_log`, `_fs` | `chrono`, `std`, `tracing`, `tokio::fs` | everything |

**`_http` is built (2026-09-10), and it is `_host`'s shape rather than a new one.**
`_http.request(method, url, headers, body, timeout, stream)` answers an asyncio future a
tokio task settles, and the pump carries it across — the same three moving parts §4.3 proved
with a sleep, which is what made this a day's work instead of a design. Two things in it are
worth keeping in mind. A **streamed** response never enters the interpreter: its `Response`
stays in Rust behind a token, owned by a task that pulls one chunk at a time into a channel
of capacity one, so a slow reader slows the transfer instead of buffering a model's whole
answer into a page's memory. And an **in-flight request has to answer a delay of its own**,
because `park_value` reads "no deadline anywhere" as a handler awaiting something nobody will
complete — without that, the very first `await client.get(...)` is declared a deadlock and
answered 500. It polls at 1 ms while anything is outstanding; a per-thread notification would
remove the poll and is the same machinery `server.rs`'s `MAX_PARK` note defers.

The Python half is `frontage_api/client.py`: a `Client` holding a base URL, headers and a
timeout, `get`/`post`/…, and a `Response` with `json()`, `raise_for_status()` and — for the
streamed form — `chunks()` and `lines()`. `lines()` is the one that earns its place: a chunk
boundary lands anywhere, so a partial line is held until the rest of it arrives, which is the
bug every hand-rolled SSE reader has. It reassembles in **bytes**, not text, because a
multi-byte character split across two chunks does not decode — which is what asked the
runtime for `bytes.find`/`startswith`/`endswith` (`rust/README.md`).

**Gate, and it is met:** the spike app's `/relay` fetches its own `/slowfeed` with
`stream=True` and re-emits each frame as it lands, and `tests/routes.py` asserts the frames
arrive **apart** rather than together — buffering the upstream is exactly what a chat that
does not stream looks like from the outside, and it passes every test that checks only *what*
arrived. Six assertions, no network: the peer is the same server. `--stress` passes too,
which is what says the pending futures are rooted where the collector can see them.

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
out — twice.** The objection was that the name reads as a subpackage of frontage, which §3
then argued it was not. Two things have happened since. §3 was decided the other way and this
now lives in frontage's own repository, so the family reading is not merely defensible, it is
the literal truth. And the objection was already weak before that: repository layout and
wheels are not product identity, and `pytest-cov` is a separate repository with its own
version and its own release path that is genuinely an extension of pytest and correctly named
for it. **This is family by its own pitch.** §4.6 only pays off with a frontage page in front of it, validation
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
