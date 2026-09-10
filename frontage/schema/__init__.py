"""Schemas for frontage: what a value must look like, checked in the page.

A schema is a tree of types. `record` is the usual top level, and its fields are **pairs**,
because MicroPython does not keep a dict's insertion order and the order of fields is visible
in the error list and in a form:

    User = record(
        ("id", integer(ge=0)),
        ("name", text(min=1, max=100)),
        ("email", email()),
        ("age", integer(gt=0, le=150), None),      # a third element is a default: optional
        ("tags", array(text()), list),             # a callable default is called per value
    )

    value, errors = array(User).validate(data)     # errors: [("$[3].email", "not an email"), …]
    value = User.parse(data)                       # or raise SchemaError with that list

Two switches cover every boundary an app has. `coerce=True` reads strings — a form's fields,
`query()` parameters, the URL fragment — so `"28"` is 28 and `""` is None for an optional
field; without it JSON is checked as typed, and a string is not an integer. `sample=N` checks
an array's first and last N items only, with the length and the type of the whole: walking a
value costs about ten times its `json.loads` (13 µs a row for five fields, 2026-09-07), which is
fine for a page load of a thousand records and not for a table of fifty thousand.

Pure Python, both interpreters. Formats (email, URL, UUID, ISO dates) are string code, not
patterns: MicroPython's `re` has no counted repeats, so `\\d{4}` silently never matches, and
`text(pattern=…)` refuses a `{` for that reason.
"""

import math

__all__ = [
    "SchemaError",
    "Type",
    "anything",
    "array",
    "boolean",
    "email",
    "fresh",
    "integer",
    "ipv4",
    "iso_date",
    "iso_datetime",
    "literal",
    "mapping",
    "number",
    "one_of",
    "optional",
    "pattern",
    "record",
    "text",
    "url",
    "uuid",
]


class SchemaError(Exception):
    """`parse` raised: `errors` is the list of `(path, message)` pairs, in schema order."""

    def __init__(self, errors):
        self.errors = errors
        Exception.__init__(self, "\n".join(path + ": " + message for path, message in errors))


def _source(name, args, kwargs):
    """Constructor source for `repr`, so a schema prints as the code that builds it."""
    parts = [repr(a) for a in args]
    for key, value in kwargs:
        parts.append(key + "=" + repr(value))
    return name + "(" + ", ".join(parts) + ")"


class Type:
    """The base of every type. `check` is the walk; the three public methods wrap it."""

    def check(self, value, path, errors, opts):
        """Append `(path, message)` pairs to `errors`; return the value, coerced or defaulted."""
        return value

    def validate(self, data, coerce=False, sample=None):
        """`(value, errors)`: the value with coercions and defaults applied, and the errors."""
        errors = []
        value = self.check(data, "$", errors, (coerce, sample))
        return value, errors

    def parse(self, data, coerce=False, sample=None):
        """The value, or `SchemaError` carrying every error found."""
        value, errors = self.validate(data, coerce, sample)
        if errors:
            raise SchemaError(errors)
        return value

    def is_valid(self, data, coerce=False, sample=None):
        return not self.validate(data, coerce, sample)[1]

    def json_schema(self):
        """This type as a JSON Schema fragment (the subset `from_json_schema` reads back)."""
        return {}

    def __call__(self, data, coerce=False, sample=None):
        return self.parse(data, coerce, sample)


# --- scalars --------------------------------------------------------------------------------


