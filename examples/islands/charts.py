"""An island named by a string, so `frontage build` leaves it out of the first payload.

`island("charts:sparkline")` is `Route(lazy=…)` for a page: the module and everything only
it reaches — `samples` here — is a chunk, fetched the first time someone scrolls to it.
"""

from samples import VALUES

from frontage import Memo, Signal, h


def sparkline(title="Thirty days"):
    scale = Signal(1)
    top = Memo(lambda: max(VALUES) * scale())

    def bar(value):
        return h.i(style_height=lambda: f"{value / top() * 100:.0f}%")

    return h.div(
        h.h3(title),
        h.div(*[bar(v) for v in VALUES], cls="spark", id="spark"),
        h.button("taller", on_click=lambda ev: scale.update(lambda s: max(0.25, s - 0.25)), id="taller"),
        h.span(lambda: f" peak {top():.0f}", id="peak"),
        cls="card",
    )
