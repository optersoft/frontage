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
```
