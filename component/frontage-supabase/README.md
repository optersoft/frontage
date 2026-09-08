# frontage-supabase

Supabase and PostgREST for [frontage](https://github.com/optersoft/frontage): queries as
resources, row-level security as a first-class outcome, and **realtime as a signal**.

```sh
pip install frontage-supabase
```

**No JavaScript, and nothing vendored.** Supabase's data API *is* PostgREST — HTTP and JSON —
and Realtime is a websocket, both of which MicroPython reaches directly. `supabase-js` would
have been 0.64 MB to do what `fetch` already does. This is the only component here with no
third-party code in it at all.

The same `Client` talks to a Supabase project or to a PostgREST you host yourself. Change the
URL; nothing above the transport differs.

## Reading

```py
from frontage import Signal, h, mount
from frontage_supabase import Client

db = Client("https://abcdefgh.supabase.co", "your-anon-key")

search = Signal("")

cities = db.resource(
    lambda: (
        db.table("cities").select("id,name,people").ilike("name", f"%{search()}%").order("people", desc=True).limit(50)
    )
)
```

`db.resource` builds its query inside the tracking phase, so every signal the query reads
becomes a dependency. Typing in the search box rebuilds the query and refetches; nothing else on
the page moves. It is an ordinary `Resource`, so `Loading` and `Errored` work as they always do,
and a refetch keeps the previous rows on screen.

The result carries the count when you ask for one, because a grid that cannot see the total has
to guess how far it scrolls:

```py
page = db.table("cities").select("*").range(0, 24)  # Range header + Prefer: count=exact
result = await db.run(page)
result.rows, result.count  # 25 rows, 573
```

Filters are PostgREST's: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `like`, `ilike`, `is_`, `in_`,
`contains`, `overlaps`, `match(**equals)`, and `filter(column, operator, value)` for anything
else. `one()` asks PostgREST to enforce exactly one row and answer 406 otherwise, which is
stricter and more useful than taking `[0]`.

## Writing

```py
await db.table("cities").insert({"name": "Girona", "people": 103000})
await db.run(db.table("cities").update({"people": 104000}).eq("id", 7))
await db.run(db.table("cities").delete().eq("id", 7))
```

`update` and `delete` return a query rather than a coroutine, so nothing is sent until it is
awaited. An `UPDATE` without a filter is a mistake you make once, and
`update({...}).eq("id", 7)` reads in the order it happens.

## Row-level security is an outcome, not an accident

The authorisation lives in Postgres, next to the data, and applies to every client that ever
connects. That is what makes a browser-only app over a database reasonable rather than a hole
in the wall — compare Streamlit, which holds a connection string in a process and expects you
to write the access control yourself in Python.

Three things go wrong and they look identical in a `try`, so they are separated here:

```py
try:
    rows = await db.run(query)
except PostgrestError as exc:
    if exc.denied:
        ...  # the policy refused you. Fix a policy or a session — never retry
    else:
        ...  # the request was wrong. exc.hint is usually the answer
except Exception:
    ...  # the request never reached the server. This one is worth retrying
```

`denied` is true for 401 and 403, for Postgres's `42501` (insufficient privilege) and for
PostgREST's `PGRST301`/`PGRST302`. A failed `fetch` is deliberately left to propagate as
itself: "the network is down" and "the database refused you" must not arrive as the same
exception.

> **Ship the anonymous key.** The service key bypasses row-level security by design, and a
> browser is a place anyone can read. This is the way the whole arrangement fails quietly.

## Signing in

```py
await db.auth.sign_in("ada@example.com", "…")
db.auth.user()  # an accessor: read it in a hole and the header updates itself
await db.auth.sign_out()
```

Every resource built on the client refetches when the token changes, which it must — row-level
security will answer differently for a signed-in reader.

What this deliberately does **not** do is refresh the token on a timer. A component that
silently re-authenticates in the background is a thing an app should opt into rather than
inherit, and the session is a plain signal, so scheduling a refresh is a few lines you can see.

## Realtime

The part that answers Streamlit's live dashboard outright. Streamlit's answer to changing data
is to re-run the script, on a timer if need be. Here the database pushes and one hole updates:

```py
from frontage_supabase import Channel

rows = Signal(initial_rows)
Channel(db, "cities").follow(rows).subscribe()
```

`follow` applies each change to the list: an `INSERT` appends, an `UPDATE` replaces by key, a
`DELETE` removes. That is deliberately all of it — ordering, filtering and windowing belong to
the app, which knows what its query meant.

For anything else, read the change yourself:

```py
channel = Channel(db, "orders", event="INSERT").subscribe()
h.p(lambda: f"last order: {channel.change()['record']['id'] if channel.change() else '—'}")
```

`channel.state()` is `closed`, `connecting`, `joined` or `errored`. A channel opened inside a
component closes itself when that component is disposed.

## Cost

**0 KB of JavaScript.** The Python is about 500 lines and travels in `app.tar` with the rest of
your app.

## What is not here yet

Honest list, so nothing is discovered the hard way:

- **Storage and Edge Functions.** Both are plain HTTP; neither is wrapped.
- **OAuth sign-in.** Only email and password. The OAuth flow is a redirect and a callback, and
  doing it properly means touching the router.
- **Automatic token refresh**, for the reason above.
- **Reconnecting a dropped websocket.** `channel.state()` reports `closed` and it is the app's
  call; a component that reconnects forever is worse than one that says it stopped.
- **Verified against a live Supabase project.** `tests/browser/test_supabase.py` drives the
  whole component through Chromium against a socket serving PostgREST's wire format and
  Phoenix's frames — reads, `Content-Range`, an RLS refusal, a write, sign-in, a reactive
  refetch, and a pushed row arriving in a list. What that does not prove is that Supabase
  itself behaves as its documentation says; no test here has talked to a Supabase project.
