from frontage import Signal, Store, component, h, mount
from frontage.flow import For, Show

store = Store({"todos": [{"id": 1, "text": "learn Frontage", "done": False}], "next_id": 2})
draft = Signal("")


def add(ev):
    ev.preventDefault()
    text = draft().strip()
    if not text:
        return
    store.set(
        lambda d: (
            d.todos.append({"id": d.next_id, "text": text, "done": False}),
            d.__setitem__("next_id", d.next_id + 1),
        )
    )
    draft.set("")


def toggle(todo):
    def handler(ev):
        store.set(lambda d: d.todos[_index(todo["id"])].__setitem__("done", not todo["done"]))

    return handler


def remove(todo):
    def handler(ev):
        store.set(lambda d: d.todos.pop(_index(todo["id"])))

    return handler


def _index(todo_id):
    for i, t in enumerate(store.todos):
        if t["id"] == todo_id:
            return i
    raise KeyError(todo_id)


def row(todo, index):
    tid = todo["id"]
    done = lambda: any(t["done"] for t in store.todos if t["id"] == tid)  # noqa: E731
    return h.li(
        h.input(type_="checkbox", prop_checked=done, on_change=toggle(todo)),
        h.span(todo["text"], class_done=done),
        h.button("×", on_click=remove(todo), cls="remove"),
        data_id=tid,
    )


@component
def app():
    remaining = lambda: sum(1 for t in store.todos if not t["done"])  # noqa: E731
    return h.div(
        h.form(
            h.input(placeholder="What needs doing?", bind_value=draft, id="new"),
            h.button("Add", type_="submit"),
            on_submit=add,
        ),
        h.ul(For(lambda: store.todos, row, key=lambda t: t["id"]), id="list"),
        h.p(
            Show(lambda: len(store.todos) > 0, lambda: h.span(remaining, " left", id="left"), fallback="Nothing to do")
        ),
    )


mount(app(), "#app")
