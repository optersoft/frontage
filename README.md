# frontage-api

**Nothing is built yet. [`PLAN.md`](./PLAN.md) is the whole repository.**

FastAPI's shape — decorators, types as the contract, OpenAPI — on **axum and hyper**, with
the handlers running on **[frontage](https://github.com/optersoft/frontage)'s own Python
runtime**: a Rust VM in the same address space, one per worker thread. No CPython, no C API,
no GIL.

**If you have a FastAPI application, this is not for you.** There is no pydantic, no
SQLAlchemy, no `requests`, no pandas, and the handler bodies are the part that does not port.
For an existing app that wants a faster server, use
[Granian](https://github.com/emmett-framework/granian) with FastAPI — it is mature, it is
fast, and `PLAN.md` §6.1 makes beating it the gate this project has to clear to exist at all.

What is new here is one thing, and it is in `PLAN.md` §4.6: **the same schema object
validates a form as it is typed in the browser and the body that form posts.** Not a
generated copy or a shared document — one Python record, one runtime, one file. That is the
thing full-stack TypeScript has and Python has not.

Apache 2.0, copyright Optersoft.
