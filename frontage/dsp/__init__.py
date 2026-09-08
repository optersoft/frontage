"""Signal processing in the page: an FFT, a power spectral density, a spectrogram, a bandpass.

Twelve kilobytes of Rust compiled to WebAssembly, and a Python API over it. What it is for is
the kind of app that has no answer in a browser today — a gravitational-wave viewer, an audio
analyser, a vibration dashboard — where the data is a long array of samples and the question is
about its frequencies.

    from frontage import dsp

    dsp.load(samples)                       # the signal crosses once
    frequency, power = dsp.psd(1024, 512, sample_rate=4096)
    dsp.bandpass(4096, low=20, high=300)    # in place, over what is loaded
    dsp.draw(canvas, 256, 64)               # a spectrogram, straight onto a canvas

The shape is deliberate and is the whole performance story: **the samples cross once**, into a
buffer inside the library, and every call after that is a question answered in its own memory.
`examples/rustlib` measures why — a list is copied element by element, so a library that took
the samples in every call would be slower than plain Python.
"""

import dsp as _js  # ty: ignore[unresolved-import]

from frontage.runtime import to_js

__all__ = [
    "bandpass",
    "capacity",
    "draw",
    "load",
    "loaded",
    "psd",
    "rms",
    "samples",
    "spectrogram",
]


def load(values):
    """Put `values` in the library. Returns how many arrived: a longer signal is truncated to
    `capacity()`, which is 131,072 samples."""
    return _js.load(to_js(list(values)))


def loaded():
    """How many samples the library is holding."""
    return _js.loaded()


def capacity():
    """The most it can hold at once."""
    return _js.capacity


def psd(size=1024, hop=None, sample_rate=1.0):
    """Welch's power spectral density: `(frequency, power)`, two lists of `size / 2 + 1`.

    `size` is the frame, a power of two; `hop` how far apart the frames are (half the frame by
    default, the usual 50% overlap); `sample_rate` scales the answer to power per hertz.
    """
    frequency, power = _js.psd(size, hop if hop is not None else size // 2, sample_rate)
    return list(frequency), list(power)


def spectrogram(size=256, hop=None, floor_db=-90.0):
    """`(rows, bins, values)`: decibels against the loudest bin, row-major, a row per frame.

    Prefer `draw` when the destination is a canvas — `rows * bins` numbers are a lot to carry
    into Python for something a browser is about to rasterise anyway.
    """
    result = _js.spectrogram(size, hop if hop is not None else size // 4, floor_db)
    return result.rows, result.bins, list(result.values)


def draw(canvas, size=256, hop=None, floor_db=-90.0):
    """Draw the spectrogram of the loaded signal onto `canvas`; returns `(rows, bins)`.

    Time runs across, frequency up. The values never reach Python, which is the point: a
    spectrogram is 128 frames of 129 bins and every one of them would be a crossing.
    """
    result = _js.draw(canvas, size, hop if hop is not None else size // 4, floor_db)
    return result.rows, result.bins


def bandpass(sample_rate, low, high):
    """Keep `[low, high]` hertz and drop the rest, in place, over the loaded signal.

    A brick wall in the frequency domain — the honest thing for a viewer, where the point is to
    see a band, rather than a filter design exercise. Returns the number of samples kept (the
    largest power of two that fits, because the transform needs one).
    """
    return _js.bandpass(sample_rate, low, high)


def rms():
    """The root mean square of the loaded signal: the one number that says how loud."""
    return _js.rms()


def samples(count=None):
    """Read the loaded signal back — after a `bandpass`, typically."""
    return list(_js.samples(count))
