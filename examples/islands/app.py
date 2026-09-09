"""A page that ships no runtime, and two islands that ask for one.

`mount(page, "#app", when="never")` is a **static page**: `frontage prerender` renders it
once, writes the HTML, and writes no boot tag — a visitor downloads the page and the
stylesheet and stops. The 265 KB of WebAssembly that an app needs is not on the critical
path of a page that has nothing to run.

What comes alive is the islands, each on a trigger of its own. The first trigger to fire
boots the runtime **once**; both islands share it, and each hydrates the markup already on
screen. The toggle is `idle` because it is above the fold and cheap; the sparkline is
`visible` and named by a string, so its module and its data are a chunk that a reader who
never scrolls never pays for.
"""

from widgets import theme_toggle

from frontage import h, island, mount

FILLER = (
    "An island is a mount with a trigger. Everything around this sentence was rendered "
    "on CPython at build time and will never be touched again: it is HTML, and the browser "
    "already knows how to show HTML."
)


def page():
    return h.main(
        h.h1("Islands"),
        h.p("Zero runtime by default; interactive where it says so.", cls="lede"),
        island(theme_toggle, when="idle", label="Dark mode"),
        *[h.p(FILLER, cls="filler") for _ in range(12)],
        island("charts:sparkline", when="visible", title="Thirty days"),
        h.p("The chart above arrived in a chunk of its own.", cls="filler"),
    )


mount(page, "#app", when="never")
