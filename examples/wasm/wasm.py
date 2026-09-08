"""A C or Rust library, compiled to WebAssembly, imported like any Python module.

The page declares it:

    <script ... data-fr-boot data-fr-entry="wasm" data-fr-js="mathlib=./mathlib.js"></script>

and the loader registers it before this file runs, so `import mathlib` is a plain import.
"""

import time

import mathlib

from frontage import Signal, h, mount

answer = Signal(mathlib.add(2, 40))


def again(ev):
    answer.update(lambda n: mathlib.add(n, 1))


# What a crossing costs: Python -> JavaScript -> the other wasm module and back. About 0.7
# microseconds, six ordinary method calls. Cheap per call; the thing to avoid is bulk,
# because the two modules have separate memories and arrays cross as a copy.
CALLS = 2000
start = time.ticks_us()
total = 0
for _ in range(CALLS):
    total = mathlib.add(total, 1)
each = (time.ticks_us() - start) / CALLS

mount(
    lambda: h.div(
        h.h1("A wasm library, imported"),
        h.p("mathlib.add(2, 40) = ", answer, id="answer"),
        h.button("add one", on_click=again, id="again"),
        h.p(f"{CALLS} crossings, {each:.2f} us each", id="cost"),
        h.p(f"loop total {total}", id="loop"),
    ),
    "#app",
)
