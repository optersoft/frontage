//! `fpy FILE.py [args…]`: run a Python file on frontage's runtime, natively.
//!
//! Modules resolve from the file's directory and `FPY_PATH` (colon-separated). `--stress`
//! collects at every safe point, which is how a missing GC root shows up at once.

use frontage_vm::host::StdHost;
use frontage_vm::vm::Vm;
use std::path::PathBuf;

fn main() {
    let mut args: Vec<String> = std::env::args().skip(1).collect();
    let stress = args.iter().any(|a| a == "--stress");
    args.retain(|a| a != "--stress");
    let docstrings = args.iter().any(|a| a == "--docstrings");
    args.retain(|a| a != "--docstrings");
    let mut compile_to: Option<String> = None;
    if let Some(i) = args.iter().position(|a| a == "--compile") {
        compile_to = args.get(i + 1).cloned();
        args.drain(i..i + 2);
    }
    let file = match args.first() {
        Some(f) => PathBuf::from(f),
        None => {
            eprintln!("usage: fpy [--stress] [--docstrings] [--compile OUT.fbc] FILE.py");
            std::process::exit(2);
        }
    };
    let source = match std::fs::read_to_string(&file) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("fpy: {}: {e}", file.display());
            std::process::exit(2);
        }
    };
    let mut search = vec![file.parent().map(|p| p.to_path_buf()).unwrap_or_else(|| PathBuf::from("."))];
    if let Ok(extra) = std::env::var("FPY_PATH") {
        search.extend(extra.split(':').filter(|s| !s.is_empty()).map(PathBuf::from));
    }
    let mut vm = Vm::new(Box::new(StdHost::new(search)));
    vm.heap.stress = stress;
    vm.argv = args.clone();
    // A `.fbc` is what a page downloads, and every framework module here is heavily
    // documented, so `--compile` drops docstrings unless asked otherwise. Running keeps
    // them: `__doc__` working is Python's norm, and the differential cases assert it.
    vm.keep_docstrings = docstrings || compile_to.is_none();
    frontage_compile::install(&mut vm);
    let code = match frontage_compile::compile(&mut vm, &source, &file.to_string_lossy()) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("SyntaxError: {e}");
            std::process::exit(1);
        }
    };
    if let Some(out) = compile_to {
        match frontage_vm::fbc::dump(&vm, &code) {
            Ok(bytes) => {
                std::fs::write(&out, bytes).expect("write .fbc");
                return;
            }
            Err(e) => {
                eprintln!("fpy: cannot serialise: {e}");
                std::process::exit(1);
            }
        }
    }
    match vm.run_main(code, &file.to_string_lossy()) {
        Ok(_) => {}
        Err(exc) => {
            let se = vm.t.system_exit;
            if vm.exc_matches(exc, se) {
                let code = vm.exc_value(exc);
                let n = vm.as_i64(code).unwrap_or(if code.is_none() { 0 } else { 1 });
                std::process::exit(n as i32);
            }
            let text = vm.format_exception(exc);
            eprint!("{text}");
            std::process::exit(1);
        }
    }
}
