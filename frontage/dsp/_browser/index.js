// The JavaScript half of `frontage.dsp`: it instantiates the Rust library and hands Python
// functions over ordinary values.
//
// The shape is the one every wasm boundary wants (`examples/rustlib` measures why): the signal
// crosses **once**, into a static buffer inside the library, and everything after that is a
// question answered from the library's own memory. A spectrogram of 128 frames never sends
// 128 frames across; it fills one buffer and says how to read it.

const url = new URL("./dsp.wasm", import.meta.url);
const { instance } = await WebAssembly.instantiate(await (await fetch(url)).arrayBuffer(), {});
const lib = instance.exports;

const signal = new Float64Array(lib.memory.buffer, lib.signal_ptr(), lib.capacity());
const out = new Float64Array(lib.memory.buffer, lib.out_ptr(), lib.out_capacity());
let length = 0;

/** Copy samples into the library. Returns how many arrived (the rest do not fit). */
export function load(samples) {
  const count = Math.min(samples.length, signal.length);
  if (samples instanceof Float64Array) signal.set(samples.subarray(0, count));
  else for (let i = 0; i < count; i++) signal[i] = samples[i];
  length = count;
  return count;
}

export function loaded() {
  return length;
}

export const capacity = signal.length;

/** Welch's power spectral density: `[frequency[], power[]]`, ready for a chart. */
export function psd(size, hop, sampleRate) {
  const bins = lib.psd(length, size, hop, sampleRate);
  const power = Array.from(out.subarray(0, bins));
  const step = sampleRate / size;
  return [Array.from({ length: bins }, (_, i) => i * step), power];
}

/** `{rows, bins, values}` — decibels against the loudest bin, row-major, one row per frame. */
export function spectrogram(size, hop, floorDb) {
  const rows = lib.spectrogram(length, size, hop, floorDb);
  const bins = lib.bins_for(size);
  return { rows, bins, values: Array.from(out.subarray(0, rows * bins)) };
}

/** Draw that spectrogram straight onto a canvas: time across, frequency up, one pixel a bin.
 * The values never reach Python — the point of doing it here is that they do not have to. */
export function draw(node, size, hop, floorDb) {
  const rows = lib.spectrogram(length, size, hop, floorDb);
  const bins = lib.bins_for(size);
  if (!rows) return { rows: 0, bins };
  node.width = rows;
  node.height = bins;
  const context = node.getContext("2d");
  const image = context.createImageData(rows, bins);
  for (let row = 0; row < rows; row++) {
    for (let bin = 0; bin < bins; bin++) {
      const db = out[row * bins + bin];
      const level = Math.max(0, Math.min(1, 1 - db / floorDb));
      // A dark-to-bright ramp: the usual spectrogram look, and no palette to ship.
      const pixel = ((bins - 1 - bin) * rows + row) * 4;
      image.data[pixel] = 255 * Math.min(1, level * 1.6);
      image.data[pixel + 1] = 255 * Math.max(0, level * 1.6 - 0.6);
      image.data[pixel + 2] = 255 * Math.max(0, level * 2.2 - 1.2) + 40 * level;
      image.data[pixel + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);
  return { rows, bins };
}

/** A brick-wall bandpass over what is loaded, in place. Returns the samples kept — and makes
 * them the signal, because everything after this must measure what was filtered rather than
 * the tail the transform could not reach. */
export function bandpass(sampleRate, low, high) {
  length = lib.bandpass(length, sampleRate, low, high);
  return length;
}

/** The loaded signal's root mean square. */
export function rms() {
  return lib.rms(length);
}

/** Read back what is in the library — after a bandpass, typically. */
export function samples(count) {
  return Array.from(signal.subarray(0, Math.min(count ?? length, length)));
}
