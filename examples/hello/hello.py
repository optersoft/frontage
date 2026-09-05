from pyscript import document

import frontage
from frontage import Effect, Memo, Signal, Store, h, render_to_string

# Exercise the reactive core and the store here too: this file runs under MicroPython in
# the browser suite, which is the only check that the package stays in its subset.
count = Signal(1)
double = Memo(lambda: count() * 2)
seen = []
Effect(lambda: seen.append(double()))
count.set(21)
store = Store({"user": {"name": "Ann"}})
names = []
Effect(lambda: names.append(store.user.name))
store.set_path("user", "name", "Bob")

view = h.p("Hello from the string renderer")
document.getElementById("app").textContent = (
    f"Frontage {frontage.__version__} on {frontage.platform}\n{render_to_string(view)}\nreactive: {seen} store: {names}"
)
