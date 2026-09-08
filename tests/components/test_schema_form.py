"""The form half: a signal per field, a message per field that waits for the visitor, and a
submit that only fires clean."""

from frontage import Action, Owner, State, field, render_to_string, run_with_owner
from frontage.schema import email, integer, optional, record, text
from frontage.schema.form import Form

User = record(("name", text(min=1)), ("email", email()), ("age", optional(integer(gt=0)), None))


def make(*args, **kw):
    owner = Owner()
    return run_with_owner(owner, lambda: Form(*args, **kw)), owner


def test_a_form_makes_a_signal_per_field_with_text_fields_empty():
    form, _ = make(User)
    assert form.signal("name").peek() == ""
    assert form.signal("email").peek() == ""
    assert form.signal("age").peek() is None


def test_errors_exist_from_the_start_but_a_message_waits_for_a_touch_or_a_submit():
    form, _ = make(User)
    assert form.valid() is False
    assert [path for path, _ in form.errors()] == ["$.name", "$.email"]
    assert form.error("name")() is None
    form.signal("name").set("A")
    form.signal("name").set("")
    assert form.error("name")() == "at least 1 characters"
    assert form.error("email")() is None  # untouched, not submitted
    form.submit(lambda v: None)()
    assert form.error("email")() == "not an email address"


def test_the_value_is_the_parsed_record_once_clean_and_submit_calls_the_action_with_it():
    form, _ = make(User)
    got = []
    form.signal("name").set("Ada")
    form.signal("email").set("ada@example.com")
    form.signal("age").set("36")  # a text input's string, coerced
    assert form.valid() is True
    assert form.value() == {"name": "Ada", "email": "ada@example.com", "age": 36}
    assert form.submit(got.append)() is True
    assert got == [{"name": "Ada", "email": "ada@example.com", "age": 36}]


def test_submit_dispatches_an_action_and_refuses_while_invalid():
    seen = []

    async def save(value):
        seen.append(value)

    form, _ = make(User)
    action = Action(save)
    assert form.submit(action)() is False
    assert form.submitted() is True
    assert seen == []


def test_a_state_lends_its_signals():
    class Signup(State):
        name = field("")
        email = field("")

    state = Signup()
    form, _ = make(User, state)
    assert form.signal("name") is state.signal("name")
    state.name = "Ada"
    assert form.snapshot()["name"] == "Ada"
    assert form.signal("age").peek() is None  # not on the State: the form made one


def test_a_dict_of_signals_works_too():
    from frontage import Signal

    name = Signal("x")
    form, _ = make(User, {"name": name})
    assert form.signal("name") is name


def test_reset():
    form, _ = make(User)
    form.signal("name").set("A")
    form.submit(lambda v: None)()
    form.reset()
    assert form.signal("name").peek() == "" and form.submitted() is False and form.touched("name") is False


def test_message_renders_an_empty_span_until_there_is_something_to_say():
    form, _ = make(User)
    assert render_to_string(lambda: form.message("name")) == '<span class="fr-error"></span>'
    form.signal("name").set("A")
    form.signal("name").set("")
    assert render_to_string(lambda: form.message("name")) == '<span class="fr-error">at least 1 characters</span>'


def test_a_form_needs_a_record():
    import pytest

    with pytest.raises(TypeError, match="record"):
        make(text())
