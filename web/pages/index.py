"""The landing page."""

import optersoft_brand as brand
from layouts.site import card, layout

from frontage import h

INTRO = (
    "A fine-grained reactive UI framework for Python, running in the browser on its own runtime "
    "compiled to WebAssembly. An app is a directory of static files: no server, no build step, no "
    "JavaScript toolchain. Signals, memos and effects update the exact text node that changed — the "
    "framework, the interpreter and the loader are downloaded once."
)

COUNTER = '''from frontage import Signal, component, html, mount

@component
def counter():
    count = Signal(0)

    def inc(ev):
        count.update(lambda n: n + 1)

    return html(t"""
        <button on:click={inc}>clicked {count} times</button>
    """)

mount(counter, "#app")'''

COMMAND = (
    "mt-8 max-w-3xl overflow-x-auto rounded-xl border border-slate-800 bg-slate-900 p-4 sm:p-5 "
    "font-mono text-[0.85rem] leading-relaxed text-slate-100"
)
BLOCK = (
    "mt-4 max-w-3xl overflow-x-auto rounded-xl border border-slate-200 bg-white p-5 font-mono text-sm "
    "leading-relaxed text-slate-800 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200"
)


def page():
    return layout(
        [
            brand.page_header(
                "Frontage",
                label="Python in the browser",
                intro=INTRO,
                glow=True,
                children=h.pre(h.code("uvx frontage build myapp/ --out site/"), cls=COMMAND),
            ),
            h.div(
                h.div(
                    card(
                        "https://academy.optersoft.com/python/frontage",
                        "Learn it",
                        "The chapters, on the academy — every code block runs in the page you are reading.",
                    ),
                    card(
                        "/gallery/",
                        "Gallery",
                        "Sixteen apps, each built with the real command and measured in a cold browser.",
                    ),
                    card(
                        "/playground/",
                        "Playground",
                        "Write Python, press Run, watch it render. Nothing is installed and nothing is sent anywhere.",
                    ),
                    cls="grid gap-4 sm:grid-cols-3",
                ),
                h.h2(
                    "A counter, whole",
                    cls="mt-14 text-2xl font-extrabold tracking-tight text-slate-900 dark:text-white",
                ),
                h.pre(h.code(COUNTER), cls=BLOCK),
                h.p(
                    "Apache 2.0 · the wheels of every release stay at ",
                    h.a(
                        "/dist/",
                        href="/dist/",
                        cls="font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300",
                    ),
                    ", because the chapters and their apps pin one by URL.",
                    cls="mt-10 text-sm text-slate-500 dark:text-slate-400",
                ),
                cls="container mx-auto px-5 sm:px-6 py-12 sm:py-16 max-w-6xl",
            ),
        ],
        title="Frontage — Python in the browser",
        description=(
            "A fine-grained reactive UI framework for Python, running in the browser on its own runtime "
            "compiled to WebAssembly. No server, no build step, no JavaScript."
        ),
        canonical="https://frontage.optersoft.com/",
    )
