//! The runtime for the browser: a WebAssembly module with a C ABI, a host of JavaScript
//! imports (`glue.js` provides them), and bytecode loaded from bytes — no parser in the page.
//!
//! Exports: `alloc(n)` a buffer the glue writes into; `init()` the VM; `add_module(name,
//! bytes)` a compiled module `import` will find; `run(bytes)` the entry as `__main__`;
//! `loop_turn()` one turn of the asyncio loop, returning the milliseconds until the next
//! timer or -1. Errors print to the host's stderr and return 1.

mod js;

use frontage_vm::host::{Host, ModuleSource};
use frontage_vm::jshooks::Slot;
use frontage_vm::vm::Vm;
use std::collections::HashMap;

/// The Python-source standard modules, precompiled by `build.rs`.
static STDLIB: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/stdlib.bin"));

#[link(wasm_import_module = "host")]
extern "C" {
    fn write(fd: u32, ptr: *const u8, len: usize);
    fn now_ms() -> f64;
    fn random() -> f64;
}

struct JsHost {
    modules: HashMap<String, Vec<u8>>,
}

impl Host for JsHost {
    fn write_stdout(&mut self, s: &str) {
        unsafe { write(1, s.as_ptr(), s.len()) }
    }
    fn write_stderr(&mut self, s: &str) {
        unsafe { write(2, s.as_ptr(), s.len()) }
    }
    fn now_ms(&self) -> f64 {
        unsafe { now_ms() }
    }
    fn time_s(&self) -> f64 {
        unsafe { now_ms() / 1000.0 }
    }
    fn find_module(&mut self, _name: &str) -> Option<ModuleSource> {
        None
    }
    fn find_module_code(&mut self, name: &str) -> Option<Vec<u8>> {
        self.modules.get(name).cloned()
    }
    fn add_module(&mut self, name: &str, bytes: Vec<u8>) {
        self.modules.insert(name.to_string(), bytes);
    }
    fn random_u64(&mut self) -> u64 {
        unsafe { (random() * (u64::MAX as f64)) as u64 }
    }
    fn sleep_ms(&mut self, _ms: f64) {
        // The browser never blocks: the glue drives the loop from timers.
    }
}

static mut VM: Option<Vm> = None;
static mut PENDING: Vec<(String, Vec<u8>)> = Vec::new();

fn vm() -> &'static mut Vm {
    unsafe { (*core::ptr::addr_of_mut!(VM)).as_mut().expect("init() first") }
}

/// A buffer of `n` bytes the glue fills; ownership passes to the next call that takes it.
#[no_mangle]
pub extern "C" fn alloc(n: usize) -> *mut u8 {
    let mut v: Vec<u8> = Vec::with_capacity(n.max(1));
    let p = v.as_mut_ptr();
    core::mem::forget(v);
    p
}

unsafe fn take(ptr: *mut u8, len: usize) -> Vec<u8> {
    Vec::from_raw_parts(ptr, len, len.max(1))
}

#[no_mangle]
pub extern "C" fn init() -> u32 {
    let mut host = JsHost { modules: HashMap::new() };
    let mut i = 0;
    while i + 8 <= STDLIB.len() {
        let nl = u32::from_le_bytes([STDLIB[i], STDLIB[i + 1], STDLIB[i + 2], STDLIB[i + 3]]) as usize;
        let name = String::from_utf8_lossy(&STDLIB[i + 4..i + 4 + nl]).into_owned();
        i += 4 + nl;
        let bl = u32::from_le_bytes([STDLIB[i], STDLIB[i + 1], STDLIB[i + 2], STDLIB[i + 3]]) as usize;
        host.modules.insert(name, STDLIB[i + 4..i + 4 + bl].to_vec());
        i += 4 + bl;
    }
    unsafe {
        for (name, bytes) in (*core::ptr::addr_of_mut!(PENDING)).drain(..) {
            host.modules.insert(name, bytes);
        }
    }
    let mut vm = Vm::new(Box::new(host));
    vm.js_hooks = Some(&js::HOOKS);
    vm.browser = true;
    vm.builtin_modules.insert("js", js::mod_js);
    vm.builtin_modules.insert("_jsffi", js::mod_jsffi_native);
    let n = vm.heap.len() as u32;
    unsafe { VM = Some(vm) };
    n
}

