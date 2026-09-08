"""Layout and status elements for frontage: the parts that make an app look like an app.

Pure Python and CSS. No JavaScript, no WebAssembly, no third-party dependency — which is why
this is the first component to build: it is the cheapest kilobyte-for-kilobyte answer to
Streamlit's `st.columns`, `st.tabs`, `st.expander`, `st.metric`, `st.progress` and friends.

Everything here returns an `Element`, so it composes with `h`, with `html(t"…")`, and with the
`with` form, and a hole anywhere inside stays a hole. Nothing wraps or intercepts children.
"""

from frontage import Signal, h

from .style import STYLESHEET

__all__ = ["STYLESHEET", "columns", "container", "divider", "expander", "metric", "progress", "spinner", "tabs"]


def _cls(base, extra):
    return f"{base} {extra}" if extra else base


def columns(*children, widths=None, gap="1rem", cls=None, **attrs):
    """Children side by side, in a CSS grid.

    `widths` are relative, as Streamlit's are: `columns(a, b, widths=[1, 3])` gives the second
    three times the room. Without them the columns are equal. They wrap on a narrow screen,
    which is a stylesheet's job and not this function's.
    """
    template = " ".join(f"{w}fr" for w in widths) if widths else f"repeat({len(children)}, 1fr)"
    cells = [h.div(child, cls="fr-col") for child in children]
    return h.div(*cells, cls=_cls("fr-columns", cls), style_grid_template_columns=template, style_gap=gap, **attrs)


def container(*children, cls=None, **attrs):
    """A plain grouping box with the component stylesheet's padding and border."""
    return h.div(*children, cls=_cls("fr-container", cls), **attrs)


def divider(**attrs):
    return h.hr(cls="fr-divider", **attrs)


def expander(label, *children, open=False, cls=None, **attrs):
    """A disclosure. `<details>`, because the browser already knows how to do this and a
    reimplementation would only be worse at keyboards and screen readers."""
    element = h.details(h.summary(label, cls="fr-expander-label"), *children, cls=_cls("fr-expander", cls), **attrs)
    if open:
        element.attrs["open"] = True
    return element


def metric(label, value, delta=None, help=None, cls=None, **attrs):
    """The number-with-a-change card. `delta` colours itself: leading `-` is a fall.

    `value` and `delta` may be accessors, so a metric over a signal updates in place rather
    than rebuilding — which is the entire reason to use this framework for a dashboard.
    """

    def direction():
        current = delta() if callable(delta) else delta
        return "fr-metric-delta fr-down" if str(current).startswith("-") else "fr-metric-delta fr-up"

    parts = [h.div(label, cls="fr-metric-label"), h.div(value, cls="fr-metric-value")]
    if delta is not None:
        parts.append(h.div(delta, cls=direction))
    return h.div(*parts, cls=_cls("fr-metric", cls), title=help, **attrs)


def progress(value, label=None, cls=None, **attrs):
    """A determinate bar. `value` is 0..1 and may be an accessor."""

    def width():
        current = value() if callable(value) else value
        return f"{max(0.0, min(1.0, float(current))) * 100:.1f}%"

    bar = h.div(h.div(cls="fr-progress-fill", style_width=width), cls="fr-progress-track")
    return h.div(h.div(label, cls="fr-progress-label") if label else None, bar, cls=_cls("fr-progress", cls), **attrs)


def spinner(label="Loading…", cls=None, **attrs):
    """A busy indicator. Pair it with `Loading` as the fallback, which is where it belongs."""
    return h.div(
        h.div(cls="fr-spinner-ring"), h.span(label, cls="fr-spinner-label"), cls=_cls("fr-spinner", cls), **attrs
    )


def tabs(panels, active=None, cls=None, **attrs):
    """`panels` is a sequence of `(label, view)` pairs. Only the selected panel is built.

    ⚠ **Pairs, not a dict, because MicroPython does not preserve insertion order.** CPython has
    guaranteed it since 3.7 and it is easy to assume everywhere; in the browser
    `{"Trend": …, "About": …}` came back as `["About", …, "Trend"]`, so the tabs were in a
    different order than they were written and the wrong one opened. Any API where the order of
    a mapping is visible has this bug — take pairs.

    `active` may be a `Signal` you own, so the selection can be read, written, routed to, or
    prerendered. Left out, the component keeps its own.
    """
    from frontage import Show

    if hasattr(panels, "items"):
        raise TypeError(
            "tabs() takes (label, view) pairs, not a dict: MicroPython does not preserve "
            "insertion order, so a dict would put your tabs in an arbitrary one"
        )
    panels = list(panels)
    if not panels:
        raise ValueError("tabs needs at least one panel")
    labels = [label for label, _ in panels]
    views = dict(panels)
    selected = active if active is not None else Signal(labels[0])

    def choose(label):
        return lambda ev: selected.set(label)

    def tab_class(label):
        return lambda: "fr-tab fr-active" if selected() == label else "fr-tab"

    strip = h.div(
        *[h.button(label, on_click=choose(label), cls=tab_class(label), type="button") for label in labels],
        cls="fr-tab-strip",
        role="tablist",
    )
    bodies = [Show(lambda label=label: selected() == label, views[label]) for label in labels]
    return h.div(strip, h.div(*bodies, cls="fr-tab-panel"), cls=_cls("fr-tabs", cls), **attrs)
