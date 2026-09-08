//! Python source → frontage bytecode, over ruff's parser.
//!
//! `compile(vm, source, filename)` parses with `ruff_python_parser`, resolves scopes
//! (`symtable`), and generates a `Code` object for the module with every nested function,
//! class body and comprehension as a nested code object (`codegen`). Constants are allocated
//! in the VM's heap and pinned, so a code object is ready to run in that VM.

pub mod codegen;
pub mod symtable;

use frontage_vm::code::Code;
use frontage_vm::vm::Vm;
use std::rc::Rc;

pub fn compile(vm: &mut Vm, source: &str, filename: &str) -> Result<Rc<Code>, String> {
    let parsed = ruff_python_parser::parse_module(source).map_err(|e| {
        let line = line_of(source, e.location.start().to_usize());
        format!("{} ({}, line {})", e.error, filename, line)
    })?;
    let module = parsed.into_syntax();
    let table = symtable::SymTable::build(&module);
    codegen::generate(vm, &module, &table, source, filename)
}

pub fn line_of(source: &str, offset: usize) -> u32 {
    source[..offset.min(source.len())].bytes().filter(|&b| b == b'\n').count() as u32 + 1
}

/// Register this compiler with a VM, so imports of Python source work.
pub fn install(vm: &mut Vm) {
    vm.compiler = Some(compile);
}