class Text(Type):
    """A string. `min`/`max` bound the length; `pattern` is searched (unanchored, as in JSON
    Schema); `strip=True` trims before checking, and the trimmed value is what comes back."""

    format = None  # a subclass's JSON Schema `format`
    message = None  # and what it says when `_format` fails

    def __init__(self, min=None, max=None, pattern=None, strip=False):
        if pattern is not None and "{" in pattern:
            raise ValueError("counted repeats ({n}) are not in MicroPython's re; write the repetition out")
        self.min = min
        self.max = max
        self.pattern = pattern
        self.strip = strip
        if pattern is None:
            self._re = None
        else:
            # Imported here, not at the top of the module. `re` runs on the browser's
            # `RegExp` and raises on import off the browser, which would make this whole
            # module — the one thing §4.6 of `API.md` needs on *both* sides — unimportable on
            # a server. Nothing else here needs a regex: every format below is string code.
            # `ast.walk` in `cli/graph.py` finds a nested import, so a page still packs it.
            import re

            self._re = re.compile(pattern)

    def _format(self, value):
        return True

    def check(self, value, path, errors, opts):
        if type(value) is not str:
            errors.append((path, "expected a string"))
            return value
        if self.strip:
            value = value.strip()
        n = len(value)
        if self.min is not None and n < self.min:
            errors.append((path, "at least %d characters" % self.min))
            return value
        if self.max is not None and n > self.max:
            errors.append((path, "at most %d characters" % self.max))
            return value
        if self._re is not None and not self._re.search(value):
            errors.append((path, "does not match " + str(self.pattern)))
            return value
        if not self._format(value):
            errors.append((path, self.message))
        return value

    def json_schema(self):
        out = {"type": "string"}
        if self.min is not None:
            out["minLength"] = self.min
        if self.max is not None:
            out["maxLength"] = self.max
        if self.pattern is not None:
            out["pattern"] = self.pattern
        if self.format is not None:
            out["format"] = self.format
        return out

    def _kwargs(self):
        out = []
        if self.min is not None:
            out.append(("min", self.min))
        if self.max is not None:
            out.append(("max", self.max))
        if self.pattern is not None and type(self) is Text:
            out.append(("pattern", self.pattern))
        if self.strip:
            out.append(("strip", True))
        return out

    def __repr__(self):
        return _source("text", [], self._kwargs())


class Pattern(Text):
    def __init__(self, pattern, min=None, max=None, strip=False):
        Text.__init__(self, min=min, max=max, pattern=pattern, strip=strip)

    def __repr__(self):
        return _source("pattern", [self.pattern], self._kwargs())


_ALNUM = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"  # ASCII only: `isalpha` is not
_LOCAL = "!#$%&'*+/=?^_`{|}~.-"


def _is_email(s):
    at = s.find("@")
    if at <= 0 or at == len(s) - 1:
        return False
    local = s[:at]
    domain = s[at + 1 :]
    if "@" in domain or local[0] == "." or local[-1] == "." or ".." in local:
        return False
    for c in local:
        if c not in _ALNUM and c not in _LOCAL:
            return False
    return _is_hostname(domain, True)


def _is_hostname(s, dotted):
    if not s or len(s) > 253 or "." not in s and dotted:
        return False
    for label in s.split("."):
        if not label or len(label) > 63 or label[0] == "-" or label[-1] == "-":
            return False
        for c in label:
            if c not in _ALNUM and c != "-":
                return False
    return True


class Email(Text):
    """`local@domain`: one `@`, a local part of the characters RFC 5322 allows unquoted, and
    a dotted ASCII hostname. Stricter than "has an @ and a dot", looser than the full grammar,
    which nobody's mail server implements either; an internationalised address is not one."""

    format = "email"
    message = "not an email address"

    def _format(self, value):
        return _is_email(value)

    def __repr__(self):
        return _source("email", [], self._kwargs())


def _is_url(s, schemes):
    i = s.find("://")
    if i <= 0:
        return False
    scheme = s[:i]
    if scheme[0] not in _ALNUM or scheme[0] in "0123456789":
        return False
    for c in scheme:
        if c not in _ALNUM and c not in "+.-":
            return False
    if schemes is not None and scheme.lower() not in schemes:
        return False
    for c in s:
        if c in " \t\r\n":
            return False
    rest = s[i + 3 :]
    end = len(rest)
    for j in range(end):
        if rest[j] in "/?#":
            end = j
            break
    return end > 0


class Url(Text):
    """`scheme://host…`. `localhost` and an IP are hosts; `schemes=("http", "https")` restricts
    the scheme, and the default allows any."""

    format = "uri"
    message = "not a URL"

    def __init__(self, schemes=None, min=None, max=None, strip=False):
        Text.__init__(self, min=min, max=max, strip=strip)
        self.schemes = tuple(s.lower() for s in schemes) if schemes is not None else None

    def _format(self, value):
        return _is_url(value, self.schemes)

    def __repr__(self):
        kwargs = self._kwargs()
        if self.schemes is not None:
            kwargs.insert(0, ("schemes", self.schemes))
        return _source("url", [], kwargs)


