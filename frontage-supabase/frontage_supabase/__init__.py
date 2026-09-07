"""Supabase and PostgREST for frontage: queries as resources, and the database as a signal.

No JavaScript and no Supabase library. Supabase's data API *is* PostgREST — HTTP and JSON — and
the browser already has `fetch`, so this package is Python the whole way down and the same
`Client` talks to a Supabase project or to a PostgREST you host yourself by changing one URL.

Three things it is for:

- **A query is a `Resource`.** `client.resource(lambda: ...)` rebuilds its query from whatever
  signals it reads, so typing in a search box refetches and nothing else on the page moves.
- **Row-level security is a first-class outcome.** `PostgrestError.denied` separates "the policy
  refused you" from "the request was wrong" and from "the network is down", which look identical
  in a `try` and mean opposite things.
- **Realtime is a signal.** The database pushes, one hole updates. Streamlit's answer to
  changing data is to re-run the script on a timer.

The authorisation lives in Postgres, next to the data, and applies to every client that ever
connects — which is why a browser-only app over a database is a reasonable thing to build and
not a hole in the wall. Ship the **anonymous** key; the service key bypasses row-level security
by design and a browser is a place anyone can read.
"""

from .client import Auth, Client, PostgrestError, Result, Table
from .query import Query
from .realtime import Channel

__all__ = ["Auth", "Channel", "Client", "PostgrestError", "Query", "Result", "Table"]
