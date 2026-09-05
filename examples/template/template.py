"""The counter again, written with a template string (Python 3.14, on both interpreters)."""

from frontage import Memo, Signal, component, html, mount


@component
def counter(initial=0):
    count = Signal(initial)
    double = Memo(lambda: count() * 2)

    def dec(ev):
        count.update(lambda n: n - 1)

    def inc(ev):
        count.update(lambda n: n + 1)

    # A lambda inside `{…}` needs parentheses, as in f-strings; named functions read better.
    def big():
        return abs(count()) > 5

    def parity():
        return "even" if count() % 2 == 0 else "odd"

    return html(t"""
        <div class="counter">
            <button on:click={dec} id="dec">-</button>
            <span id="value">Value: {count}, doubled: {double}</span>
            <button on:click={inc} id="inc">+</button>
            <p id="parity" class:big={big}>{parity}</p>
        </div>
    """)


mount(lambda: counter(initial=0), "#app")
