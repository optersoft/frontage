"""The routes as an OpenAPI document (`API.md` §6.3).

    from frontage_api.openapi import document
    document(app)                       # a dict, ready to be JSON

`App` serves it at `/openapi.json` and a page that reads it at `/docs`, both of which
`App(docs=None)` turns off.

**The document is derived, never declared.** Every field in it already exists somewhere the
route needed anyway: the path's parameters come from the path, their types from the same
converters `_bind` uses, and a body's schema from `frontage.schema`'s own `json_schema()` —
which is what §4.6 is about. A record that validates a form in the page is the same object
that describes the body here, so the document cannot drift from what the server accepts. That
is the gate: `tests/test_openapi.py` asserts the emitted schema accepts exactly the values
the route does.

A summary is the handler's docstring, and `summary=` overrides it. That took a compiler
change: docstrings were discarded outright until 2026-09-10, so `__doc__` was `None` on the
server and the prose a reader was meant to see existed only under pytest. `fpy --compile`
still drops them, because a `.fbc` is what a page downloads and no page reads `__doc__`
(`rust/README.md`) — so the *page* pays nothing for this and the server gets it.
"""

__all__ = ["document"]

OPENAPI_VERSION = "3.1.0"

#: A converter that is a plain builtin, as a schema. Anything with `json_schema()` describes
#: itself and never reaches this list. Pairs and `is`, not a dict: the key would be whatever
#: the route declared, and asking an arbitrary object for its hash to look it up is a way to
#: turn a documentation call into someone else's `__eq__`.
BUILTIN_SCHEMAS = (
    (int, {"type": "integer"}),
    (float, {"type": "number"}),
    (str, {"type": "string"}),
    (bool, {"type": "boolean"}),
    (bytes, {"type": "string", "format": "binary"}),
)

#: What `_problem` writes for a 422, which is FastAPI's shape and what the fleet's pages
#: already read. It goes in `components` under `ValidationError`, once per document.
VALIDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "detail": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"loc": {"type": "string"}, "msg": {"type": "string"}},
                "required": ["loc", "msg"],
            },
        }
    },
    "required": ["detail"],
}


def document(app, version="0.1.0", description=None, servers=None):
    """The whole document, as a dict."""
    out = {
        "openapi": OPENAPI_VERSION,
        "info": {"title": app.title, "version": version},
        "paths": {},
    }
    if description:
        out["info"]["description"] = description
    if servers:
        out["servers"] = [{"url": url} if isinstance(url, str) else url for url in servers]
    named = _Named()
    seen = {}
    for route in app.router.routes:
        if not route.spec.get("schema", True):
            continue
        path = out["paths"].setdefault(route.path, {})
        path[route.method.lower()] = _operation(route, named, seen)
    if named.schemas:
        out["components"] = {"schemas": named.schemas}
    return out


class _Named:
    """Schemas that have a name in the module they were declared in, so the document can
    `$ref` them instead of repeating a record at every route that takes it.

    The name comes from an identity scan of the handler's globals, which is the only place it
    exists: `record(…)` makes an anonymous object and the name is the variable it was bound
    to. An object bound to nothing stays inline, which is correct rather than a shortfall.
    """

    def __init__(self):
        self.schemas = {}
        self._by_id = {}

    def ref(self, kind, namespace):
        name = self._by_id.get(id(kind))
        if name is None:
            name = _name_of(kind, namespace)
            # Anonymous, or a name another object already took: inline it. Describing two
            # different records under one name is worse than repeating one of them.
            if name is None or name in self.schemas:
                return None
            self.schemas[name] = kind.json_schema()
            self._by_id[id(kind)] = name
        return {"$ref": "#/components/schemas/" + name}

    def fixed(self, name, schema):
        """A schema this module owns rather than one a route declared — the error bodies.
        Registered on first use, so a document with no fallible route does not carry it."""
        if name not in self.schemas:
            self.schemas[name] = schema
        return {"$ref": "#/components/schemas/" + name}


def _name_of(kind, namespace):
    for name, value in namespace.items():
        if value is kind and not name.startswith("_"):
            return name
    return None


def _schema_of(kind, named=None, namespace=None):
    """One converter as a JSON Schema fragment, `$ref`ed when it has a name."""
    if kind is None or kind is True:
        return {}
    for builtin, schema in BUILTIN_SCHEMAS:
        if kind is builtin:
            return dict(schema)
    emit = getattr(kind, "json_schema", None)
    if emit is None:
        return {}
    if named is not None and namespace is not None:
        ref = named.ref(kind, namespace)
        if ref is not None:
            return ref
    return emit()


def _prose(route):
    """`summary` and `description`, from the decorator or from a docstring where there is
    one. The first line is the summary and the rest is the description, which is the
    convention every OpenAPI generator uses."""
    spec = route.spec
    summary = spec.get("summary")
    description = spec.get("description")
    if summary is None and description is None:
        doc = getattr(route.handler, "__doc__", None)
        if doc:
            lines = [line.strip() for line in doc.strip().split("\n")]
            summary = lines[0]
            rest = "\n".join(lines[1:]).strip()
            description = rest or None
    return summary, description


def _operation(route, named, seen):
    spec = route.spec
    namespace = getattr(route.handler, "__globals__", None) or {}
    out = {"operationId": _operation_id(route, seen)}
    summary, description = _prose(route)
    if summary:
        out["summary"] = summary
    if description:
        out["description"] = description
    if spec.get("tags"):
        out["tags"] = list(spec["tags"])

    parameters = []
    for name in route.names:
        parameters.append(
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": _schema_of(spec["path"].get(name, str), named, namespace),
            }
        )
    for name, kind in spec["query"].items():
        # Not required: `_bind` sets a query parameter only when it was sent, and the
        # handler's own default is what happens otherwise — which this cannot see.
        parameters.append(
            {
                "name": name,
                "in": "query",
                "required": False,
                "schema": _schema_of(kind, named, namespace),
            }
        )
    if parameters:
        out["parameters"] = parameters

    body = spec.get("body")
    if body is not None:
        media = "application/octet-stream" if body is bytes else "application/json"
        out["requestBody"] = {
            "required": True,
            "content": {media: {"schema": _schema_of(body, named, namespace)}},
        }

    responses = {"200": _success(spec.get("returns"), named, namespace)}
    # 422 is emitted where something can fail to convert, and only there: a route with no
    # parameters and no body has no way to answer it.
    if body is not None or spec["path"] or spec["query"]:
        responses["422"] = {
            "description": "the request did not match the route's types",
            "content": {"application/json": {"schema": named.fixed("ValidationError", VALIDATION_SCHEMA)}},
        }
    out["responses"] = responses
    return out


def _success(returns, named, namespace):
    if returns is None:
        return {"description": "OK"}
    if returns is bytes:
        return {
            "description": "OK",
            "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        }
    if returns is str:
        return {"description": "OK", "content": {"text/plain": {"schema": {"type": "string"}}}}
    return {"description": "OK", "content": {"application/json": {"schema": _schema_of(returns, named, namespace)}}}


def _operation_id(route, seen):
    """`name`, then `name_post` and so on. Unique across the document, which is what a client
    generator needs and what a repeated handler name would otherwise break."""
    base = route.name
    if base not in seen:
        seen[base] = 1
        return base
    seen[base] += 1
    return base + "_" + route.method.lower()
