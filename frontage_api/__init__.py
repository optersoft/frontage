"""frontage-api: FastAPI's shape, on axum, on frontage's own Python runtime.

`API.md` at the repository root is the design. This is §6.2, the surface: an `App`, method
decorators, arguments built from a route's spec, `HTTPError`, and the response rules.

    from frontage_api import App, HTTPError
    from frontage.schema import record, text, integer

    app = App()
    Trip = record(("id", integer(ge=0)), ("note", text()))

    @app.get("/trips/{trip_id}", path={"trip_id": int})
    async def trip(trip_id):
        row = TRIPS.get(trip_id)
        if row is None:
            raise HTTPError(404, "no such trip")
        return row                      # a dict answers as JSON

    @app.post("/trips", body=Trip)
    async def create(body):             # validated, coerced, 422 with the field errors
        return {"id": store(body)}

**A route declares its types in the decorator, and that is a runtime constraint, not a
preference.** This runtime parses annotations and discards them — `def f(x: Undefined)` does
not even raise — so there is no `__annotations__` to read and nothing to build a contract
from. `API.md` §6.2 has the compiler change that adds them; when it lands, an annotation
becomes the preferred spelling and fills in exactly the same spec this file already takes, so
nothing here changes shape.

**One entry, one crossing.** `App.handle` is the whole of what the server calls per request
(§4.4). Everything above — matching, conversion, validation, the response rules — is Python
on this side of that one call.
"""

import json

from . import depends as _depends
from .cors import Cors
from .depends import Depends
from .routing import Route, Router
from .streaming import SSE_DONE, Stream, sse

__all__ = [
    "SSE_DONE",
    "App",
    "Cors",
    "Depends",
    "HTTPError",
    "Response",
    "Stream",
    "json_response",
    "sse",
    "text_response",
]

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")

#: Names the request itself supplies, which an annotation must not turn into a query
#: parameter. `headers: Headers` should read as documentation, not as `?headers=`.
RESERVED = ("headers", "scope", "path_params")

JSON_TYPE = "application/json"
TEXT_TYPE = "text/plain; charset=utf-8"
BYTES_TYPE = "application/octet-stream"


class HTTPError(Exception):
    """An answer, raised. `detail` is what the body's `detail` field says."""

    def __init__(self, status, detail=None, headers=None):
        Exception.__init__(self, detail or ("HTTP " + str(status)))
        self.status = status
        self.detail = detail if detail is not None else _reason(status)
        self.headers = headers or []


REASONS = {
    400: "bad request",
    401: "unauthorized",
    403: "forbidden",
    404: "not found",
    405: "method not allowed",
    409: "conflict",
    413: "payload too large",
    415: "unsupported media type",
    422: "unprocessable entity",
    429: "too many requests",
    500: "internal server error",
    503: "service unavailable",
}


def _reason(status):
    return REASONS.get(status, "error")


class Response:
    """A body with a status, headers and a content type, when the shorthands are not enough."""

    def __init__(self, body, status=200, headers=None, media_type=None):
        if isinstance(body, str):
            self.body = body.encode("utf-8")
            media_type = media_type or TEXT_TYPE
        elif isinstance(body, bytes):
            self.body = body
            media_type = media_type or BYTES_TYPE
        else:
            self.body = json.dumps(body).encode("utf-8")
            media_type = media_type or JSON_TYPE
        self.status = status
        self.headers = list(headers or [])
        self.media_type = media_type

    def parts(self):
        headers = [("content-type", self.media_type)]
        headers.extend(self.headers)
        return self.status, headers, self.body


def json_response(data, status=200, headers=None):
    return Response(data, status=status, headers=headers, media_type=JSON_TYPE)


def text_response(body, status=200, headers=None):
    return Response(body, status=status, headers=headers, media_type=TEXT_TYPE)


