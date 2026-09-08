//! The DOM op stream (`FASTER.md` §4, `RUNTIME.md` §3.8): nodes are integers in the glue's
//! array, operations are bytes in a buffer the glue executes in one crossing, and only a
//! question about the document (a parent, a sibling, `isConnected`) crosses on its own,
//! after flushing what is pending.
//!
//! `_dom` is the Python surface; `frontage/dom.py`'s streaming renderer is written over it.
//! Ids: the runtime hands out positive ones; a negative id `-m` means "the parent of node m",
//! so a hole's parent never has to be asked for. The glue registers nodes it meets on its
//! own (a parent it was asked for) from 2^30 up.

use crate::value::Value;
use crate::vm::{PyResult, Vm};

pub const OP_DEFINE_TEMPLATE: u8 = 0;
pub const OP_CLONE: u8 = 1;
pub const OP_FIND_HOLES: u8 = 2;
pub const OP_CREATE_ELEMENT: u8 = 3;
pub const OP_CREATE_TEXT: u8 = 4;
pub const OP_CREATE_COMMENT: u8 = 5;
pub const OP_SET_TEXT: u8 = 6;
pub const OP_SET_ATTR: u8 = 7;
pub const OP_REMOVE_ATTR: u8 = 8;
pub const OP_SET_PROP: u8 = 9;
pub const OP_SET_PROP_BOOL: u8 = 10;
pub const OP_TOGGLE_CLASS: u8 = 11;
pub const OP_SET_STYLE: u8 = 12;
pub const OP_REMOVE_STYLE: u8 = 13;
pub const OP_APPEND: u8 = 14;
pub const OP_INSERT: u8 = 15;
pub const OP_REMOVE: u8 = 16;
pub const OP_REPLACE: u8 = 17;
pub const OP_LISTEN: u8 = 18;
pub const OP_UNLISTEN: u8 = 19;
pub const OP_RELEASE: u8 = 20;
pub const OP_SET_DISPATCHER: u8 = 21;
pub const OP_TEARDOWN: u8 = 22;

const FLUSH_AT: usize = 64 * 1024;

#[derive(Default)]
pub struct DomStream {
    pub ops: Vec<u8>,
    pub next_id: u32,
    pub next_template: u32,
}

impl DomStream {
    pub fn new() -> DomStream {
        DomStream { ops: Vec::with_capacity(FLUSH_AT), next_id: 1, next_template: 0 }
    }
    fn alloc(&mut self, n: u32) -> u32 {
        let id = self.next_id;
        self.next_id += n;
        id
    }
    fn u8(&mut self, v: u8) {
        self.ops.push(v);
    }
    fn u32(&mut self, v: u32) {
        self.ops.extend_from_slice(&v.to_le_bytes());
    }
    fn i32(&mut self, v: i32) {
        self.ops.extend_from_slice(&v.to_le_bytes());
    }
    fn str(&mut self, s: &str) {
        self.u32(s.len() as u32);
        self.ops.extend_from_slice(s.as_bytes());
    }
}

impl Vm {
    /// Hand the pending operations to the glue, if any.
    pub fn dom_flush(&mut self) -> PyResult<()> {
        if self.dom.ops.is_empty() {
            return Ok(());
        }
        let hooks = self.js()?;
        let ops = core::mem::replace(&mut self.dom.ops, Vec::with_capacity(FLUSH_AT));
        (hooks.dom_flush)(&ops);
        Ok(())
    }
    pub fn dom_pending(&self) -> bool {
        !self.dom.ops.is_empty()
    }
    fn dom_maybe_flush(&mut self) -> PyResult<()> {
        if self.dom.ops.len() >= FLUSH_AT {
            self.dom_flush()?;
        }
        Ok(())
    }
}

fn id_arg(vm: &mut Vm, args: &[Value], i: usize, what: &str) -> PyResult<i32> {
    match args.get(i).and_then(|&v| vm.as_i64(v)) {
        Some(n) => Ok(n as i32),
        None => Err(vm.type_error(format!("_dom: {what} must be a node id"))),
    }
}
fn str_arg(vm: &mut Vm, args: &[Value], i: usize, what: &str) -> PyResult<String> {
    match args.get(i) {
        Some(&v) => vm.str_of(v),
        None => Err(vm.type_error(format!("_dom: missing {what}"))),
    }
}
fn bool_arg(vm: &mut Vm, args: &[Value], i: usize) -> PyResult<bool> {
    match args.get(i) {
        Some(&v) => vm.truthy(v),
        None => Ok(false),
    }
}

