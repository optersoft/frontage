# Libraries an app calls, compiled to WebAssembly

Not part of the runtime, and deliberately outside its workspace (`exclude = ["components"]`):
these are ordinary Rust crates that become `.wasm` files an app imports through `data-fr-js`,
the way `examples/rustlib/` shows.

| | |
|---|---|
| `dsp/` | FFT, windows, Welch PSD and a spectrogram — what `frontage.dsp` runs on |

Each is built for the browser with plain cargo and copied into the component that ships it:

```sh
cd dsp && cargo build --release --target wasm32-unknown-unknown
cp target/wasm32-unknown-unknown/release/dsp.wasm ../../../frontage/dsp/_browser/dsp.wasm
```

`mk components.wasm` does that for every crate here. The built `.wasm` is committed, so
`pip install frontage` needs no Rust.

They keep `panic = "abort"` and `#![no_std]`: a panic in the page is a trap with no unwinding
machinery to carry, and `no_std` is what keeps them kilobytes rather than tens of them.