_HEX = "0123456789abcdefABCDEF"


def _is_uuid(s):
    if len(s) != 36 or s[8] != "-" or s[13] != "-" or s[18] != "-" or s[23] != "-":
        return False
    # Not `int(_, 16)`: it also takes a sign, spaces, underscores and a 0x prefix.
    for c in s:
        if c != "-" and c not in _HEX:
            return False
    return True


class Uuid(Text):
    """8-4-4-4-12 hex, any version, either case."""

    format = "uuid"
    message = "not a UUID"

    def _format(self, value):
        return _is_uuid(value)

    def __repr__(self):
        return _source("uuid", [], self._kwargs())


def _is_ipv4(s):
    parts = s.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part or len(part) > 3 or not part.isdigit() or (len(part) > 1 and part[0] == "0"):
            return False
        try:
            if int(part) > 255:
                return False
        except ValueError:
            return False
    return True


class Ipv4(Text):
    format = "ipv4"
    message = "not an IPv4 address"

    def _format(self, value):
        return _is_ipv4(value)

    def __repr__(self):
        return _source("ipv4", [], self._kwargs())


_DAYS = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _int(s):
    """`int` of an ASCII digit string, else None (`isdigit` also passes superscripts)."""
    if not s.isdigit():
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _is_date(s):
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return False
    y, m, d = _int(s[0:4]), _int(s[5:7]), _int(s[8:10])
    if y is None or m is None or d is None or m < 1 or m > 12 or d < 1:
        return False
    days = _DAYS[m]
    if m == 2 and y % 4 == 0 and (y % 100 != 0 or y % 400 == 0):
        days = 29
    return d <= days


def _is_time(s):
    parts = s.split(":")
    if len(parts) < 2 or len(parts) > 3:
        return False
    h, m = _int(parts[0]), _int(parts[1])
    if len(parts[0]) != 2 or len(parts[1]) != 2 or h is None or m is None or h > 23 or m > 59:
        return False
    if len(parts) == 3:
        sec = parts[2]
        dot = sec.find(".")
        frac = ""
        if dot >= 0:
            sec, frac = sec[:dot], sec[dot + 1 :]
            if not frac or _int(frac) is None:
                return False
        n = _int(sec)
        if len(sec) != 2 or n is None or n > 60:  # 60: a leap second
            return False
    return True


def _is_datetime(s):
    if len(s) < 16 or not _is_date(s[:10]) or s[10] not in "Tt ":
        return False
    rest = s[11:]
    if rest[-1] in "Zz":
        return _is_time(rest[:-1])
    k = max(rest.rfind("+"), rest.rfind("-"))
    if k <= 0:
        return _is_time(rest)
    zone = rest[k + 1 :]
    if len(zone) == 5 and zone[2] == ":":
        zone = zone[:2] + zone[3:]
    if len(zone) not in (2, 4):
        return False
    zh, zm = _int(zone[:2]), _int(zone[2:]) if len(zone) == 4 else 0
    if zh is None or zm is None or zh > 23 or zm > 59:
        return False
    return _is_time(rest[:k])


class IsoDate(Text):
    """`YYYY-MM-DD`, a real calendar date: `2026-02-30` is not one."""

    format = "date"
    message = "not a date (YYYY-MM-DD)"

    def _format(self, value):
        return _is_date(value)

    def __repr__(self):
        return _source("iso_date", [], self._kwargs())


class IsoDateTime(Text):
    """`YYYY-MM-DDTHH:MM[:SS[.fff]]` with an optional `Z` or `±HH:MM`. A space for the `T`
    is accepted, as RFC 3339 allows."""

    format = "date-time"
    message = "not a date-time (YYYY-MM-DDTHH:MM:SS)"

    def _format(self, value):
        return _is_datetime(value)

    def __repr__(self):
        return _source("iso_datetime", [], self._kwargs())


def _bounds(value, path, errors, gt, ge, lt, le, multiple_of):
    if gt is not None and not value > gt:
        errors.append((path, "must be greater than %s" % gt))
    elif ge is not None and not value >= ge:
        errors.append((path, "must be at least %s" % ge))
    if lt is not None and not value < lt:
        errors.append((path, "must be less than %s" % lt))
    elif le is not None and not value <= le:
        errors.append((path, "must be at most %s" % le))
    if multiple_of is not None and value % multiple_of != 0:
        errors.append((path, "must be a multiple of %s" % multiple_of))


