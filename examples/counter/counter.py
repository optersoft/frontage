from frontage import Memo, Signal, component, h, mount


@component
def counter(initial=0, step=1):
    count = Signal(initial)
    double = Memo(lambda: count() * 2)
    return h.div(
        h.button("-", on_click=lambda ev: count.update(lambda n: n - step), id="dec"),
        h.span("Value: ", count, ", doubled: ", double, id="value"),
        h.button("+", on_click=lambda ev: count.update(lambda n: n + step), id="inc"),
        h.p(lambda: "even" if count() % 2 == 0 else "odd", class_big=lambda: abs(count()) > 5, id="parity"),
        cls="counter",
    )


mount(lambda: counter(initial=0), "#app")