/// Register compiled module bytes under a dotted name (before or after `init`).
#[no_mangle]
pub extern "C" fn add_module(name_ptr: *mut u8, name_len: usize, ptr: *mut u8, len: usize) {
    let name = String::from_utf8_lossy(&unsafe { take(name_ptr, name_len) }).into_owned();
    let bytes = unsafe { take(ptr, len) };
    unsafe {
        if (*core::ptr::addr_of!(VM)).is_some() {
            vm().host.add_module(&name, bytes);
        } else {
            (*core::ptr::addr_of_mut!(PENDING)).push((name, bytes));
        }
    }
}

/// Run bytecode as `__main__`. 0 on success, 1 after printing the traceback.
#[no_mangle]
pub extern "C" fn run(ptr: *mut u8, len: usize) -> u32 {
    let bytes = unsafe { take(ptr, len) };
    let vm = vm();
    let code = match frontage_vm::fbc::load(vm, &bytes) {
        Ok(c) => c,
        Err(e) => {
            vm.host.write_stderr(&format!("frontage: bad bytecode: {e}\n"));
            return 1;
        }
    };
    let filename = code.filename.to_string();
    let r = vm.run_main(code, &filename);
    let _ = vm.dom_flush();
    match r {
        Ok(_) => 0,
        Err(exc) => {
            // `SystemExit` is a request, not an error: 2 + its code, nothing printed.
            let se = vm.t.system_exit;
            if vm.exc_matches(exc, se) {
                let code = vm.exc_value(exc);
                let n = vm.as_i64(code).unwrap_or(if code.is_none() { 0 } else { 1 });
                return 2 + n.clamp(0, 250) as u32;
            }
            let text = vm.format_exception(exc);
            vm.host.write_stderr(&text);
            1
        }
    }
}

/// One turn of the asyncio loop: milliseconds until the next timer, -1 when idle (or when
/// nothing has imported asyncio yet), -2 on an error, which is printed.
#[no_mangle]
pub extern "C" fn loop_turn() -> f64 {
    let vm = vm();
    let key = vm.intern("asyncio");
    let modules = vm.modules;
    let m = match vm.dict_get(modules, key) {
        Some(m) => m,
        None => return -1.0,
    };
    let r = (|| {
        let get = vm.intern("get_event_loop");
        let f = vm.get_attr(m, get)?;
        let l = vm.call(f, &[], &[])?;
        let ro = vm.intern("run_once");
        let f = vm.get_attr(l, ro)?;
        let v = vm.call(f, &[], &[])?;
        vm.dom_flush()?;
        Ok(v)
    })();
    match r {
        Ok(v) => {
            if v.is_none() {
                -1.0
            } else {
                vm.as_f64(v).unwrap_or(0.0) * 1000.0
            }
        }
        Err(exc) => {
            let text = vm.format_exception(exc);
            vm.host.write_stderr(&text);
            -2.0
        }
    }
}

/// JavaScript calling a proxied Python callable. 0 on success; on an error the traceback is
/// printed and `out` is left undefined.
#[no_mangle]
pub extern "C" fn py_call(pin: u32, argv: *const Slot, argc: usize, out: *mut Slot) -> u32 {
    let vm = vm();
    let args: Vec<Slot> = unsafe { core::slice::from_raw_parts(argv, argc) }.to_vec();
    let r = js::call_pinned(vm, pin, &args).and_then(|slot| {
        vm.dom_flush()?;
        Ok(slot)
    });
    match r {
        Ok(slot) => {
            unsafe { *out = slot };
            0
        }
        Err(exc) => {
            let text = vm.format_exception(exc);
            vm.host.write_stderr(&text);
            unsafe { *out = Slot::default() };
            1
        }
    }
}

/// Collect now; returns the number of objects freed.
#[no_mangle]
pub extern "C" fn collect() -> u32 {
    vm().collect() as u32
}

#[no_mangle]
pub extern "C" fn heap_len() -> u32 {
    vm().heap.len() as u32
}