def _bounds_schema(out, gt, ge, lt, le, multiple_of):
    if gt is not None:
        out["exclusiveMinimum"] = gt
    if ge is not None:
        out["minimum"] = ge
    if lt is not None:
        out["exclusiveMaximum"] = lt
    if le is not None:
        out["maximum"] = le
    if multiple_of is not None:
        out["multipleOf"] = multiple_of


def _bounds_kwargs(gt, ge, lt, le, multiple_of):
    out = []
    for key, value in (("gt", gt), ("ge", ge), ("lt", lt), ("le", le), ("multiple_of", multiple_of)):
        if value is not None:
            out.append((key, value))
    return out


class Integer(Type):
    """An `int`, and not a `bool`. Coercion reads a decimal string or an integral float."""

    def __init__(self, gt=None, ge=None, lt=None, le=None, multiple_of=None):
        self.gt = gt
        self.ge = ge
        self.lt = lt
        self.le = le
        self.multiple_of = multiple_of

    def check(self, value, path, errors, opts):
        if type(value) is not int:
            coerced = None
            if opts[0]:
                if type(value) is str:
                    try:
                        coerced = int(value.strip())
                    except ValueError:
                        coerced = None
                elif type(value) is float and value == int(value):
                    coerced = int(value)
            if coerced is None:
                errors.append((path, "expected an integer"))
                return value
            value = coerced
        _bounds(value, path, errors, self.gt, self.ge, self.lt, self.le, self.multiple_of)
        return value

    def json_schema(self):
        out = {"type": "integer"}
        _bounds_schema(out, self.gt, self.ge, self.lt, self.le, self.multiple_of)
        return out

    def __repr__(self):
        return _source("integer", [], _bounds_kwargs(self.gt, self.ge, self.lt, self.le, self.multiple_of))


class Number(Type):
    """An `int` or a `float`, finite unless `finite=False`. Coercion reads a decimal string."""

    def __init__(self, gt=None, ge=None, lt=None, le=None, multiple_of=None, finite=True):
        self.gt = gt
        self.ge = ge
        self.lt = lt
        self.le = le
        self.multiple_of = multiple_of
        self.finite = finite

    def check(self, value, path, errors, opts):
        t = type(value)
        if t is not int and t is not float:
            coerced = None
            if opts[0] and t is str:
                try:
                    coerced = float(value.strip())
                except ValueError:
                    coerced = None
            if coerced is None:
                errors.append((path, "expected a number"))
                return value
            value = coerced
        if self.finite and type(value) is float and not math.isfinite(value):
            errors.append((path, "must be finite"))
            return value
        _bounds(value, path, errors, self.gt, self.ge, self.lt, self.le, self.multiple_of)
        return value

    def json_schema(self):
        out = {"type": "number"}
        _bounds_schema(out, self.gt, self.ge, self.lt, self.le, self.multiple_of)
        return out

    def __repr__(self):
        kwargs = _bounds_kwargs(self.gt, self.ge, self.lt, self.le, self.multiple_of)
        if not self.finite:
            kwargs.append(("finite", False))
        return _source("number", [], kwargs)


_TRUE = ("true", "1", "yes", "on")
_FALSE = ("false", "0", "no", "off", "")


class Boolean(Type):
    """A `bool`. Coercion reads `true`/`false`, `1`/`0`, `yes`/`no`, `on`/`off`."""

    def check(self, value, path, errors, opts):
        if type(value) is bool:
            return value
        if opts[0] and type(value) is str:
            low = value.strip().lower()
            if low in _TRUE:
                return True
            if low in _FALSE:
                return False
        errors.append((path, "expected true or false"))
        return value

    def json_schema(self):
        return {"type": "boolean"}

    def __repr__(self):
        return "boolean()"


