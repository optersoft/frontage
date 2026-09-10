"""Paths, and matching one.

A path is `/trips/{trip_id}/legs` — literal segments and named parameters, the spelling
FastAPI made familiar. There is no regex here and no converter syntax in the path itself:
what a parameter *is* comes from the route's spec, so the path stays a path.

**This is the specification, and it runs in two places.** The test client dispatches through
it on CPython, and the server dispatches through it in the page's runtime. If a Rust matcher
ever replaces it for speed, this file stays the reference and a test asserts the two agree —
the same arrangement `frontage/reactive.py` has with `rust/vm/src/core.rs`.
"""

__all__ = ["Route", "Router", "compile_path"]


def compile_path(path):
    """`/trips/{trip_id}` to segments and parameter names.

    A segment is either a literal string or `None` in the parameter positions, and the names
    come back in order, so matching is a walk with no allocation per literal.
    """
    if not path.startswith("/"):
        raise ValueError("a path must start with '/': " + repr(path))
    segments = []
    names = []
    for raw in path.split("/")[1:]:
        if raw.startswith("{") and raw.endswith("}"):
            name = raw[1:-1]
            if not name or not _is_identifier(name):
                raise ValueError("not a parameter name: " + repr(raw))
            if name in names:
                raise ValueError("the parameter " + repr(name) + " appears twice in " + repr(path))
            segments.append(None)
            names.append(name)
        else:
            if "{" in raw or "}" in raw:
                raise ValueError("a brace outside a whole segment: " + repr(path))
            segments.append(raw)
    return segments, names


def _is_identifier(s):
    """The runtime has no `str.isidentifier`, and this is the whole of what it needs."""
    if not s:
        return False
    first = s[0]
    if not (first == "_" or ("a" <= first <= "z") or ("A" <= first <= "Z")):
        return False
    for ch in s[1:]:
        if not (ch == "_" or ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9")):
            return False
    return True


class Route:
    """One method and path, the function to call, and how to build its arguments."""

    def __init__(self, method, path, handler, spec):
        self.method = method
        self.path = path
        self.handler = handler
        self.spec = spec
        self.segments, self.names = compile_path(path)
        self.name = getattr(handler, "__name__", "handler")

    def match(self, segments):
        """The path parameters as raw strings, or None. The caller has already split."""
        if len(segments) != len(self.segments):
            return None
        found = None
        index = 0
        for i, expected in enumerate(self.segments):
            if expected is None:
                if found is None:
                    found = {}
                found[self.names[index]] = segments[i]
                index += 1
            elif expected != segments[i]:
                return None
        return found if found is not None else {}

    def __repr__(self):
        return "<Route %s %s -> %s>" % (self.method, self.path, self.name)


class Router:
    """Every route, matched in declaration order.

    Order matters and is the author's: `/trips/new` declared before `/trips/{id}` wins, and
    declared after it never runs. That is a rule to state rather than a subtlety to discover,
    and it is why this does not sort by specificity behind your back.
    """

    def __init__(self):
        self.routes = []

    def add(self, route):
        self.routes.append(route)

    def find(self, method, path):
        """`(route, params)`, or `(None, allowed)` where `allowed` is the methods this path
        does accept — which is what separates a 404 from a 405."""
        segments = path.split("/")[1:]
        if len(segments) > 1 and segments[-1] == "":
            segments = segments[:-1]  # a trailing slash matches the path without one
        allowed = []
        for route in self.routes:
            params = route.match(segments)
            if params is None:
                continue
            if route.method == method:
                return route, params
            if route.method not in allowed:
                allowed.append(route.method)
        return None, allowed
