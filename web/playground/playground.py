"""The playground: the code in the editor runs against the frontage package on this site; the
URL fragment carries the code, so a link is a saved snippet. Runs on MicroPython."""

from pyscript import document, ffi, window

import frontage
from frontage.errors import format_exception

EXAMPLES = {
    "counter": '''from frontage import Signal, component, html, mount


@component
def counter(initial=0):
    count = Signal(initial)

    def inc(ev):
        count.update(lambda n: n + 1)

    def dec(ev):
        count.update(lambda n: n - 1)

    return html(t"""
        <div>
            <button on:click={dec}>-</button>
            <span> {count} </span>
            <button on:click={inc}>+</button>
        </div>
    """)


mount(lambda: counter(initial=0), "#app")
''',
    "todo": '''from frontage import For, Signal, Store, component, html, mount

store = Store({"todos": [{"id": 1, "text": "try the playground", "done": False}], "next": 2})
draft = Signal("")


def add(ev):
    ev.preventDefault()
    if draft().strip():
        store.set(lambda d: (d.todos.append({"id": d.next, "text": draft(), "done": False}), d.__setitem__("next", d.next + 1)))
        draft.set("")


def row(todo, index):
    def toggle(ev):
        store.set(lambda d: d.todos[index()].__setitem__("done", not d.todos[index()]["done"]))

    def decoration():
        return "line-through" if store.todos[index()]["done"] else "none"

    return html(t"""
        <li>
            <input type="checkbox" on:change={toggle}>
            <span style:text-decoration={decoration}>{todo["text"]}</span>
        </li>
    """)


@component
def app():
    return html(t"""
        <form on:submit={add}>
            <input bind:value={draft} placeholder="what needs doing?">
            <button>Add</button>
        </form>
        <ul>{For(lambda: store.todos, row, key=lambda t: t["id"])}</ul>
    """)


mount(app, "#app")
''',
    "fetch": '''import asyncio

from frontage import Errored, Loading, Resource, Signal, component, html, mount


async def load(n):
    await asyncio.sleep(0.5)
    if n > 3:
        raise ValueError(f"{n} is too many")
    return [f"item {i}" for i in range(n)]


@component
def app():
    n = Signal(1)
    items = Resource(load, source=n)

    def more(ev):
        n.update(lambda v: v + 1)

    def failed(exc, reset):
        def retry(ev):
            n.set(1)
            reset()

        return html(t"<p>{str(exc)} <button on:click={retry}>reset</button></p>")

    def listing():
        return html(t"<ul>{[html(t'<li>{x}</li>') for x in items()]}</ul>")

    return html(t"""
        <div>
            <button on:click={more}>more</button>
            {Errored(failed, lambda: Loading(html(t"<p>loading…</p>"), listing))}
        </div>
    """)


mount(app, "#app")
''',
    "state": '''from frontage import State, component, computed, field, html, mount
from frontage.widgets import checkbox, select, slider, text_input


class Order(State):
    name = field("")
    size = field("m")
    qty = field(1)
    gift = field(False)

    @computed
    def summary(self):
        wrap = ", gift-wrapped" if self.gift else ""
        return f"{self.qty} x {self.size.upper()} for {self.name or 'someone'}{wrap}"


@component
def app():
    o = Order()

    def summary():
        return o.summary

    return html(t"""
        <div>
            {text_input(o.signal("name"), "Name")}
            {select(o.signal("size"), ["s", "m", "l"], "Size")}
            {slider(o.signal("qty"), "Quantity", min=1, max=10)}
            {checkbox(o.signal("gift"), "Gift wrap")}
            <p><b>{summary}</b></p>
        </div>
    """)


mount(app, "#app")
''',
    "tailwind": '''from frontage import Signal, component, html, mount

# Tailwind's browser build is on this page, so utility classes just work: it watches the
# DOM and writes the CSS for every class it sees, including the ones Frontage inserts.


@component
def card():
    count = Signal(0)

    def inc(ev):
        count.update(lambda n: n + 1)

    def times():
        return f"clicked {count()} times"

    return html(t"""
        <div class="max-w-sm rounded-xl bg-white p-6 shadow-lg ring-1 ring-zinc-200 dark:bg-zinc-800 dark:ring-zinc-700">
            <h2 class="text-xl font-semibold text-zinc-900 dark:text-zinc-100">Tailwind</h2>
            <p class="mt-2 text-sm text-zinc-600 dark:text-zinc-300">{times}</p>
            <button on:click={inc}
                    class="mt-4 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500">
                Count
            </button>
        </div>
    """)


mount(card, "#app")
''',
}

editor = document.getElementById("code")
status = document.getElementById("status")
picker = document.getElementById("example")
handle = [None]


def current_code():
    fragment = str(window.location.hash)
    if fragment.startswith("#code="):
        return str(window.decodeURIComponent(fragment[6:]))
    return EXAMPLES["counter"]


def run(ev=None):
    if handle[0] is not None:
        handle[0].dispose()
        handle[0] = None
    out = document.getElementById("out")
    out.innerHTML = '<div id="app"></div>'
    namespace = {"__name__": "__main__"}
    try:
        exec(str(editor.value), namespace)
        status.textContent = f"ran on {frontage.platform} · Frontage {frontage.__version__}"
    except Exception as exc:
        pre = document.createElement("pre")
        pre.className = "frontage-error"
        pre.textContent = format_exception(exc)
        out.appendChild(pre)
        status.textContent = "error"


def share(ev=None):
    code = str(editor.value)
    window.location.hash = "code=" + str(window.encodeURIComponent(code))
    try:
        window.navigator.clipboard.writeText(str(window.location.href))
        status.textContent = "link copied"
    except Exception:
        status.textContent = "link is in the address bar"


def pick(ev):
    editor.value = EXAMPLES[str(picker.value)]
    run()


editor.value = current_code()
document.getElementById("run").addEventListener("click", ffi.create_proxy(run))
document.getElementById("share").addEventListener("click", ffi.create_proxy(share))
picker.addEventListener("change", ffi.create_proxy(pick))
run()