class Literal(Type):
    """One of the given values, compared by type and equality, so `1` is not `True`."""

    def __init__(self, *values):
        if not values:
            raise ValueError("literal needs at least one value")
        self.values = values

    def check(self, value, path, errors, opts):
        for allowed in self.values:
            if type(value) is type(allowed) and value == allowed:
                return value
        if opts[0] and type(value) is str:
            for allowed in self.values:
                if str(allowed) == value:
                    return allowed
        errors.append((path, "must be one of " + ", ".join(repr(v) for v in self.values)))
        return value

    def json_schema(self):
        if len(self.values) == 1:
            return {"const": self.values[0]}
        return {"enum": list(self.values)}

    def __repr__(self):
        return _source("literal", list(self.values), [])


class Anything(Type):
    def json_schema(self):
        return {}

    def __repr__(self):
        return "anything()"


# --- containers -----------------------------------------------------------------------------


class Optional(Type):
    """`inner` or None. Coercion reads an empty string as None, which is what an empty
    form field or an absent query parameter is."""

    def __init__(self, inner):
        self.inner = inner

    def check(self, value, path, errors, opts):
        if value is None or (opts[0] and type(value) is str and value == ""):
            return None
        return self.inner.check(value, path, errors, opts)

    def json_schema(self):
        return {"anyOf": [self.inner.json_schema(), {"type": "null"}]}

    def __repr__(self):
        return _source("optional", [self.inner], [])


class Array(Type):
    """A list (a tuple passes too) of `item`. With `sample=N` in the options only the first
    and last N items are walked, and the list comes back as it was."""

    def __init__(self, item, min=None, max=None):
        self.item = item
        self.min = min
        self.max = max

    def check(self, value, path, errors, opts):
        t = type(value)
        if t is not list and t is not tuple:
            errors.append((path, "expected a list"))
            return value
        n = len(value)
        if self.min is not None and n < self.min:
            errors.append((path, "at least %d items" % self.min))
            return value
        if self.max is not None and n > self.max:
            errors.append((path, "at most %d items" % self.max))
            return value
        item = self.item
        sample = opts[1]
        if sample is not None and n > 2 * sample:
            for i in range(sample):
                item.check(value[i], path + "[" + str(i) + "]", errors, opts)
            for i in range(n - sample, n):
                item.check(value[i], path + "[" + str(i) + "]", errors, opts)
            return value
        out = []
        i = 0
        for element in value:
            out.append(item.check(element, path + "[" + str(i) + "]", errors, opts))
            i += 1
        return out

    def json_schema(self):
        out = {"type": "array", "items": self.item.json_schema()}
        if self.min is not None:
            out["minItems"] = self.min
        if self.max is not None:
            out["maxItems"] = self.max
        return out

    def __repr__(self):
        kwargs = []
        if self.min is not None:
            kwargs.append(("min", self.min))
        if self.max is not None:
            kwargs.append(("max", self.max))
        return _source("array", [self.item], kwargs)


_MISSING = object()


class fresh:
    """A default that is a copy of `value` per parse, for a list or dict default that must not
    be shared between values: `("tags", array(text()), fresh(["new"]))`. `list` and `dict`
    themselves do for an empty one."""

    def __init__(self, value):
        self.value = value

    def __call__(self):
        return list(self.value) if type(self.value) is list else dict(self.value)

    def __repr__(self):
        return "fresh(" + repr(self.value) + ")"


def _default_json(default):
    """What a callable default is worth in JSON Schema, if it can be said."""
    if type(default) is fresh:
        return default.value
    if default is list:
        return []
    if default is dict:
        return {}
    return _MISSING


