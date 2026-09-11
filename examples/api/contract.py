"""What the page and the server both know: one record, in a module of its own.

⚠ **It has to be a module of its own, and that is not tidiness.** Put `Signup` in `server.py`
and the page's `from server import Signup` drags the whole server module into the browser —
`frontage build` follows the import, ships `server.fbc`, and does *not* ship `frontage_api`,
which is not a browser package. The build says nothing; the page fails on
`ModuleNotFoundError` at boot. A shared contract must import only what both sides have, and
`frontage.schema` is exactly that: it runs in the page and on the server.
"""

from frontage.schema import email, integer, optional, record, text

Signup = record(
    ("name", text(min=2, max=40, strip=True)),
    ("email", email()),
    ("seats", integer(ge=1, le=10)),
    ("note", optional(text(max=200)), None),
)

#: How many seats the room has. The page shows what is left; the server is what knows.
CAPACITY = 100