def _awaitable(value):
    """Is this a thing to `await`?

    ⚠ **`hasattr(x, "send")` is not the test**, though it reads like one: a plain generator
    has `send` too, so a generator dependency was being awaited instead of being stepped, and
    a handler that returned a generator would have gone the same way. `__await__` is on a
    coroutine and not on a generator, on CPython and on this runtime alike.
    """
    return hasattr(value, "__await__")


def _params_of(handler):
    """The names a handler takes. `co_varnames` is parameters first, `argcount` of them —
    the runtime has no `inspect`, and this is the whole of what it would be used for."""
    code = getattr(handler, "__code__", None)
    if code is None:
        return ()
    names = getattr(code, "co_varnames", ())
    count = getattr(code, "co_argcount", len(names))
    return tuple(names[:count])


#: What an annotation's text may name, when the route does not say otherwise. Deliberately
#: short: this is a router, not a type system, and anything else has to be declared.
BUILTIN_TYPES = {
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "bytes": bytes,
}


def _annotations_of(handler, namespace):
    """A route's spec, read from the handler's signature.

    ⚠ **The values are source text, not objects.** This runtime stores an annotation's
    spelling and never evaluates it (`rust/README.md`), so `int` arrives as `"int"` and a
    schema arrives as the name it was bound to — which is why `namespace` is the module the
    handler came from. That also means an annotation this cannot resolve is *not* an error:
    it is simply a parameter the route does not bind, exactly as before annotations existed.
    """
    out = {}
    for name, value in getattr(handler, "__annotations__", {}).items():
        if name == "return":
            continue
        kind = _resolve(value, namespace)
        if kind is not None:
            out[name] = kind
    return out


def _resolve(value, namespace):
    """One annotation to a converter, whichever runtime wrote it.

    ⚠ **Both shapes have to work.** On frontage's runtime an annotation is its *source text*
    (`rust/README.md`), so `int` arrives as `"int"`; on CPython it is the object itself,
    because this package is written and tested there. Handling only strings would crash every
    annotated handler under pytest, which is exactly where they are first written.
    """
    if not isinstance(value, str):
        return value if (callable(value) or hasattr(value, "parse")) else None
    text = value.strip()
    if len(text) > 1 and text[0] in "\"'" and text[-1] == text[0]:
        text = text[1:-1].strip()  # a string annotation: what it says, not its quotes
    kind = BUILTIN_TYPES.get(text)
    if kind is None:
        kind = namespace.get(text)
    return kind


def _namespace_of(handler):
    globals_ = getattr(handler, "__globals__", None)
    if isinstance(globals_, dict):
        return globals_
    return {}


def _convert(value, kind, where, name, errors):
    """One raw string through one converter. A `frontage.schema` type validates and coerces;
    a plain callable (`int`, `float`, `str`) converts; anything else is passed through."""
    parse = getattr(kind, "parse", None)
    if parse is not None:
        try:
            return parse(value, coerce=True)
        except Exception as exc:
            for path, message in getattr(exc, "errors", [("$", str(exc))]):
                errors.append((where + "." + name + path.lstrip("$"), message))
            return None
    if kind is bool:
        low = value.lower() if isinstance(value, str) else value
        if low in (True, "1", "true", "yes", "on"):
            return True
        if low in (False, "0", "false", "no", "off", ""):
            return False
        errors.append((where + "." + name, "not a boolean"))
        return None
    if callable(kind):
        try:
            return kind(value)
        except Exception:
            errors.append((where + "." + name, "not a " + getattr(kind, "__name__", str(kind))))
            return None
    return value


def _path_names(path):
    from .routing import compile_path

    return compile_path(path)[1]


class Headers:
    """The request's headers, read by lowercase name. A list of pairs underneath, because a
    header may legitimately repeat and `get_all` is what a `set-cookie` reader needs."""

    def __init__(self, pairs):
        self.pairs = list(pairs or [])

    def get(self, name, default=None):
        name = name.lower()
        for key, value in self.pairs:
            if key.lower() == name:
                return value
        return default

    def get_all(self, name):
        name = name.lower()
        return [value for key, value in self.pairs if key.lower() == name]

    def __contains__(self, name):
        return self.get(name) is not None

    def __iter__(self):
        return iter(self.pairs)


