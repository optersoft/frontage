"""A small catalogue of form controls bound to signals: the vocabulary Streamlit and Shiny
give a beginner, as plain HTML elements with a class hook and nothing else.

Every widget takes the `Signal` it reads and writes, an optional `label`, and any extra
attributes for the element. They return views, so they go anywhere a view goes.
"""

from .reactive import Signal
from .view import h, unique_id

__all__ = ["button", "checkbox", "number_input", "radio_group", "select", "slider", "text_input", "textarea"]


def _labelled(control, label, control_id=None, **attrs):
    if label is None:
        return control
    if control_id is not None:
        attrs["for_"] = control_id
    return h.label(label, " ", control, cls="fr-field", **attrs)


def _id(attrs):
    """Every control gets an id (`unique_id()` unless given), so its label can name it."""
    return attrs.setdefault("id", unique_id())


def _check(signal, what):
    if not isinstance(signal, Signal):
        raise TypeError(f"{what} needs a Signal")


def text_input(signal, label=None, **attrs):
    """`<input type=text>` bound two-way to `signal`."""
    _check(signal, "text_input")
    uid = _id(attrs)
    attrs.setdefault("type", "text")
    return _labelled(h.input(bind_value=signal, cls="fr-input", **attrs), label, uid)


def textarea(signal, label=None, **attrs):
    _check(signal, "textarea")
    uid = _id(attrs)
    return _labelled(h.textarea(bind_value=signal, cls="fr-textarea", **attrs), label, uid)


def number_input(signal, label=None, **attrs):
    """`<input type=number>`; the signal holds a number (or None while the field is empty)."""
    _check(signal, "number_input")
    uid = _id(attrs)

    def parse(ev):
        raw = ev.target.value
        if raw == "" or raw is None:
            signal.set(None)
            return
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return
        signal.set(int(value) if value == int(value) else value)

    return _labelled(
        h.input(
            type="number",
            prop_value=lambda: "" if signal() is None else signal(),
            on_input=parse,
            cls="fr-input",
            **attrs,
        ),
        label,
        uid,
    )


def slider(signal, label=None, min=0, max=100, step=1, **attrs):
    """`<input type=range>`; the signal holds a number, shown after the label."""
    _check(signal, "slider")

    def parse(ev):
        raw = ev.target.value
        value = float(raw)
        signal.set(int(value) if step == int(step) and value == int(value) else value)

    uid = _id(attrs)
    control = h.input(
        type="range", min=min, max=max, step=step, prop_value=signal, on_input=parse, cls="fr-slider", **attrs
    )
    if label is None:
        return control
    return h.label(label, " ", control, " ", h.output(signal, cls="fr-value", for_=uid), cls="fr-field", for_=uid)


def checkbox(signal, label=None, **attrs):
    _check(signal, "checkbox")
    uid = _id(attrs)
    return _labelled(h.input(type="checkbox", bind_checked=signal, cls="fr-checkbox", **attrs), label, uid)


def select(signal, options, label=None, **attrs):
    """`<select>` bound to `signal`. `options` is a list of values, or of `(value, label)`."""
    _check(signal, "select")
    uid = _id(attrs)
    pairs = [(o, o) if not isinstance(o, tuple) else o for o in options]

    def change(ev):
        signal.set(ev.target.value)

    control = h.select(
        *[
            h.option(str(text), value=str(value), prop_selected=lambda v=value: str(signal()) == str(v))
            for value, text in pairs
        ],
        prop_value=lambda: str(signal()),
        on_change=change,
        cls="fr-select",
        **attrs,
    )
    return _labelled(control, label, uid)


def radio_group(signal, options, label=None, name=None, **attrs):
    """A set of radios sharing `name`, bound as a group to `signal`."""
    _check(signal, "radio_group")
    pairs = [(o, o) if not isinstance(o, tuple) else o for o in options]
    name = name or unique_id("fr-radio")
    radios = [
        h.label(h.input(type="radio", name=name, value=str(value), bind_group=signal), " ", str(text))
        for value, text in pairs
    ]
    group = h.fieldset(*([h.legend(label)] if label is not None else []), *radios, cls="fr-radios", **attrs)
    return group


def button(label, on_click=None, **attrs):
    """A `<button type=button>`; `label` may be a signal or a function."""
    attrs.setdefault("type", "button")
    if on_click is not None:
        attrs["on_click"] = on_click
    return h.button(label, cls="fr-button", **attrs)
