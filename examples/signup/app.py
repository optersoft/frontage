"""One schema, two boundaries: a form checked as it is typed, and JSON checked when it lands.

`User` is written once. On the left, `Form(User)` gives every field a signal and a message;
on the right, `array(User).validate` reads what someone pasted and lists each error by path.
"""

import json

from frontage import For, Show, Signal, h, mount
from frontage.schema import array, email, integer, literal, optional, record, text, url
from frontage.schema.form import Form
from frontage.widgets import button, number_input, select, text_input, textarea

User = record(
    ("name", text(min=1, max=100, strip=True)),
    ("email", email()),
    ("age", optional(integer(gt=0, le=150)), None),
    ("role", literal("admin", "user"), "user"),
    ("website", optional(url(schemes=("http", "https"))), None),
)

# --- the form -------------------------------------------------------------------------------

form = Form(User)
saved = Signal(None)


def save(user):
    saved.set(user)


def signup():
    return h.section(
        h.h2("A form"),
        h.form(
            text_input(form.signal("name"), "Name", id="name"),
            form.message("name", id="e-name"),
            text_input(form.signal("email"), "Email", id="email"),
            form.message("email", id="e-email"),
            number_input(form.signal("age"), "Age", id="age"),
            form.message("age", id="e-age"),
            select(form.signal("role"), ["user", "admin"], "Role", id="role"),
            form.message("role", id="e-role"),
            text_input(form.signal("website"), "Website", id="website", placeholder="https://"),
            form.message("website", id="e-website"),
            button("Save", type="submit", disabled=lambda: not form.valid(), id="save"),
            on_submit=form.submit(save),
        ),
        Show(lambda: saved() is not None, lambda: h.pre(json.dumps(saved()), id="saved")),
    )


# --- the JSON -------------------------------------------------------------------------------

# Not `json.dumps(…, indent=2)`: MicroPython's `dumps` takes no `indent`.
pasted = Signal(
    "[\n"
    '  {"name": "Ada", "email": "ada@example.com", "age": 36},\n'
    '  {"name": "", "email": "nope", "age": 0, "role": "root"}\n'
    "]"
)
report = Signal(None)


def check(ev=None):
    try:
        data = json.loads(pasted())
    except ValueError as exc:
        report.set([("$", "not JSON: " + str(exc))])
        return
    report.set(array(User).validate(data)[1])


def verdict():
    errors = report()
    if errors is None:
        return ""
    return "valid" if not errors else "%d errors" % len(errors)


def paste():
    return h.section(
        h.h2("The same schema over JSON"),
        textarea(pasted, id="json"),
        button("Check", on_click=check, id="check"),
        h.p(verdict, id="verdict"),
        h.ul(For(lambda: report() or [], lambda err, i: h.li(err[0] + ": " + err[1])), id="report"),
    )


mount(
    lambda: h.div(
        h.h1("Sign up"),
        h.p("One schema. The form checks each field as you type; the box checks a document.", cls="lede"),
        h.div(signup(), paste(), cls="halves"),
    ),
    "#app",
)
