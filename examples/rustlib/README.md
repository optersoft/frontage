# Your own Rust, in the page

A template. Copy this directory, rename the crate, and you are calling your own Rust from
Python in the browser. There is no bindings generator and no build step of frontage's own —
the whole contract is *a `.wasm` file, a `.js` file that instantiates it, and one attribute on
the boot tag*.

## The fifteen minutes

1. **Write the library** in `rust/src/lib.rs`. `#![no_std]`, `crate-type = ["cdylib"]`, and
   `#[no_mangle] pub extern "C"` on everything the page should see. Numbers in, numbers out.

   ```sh
   cd rust && cargo build --release --target wasm32-unknown-unknown
   cp target/wasm32-unknown-unknown/release/statlib.wasm ../statlib.wasm
   ```

   This one is **1,036 bytes**. `wasm-opt -Oz` (with `--enable-bulk-memory --enable-sign-ext
   --enable-mutable-globals --enable-nontrapping-float-to-int --enable-reference-types`, which
   is what the Rust target emits) takes it to 915, and is optional.

2. **Write the glue** — `statlib.js` here, about thirty lines. It fetches the `.wasm`,
   instantiates it, and exports functions that take and return ordinary values.

3. **Name it on the boot tag**:

   ```html
   <script type="module" src="./_frontage/boot.js" data-fr-boot data-fr-entry="app"
           data-fr-js="statlib=./statlib.js"></script>
   ```

   The loader imports and awaits it before your entry runs, so `import statlib` in Python is a
   plain import.

## The one thing to get right

**The two WebAssembly modules have separate memories.** A number crosses by value. A list does
not cross at all — it is copied, element by element, and each element is a crossing of its own.

This page measures it: loading 20,000 numbers costs about **1.5 ms**, and computing the mean
*and* the standard deviation over them costs **0.16 ms** — against 2.0 ms for the same
statistics in Python. So the library is 13× faster at the arithmetic and would still lose if it
took the list as an argument every time.

That is why the API here is in two halves: `load(values)` once, then `mean()`, `stddev()`,
`range()`, `histogram(bins, low, high)` as often as you like. Clicking "more bins" recounts
20,000 values in Rust and does not touch the list again.

Design your own boundary the same way: **coarse**. One call that does a lot, not many calls
that each do a little.

## What is in here

| | |
|---|---|
| `rust/` | the crate: `no_std`, no allocator, one static buffer JavaScript writes into |
| `statlib.wasm` | the build output, committed so the example runs with no Rust installed |
| `statlib.js` | the glue: instantiate, one `Float64Array` view, `load` + the questions |
| `app.py` | the page: the same statistics in both languages, timed |
