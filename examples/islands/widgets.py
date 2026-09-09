"""The one island above the fold: a toggle, three lines of state, no runtime until idle."""

from frontage import Signal, h
from frontage.runtime import document, in_browser


def theme_toggle(label="Dark mode"):
    dark = Signal(False)

    def flip(ev):
        dark.set(not dark())
        if in_browser:
            document.body.classList.toggle("dark", dark())

    return h.div(
        h.button(label, on_click=flip, id="theme"),
        h.span(lambda: " on" if dark() else " off", id="theme-state"),
        cls="card",
    )
