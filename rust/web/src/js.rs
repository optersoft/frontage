//! The JavaScript bridge, browser side: the hooks the VM calls, over imports the glue provides.

use frontage_vm::jshooks::*;
use frontage_vm::object::Obj;
use frontage_vm::value::Value;
use frontage_vm::vm::{PyResult, Vm};

#[link(wasm_import_module = "js")]
extern "C" {
    fn js_get(h: u32, name: *const u8, len: usize, out: *mut Slot) -> i32;
    fn js_set(h: u32, name: *const u8, len: usize, val: *const Slot) -> i32;
    fn js_call(h: u32, this: u32, argv: *const Slot, argc: usize, out: *mut Slot) -> i32;
    fn js_new(h: u32, argv: *const Slot, argc: usize, out: *mut Slot) -> i32;
    fn js_index(h: u32, key: *const Slot, out: *mut Slot) -> i32;
    fn js_set_index(h: u32, key: *const Slot, val: *const Slot) -> i32;
    fn js_len(h: u32) -> i32;
    fn js_truthy(h: u32) -> i32;
    fn js_str(h: u32, out: *mut Slot);
    fn js_kind(h: u32, out: *mut Slot);
    fn js_make_proxy(pin: u32) -> u32;
    fn js_release(h: u32);
    fn js_same(a: u32, b: u32) -> i32;
    fn dom_flush(ptr: *const u8, len: usize);
    fn dom_query(kind: u32, id: i32) -> f64;
    fn dom_node(id: i32) -> u32;
    fn dom_id_of(h: u32) -> u32;
}

/// A slot the glue filled; an error slot holds the thrown value.
fn raise(vm: &mut Vm, out: Slot) -> Value {
    let v = vm.from_slot(out).unwrap_or(Value::NONE);
    let jsffi = vm.import_module("jsffi").ok();
    if let Some(m) = jsffi {
        let key = vm.intern("JsException");
        if let Ok(cls) = vm.get_attr(m, key) {
            if let Ok(e) = vm.call(cls, &[v], &[]) {
                return e;
            }
        }
    }
    vm.runtime_error("JavaScript error")
}

fn h_get(vm: &mut Vm, h: u32, name: &str) -> PyResult<Slot> {
    let mut out = Slot::default();
    let r = unsafe { js_get(h, name.as_ptr(), name.len(), &mut out) };
    if r != 0 {
        return Err(raise(vm, out));
    }
    Ok(out)
}
fn h_set(vm: &mut Vm, h: u32, name: &str, val: Slot) -> PyResult<()> {
    let r = unsafe { js_set(h, name.as_ptr(), name.len(), &val) };
    if r != 0 {
        let mut out = Slot::default();
        unsafe { js_str(h, &mut out) };
        return Err(raise(vm, out));
    }
    Ok(())
}
fn h_call(vm: &mut Vm, h: u32, this: u32, args: &[Slot]) -> PyResult<Slot> {
    let mut out = Slot::default();
    let r = unsafe { js_call(h, this, args.as_ptr(), args.len(), &mut out) };
    if r != 0 {
        return Err(raise(vm, out));
    }
    Ok(out)
}
fn h_new(vm: &mut Vm, h: u32, args: &[Slot]) -> PyResult<Slot> {
    let mut out = Slot::default();
    let r = unsafe { js_new(h, args.as_ptr(), args.len(), &mut out) };
    if r != 0 {
        return Err(raise(vm, out));
    }
    Ok(out)
}
fn h_index(vm: &mut Vm, h: u32, key: Slot) -> PyResult<Slot> {
    let mut out = Slot::default();
    let r = unsafe { js_index(h, &key, &mut out) };
    if r != 0 {
        return Err(raise(vm, out));
    }
    Ok(out)
}
fn h_set_index(vm: &mut Vm, h: u32, key: Slot, val: Slot) -> PyResult<()> {
    let r = unsafe { js_set_index(h, &key, &val) };
    if r != 0 {
        return Err(vm.runtime_error("JavaScript item assignment failed"));
    }
    Ok(())
}
fn h_len(_vm: &mut Vm, h: u32) -> i32 {
    unsafe { js_len(h) }
}
fn h_truthy(_vm: &mut Vm, h: u32) -> bool {
    unsafe { js_truthy(h) != 0 }
}
fn h_str(vm: &mut Vm, h: u32) -> PyResult<String> {
    let mut out = Slot::default();
    unsafe { js_str(h, &mut out) };
    let v = vm.from_slot(out)?;
    Ok(vm.as_str(v).unwrap_or("").to_string())
}
fn h_kind(vm: &mut Vm, h: u32) -> String {
    let mut out = Slot::default();
    unsafe { js_kind(h, &mut out) };
    let v = vm.from_slot(out).unwrap_or(Value::NONE);
    vm.as_str(v).unwrap_or("object").to_string()
}
fn h_make_proxy(_vm: &mut Vm, pin: u32) -> u32 {
    unsafe { js_make_proxy(pin) }
}
fn h_release(handles: &[u32]) {
    for &h in handles {
        unsafe { js_release(h) }
    }
}
fn h_same(a: u32, b: u32) -> bool {
    unsafe { js_same(a, b) != 0 }
}
fn h_dom_flush(ops: &[u8]) {
    unsafe { dom_flush(ops.as_ptr(), ops.len()) }
}
fn h_dom_query(kind: u32, id: i32) -> i64 {
    unsafe { dom_query(kind, id) as i64 }
}
fn h_dom_node(id: i32) -> u32 {
    unsafe { dom_node(id) }
}
fn h_dom_id_of(h: u32) -> u32 {
    unsafe { dom_id_of(h) }
}

