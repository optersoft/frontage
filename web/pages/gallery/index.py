"""The gallery index: every app, with the numbers `tools/gallery.py` measured.

The apps themselves are built into `www/gallery/<name>/`; this page is merged in beside them.
"""

import optersoft_brand as brand
from gallery import gallery
from layouts.site import card, layout

from frontage import h

INTRO = (
    "Python in the browser, on its own runtime compiled to WebAssembly. Every app below is a directory "
    "of static files: no server, no build step, no JavaScript toolchain. The numbers are measured, not "
    "claimed — they come from loading each page in Chromium with a cold cache."
)
FOOT = (
    "mt-1 flex gap-5 border-t border-slate-200 pt-2 text-xs tabular-nums text-slate-500 "
    "dark:border-slate-800 dark:text-slate-400"
)
STRONG = "font-semibold text-slate-900 dark:text-white"


def _foot(app):
    return h.div(
        h.span(h.b(f"{app['bytes'] // 1024:,}", cls=STRONG), " KB"),
        h.span("shows in " if app.get("deferred") else "starts in ", h.b(str(app["ms"]), cls=STRONG), " ms")
        if app.get("ms") is not None
        else None,
        h.span("no runtime", cls="font-semibold text-emerald-700 dark:text-emerald-400")
        if app.get("deferred")
        else None,
        cls=FOOT,
    )


def _cards(data):
    return [
        h.div(
            *[card(f"./{app['name']}/", app["title"], _blurb(app["blurb"]), foot=_foot(app)) for app in data["apps"]],
            cls="grid gap-4 sm:grid-cols-2 lg:grid-cols-3",
        ),
        h.p(
            f"Measured {data['when']} · ",
            "Chromium, cold cache, first paint of the app's own content" if data["measured"] else "sizes only",
            f" · the interpreter, the loader and the framework are {data['shared_kb']:,} KB of every figure and "
            "are byte-identical, so a browser downloads them once for all of them. A card marked ",
            h.b("no runtime", cls=STRONG),
            " is a static page with islands: it was measured with the runtime denied, so its figure is the page, "
            "its stylesheet and the 1.3 KB loader — the runtime arrives later, when an island's trigger fires, "
            "or never.",
            cls="mt-10 text-sm text-slate-500 dark:text-slate-400",
        ),
    ]


def _blurb(text):
    """A blurb is authored in `gallery.py` and may write `<code>`; nothing here is input."""
    from frontage.content import view_of

    return view_of(text)


def page():
    data = gallery()
    return layout(
        [
            brand.page_header("Python apps, in the browser, measured.", label="Gallery", intro=INTRO),
            h.div(
                _cards(data)
                if data
                else h.p(
                    h.em("Nothing measured yet — ", h.code("mk gallery"), " builds the apps and writes the numbers."),
                    cls="text-slate-500 dark:text-slate-400",
                ),
                cls="container mx-auto px-5 sm:px-6 py-12 sm:py-16 max-w-6xl",
            ),
        ],
        title="Frontage gallery",
        description="Python apps running in the browser on WebAssembly. No server, no build step, no JavaScript.",
        canonical="https://frontage.optersoft.com/gallery/",
    )
