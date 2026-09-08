# frontage.schema

Validation for [frontage](https://github.com/optersoft/frontage) apps, in the page: JSON checked
at the boundary it crosses, and forms checked as they are typed. Pure Python on both
interpreters, no dependency, nothing in the browser but the Python that runs.

```sh
pip install frontage
```

## A schema

```python
from frontage.schema import record, text, email, integer, optional, array, literal

User = record(
    ("id", integer(ge=0)),
    ("name", text(min=1, max=100)),
    ("email", email()),
    ("age", optional(integer(gt=0, le=150)), None),  # a third element is a default: optional
    ("role", literal("admin", "user"), "user"),
    ("tags", array(text()), list),  # a callable default is called per value
)
```

Fields are **pairs, not keyword arguments**, because MicroPython does not keep a dict's
insertion order and the order of fields shows in the error list and in a form.

| type | accepts |
|---|---|
| `text(min, max, pattern, strip)` | a string; `pattern` is searched, unanchored, as in JSON Schema |
| `integer(gt, ge, lt, le, multiple_of)` | an `int`, and not a `bool` |
| `number(…, finite=True)` | an `int` or a `float`; NaN and infinity are not numbers unless you say so |
| `boolean()` | a `bool` |
| `literal(*values)` | one of the values, by type and equality, so `1` is not `True` |
| `email()`, `url(schemes=)`, `uuid()`, `ipv4()`, `iso_date()`, `iso_datetime()` | the formats, as string code (see below) |
| `pattern(p)` | `text(pattern=p)` |
| `optional(t)` | `t` or None |
| `array(t, min, max)` | a list of `t` |
| `record(*fields, extra="ignore")` | a dict with those fields; `extra` drops, keeps (`"allow"`) or reports (`"forbid"`) undeclared keys |
| `mapping(t, key=)` | a dict of `t` under string keys |
| `one_of(*types)` | the first alternative that fits |
| `anything()` | anything |

A schema prints as the code that builds it, so `repr(User)` is documentation and `eval` of it
is the same schema.

## Checking a value

```python
value, errors = User.validate(data)  # errors: [("$.email", "not an email address"), …]
value = User.parse(data)  # or raise SchemaError, whose .errors is that list
User.is_valid(data)
```

`value` is the data with defaults filled and coercions applied; `errors` is a list of
`(path, message)` pairs in schema order, with paths like `$.lines[2].qty`. Every error is
collected, the walk never raises, and a wrong container stops the walk at that node.

Two switches cover every boundary an app has:

- **`coerce=True`** reads strings. A text input holds `"28"` whatever the schema says, a query
  parameter is always a string, and an empty field is `""`; with `coerce`, `"28"` is 28,
  `"on"` is True, and `""` is None for an `optional` field. Without it, JSON is checked as
  typed: a string is not an integer.
- **`sample=N`** walks an array's first and last N items only, with the length and the type of
  the whole, and hands the list back as it was. Walking a value costs about ten times its
  `json.loads` (13 µs a row for five fields, MicroPython, 2026-09-07): fine for a page load of
  a thousand records, not for a table of fifty thousand.

```python
rows = array(User).parse(await fetch_json(url), sample=20)  # the shape, and both ends
params = Query.parse(dict(use_query()), coerce=True)  # strings in, typed out
```

## A form

```python
from frontage import h, Action
from frontage.widgets import text_input, number_input, button
from frontage.schema.form import Form

form = Form(User)  # a Signal per field; or Form(User, state)


async def save(user): ...


saving = Action(save)

view = h.form(
    text_input(form.signal("name"), "Name"),
    form.message("name"),
    text_input(form.signal("email"), "Email"),
    form.message("email"),
    number_input(form.signal("age"), "Age"),
    form.message("age"),
    button("Save", type="submit", disabled=lambda: not form.valid()),
    on_submit=form.submit(saving),
)
```

`form.signal(name)` is what a widget binds to. `form.error(name)` is an accessor for the
field's first message, which stays None until the field has been edited or a submit was
attempted, so a visitor is not shouted at before typing. `form.message(name)` is that in a
`<span class="fr-error">`. `form.valid`, `form.errors` and `form.value` are memos over the
whole record, and `form.submit(action)` is the `on_submit` handler: it prevents the reload,
shows every message, and calls the action (`.dispatch` if it has one) with the **parsed**
value only when there is no error. A `State` lends its signals: `Form(User, state)` binds the
fields it has and makes signals for the rest.

## Pydantic, and JSON Schema

Pydantic cannot run in the page (MicroPython keeps no `__annotations__`, has no `typing`, and
`metaclass=` raises), so it stays on CPython where the models already live, and reaches the
page as JSON Schema:

```sh
frontage schema app.models:User app.models:Order -o app/schemas.py
```

reads each model's `model_json_schema()` and writes `User = record(…)` as source. Anything
that only exists as Python — a `@field_validator` — does not cross, and the file names each one
it skipped. `--json openapi.json --ref '#/components/schemas/User'` compiles a published schema
instead. At runtime, `from_json_schema(document)` does the same in the page, for an API
whose schema is fetched, and `schema.json_schema()` goes back the other way.

The subset read: `type` (one, or a list with `"null"`), `properties` / `required` /
`additionalProperties`, `items` / `minItems` / `maxItems`, `enum` / `const`, the numeric
bounds, `minLength` / `maxLength` / `pattern`, `format` for email, uri, uuid, ipv4, date and
date-time, `default`, `anyOf` / `oneOf`, and local `$ref`s.

## The formats are string code, on purpose

MicroPython's `re` has no counted repeats: `\d{4}` compiles and then never matches, silently.
So the email, URL, UUID, IPv4 and ISO date checks are written out as string code, and
`text(pattern=…)` refuses a pattern containing `{` rather than let it fail in the browser only.

What they accept is deliberately what a form wants: `http://localhost:8000` is a URL,
`a@@b.c` is not an email, `2026-02-30` is not a date, and an internationalised address is not
accepted (the hostname must be ASCII).

## Size

The page gets ~40 KB of Python source (the core, the form, the JSON Schema bridge) and no
JavaScript; the compiler stays on CPython, and the stylesheet is one rule for `.fr-error`. Apache 2.0.