pub static HOOKS: JsHooks = JsHooks {
    get: h_get,
    set: h_set,
    call: h_call,
    new: h_new,
    index: h_index,
    set_index: h_set_index,
    len: h_len,
    truthy: h_truthy,
    str: h_str,
    kind: h_kind,
    make_proxy: h_make_proxy,
    release: h_release,
    same: h_same,
    dom_flush: h_dom_flush,
    dom_query: h_dom_query,
    dom_node: h_dom_node,
    dom_id_of: h_dom_id_of,
};

// -- the `js` module: `js.document` is `globalThis.document` ----------------------------------

fn js_module_getattr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let name = vm.expect_str(args[0], "name")?;
    let slot = h_get(vm, GLOBAL, &name)?;
    if slot.tag == TAG_UNDEFINED {
        return Err(vm.attribute_error(format!("no JavaScript global named '{name}'")));
    }
    vm.from_slot(slot)
}

pub fn mod_js(vm: &mut Vm) -> PyResult {
    let m = vm.new_module("js");
    let d = vm.module_dict(m);
    let f = vm.native("__getattr__", js_module_getattr);
    vm.dict_set_str(d, "__getattr__", f);
    let g = vm.js_object(GLOBAL);
    vm.dict_set_str(d, "globalThis", g);
    vm.dict_set_str(d, "window", g);
    Ok(m)
}

// -- `_jsffi`: what jsffi.py needs from the runtime -----------------------------------------------

fn ffi_pin(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let pin = vm.pin(args[0]);
    Ok(Value::int(pin as i32))
}
fn ffi_unpin(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let pin = vm.expect_int(args[0], "pin")?;
    vm.unpin(pin as u32);
    Ok(Value::NONE)
}
fn ffi_make_proxy(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let pin = vm.expect_int(args[0], "pin")?;
    let h = h_make_proxy(vm, pin as u32);
    Ok(vm.js_object(h))
}
pub fn mod_jsffi_native(vm: &mut Vm) -> PyResult {
    let m = vm.new_module("_jsffi");
    let d = vm.module_dict(m);
    for (name, f) in [("pin", ffi_pin as frontage_vm::object::NativeFn), ("unpin", ffi_unpin), ("make_proxy", ffi_make_proxy)] {
        let nf = vm.native(name, f);
        vm.dict_set_str(d, name, nf);
    }
    Ok(m)
}

/// JavaScript calling a pinned Python callable: `py_call(pin, argv, argc, out)`; 0 on success.
pub fn call_pinned(vm: &mut Vm, pin: u32, argv: &[Slot]) -> Result<Slot, Value> {
    let f = match vm.js_pins.get(pin as usize).copied() {
        Some(f) if !f.is_undef() => f,
        _ => return Err(vm.runtime_error("a JavaScript callback into a released proxy")),
    };
    let mut args = Vec::with_capacity(argv.len());
    for &s in argv {
        args.push(vm.from_slot(s)?);
    }
    let holder = vm.list(args.clone());
    vm.roots.push(holder);
    let r = vm.call(f, &args, &[]);
    vm.roots.pop();
    let v = r?;
    let mut trees = Vec::new();
    let slot = vm.to_slot(v, &mut trees)?;
    // A tree's bytes must outlive this call: the glue decodes before returning, so leak
    // nothing — copy into an alloc'd buffer the glue frees.
    if slot.tag == TAG_TREE {
        let buf = trees.pop().unwrap();
        let len = buf.len();
        let p = crate::alloc(len);
        unsafe { core::ptr::copy_nonoverlapping(buf.as_ptr(), p, len) };
        return Ok(Slot { tag: TAG_TREE, aux: len as u32, payload: p as usize as u64 });
    }
    if slot.tag == TAG_STRING {
        // point into a buffer that survives: copy the string
        let len = slot.aux as usize & 0x7fff_ffff;
        let p = crate::alloc(len);
        unsafe { core::ptr::copy_nonoverlapping(slot.payload as usize as *const u8, p, len) };
        return Ok(Slot { tag: TAG_STRING, aux: slot.aux, payload: p as usize as u64 });
    }
    let _ = Obj::Free;
    Ok(slot)
}
