// The glue around a Rust library compiled to WebAssembly: instantiate it, and give Python
// functions that take and return ordinary values.
//
// There is no wasm-bindgen here and nothing generated. A library of plain `extern "C"`
// functions over numbers needs about thirty lines, and reading them is what teaches the one
// thing that matters: **the two modules have separate memories**. A number crosses by value; a
// list has to be copied, element by element, and each element is a crossing of its own.
//
// So the API is in two halves. `load(values)` pays that cost once; everything after it reads
// what is already there and costs nothing but the arithmetic. A library shaped the other way —
// `mean(values)`, `stddev(values)`, each copying again — would be slower than plain Python,
// and the page next door measures exactly that.

const url = new URL("./statlib.wasm", import.meta.url);
const { instance } = await WebAssembly.instantiate(await (await fetch(url)).arrayBuffer(), {});
const lib = instance.exports;

// One view over the module's memory, made once. `values_ptr()` is a static buffer in the
// library, so the address never moves and there is no allocator on either side.
const heap = new Float64Array(lib.memory.buffer, lib.values_ptr(), lib.capacity());
const counts = new Uint32Array(lib.memory.buffer, lib.counts_ptr(), lib.bins());
let loaded = 0;

/** Copy `values` into the library's buffer. Returns how many arrived. */
export function load(values) {
  const length = Math.min(values.length, heap.length);
  for (let i = 0; i < length; i++) heap[i] = values[i];
  loaded = length;
  return length;
}

export function mean() {
  return lib.mean(loaded);
}

export function stddev() {
  return lib.stddev(loaded);
}

export function range() {
  return [lib.minimum(loaded), lib.maximum(loaded)];
}

/** `[count, …]` over `[low, high]`, `bins` of them, from the values already loaded. */
export function histogram(bins, low, high) {
  const written = lib.histogram(loaded, bins, low, high);
  return Array.from(counts.subarray(0, written));
}

/** What the library can hold at once, so a caller can say so rather than lose the tail. */
export const capacity = heap.length;
