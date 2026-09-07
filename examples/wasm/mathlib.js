// The JavaScript glue around a WebAssembly library. `wasm-bindgen` (Rust) and `emcc` (C)
// generate a file this shape for you; this one is written out because the whole point of the
// example is that you can read every byte of it.
//
// `mathlib.wasm` is 41 bytes and exports one function, `add(i32, i32) -> i32`:
//
//   00 61 73 6d 01 00 00 00   magic, version
//   01 07 01 60 02 7f 7f 01 7f  type section: one type, (i32, i32) -> i32
//   03 02 01 00               function section: one function, of type 0
//   07 07 01 03 "add" 00 00   export section: "add" is function 0
//   0a 09 01 07 00 20 00 20 01 6a 0b   code: local.get 0, local.get 1, i32.add
//
// A real library is bigger and you would not hand-assemble it, but nothing else changes.

const bytes = await (await fetch(new URL("./mathlib.wasm", import.meta.url))).arrayBuffer();
const { instance } = await WebAssembly.instantiate(bytes, {});

export const add = instance.exports.add;