def parse_query(query_string):
    """`a=1&b=two` to a dict. Last one wins, which is what a form does; `%` escapes and `+`
    are decoded, because a query parameter that is a sentence is normal."""
    out = {}
    if not query_string:
        return out
    for pair in query_string.split("&"):
        if not pair:
            continue
        if "=" in pair:
            key, _, value = pair.partition("=")
        else:
            key, value = pair, ""
        out[_unquote(key)] = _unquote(value)
    return out


def _unquote(s):
    s = s.replace("+", " ")
    if "%" not in s:
        return s
    out = []
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s) + 1:
            try:
                out.append(chr(int(s[i + 1 : i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(s[i])
        i += 1
    return "".join(out)


class App:
    """The routes, and the one entry the server calls."""

    def __init__(self, title="frontage-api", cors=None, static=None):
        self.title = title
        self.router = Router()
        self.cors = cors if isinstance(cors, Cors) or cors is None else Cors(cors)
        # Read by the server at load: files are served by Rust, not by walking a directory
        # through an interpreter. A page and its API from one process is the simple
        # deployment and the one with no CORS in it.
        self.static = static
        self._startup = []
        self._shutdown = []

    def on_startup(self, fn):
        """Run once per **worker**, which is the part to hold on to: there is one interpreter
        per thread, so this runs N times per process. Anything that must happen once for the
        process belongs outside the app."""
        self._startup.append(fn)
        return fn

    def on_shutdown(self, fn):
        self._shutdown.append(fn)
        return fn

    async def startup(self):
        for fn in self._startup:
            result = fn()
            if _awaitable(result):
                await result

    async def shutdown(self):
        for fn in reversed(self._shutdown):
            result = fn()
            if _awaitable(result):
                await result

    def route(self, method, path, path_types=None, query=None, body=None, needs=None):
        method = method.upper()
        if method not in METHODS:
            raise ValueError("not a method: " + repr(method))

        def decorate(handler):
            params = _params_of(handler)
            declared = _annotations_of(handler, _namespace_of(handler))
            # The decorator wins where both speak, so a route can always override what a
            # signature says without editing the signature.
            names = _path_names(path)
            spec = {
                "path": {n: declared[n] for n in names if n in declared},
                "query": {},
                "body": body,
                "needs": needs or {},
                "params": params,
            }
            for name, kind in declared.items():
                if name in names or name in spec["needs"] or name in RESERVED:
                    continue
                if name == "body":
                    if spec["body"] is None:
                        spec["body"] = kind
                    continue
                spec["query"][name] = kind
            spec["path"].update(path_types or {})
            spec["query"].update(query or {})
            self.router.add(Route(method, path, handler, spec))
            return handler

        return decorate

    # `get`, `post`, `put`, `patch`, `delete`, `head` and `options` are installed at the
    # bottom of this file, one per method, rather than written out seven times.

    def cors_headers(self, origin):
        """What a *file* response should carry, asked for by the server.

        A file is served by Rust and never reaches `handle`, so it would otherwise answer a
        cross-origin `fetch` with no headers at all — which matters here, because the docs'
        sandboxed runner sits in an opaque origin and frontage's own `_headers` file exists
        for exactly this. Asked only when the request carried an `Origin`, so a same-origin
        page pays nothing.
        """
        if self.cors is None:
            return []
        return self.cors.headers_for(origin)

    async def handle(self, scope):
        """One request in, `(status, headers, body)` out. The only thing the server calls."""
        headers = Headers(scope.get("headers"))
        origin = headers.get("origin")
        finalizers = []
        try:
            answer = await self._handle(scope, headers, finalizers)
        except HTTPError as exc:
            answer = _problem(exc.status, exc.detail, exc.headers)
        except Exception as exc:  # a handler's own failure, not the caller's
            answer = _problem(500, _reason(500) + ": " + str(exc))
        problems = _depends.finish(finalizers)
        for problem in problems:
            _warn("a dependency failed while closing: " + str(problem))
        if self.cors is not None:
            status, out, body = answer
            answer = (status, out + self.cors.headers_for(origin), body)
        return answer

    async def _handle(self, scope, headers, finalizers):
        method = scope.get("method", "GET")
        path = scope.get("path", "/")
        route, params = self.router.find(method, path)
        if route is None:
            # A preflight asks about a route that exists under another method, so answer it
            # from what that path *does* accept rather than from a fixed list.
            if method == "OPTIONS" and self.cors is not None and params:
                allowed = self.cors.headers_for(headers.get("origin"), preflight=True)
                return 204, allowed + [("allow", ", ".join(sorted(params)))], b""
            if params:
                return _problem(405, "method not allowed", [("allow", ", ".join(sorted(params)))])
            return _problem(404, "not found")
        kwargs = await _bind(route, params, scope, headers, finalizers)
        result = route.handler(**kwargs)
        if _awaitable(result):
            result = await result
        return _respond(result)


async def _bind(route, params, scope, headers, finalizers):
    """Path, query, body, headers and dependencies into the handler's parameter names."""
    spec = route.spec
    wanted = spec["params"]
    errors = []
    values = {"headers": headers, "scope": scope, "path_params": params}
    for name, raw in params.items():
        values[name] = _convert(raw, spec["path"].get(name, str), "path", name, errors)
    if spec["query"]:
        query = parse_query(scope.get("query_string", ""))
        for name, kind in spec["query"].items():
            if name in query:
                values[name] = _convert(query[name], kind, "query", name, errors)
    if spec["body"] is not None:
        values["body"] = _body(scope, spec["body"], errors)
    if errors:
        raise HTTPError(422, [{"loc": where, "msg": message} for where, message in errors])
    if spec["needs"]:
        values.update(await _depends.resolve(spec["needs"], values, {}, finalizers))
    return {name: values[name] for name in wanted if name in values}


def _body(scope, kind, errors):
    raw = scope.get("body", b"")
    if kind is bytes:
        # The body untouched, for a route that is not JSON: an upload, a webhook signature,
        # a proxy. Declared rather than inferred, so nothing is parsed by accident.
        return raw
    if not raw:
        payload = None
    else:
        try:
            payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        except Exception:
            raise HTTPError(400, "the body is not JSON") from None
    if kind is True:
        return payload
    parse = getattr(kind, "parse", None)
    if parse is None:
        return payload
    try:
        return parse(payload)
    except Exception as exc:
        for path, message in getattr(exc, "errors", [("$", str(exc))]):
            errors.append(("body" + path.lstrip("$"), message))
        return None


def _respond(result):
    if isinstance(result, Stream):
        # The third element is not bytes, and that is the signal: the server pulls from it
        # instead of writing it. `API.md` §6.2.
        status, headers = result.parts()
        return status, headers, result.chunks()
    if isinstance(result, Response):
        return result.parts()
    if result is None:
        return 204, [], b""
    if isinstance(result, bytes):
        return 200, [("content-type", BYTES_TYPE)], result
    if isinstance(result, str):
        return 200, [("content-type", TEXT_TYPE)], result.encode("utf-8")
    return 200, [("content-type", JSON_TYPE)], json.dumps(result).encode("utf-8")


def _problem(status, detail, headers=None):
    """FastAPI's shape for an error body, because the fleet's pages already read it."""
    body = json.dumps({"detail": detail}).encode("utf-8")
    out = [("content-type", JSON_TYPE)]
    out.extend(headers or [])
    return status, out, body


def _warn(message):
    """Something worth saying that must not replace a correct answer."""
    print("frontage-api: " + message)


def _method_decorator(method):
    def decorator(self, path, path_types=None, query=None, body=None, needs=None):
        return self.route(method, path, path_types=path_types, query=query, body=body, needs=needs)

    decorator.__name__ = method.lower()
    return decorator


for _method in METHODS:
    setattr(App, _method.lower(), _method_decorator(_method))
del _method
