"""The one island: a reaction counter, hydrated when a reader scrolls to the post that has it."""

from frontage import Signal, html


def reactions(post="", label="Useful"):
    count = Signal(0)
    mine = Signal(False)

    def toggle(ev):
        mine.set(not mine())
        count.update(lambda n: n + (1 if mine() else -1))

    def text():
        return f"{count()} so far" if count() else "be the first"

    return html(t"""
        <div class="box">
            <button on:click={toggle}>{label}</button>
            <span> {text}</span>
        </div>
    """)
