# frontage.dsp

Signal processing in the page: an FFT, Welch's power spectral density, a spectrogram, a
brick-wall bandpass and an RMS — twelve kilobytes of Rust compiled to WebAssembly, with a
Python API over it.

```py
from frontage import dsp

dsp.load(samples)                                  # the signal crosses once
frequency, power = dsp.psd(1024, 512, sample_rate=4096)
dsp.bandpass(4096, low=20, high=300)               # in place; returns what it filtered
rows, bins = dsp.draw(canvas, 256, 64)             # a spectrogram, straight onto a canvas
```

## The shape, and why

The two WebAssembly modules — the Python runtime and this library — have separate memories, so
a list does not cross: it is copied, one element at a time. Everything here therefore works on
**one buffer the library owns**. `load` pays the copy once; `psd`, `spectrogram`, `rms` and
`bandpass` are questions answered in the library's own memory.

`draw` goes further and never gives the numbers to Python at all: a spectrogram is a few
hundred frames of a hundred-odd bins, and every one of them would be a crossing. It rasterises
straight onto a canvas.

`examples/rustlib` measures what this is worth; `examples/spectrum` is this module in use.

## What to know before trusting a number

- **`bandpass` filters the largest power of two that fits**, capped at 16,384 samples, and
  returns how many. That count becomes the signal's length: everything after it measures what
  was filtered. Without that rule a filter over a longer signal looks like it did nothing,
  because the questions afterwards were about samples it never reached.
- **The bandpass is a brick wall in the frequency domain**, not a filter design. It is the
  honest thing for a viewer, where the point is to see a band; it is not what you would use to
  process audio for listening.
- **`psd` is Welch's method** over Hann-windowed frames, normalised by the window's power and
  folded so a real signal's power lands once. Pass `sample_rate=1.0` for power per bin.
- **A spectrogram is decibels against its own loudest bin**, floored where you say. That makes
  it a picture rather than a measurement, which is what a spectrogram is for.

The mathematics is in `rust/components/dsp/`, with tests against a naive DFT and against
`std`'s own `cos`, `ln` and `sqrt` — the crate is `no_std` in the browser and has to compute
those itself.
