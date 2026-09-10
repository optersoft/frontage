# frontage-api

FastAPI's shape — decorators, types as the contract, OpenAPI — on **axum and hyper**, with the
handlers running on frontage's own Python runtime: one `Vm` per worker thread, in the same
address space, with no CPython, no C API and no GIL.

**[`API.md`](../../API.md) at the repository root is the design, the measurements and the
plan.** §6.1 is built and its gate is met; §6.2, the surface, is next.

**If you have a FastAPI application, this is not for you.** There is no pydantic, no
SQLAlchemy, no `requests`, no pandas, and the handler bodies are the part that does not port.
For an existing app that wants a faster server, use
[Granian](https://github.com/emmett-framework/granian) with FastAPI — it is mature, it is
fast, and beating it is the gate this had to clear to exist at all.

What is new here is one thing: **the same schema object validates a form as it is typed in the
browser and the body that form posts.** Not a generated copy or a shared document — one
`frontage.schema` record, one runtime, one file, now in one repository.

```sh
cd rust && cargo build -p frontage-api --profile api
rust/target/api/frontage-api rust/api/examples/spike/app.py     # from the repository root
python3 rust/api/tests/routes.py                                # 13 assertions
python3 rust/api/tests/routes.py --stress                       # the same, collecting at every safe point
python3 rust/api/tests/gate.py                                  # 21 assertions about the sign-in gate
```

## A private site

`--auth google` puts Google sign-in in front of everything the server answers, the static
files included, and lets nobody in who is not on the list (`API.md` §5a):

```sh
export FRONTAGE_AUTH_GOOGLE_CLIENT_ID=…            # or AXUM_OAUTH_*, the fleet's namespace
export FRONTAGE_AUTH_GOOGLE_CLIENT_SECRET=…        # $CREDENTIALS_DIRECTORY beats the environment
export FRONTAGE_AUTH_BASE_URL=https://governor.optersoft.com
export FRONTAGE_AUTH_ALLOWED_EMAILS=someone@optersoft.com,another@optersoft.com
frontage-api app.py --auth google --auth-label governor
```

The OAuth client's *Authorized redirect URI* is `{BASE_URL}/auth/google/callback` and nothing
else: the state cookie is scoped to `/auth/google`, so a callback registered anywhere else
never receives it and every sign-in ends at "state missing". `rust/api/examples/private/` is
the whole shape — a `www/` of prerendered pages, plus the `/healthz` and `/version` a deploy
probes, which are the only paths that answer without a session.

**A site with nothing dynamic in it needs no app at all**, and then there is no interpreter in
the process:

```sh
frontage-api --serve ./www --auth google --auth-label governor
```

`/healthz` and `/version` are answered by the server itself there, because a fleet smoke test
requires **200** and would read the gate's `303` as a dead app.

**Every option is also `FRONTAGE_API_*` in the environment** — `_APP`, `_SERVE`, `_ADDR`,
`_WORKERS`, `_PATH` (colon separated), `_AUTH`, `_AUTH_LABEL` — because a fleet unit's
`ExecStart=` is the binary path and nothing else, and its configuration arrives through
`EnvironmentFile=`. A flag wins over the variable. The process signals `READY=1` on
`$NOTIFY_SOCKET` when the workers are up, which is what a `Type=notify` unit waits for.