fn f_define_template(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let html = str_arg(vm, args, 0, "html")?;
    let tid = vm.dom.next_template;
    vm.dom.next_template += 1;
    vm.dom.u8(OP_DEFINE_TEMPLATE);
    vm.dom.u32(tid);
    vm.dom.str(&html);
    vm.dom_maybe_flush()?;
    Ok(Value::int(tid as i32))
}
fn f_clone(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let tid = id_arg(vm, args, 0, "template")?;
    let id = vm.dom.alloc(1);
    vm.dom.u8(OP_CLONE);
    vm.dom.u32(id);
    vm.dom.u32(tid as u32);
    vm.dom_maybe_flush()?;
    Ok(Value::int(id as i32))
}
/// `find_holes(root, n_elements, n_markers, keep_attr) -> first id`: the elements carrying
/// `data-fr-h` get `first + n` by their number, the `<!--h-->` markers in document order get
/// `first + n_elements + k`.
fn f_find_holes(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let root = id_arg(vm, args, 0, "root")?;
    let n_el = id_arg(vm, args, 1, "n_elements")? as u32;
    let n_mk = id_arg(vm, args, 2, "n_markers")? as u32;
    let keep = bool_arg(vm, args, 3)?;
    let first = vm.dom.alloc(n_el + n_mk);
    vm.dom.u8(OP_FIND_HOLES);
    vm.dom.i32(root);
    vm.dom.u32(first);
    vm.dom.u32(n_el);
    vm.dom.u32(n_mk);
    vm.dom.u8(keep as u8);
    vm.dom_maybe_flush()?;
    Ok(Value::int(first as i32))
}
fn create(vm: &mut Vm, args: &[Value], op: u8, what: &str) -> PyResult {
    let s = str_arg(vm, args, 0, what)?;
    let id = vm.dom.alloc(1);
    vm.dom.u8(op);
    vm.dom.u32(id);
    vm.dom.str(&s);
    vm.dom_maybe_flush()?;
    Ok(Value::int(id as i32))
}
fn f_create_element(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    create(vm, args, OP_CREATE_ELEMENT, "tag")
}
fn f_create_text(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    create(vm, args, OP_CREATE_TEXT, "text")
}
fn f_create_comment(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    create(vm, args, OP_CREATE_COMMENT, "text")
}
fn id_str(vm: &mut Vm, args: &[Value], op: u8) -> PyResult {
    let id = id_arg(vm, args, 0, "node")?;
    let s = str_arg(vm, args, 1, "text")?;
    vm.dom.u8(op);
    vm.dom.i32(id);
    vm.dom.str(&s);
    vm.dom_maybe_flush()?;
    Ok(Value::NONE)
}
fn id_str_str(vm: &mut Vm, args: &[Value], op: u8) -> PyResult {
    let id = id_arg(vm, args, 0, "node")?;
    let a = str_arg(vm, args, 1, "name")?;
    let b = str_arg(vm, args, 2, "value")?;
    vm.dom.u8(op);
    vm.dom.i32(id);
    vm.dom.str(&a);
    vm.dom.str(&b);
    vm.dom_maybe_flush()?;
    Ok(Value::NONE)
}
fn id_str_bool(vm: &mut Vm, args: &[Value], op: u8) -> PyResult {
    let id = id_arg(vm, args, 0, "node")?;
    let a = str_arg(vm, args, 1, "name")?;
    let on = bool_arg(vm, args, 2)?;
    vm.dom.u8(op);
    vm.dom.i32(id);
    vm.dom.str(&a);
    vm.dom.u8(on as u8);
    vm.dom_maybe_flush()?;
    Ok(Value::NONE)
}
fn f_set_text(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    id_str(vm, args, OP_SET_TEXT)
}
fn f_set_attr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    id_str_str(vm, args, OP_SET_ATTR)
}
fn f_remove_attr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    id_str(vm, args, OP_REMOVE_ATTR)
}
fn f_set_prop(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    id_str_str(vm, args, OP_SET_PROP)
}
fn f_set_prop_bool(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    id_str_bool(vm, args, OP_SET_PROP_BOOL)
}
fn f_toggle_class(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    id_str_bool(vm, args, OP_TOGGLE_CLASS)
}
fn f_set_style(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    id_str_str(vm, args, OP_SET_STYLE)
}
fn f_remove_style(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    id_str(vm, args, OP_REMOVE_STYLE)
}
fn f_append(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let p = id_arg(vm, args, 0, "parent")?;
    let n = id_arg(vm, args, 1, "node")?;
    vm.dom.u8(OP_APPEND);
    vm.dom.i32(p);
    vm.dom.i32(n);
    vm.dom_maybe_flush()?;
    Ok(Value::NONE)
}
fn f_insert(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let p = id_arg(vm, args, 0, "parent")?;
    let n = id_arg(vm, args, 1, "node")?;
    let a = id_arg(vm, args, 2, "anchor")?;
    vm.dom.u8(OP_INSERT);
    vm.dom.i32(p);
    vm.dom.i32(n);
    vm.dom.i32(a);
    vm.dom_maybe_flush()?;
    Ok(Value::NONE)
}
fn f_remove(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let p = id_arg(vm, args, 0, "parent")?;
    let n = id_arg(vm, args, 1, "node")?;
    vm.dom.u8(OP_REMOVE);
    vm.dom.i32(p);
    vm.dom.i32(n);
    vm.dom_maybe_flush()?;
    Ok(Value::NONE)
}
fn f_replace(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let p = id_arg(vm, args, 0, "parent")?;
    let new = id_arg(vm, args, 1, "new")?;
    let old = id_arg(vm, args, 2, "old")?;
    vm.dom.u8(OP_REPLACE);
    vm.dom.i32(p);
    vm.dom.i32(new);
    vm.dom.i32(old);
    vm.dom_maybe_flush()?;
    Ok(Value::NONE)
}
fn f_listen(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    id_str(vm, args, OP_LISTEN)
}
fn f_unlisten(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    id_str(vm, args, OP_UNLISTEN)
}
fn f_release(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let id = id_arg(vm, args, 0, "node")?;
    vm.dom.u8(OP_RELEASE);
    vm.dom.i32(id);
    Ok(Value::NONE)
}
/// `set_dispatcher(js_function)`: what a delegated event calls, `(id, event, ev)`.
fn f_set_dispatcher(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let f = args.first().copied().unwrap_or(Value::NONE);
    let h = vm.js_handle(f).ok_or_else(|| vm.type_error("_dom.set_dispatcher needs a JavaScript function (create_proxy)"))?;
    vm.dom.u8(OP_SET_DISPATCHER);
    vm.dom.u32(h);
    // The handle must outlive the flush: keep the proxy pinned on the VM side.
    vm.roots.push(f);
    vm.dom_flush()?;
    Ok(Value::NONE)
}
fn f_teardown(vm: &mut Vm, _a: &[Value], _k: &[(Value, Value)]) -> PyResult {
    vm.dom.u8(OP_TEARDOWN);
    vm.dom_flush()?;
    Ok(Value::NONE)
}
fn f_flush(vm: &mut Vm, _a: &[Value], _k: &[(Value, Value)]) -> PyResult {
    vm.dom_flush()?;
    Ok(Value::NONE)
}
/// `query(kind, id)`: 0 parent, 1 first_child, 2 next_sibling, 3 previous_sibling,
/// 4 last_child (an id, or 0 for none); 5 node_type; 6 is_connected.
fn f_query(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let kind = id_arg(vm, args, 0, "kind")? as u32;
    let id = id_arg(vm, args, 1, "node")?;
    vm.dom_flush()?;
    let hooks = vm.js()?;
    let r = (hooks.dom_query)(kind, id);
    Ok(Value::int(r as i32))
}
/// `node(id)`: the JavaScript node itself, for a `ref`, a direct listener, an event to fire.
fn f_node(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let id = id_arg(vm, args, 0, "node")?;
    vm.dom_flush()?;
    let hooks = vm.js()?;
    let h = (hooks.dom_node)(id);
    if h == crate::jshooks::UNDEFINED_HANDLE {
        return Ok(Value::NONE);
    }
    Ok(vm.js_object(h))
}
/// `id_of(js_node)`: the id of a node that came from JavaScript (a mount target, an adopted
/// node while hydrating), registered on first sight.
fn f_id_of(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = args.first().copied().unwrap_or(Value::NONE);
    if let Some(n) = vm.as_i64(v) {
        return Ok(Value::int(n as i32));
    }
    let h = vm.js_handle(v).ok_or_else(|| vm.type_error("_dom.id_of needs a JavaScript node"))?;
    vm.dom_flush()?;
    let hooks = vm.js()?;
    Ok(Value::int((hooks.dom_id_of)(h) as i32))
}

