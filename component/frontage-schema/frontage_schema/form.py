"""A form over a schema: one signal per field, one error per field, a guarded submit.

    User = record(("name", text(min=1)), ("email", email()), ("age", integer(gt=0), None))
    form = Form(User)                      # a Signal per field, or Form(User, state)

    h.form(
        text_input(form.signal("name"), "Name"), form.message("name"),
        text_input(form.signal("email"), "Email"), form.message("email"),
        number_input(form.signal("age"), "Age"), form.message("age"),
        button("Save", type="submit", disabled=lambda: not form.valid()),
        on_submit=form.submit(save),       # save: an Action, or any callable of the value
    )

The fields are checked with `coerce=True` as they change, since a text input holds a string
whatever the schema says. A field's message shows once the field has been edited or a submit
was attempted, not before the visitor has typed anything, and `valid` is true the moment every
message is gone. `submit` calls the action with the parsed value only when there are none.
"""

from frontage import Effect, Memo, Signal, h

from . import Record, Text

__all__ = ["Form"]


class Form:
    def __init__(self, schema, source=None):
        if not isinstance(schema, Record):
            raise TypeError("Form needs a record schema")
        self.schema = schema
        self._signals = {}
        self._touched = {}
        self._messages = {}
        self._submitted = Signal(False)
        for name, t, default in schema.fields:
            signal = _adopt(source, name)
            if signal is None:
                signal = Signal(_initial(t, default))
            self._signals[name] = signal
            self._touched[name] = Signal(False)
            self._watch(name, signal)
        self._result = Memo(self._compute)
        self.errors = Memo(lambda: self._result()[1])
        self.valid = Memo(lambda: not self._result()[1])
        self.value = Memo(lambda: None if self._result()[1] else self._result()[0])
        # Every field's memo is made here, under the form's owner, not on first read: a memo
        # first read inside a hole would belong to the hole and die with its next run.
        for name in self._signals:
            self._messages[name] = Memo(self._finder(name))

    def _watch(self, name, signal):
        touched = self._touched[name]
        seen = [False]

        def mark(_value, _prev):
            if seen[0]:
                touched.set(True)
            seen[0] = True

        Effect(signal, effect=mark)

    def _compute(self):
        data = {}
        for name, signal in self._signals.items():
            data[name] = signal()
        return self.schema.validate(data, coerce=True)

    def _finder(self, name):
        prefix = "$." + name
        touched = self._touched[name]
        submitted = self._submitted

        def find():
            if not (submitted() or touched()):
                return None
            for path, message in self._result()[1]:
                if path == prefix or path.startswith(prefix + ".") or path.startswith(prefix + "["):
                    return message
            return None

        return find

    # --- what a view uses -------------------------------------------------------------------

    def signal(self, name):
        """The `Signal` behind a field, to give a widget."""
        return self._signals[name]

    def error(self, name):
        """An accessor: the field's first message, or None while it has none to show."""
        return self._messages[name]

    def message(self, name, cls="fr-error", **attrs):
        """The element that shows `error(name)`: a `<span>` that is empty while there is none."""
        return h.span(self._messages[name], cls=cls, **attrs)

    def touched(self, name):
        return self._touched[name]()

    def submitted(self):
        return self._submitted()

    def snapshot(self):
        """The fields as typed, untracked."""
        return {name: signal.peek() for name, signal in self._signals.items()}

    def submit(self, action):
        """The `on_submit` handler: prevents the reload, marks the form submitted so every
        message shows, and calls `action` (`.dispatch` if it has one) with the parsed value
        when there is no error. Returns whether it did."""

        def on_submit(ev=None):
            if ev is not None and hasattr(ev, "preventDefault"):
                ev.preventDefault()
            self._submitted.set(True)
            value, errors = self.schema.validate(self.snapshot(), coerce=True)
            if errors:
                return False
            if hasattr(action, "dispatch"):
                action.dispatch(value)
            else:
                action(value)
            return True

        return on_submit

    def reset(self):
        """Back to the defaults, untouched, unsubmitted."""
        for name, t, default in self.schema.fields:
            self._signals[name].set(_initial(t, default))
        for touched in self._touched.values():
            touched.set(False)
        self._submitted.set(False)


def _adopt(source, name):
    """The signal a `State` or a dict already holds for `name`, if any."""
    if source is None:
        return None
    signals = getattr(source, "_signals", None)
    if signals is not None and hasattr(source, "signal"):
        return source.signal(name) if name in signals else None
    return source.get(name)


def _initial(t, default):
    from . import _MISSING

    if default is not _MISSING:
        return default() if callable(default) else default
    return "" if isinstance(t, Text) else None
