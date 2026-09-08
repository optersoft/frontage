//! Precompile the Python-source standard modules (`asyncio`, `io`, `collections`, …) and
//! the `jsffi` module into bytecode embedded in the browser build, which carries no compiler.

use std::env;
use std::fs;
use std::path::Path;

fn main() {
    let out = Path::new(&env::var("OUT_DIR").unwrap()).join("stdlib.bin");
    let mut vm = frontage_vm::vm::Vm::new(Box::new(frontage_vm::host::StdHost::new(vec![])));
    let mut blob: Vec<u8> = Vec::new();
    let mut entries: Vec<(&str, &str)> = frontage_vm::modules::PY_MODULES.to_vec();
    entries.push(("jsffi", include_str!("src/jsffi.py")));
    for (name, source) in entries {
        let code = frontage_compile::compile(&mut vm, source, &format!("<frontage:{name}>")).unwrap_or_else(|e| panic!("stdlib module {name}: {e}"));
        let bytes = frontage_vm::fbc::dump(&vm, &code).expect("serialise");
        blob.extend_from_slice(&(name.len() as u32).to_le_bytes());
        blob.extend_from_slice(name.as_bytes());
        blob.extend_from_slice(&(bytes.len() as u32).to_le_bytes());
        blob.extend_from_slice(&bytes);
    }
    fs::write(&out, blob).unwrap();
    println!("cargo:rerun-if-changed=src/jsffi.py");
    println!("cargo:rerun-if-changed=../vm/src/lib");
    println!("cargo:rerun-if-changed=../vm/src/modules.rs");
}
