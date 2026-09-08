"""Your own Rust, called from Python, in the page.

`statlib` is a Rust crate in `rust/`, compiled to WebAssembly with nothing but cargo:

    cargo build --release --target wasm32-unknown-unknown

The page names its glue on the boot tag (`data-fr-js="statlib=./statlib.js"`), the loader
imports it before this file runs, and `import statlib` is then a plain import. That is the
whole contract: no bindings generator, no build step of ours, one kilobyte of WebAssembly.

What the numbers on this page are actually about is the **shape** of such a library. The two
WebAssembly modules have separate memories, so a list does not cross — it is copied, one
element at a time, and each element is a crossing. Loading 20,000 numbers therefore costs far
more than computing anything about them. A library that takes the list in every call would be
slower than plain Python; this one loads once and then answers questions for free.
"""

import time

import statlib

from frontage import Memo, Signal, h, mount

SIZE = 20_000


def sample(seed=7, count=SIZE):
    """A deterministic bell-ish sample, made here so the page needs no data file."""
    out = []
    state = seed
    for _ in range(count):
        total = 0
        for _ in range(4):  # four uniforms summed: enough of a bell for a histogram
            state = (1103515245 * state + 12345) % 2147483648
            total += state / 2147483648
        out.append((total - 2) * 3)
    return out


DATA = sample()


def python_mean(values):
    return sum(values) / len(values)


def python_stddev(values):
    average = python_mean(values)
    total = 0.0
    for value in values:
        total += (value - average) ** 2
    return (total / (len(values) - 1)) ** 0.5


def timed(fn):
    start = time.ticks_us()
    value = fn()
    return value, time.ticks_us() - start


_, load_us = timed(lambda: statlib.load(DATA))
stats, rust_us = timed(lambda: (statlib.mean(), statlib.stddev()))
python_stats, python_us = timed(lambda: (python_mean(DATA), python_stddev(DATA)))
low, high = statlib.range()

bins = Signal(48)
counts = Memo(lambda: statlib.histogram(bins(), low, high))


def rebin(step):
    def handler(ev):
        bins.set(max(8, min(192, bins() + step)))

    return handler


def bars():
    values = counts()
    tallest = max(values) or 1
    return [h.i(style=f"height:{100 * value / tallest:.1f}%") for value in values]


mount(
    lambda: h.div(
        h.h1("Your own Rust, in the page"),
        h.p(
            f"{SIZE:,} numbers, summarised by a one-kilobyte WebAssembly library written in Rust "
            "and imported like any Python module.",
            cls="note",
        ),
        h.div(
            h.div(h.span("mean"), h.strong(f"{stats[0]:.4f}"), id="mean"),
            h.div(h.span("std dev"), h.strong(f"{stats[1]:.4f}"), id="stddev"),
            h.div(h.span("rust"), h.strong(f"{rust_us / 1000:.2f} ms"), id="rust-ms"),
            h.div(h.span("python"), h.strong(f"{python_us / 1000:.2f} ms"), id="python-ms"),
            h.div(h.span("faster"), h.strong(f"{python_us / max(rust_us, 1):.0f}×"), id="ratio"),
            cls="numbers",
        ),
        h.div(bars, cls="bars", id="histogram"),
        h.p(
            h.button("fewer bins", on_click=rebin(-16), id="fewer"),
            " ",
            h.button("more bins", on_click=rebin(16), id="more"),
            " ",
            h.span(bins, id="bins"),
            " bins, recounted in Rust on every click — over the numbers it already has.",
        ),
        h.p(
            f"Getting the list there cost {load_us / 1000:.1f} ms: {SIZE:,} crossings, one per "
            f"number, against {rust_us / 1000:.2f} ms to compute both statistics. That ratio is "
            "the whole design rule — load once, ask many times.",
            cls="note",
            id="crossing",
        ),
        h.p(
            "Both answers agree to the last digit shown: ",
            f"Python says {python_stats[0]:.4f} and {python_stats[1]:.4f}.",
            cls="note",
            id="agree",
        ),
    ),
    "#app",
)
