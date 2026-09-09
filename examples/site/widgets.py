"""The one island on the whole site."""

from frontage import Signal, h


def reactions(post="", label="Useful"):
    count = Signal(0)
    mine = Signal(False)

    def toggle(ev):
        mine.set(not mine())
        count.update(lambda n: n + (1 if mine() else -1))

    return h.div(
        h.button(label, on_click=toggle, id="react"),
        h.span(lambda: f" {count()} so far" if count() else " be the first", id="react-count"),
        cls="box",
    )
