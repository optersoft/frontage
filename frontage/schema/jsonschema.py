"""JSON Schema in, a schema out; and the reverse, which every type does itself.

`from_json_schema` reads the subset a Pydantic model or an OpenAPI document produces:
`type` (one, or a list with `"null"`), `properties` / `required` / `additionalProperties`,
`items` / `minItems` / `maxItems`, `enum` / `const`, the numeric bounds, `minLength` /
`maxLength` / `pattern`, `format` for email, uri/url, uuid, ipv4, date and date-time,
`default`, `anyOf` / `oneOf`, and `$ref` into `#/$defs`, `#/definitions` or
`#/components/schemas`. Keywords outside that list are ignored, and a `pattern` with a
counted repeat raises, because MicroPython's `re` would silently never match it.

    User = from_json_schema(json.loads(text))       # in the page, or on CPython
    User.json_schema()                              # back out: what `frontage.schema` writes
"""

from . import (
    Anything,
    Array,
    Boolean,
    Email,
    Integer,
    Ipv4,
    IsoDate,
    IsoDateTime,
    Literal,
    Mapping,
    Number,
    OneOf,
    Optional,
    Record,
    Text,
    Url,
    Uuid,
    fresh,
)

__all__ = ["from_json_schema", "to_json_schema"]

_FORMATS = {
    "email": Email,
    "uri": Url,
    "url": Url,
    "uuid": Uuid,
    "ipv4": Ipv4,
    "date": IsoDate,
    "date-time": IsoDateTime,
}


def to_json_schema(schema):
    return schema.json_schema()


def from_json_schema(schema, root=None):
    """The schema for a JSON Schema dict. `root` is the document `$ref`s resolve in; it
    defaults to `schema` itself, which is right for a whole document."""
    if root is None:
        root = schema
    return _convert(schema, root, [], schema)


def _convert(s, root, stack, scope):
    if s is True or s == {}:
        return Anything()
    if type(s) is not dict:
        raise ValueError("a JSON Schema is an object, got %r" % (s,))
    if "$defs" in s or "definitions" in s:
        scope = s  # a model's schema carries its own $defs, wherever the document put it
    ref = s.get("$ref")
    if ref is not None:
        if ref in stack:
            raise ValueError("recursive $ref is not supported: " + ref)
        return _convert(_resolve(ref, root, scope), root, stack + [ref], scope)

    alternatives = s.get("anyOf") or s.get("oneOf")
    if alternatives is not None:
        return _union([_convert(a, root, stack, scope) for a in alternatives], [a for a in alternatives])

    if "const" in s:
        return Literal(s["const"])
    if "enum" in s:
        return Literal(*s["enum"])

    kind = s.get("type")
    nullable = False
    if type(kind) is list:
        kinds = [k for k in kind if k != "null"]
        nullable = len(kinds) != len(kind)
        if len(kinds) == 1:
            kind = kinds[0]
        elif not kinds:
            return Literal(None)
        else:
            inner = OneOf(*[_convert(dict(s, type=k), root, stack, scope) for k in kinds])
            return Optional(inner) if nullable else inner
    if kind is None:
        kind = "object" if "properties" in s else "array" if "items" in s else None

    if kind == "string":
        out = _string(s)
    elif kind == "integer":
        out = Integer(**_bounds(s))
    elif kind == "number":
        out = Number(**_bounds(s))
    elif kind == "boolean":
        out = Boolean()
    elif kind == "null":
        out = Literal(None)
    elif kind == "array":
        items = s.get("items")
        out = Array(
            _convert(items, root, stack, scope) if items is not None else Anything(),
            min=s.get("minItems"),
            max=s.get("maxItems"),
        )
    elif kind == "object":
        out = _object(s, root, stack, scope)
    else:
        out = Anything()
    return Optional(out) if nullable else out


def _string(s):
    fmt = _FORMATS.get(s.get("format"))
    kwargs = {"min": s.get("minLength"), "max": s.get("maxLength")}
    if fmt is None:
        return Text(pattern=s.get("pattern"), **kwargs)
    return fmt(**kwargs)


def _bounds(s):
    out = {}
    for key, name in (
        ("exclusiveMinimum", "gt"),
        ("minimum", "ge"),
        ("exclusiveMaximum", "lt"),
        ("maximum", "le"),
        ("multipleOf", "multiple_of"),
    ):
        if key in s:
            out[name] = s[key]
    # Draft 4 spelled the exclusive bounds as booleans beside the inclusive ones.
    if out.get("gt") is True:
        out["gt"] = out.pop("ge", None)
    if out.get("lt") is True:
        out["lt"] = out.pop("le", None)
    return {k: v for k, v in out.items() if v is not None}


def _object(s, root, stack, scope):
    properties = s.get("properties")
    additional = s.get("additionalProperties", True)
    if properties is None:
        if type(additional) is dict:
            return Mapping(_convert(additional, root, stack, scope))
        return Mapping(Anything()) if additional is not False else Record()
    required = s.get("required") or []
    fields = []
    # `properties` is a dict, so on MicroPython its order is whatever it is. That order only
    # shows in a form, and a form's schema is compiled on CPython by `frontage.schema`.
    for name in _ordered(properties, required):
        prop = properties[name]
        t = _convert(prop, root, stack, scope)
        if name in required:
            fields.append((name, t))
        elif type(prop) is dict and "default" in prop:
            default = prop["default"]
            if type(default) is list or type(default) is dict:
                fields.append((name, t, _fresh(default)))
            else:
                fields.append((name, t, default))
        else:
            fields.append((name, Optional(t) if not isinstance(t, Optional) else t, None))
    extra = "ignore"
    if additional is False:
        extra = "forbid"
    return Record(*fields, extra=extra)


def _fresh(value):
    """A callable default, so a list or dict default is a new one per value; `list` or `dict`
    for an empty one, which is what `repr` prints best."""
    if not value:
        return list if type(value) is list else dict
    return fresh(value)


def _ordered(properties, required):
    """The document's own order, which CPython keeps and MicroPython does not."""
    return list(properties)


def _union(types, raw):
    """`anyOf` with a `null` branch is `optional`; anything else is `one_of`."""
    rest = []
    for i in range(len(types)):  # not zip: MicroPython's has no `strict`, and the rule wants it
        r = raw[i]
        if not (type(r) is dict and r.get("type") == "null"):
            rest.append(types[i])
    nullable = len(rest) != len(types)
    if not rest:
        return Literal(None)
    inner = rest[0] if len(rest) == 1 else OneOf(*rest)
    return Optional(inner) if nullable else inner


def _resolve(ref, root, scope=None):
    if not ref.startswith("#/"):
        raise ValueError("only local $refs are supported: " + ref)
    node = _walk(ref, root)
    if node is None and scope is not None and scope is not root:
        node = _walk(ref, scope)
    if node is None:
        raise ValueError("unresolved $ref: " + ref)
    return node


def _walk(ref, node):
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if type(node) is not dict or part not in node:
            return None
        node = node[part]
    return node
