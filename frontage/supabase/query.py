"""Building a PostgREST request, and reading what comes back when it refuses.

PostgREST turns a Postgres schema into an HTTP API, so a query is a URL: filters are query
parameters, ordering is a parameter, paging is a header. Nothing here talks to the network —
`Query` is an immutable description that `Client` executes — which is what makes it testable on
CPython and cheap to rebuild inside a memo.
"""

__all__ = ["PostgrestError", "Query"]

# Percent-encoding, because MicroPython has no `urllib.parse`. Unreserved characters are
# RFC 3986's; everything else goes as %XX, including the `,` and `.` PostgREST uses as
# grammar, since those are separators only where we put them literally.
_SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def quote(text):
    out = []
    for byte in str(text).encode():
        char = chr(byte)
        out.append(char if char in _SAFE else "%%%02X" % byte)
    return "".join(out)


def _value(value):
    """A filter's right-hand side. `None` is PostgREST's `null`; everything else is text."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _list(values):
    """`in.(a,b,c)`. A member containing a comma, a quote or a paren must be double-quoted, and
    an embedded double quote doubled — the same rule as CSV, which is what PostgREST parses."""
    parts = []
    for value in values:
        text = _value(value)
        if any(c in text for c in ',"()'):
            text = '"' + text.replace('"', '""') + '"'
        parts.append(text)
    return "(" + ",".join(parts) + ")"


class PostgrestError(Exception):
    """A request PostgREST answered with a status outside 2xx.

    Carries the whole body, because PostgREST's is a JSON object with `message`, `details`,
    `hint` and `code`, and the hint is usually the thing that tells you what you did wrong.
    """

    def __init__(self, status, body, url=None):
        self.status = status
        self.body = body if isinstance(body, dict) else {}
        self.url = url
        self.code = self.body.get("code")
        self.message = self.body.get("message") or (body if isinstance(body, str) else "") or f"HTTP {status}"
        self.details = self.body.get("details")
        self.hint = self.body.get("hint")
        # `super().__init__`, not `Exception.__init__(self, …)`: MicroPython has no
        # unbound `Exception.__init__`, and the AttributeError only appears in a page.
        super().__init__(self.message)

    @property
    def denied(self):
        """Row-level security refused, as opposed to the request being wrong or the network
        being down.

        Worth its own name because the two look identical in a `try` and mean opposite things:
        a denied read is the policy working, and the fix is a policy or a session, never a
        retry. `42501` is Postgres's insufficient_privilege; `PGRST301`/`PGRST302` are
        PostgREST's own for a missing or unacceptable JWT.
        """
        return self.status in (401, 403) or self.code in ("42501", "PGRST301", "PGRST302")

    def __str__(self):
        parts = [self.message]
        if self.hint:
            parts.append("hint: " + str(self.hint))
        if self.details:
            parts.append(str(self.details))
        return " — ".join(parts)


class Query:
    """An immutable PostgREST request. Every method returns a new one, so a query held in a
    variable can be branched without the branches affecting each other."""

    def __init__(self, table, params=None, headers=None, columns=None, method="GET", body=None, single=False):
        self.table = table
        self.params = list(params or ())  # (key, value) pairs: PostgREST allows repeats
        self.headers = dict(headers or {})
        self.columns = columns
        self.method = method
        self.body = body
        self.single = single

    def _with(self, **changes):
        state = {
            "table": self.table,
            "params": self.params,
            "headers": self.headers,
            "columns": self.columns,
            "method": self.method,
            "body": self.body,
            "single": self.single,
        }
        state.update(changes)
        return Query(**state)

    def _param(self, key, value):
        return self._with(params=self.params + [(key, value)])

    # -- shaping ------------------------------------------------------------------------------

    def select(self, columns="*"):
        """The columns to return. PostgREST's embedding syntax works here as written:
        `select("id,name,city(name)")` returns the joined row."""
        return self._with(columns=columns)

    def order(self, column, desc=False, nulls_first=False):
        spec = column + (".desc" if desc else ".asc") + (".nullsfirst" if nulls_first else ".nullslast")
        return self._param("order", spec)

    def limit(self, count):
        return self._param("limit", str(int(count)))

    def offset(self, start):
        return self._param("offset", str(int(start)))

    def range(self, start, end):
        """Rows `start` to `end` inclusive, as a header — which is also what makes PostgREST
        return the total in `Content-Range`, so a grid can know how far it can scroll."""
        headers = dict(self.headers)
        headers["Range-Unit"] = "items"
        headers["Range"] = f"{int(start)}-{int(end)}"
        return self._with(headers=headers).count()

    def count(self, kind="exact"):
        return self._prefer("count=" + kind)

    def one(self):
        """Exactly one row, as a dict rather than a list of one.

        PostgREST enforces this itself through the Accept header and answers 406 when the
        filters matched none or several, which is stricter and more useful than taking `[0]`.
        Named `one` rather than `single` because `single` reads as a column modifier next to
        `select` and `order`, and this is a modifier of the whole request.
        """
        headers = dict(self.headers)
        headers["Accept"] = "application/vnd.pgrst.object+json"
        return self._with(headers=headers, single=True)

    def _prefer(self, value):
        headers = dict(self.headers)
        existing = headers.get("Prefer")
        headers["Prefer"] = existing + "," + value if existing else value
        return self._with(headers=headers)

    # -- filters ------------------------------------------------------------------------------

    def filter(self, column, operator, value):
        """The general form, for an operator this class does not name."""
        return self._param(column, operator + "." + _value(value))

    def eq(self, column, value):
        return self.filter(column, "eq", value)

    def neq(self, column, value):
        return self.filter(column, "neq", value)

    def gt(self, column, value):
        return self.filter(column, "gt", value)

    def gte(self, column, value):
        return self.filter(column, "gte", value)

    def lt(self, column, value):
        return self.filter(column, "lt", value)

    def lte(self, column, value):
        return self.filter(column, "lte", value)

    def like(self, column, pattern):
        return self.filter(column, "like", pattern)

    def ilike(self, column, pattern):
        return self.filter(column, "ilike", pattern)

    def is_(self, column, value):
        """`is.null`, `is.true`, `is.false` — the only three Postgres allows after IS."""
        return self.filter(column, "is", value)

    def in_(self, column, values):
        return self._param(column, "in." + _list(values))

    def contains(self, column, values):
        """Array or jsonb containment, `@>`."""
        return self._param(column, "cs." + _list(values))

    def overlaps(self, column, values):
        return self._param(column, "ov." + _list(values))

    def match(self, **equals):
        """Several `eq` at once. Keyword order is not preserved by MicroPython, and does not
        need to be: `AND` is commutative and PostgREST joins these with AND."""
        query = self
        for column in sorted(equals):
            query = query.eq(column, equals[column])
        return query

    # -- the request --------------------------------------------------------------------------

    @property
    def path(self):
        """`table?select=…&col=eq.…`, ready to hang off the PostgREST base URL.

        Sorted, so that two queries built by different code paths with the same meaning produce
        the same string — which is what lets a `Resource` use this as its source and not refetch
        when nothing really changed.
        """
        params: list = list(self.params)
        if self.columns:
            params.append(("select", self.columns))
        pairs = sorted((quote(k) + "=" + quote(v)) for k, v in params)
        return self.table + ("?" + "&".join(pairs) if pairs else "")

    def __eq__(self, other):
        return (
            isinstance(other, Query)
            and self.path == other.path
            and self.method == other.method
            and self.headers == other.headers
            and self.body == other.body
        )

    def __repr__(self):
        return "<Query " + self.method + " " + self.path + ">"
