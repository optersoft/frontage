"""A signal, analysed in the page: a power spectrum, a spectrogram, and a filter.

`frontage.dsp` is twelve kilobytes of Rust compiled to WebAssembly. Nothing here talks to a
server, and nothing here is a picture rendered somewhere else: the samples are made in Python,
handed to the library once, and every question after that — the spectrum, the spectrogram, the
bandpass — is answered in the library's own memory and drawn by the page.

The signal is a chirp that sweeps from 30 Hz to 300 Hz in the last second, buried in noise.
That shape is not an accident: it is what a gravitational-wave inspiral looks like, and it is
the demo this framework could not run before.
"""

import time

from frontage import Memo, NodeRef, Signal, dsp, h, mount, on_cleanup
from frontage.chart import line_chart
from frontage.widgets import slider

RATE = 4096  # samples per second
SECONDS = 4
SIZE = RATE * SECONDS


def chirp():
    """A 30 → 300 Hz sweep in the last second, plus noise everywhere."""
    out = []
    state = 12345
    phase = 0.0
    for i in range(SIZE):
        t = i / RATE
        state = (1103515245 * state + 12345) % 2147483648
        noise = (state / 2147483648 - 0.5) * 0.8
        if t > SECONDS - 1:
            # The frequency rises through the last second; integrating it keeps the phase
            # continuous, which is what makes it sound and look like a sweep rather than a step.
            progress = t - (SECONDS - 1)
            frequency = 30.0 + 270.0 * progress
            phase += 2 * 3.141592653589793 * frequency / RATE
            out.append(noise + 1.6 * _sin(phase))
        else:
            out.append(noise)
    return out


def _sin(x):
    """The runtime has `math`, but this example is about the library doing the arithmetic —
    the Python here only makes the input."""
    import math

    return math.sin(x)


SAMPLES = chirp()

start = time.ticks_us()
dsp.load(SAMPLES)
load_us = time.ticks_us() - start

low = Signal(20)
high = Signal(400)
filtered = Signal(False)
canvas = NodeRef()


def analyse():
    """Reload the signal, apply the filter if asked, and time the whole analysis."""
    began = time.ticks_us()
    dsp.load(SAMPLES)
    if filtered():
        dsp.bandpass(RATE, low(), high())
    frequency, power = dsp.psd(1024, 512, RATE)
    loudness = dsp.rms()
    node = canvas()
    rows = bins = 0
    if node is not None:
        rows, bins = dsp.draw(node, 256, 64, -80.0)
    return {
        "series": [frequency, power],
        "rms": loudness,
        "rows": rows,
        "bins": bins,
        "us": time.ticks_us() - began,
    }


analysis = Memo(analyse)
on_cleanup(lambda: None)


def toggle(ev):
    filtered.update(lambda on: not on)


mount(
    lambda: h.div(
        h.h1("A signal, analysed in the page"),
        h.p(
            f"{SIZE:,} samples at {RATE:,} Hz — a chirp from 30 to 300 Hz in the last second, "
            "under noise. Everything below is computed here, in twelve kilobytes of Rust.",
            cls="note",
        ),
        h.canvas(ref=canvas, id="spectrogram"),
        h.p(
            "Time runs across, frequency up: the bright curve rising at the right is the chirp.",
            cls="note",
        ),
        h.div(
            h.label("low ", slider(low, min=0, max=2000, step=10), id="low"),
            h.label("high ", slider(high, min=0, max=2000, step=10), id="high"),
            h.button(lambda: "filtering" if filtered() else "no filter", on_click=toggle, id="filter"),
            h.span(lambda: f"{low()}–{high()} Hz", cls="note", id="band"),
            cls="row",
        ),
        h.div(
            h.div(h.span("rms"), h.strong(lambda: f"{analysis()['rms']:.3f}"), id="rms"),
            h.div(h.span("analysis"), h.strong(lambda: f"{analysis()['us'] / 1000:.1f} ms"), id="ms"),
            h.div(h.span("frames"), h.strong(lambda: str(analysis()["rows"])), id="rows"),
            h.div(h.span("bins"), h.strong(lambda: str(analysis()["bins"])), id="bins"),
            h.div(h.span("load"), h.strong(f"{load_us / 1000:.1f} ms"), id="load"),
            cls="numbers",
        ),
        h.h2("Power spectrum"),
        line_chart(lambda: analysis()["series"], height=260, id="psd"),
        h.p(
            "Welch's method, 1,024-point frames at half overlap. Move the sliders and turn the "
            "filter on: the spectrum, the spectrogram and the loudness all follow, because they "
            "are one memo over the same loaded signal.",
            cls="note",
        ),
    ),
    "#app",
)