class Record(Type):
    """A dict with named fields, given as pairs: `(name, type)` is required, `(name, type,
    default)` is optional and a missing field takes the default (called if callable, so a
    list default is a fresh list each time). `extra` says what an undeclared key does:
    `"ignore"` drops it, `"allow"` keeps it, `"forbid"` reports it."""

    def __init__(self, *fields, extra="ignore"):
        if extra not in ("ignore", "allow", "forbid"):
            raise ValueError("extra must be 'ignore', 'allow' or 'forbid'")
        self.fields = []
        self.extra = extra
        names = {}
        for spec in fields:
            if type(spec) is dict:
                raise TypeError(
                    "record takes (name, type[, default]) pairs, not a dict: MicroPython keeps no dict order"
                )
            if type(spec) is not tuple or len(spec) not in (2, 3) or type(spec[0]) is not str:
                raise TypeError("a field is (name, type) or (name, type, default)")
            name = spec[0]
            if name in names:
                raise ValueError("duplicate field " + repr(name))
            if not isinstance(spec[1], Type):
                raise TypeError("field %r: expected a schema type, got %r" % (name, spec[1]))
            names[name] = True
            default = spec[2] if len(spec) == 3 else _MISSING
            self.fields.append((name, spec[1], default))
        self._names = names

    def names(self):
        return [name for name, _, _ in self.fields]

    def field(self, name):
        for field_name, t, _ in self.fields:
            if field_name == name:
                return t
        raise KeyError(name)

    def check(self, value, path, errors, opts):
        if type(value) is not dict:
            errors.append((path, "expected an object"))
            return value
        out = {}
        for name, t, default in self.fields:
            if name in value:
                out[name] = t.check(value[name], path + "." + name, errors, opts)
            elif default is not _MISSING:
                out[name] = default() if callable(default) else default  # ty: ignore[call-top-callable]
            else:
                errors.append((path + "." + name, "missing"))
        if self.extra != "ignore":
            names = self._names
            for key in value:
                if key not in names:
                    if self.extra == "forbid":
                        errors.append((path + "." + str(key), "not a field"))
                    else:
                        out[key] = value[key]
        return out

    def json_schema(self):
        properties = {}
        required = []
        for name, t, default in self.fields:
            prop = t.json_schema()
            if default is _MISSING:
                required.append(name)
            else:
                value = _default_json(default) if callable(default) else default
                if value is not _MISSING:
                    prop = dict(prop)
                    prop["default"] = value
            properties[name] = prop
        out = {"type": "object", "properties": properties}
        if required:
            out["required"] = required
        if self.extra == "forbid":
            out["additionalProperties"] = False
        return out

    def __repr__(self):
        parts = []
        for name, t, default in self.fields:
            field = repr(name) + ", " + repr(t)
            if default is not _MISSING:
                # `list` and `dict` are their names, not `<class 'list'>`, so the source runs.
                field += ", " + ("list" if default is list else "dict" if default is dict else repr(default))
            parts.append("(" + field + ")")
        if self.extra != "ignore":
            parts.append("extra=" + repr(self.extra))
        return "record(" + ", ".join(parts) + ")"


class Mapping(Type):
    """A dict of `value`s under string keys (`key` narrows the key, e.g. `pattern`)."""

    def __init__(self, value, key=None):
        self.value = value
        self.key = key

    def check(self, value, path, errors, opts):
        if type(value) is not dict:
            errors.append((path, "expected an object"))
            return value
        out = {}
        key_type = self.key
        for key in value:
            here = path + "." + str(key)
            if type(key) is not str:
                errors.append((here, "keys must be strings"))
                continue
            if key_type is not None:
                key_type.check(key, here, errors, opts)
            out[key] = self.value.check(value[key], here, errors, opts)
        return out

    def json_schema(self):
        out = {"type": "object", "additionalProperties": self.value.json_schema()}
        if self.key is not None and getattr(self.key, "pattern", None) is not None:
            out["propertyNames"] = {"pattern": self.key.pattern}
        return out

    def __repr__(self):
        return _source("mapping", [self.value], [("key", self.key)] if self.key is not None else [])


class OneOf(Type):
    """The first alternative the value satisfies. The error names how many were tried; the
    alternatives' own messages would be one list per branch, which helps nobody."""

    def __init__(self, *types):
        if len(types) < 2:
            raise ValueError("one_of needs at least two alternatives")
        self.types = types

    def check(self, value, path, errors, opts):
        for t in self.types:
            scratch = []
            out = t.check(value, path, scratch, opts)
            if not scratch:
                return out
        errors.append((path, "matched none of %d alternatives" % len(self.types)))
        return value

    def json_schema(self):
        return {"anyOf": [t.json_schema() for t in self.types]}

    def __repr__(self):
        return _source("one_of", list(self.types), [])


# The API is lowercase: a schema reads as a description, and `repr` prints one back.
text = Text
pattern = Pattern
email = Email
url = Url
uuid = Uuid
ipv4 = Ipv4
iso_date = IsoDate
iso_datetime = IsoDateTime
integer = Integer
number = Number
boolean = Boolean
literal = Literal
anything = Anything
optional = Optional
array = Array
record = Record
mapping = Mapping
one_of = OneOf