pub fn install_module(vm: &mut Vm) -> PyResult {
    let m = vm.new_module("_dom");
    let d = vm.module_dict(m);
    let fns: &[(&'static str, crate::object::NativeFn)] = &[
        ("define_template", f_define_template),
        ("clone", f_clone),
        ("find_holes", f_find_holes),
        ("create_element", f_create_element),
        ("create_text", f_create_text),
        ("create_comment", f_create_comment),
        ("set_text", f_set_text),
        ("set_attr", f_set_attr),
        ("remove_attr", f_remove_attr),
        ("set_prop", f_set_prop),
        ("set_prop_bool", f_set_prop_bool),
        ("toggle_class", f_toggle_class),
        ("set_style", f_set_style),
        ("remove_style", f_remove_style),
        ("append", f_append),
        ("insert", f_insert),
        ("remove", f_remove),
        ("replace", f_replace),
        ("listen", f_listen),
        ("unlisten", f_unlisten),
        ("release", f_release),
        ("set_dispatcher", f_set_dispatcher),
        ("teardown", f_teardown),
        ("flush", f_flush),
        ("query", f_query),
        ("node", f_node),
        ("id_of", f_id_of),
    ];
    for &(name, f) in fns {
        let nf = vm.native(name, f);
        vm.dict_set_str(d, name, nf);
    }
    vm.dict_set_str(d, "available", Value::bool(vm.js_hooks.is_some()));
    Ok(m)
}
