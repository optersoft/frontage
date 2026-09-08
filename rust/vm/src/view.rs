//! The view layer's hot path, native (`RUNTIME.md` §3.8): instantiating a compiled Template —
//! the extract walk over the author's Element tree, the clone, the holes — and the two kinds
//! of hole effect, a child position with the insert rules and reconcile, and a bound
//! attribute. Writes DOM operations straight into the op stream (`dom.rs`).
//!
//! Taken only on the streaming renderer with no hydration in progress and a Template already
//! compiled and cached; everything else (the first row of a shape, prerender, hydration, the
//! HtmlRenderer, floating holes) runs `frontage/view.py`, which stays the specification.
//! `_view.setup(...)` hands over the classes and the Python fallbacks.

use crate::core;
use crate::dom::*;
use crate::object::Obj;
use crate::value::Value;
use crate::vm::{PyResult, Vm};
use std::collections::HashMap;

/// A hole effect's native half: where it writes, and what it wrote last time.
pub struct Hole {
    pub renderer: Value,
    /// A child hole: the parent (a negative id, "the marker's parent") and the marker.
    pub parent: i32,
    pub marker: i32,
    pub current: Vec<i32>,
    pub text: i32,
    /// An attribute hole: the element, the kind and the name.
    pub node: i32,
    pub attr: Option<(AttrKind, String)>,
}

impl Hole {
    pub fn trace(&self, visit: &mut impl FnMut(Value)) {
        visit(self.renderer);
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AttrKind {
    Attr,
    Prop,
    Class,
    Style,
    Event,
    Capture,
    Bind,
    Ref,
    ClassDict,
}

#[derive(Default)]
pub struct ViewState {
    pub element_cls: Value,
    pub text_cls: Value,
    pub mounted_cls: Value,
    pub stream_cls: Value,
    pub view_module: Value,
    pub build_template_py: Value,
    pub apply_attr_py: Value,
    pub listen_py: Value,
    pub build_nodes_py: Value,
    /// `_classify` memoized: raw keyword → (kind, name).
    pub classified: HashMap<u32, (AttrKind, String)>,
    pub names: ViewNames,
}

macro_rules! view_names {
    ($($field:ident = $text:expr),* $(,)?) => {
        #[derive(Default, Clone, Copy)]
        pub struct ViewNames { $(pub $field: Value,)* }
        impl ViewNames {
            fn fill(vm: &mut Vm) {
                $( let v = vm.intern($text); vm.view.names.$field = v; )*
            }
        }
    };
}
view_names! {
    tag = "tag", attrs = "attrs", children = "children", value = "value", nodes = "nodes",
    specs = "specs", html = "html", tid = "_tid", template = "template", hydration = "hydration",
    hydration_markers = "hydration_markers", current_renderer = "_current_renderer",
    handlers = "_handlers", dispatcher = "_dispatcher", stream = "_stream",
}

impl ViewState {
    pub fn trace(&self, visit: &mut impl FnMut(Value)) {
        for v in [self.element_cls, self.text_cls, self.mounted_cls, self.stream_cls, self.view_module, self.build_template_py, self.apply_attr_py, self.listen_py, self.build_nodes_py] {
            visit(v);
        }
    }
}

const PROPERTIES: &[&str] = &["value", "checked", "selected", "textContent", "innerHTML", "muted", "volume", "currentTime"];
const BOOLEAN_ATTRS: &[&str] = &["disabled", "hidden", "readonly", "required", "open", "multiple", "autofocus", "autoplay", "controls", "loop", "novalidate", "reversed", "selected", "checked"];
const VOID: &[&str] = &["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"];

fn is_instance(vm: &Vm, v: Value, cls: Value) -> bool {
    v.is_obj() && vm.type_of(v) == cls
}

fn attr_name(raw: &str) -> String {
    let base = match raw {
        "cls" | "class_" => return "class".into(),
        "for_" => return "for".into(),
        _ => raw,
    };
    let base = base.strip_suffix('_').unwrap_or(base);
    base.replace('_', "-")
}

/// `_classify_uncached`, line for line.
fn classify_uncached(raw: &str) -> (AttrKind, String) {
    if raw == "ref" {
        return (AttrKind::Ref, raw.into());
    }
    if raw == "cls" || raw == "class_" || raw == "class" {
        return (AttrKind::ClassDict, "class".into());
    }
    const PREFIXES: &[(&str, AttrKind)] = &[
        ("oncapture_", AttrKind::Capture),
        ("oncapture:", AttrKind::Capture),
        ("on_", AttrKind::Event),
        ("on:", AttrKind::Event),
        ("prop_", AttrKind::Prop),
        ("prop:", AttrKind::Prop),
        ("class_", AttrKind::Class),
        ("class:", AttrKind::Class),
        ("style_", AttrKind::Style),
        ("style:", AttrKind::Style),
        ("bind_", AttrKind::Bind),
        ("bind:", AttrKind::Bind),
        ("attr:", AttrKind::Attr),
    ];
    for &(prefix, kind) in PREFIXES {
        if raw.starts_with(prefix) && raw.len() > prefix.len() {
            let rest = &raw[prefix.len()..];
            return match kind {
                AttrKind::Class | AttrKind::Style => (kind, rest.replace('_', "-")),
                AttrKind::Event | AttrKind::Capture | AttrKind::Bind | AttrKind::Prop => (kind, rest.into()),
                _ => (AttrKind::Attr, attr_name(rest)),
            };
        }
    }
    (AttrKind::Attr, attr_name(raw))
}

fn classify(vm: &mut Vm, raw: Value) -> (AttrKind, String) {
    let key = raw.as_obj() as u32;
    if let Some(c) = vm.view.classified.get(&key) {
        return c.clone();
    }
    let s = vm.as_str(raw).unwrap_or("").to_string();
    let c = classify_uncached(&s);
    vm.view.classified.insert(key, c.clone());
    c
}

/// `_static_kind`: an attribute whose plain value goes into the template's HTML.
fn static_kind(vm: &mut Vm, raw: Value, value: Value) -> bool {
    let (kind, _) = classify(vm, raw);
    match kind {
        AttrKind::Attr => true,
        AttrKind::ClassDict => !(value.is_obj() && matches!(vm.heap.get(value), Obj::Dict(_))),
        _ => false,
    }
}

// -- the streaming renderer, by id -------------------------------------------------------------

/// True when the native path applies: a streaming renderer, no hydration in progress.
fn streaming(vm: &mut Vm, renderer: Value) -> PyResult<bool> {
    let cls = vm.view.stream_cls;
    if cls.is_none() || !vm.is_instance_of(renderer, cls) {
        return Ok(false);
    }
    let h = vm.view.names.hydration;
    let hyd = vm.get_attr(renderer, h)?;
    if !hyd.is_none() {
        return Ok(false);
    }
    let hm = vm.view.names.hydration_markers;
    let markers = vm.get_attr(renderer, hm)?;
    Ok(!vm.truthy(markers)?)
}

fn set_property(vm: &mut Vm, node: i32, name: &str, value: Value) -> PyResult<()> {
    if PROPERTIES.contains(&name) {
        if value.is_bool() {
            vm.dom.op_id_str_bool(OP_SET_PROP_BOOL, node, name, value.as_bool());
        } else {
            let s = if value.is_none() { String::new() } else { vm.str_of(value)? };
            vm.dom.op_id_str_str(OP_SET_PROP, node, name, &s);
        }
    } else if BOOLEAN_ATTRS.contains(&name) || value.is_bool() {
        if vm.truthy(value)? {
            vm.dom.op_id_str_str(OP_SET_ATTR, node, name, "");
        } else {
            vm.dom.op_id_str(OP_REMOVE_ATTR, node, name);
        }
    } else if value.is_none() {
        vm.dom.op_id_str(OP_REMOVE_ATTR, node, name);
    } else {
        let s = vm.str_of(value)?;
        vm.dom.op_id_str_str(OP_SET_ATTR, node, name, &s);
    }
    Ok(())
}

fn set_kind(vm: &mut Vm, node: i32, kind: AttrKind, name: &str, value: Value) -> PyResult<()> {
    match kind {
        AttrKind::Attr | AttrKind::Prop => set_property(vm, node, name, value),
        AttrKind::Class => {
            let on = vm.truthy(value)?;
            vm.dom.op_id_str_bool(OP_TOGGLE_CLASS, node, name, on);
            Ok(())
        }
        AttrKind::Style => {
            if value.is_none() || value == Value::FALSE {
                vm.dom.op_id_str(OP_REMOVE_STYLE, node, name);
            } else {
                let s = vm.str_of(value)?;
                vm.dom.op_id_str_str(OP_SET_STYLE, node, name, &s);
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

// -- the template walk ---------------------------------------------------------------------------

struct Extracted {
    /// Per numbered element: its dynamic `(raw, value)` pairs.
    element_holes: Vec<Vec<(Value, Value)>>,
    child_holes: Vec<Value>,
}

/// `Template.extract`: the hole values of an Element tree of the template's shape, or None.
fn extract(vm: &mut Vm, specs: &[Value], element: Value) -> PyResult<Option<Extracted>> {
    let mut out = Extracted { element_holes: Vec::new(), child_holes: Vec::new() };
    let mut cursor = 0usize;
    if !walk(vm, specs, element, &mut cursor, &mut out)? || cursor != specs.len() {
        return Ok(None);
    }
    Ok(Some(out))
}

fn walk(vm: &mut Vm, specs: &[Value], el: Value, cursor: &mut usize, out: &mut Extracted) -> PyResult<bool> {
    let i = *cursor;
    if i >= specs.len() {
        return Ok(false);
    }
    *cursor = i + 1;
    let spec = vm.collect_iter(specs[i])?;
    if spec.len() != 3 {
        return Ok(false);
    }
    let (tag, static_, dynamic) = (spec[0], spec[1], spec[2]);
    let n = vm.view.names;
    let el_tag = vm.get_attr(el, n.tag)?;
    let attrs = vm.get_attr(el, n.attrs)?;
    if !vm.eq(el_tag, tag)? {
        return Ok(false);
    }
    let n_static = vm.len_of(static_).unwrap_or(0);
    let dynamic_names = vm.collect_iter(dynamic)?;
    if vm.len_of(attrs).unwrap_or(0) != n_static + dynamic_names.len() {
        return Ok(false);
    }
    let mut values = Vec::with_capacity(dynamic_names.len());
    for raw in dynamic_names {
        let value = match vm.key_get(attrs, raw)? {
            Some(v) => v,
            None => return Ok(false),
        };
        if !core::callable(vm, value) && static_kind(vm, raw, value) {
            return Ok(false);
        }
        values.push((raw, value));
    }
    for (name, expected) in vm.mapping_items(static_)? {
        let value = match vm.key_get(attrs, name)? {
            Some(v) => v,
            None => return Ok(false),
        };
        if core::callable(vm, value) || !vm.eq(value, expected)? {
            return Ok(false);
        }
    }
    if !values.is_empty() {
        out.element_holes.push(values);
    }
    let tag_s = vm.as_str(tag).unwrap_or("").to_string();
    if VOID.contains(&tag_s.as_str()) {
        return Ok(true);
    }
    let children = vm.get_attr(el, n.children)?;
    let element_cls = vm.view.element_cls;
    for child in vm.collect_iter(children)? {
        if is_instance(vm, child, element_cls) {
            if !walk(vm, specs, child, cursor, out)? {
                return Ok(false);
            }
        } else {
            out.child_holes.push(child);
        }
    }
    Ok(true)
}

// -- instantiation ---------------------------------------------------------------------------------

/// `build_template(element, renderer, cache)`: the root node id, or None when the Python
/// path must run (no cached Template, a shape mismatch, hydration, another renderer).
fn f_build_template(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    if args.len() < 3 {
        return Err(vm.type_error("build_template(element, renderer, cache)"));
    }
    let (element, renderer, cache) = (args[0], args[1], args[2]);
    if cache.is_none() || !streaming(vm, renderer)? {
        return Ok(Value::NONE);
    }
    let tkey = vm.view.names.template;
    let template = match vm.key_get(cache, tkey)? {
        Some(t) => t,
        None => return Ok(Value::NONE),
    };
    let n = vm.view.names;
    let specs_v = vm.get_attr(template, n.specs)?;
    let specs = vm.collect_iter(specs_v)?;
    let extracted = match extract(vm, &specs, element)? {
        Some(e) => e,
        None => return Ok(Value::NONE),
    };
    // The template's id in the glue, defined once and kept on the Template object.
    let tid = match vm.get_attr(template, n.tid) {
        Ok(v) if !v.is_none() => vm.as_i64(v).unwrap_or(0) as u32,
        _ => {
            let html_v = vm.get_attr(template, n.html)?;
            let html = vm.str_of(html_v)?;
            let tid = vm.dom.next_template;
            vm.dom.next_template += 1;
            vm.dom.u8(OP_DEFINE_TEMPLATE);
            vm.dom.u32(tid);
            vm.dom.str(&html);
            let tv = Value::int(tid as i32);
            vm.set_attr(template, n.tid, tv)?;
            tid
        }
    };
    let root = vm.dom.alloc(1);
    vm.dom.u8(OP_CLONE);
    vm.dom.u32(root);
    vm.dom.u32(tid);
    let n_el = extracted.element_holes.len() as u32;
    let n_mk = extracted.child_holes.len() as u32;
    if n_el + n_mk > 0 {
        let first = vm.dom.alloc(n_el + n_mk);
        vm.dom.u8(OP_FIND_HOLES);
        vm.dom.i32(root as i32);
        vm.dom.u32(first);
        vm.dom.u32(n_el);
        vm.dom.u32(n_mk);
        vm.dom.u8(0);
        for (i, holes) in extracted.element_holes.iter().enumerate() {
            let node = (first + i as u32) as i32;
            for &(raw, value) in holes {
                apply_attr(vm, node, raw, value, renderer)?;
            }
        }
        let text_cls = vm.view.text_cls;
        let mounted_cls = vm.view.mounted_cls;
        for (k, &child) in extracted.child_holes.iter().enumerate() {
            let marker = (first + n_el + k as u32) as i32;
            let parent = -marker;
            if is_instance(vm, child, text_cls) {
                let v = vm.get_attr(child, n.value)?;
                let s = vm.str_of(v)?;
                let t = vm.dom.alloc(1);
                vm.dom.u8(OP_CREATE_TEXT);
                vm.dom.u32(t);
                vm.dom.str(&s);
                vm.dom.u8(OP_REPLACE);
                vm.dom.i32(parent);
                vm.dom.i32(t as i32);
                vm.dom.i32(marker);
            } else if is_instance(vm, child, mounted_cls) {
                let nodes_v = vm.get_attr(child, n.nodes)?;
                for node in vm.collect_iter(nodes_v)? {
                    let id = vm.as_i64(node).unwrap_or(0) as i32;
                    vm.dom.u8(OP_INSERT);
                    vm.dom.i32(parent);
                    vm.dom.i32(id);
                    vm.dom.i32(marker);
                }
            } else {
                mount_hole(vm, renderer, parent, child, marker)?;
            }
        }
    }
    vm.dom_maybe_flush_pub()?;
    Ok(Value::int(root as i32))
}

fn apply_attr(vm: &mut Vm, node: i32, raw: Value, value: Value, renderer: Value) -> PyResult<()> {
    let (kind, name) = classify(vm, raw);
    match kind {
        AttrKind::Ref | AttrKind::Bind | AttrKind::Capture | AttrKind::ClassDict => {
            // Rare, or hydration-sensitive: the Python `_apply_attr`.
            let f = vm.view.apply_attr_py;
            vm.call(f, &[Value::int(node), raw, value, renderer], &[])?;
            Ok(())
        }
        AttrKind::Event => listen(vm, node, &name, value, renderer),
        _ => {
            if core::callable(vm, value) {
                attr_hole(vm, renderer, node, kind, name, value)
            } else {
                set_kind(vm, node, kind, &name, value)
            }
        }
    }
}

/// `_listen` for a delegated event: the handler and its owner into the renderer's table, the
/// LISTEN op, and an unlisten record among the owner's cleanups.
fn listen(vm: &mut Vm, node: i32, event: &str, handler: Value, renderer: Value) -> PyResult<()> {
    let n = vm.view.names;
    let dispatcher = vm.get_attr(renderer, n.dispatcher)?;
    if dispatcher.is_none() || !crate::dom::DELEGATED.contains(&event) {
        // The first listener installs the dispatcher; a direct listener needs the node itself.
        let f = vm.view.listen_py;
        let ev = vm.str(event);
        vm.call(f, &[Value::int(node), ev, handler, renderer], &[])?;
        return Ok(());
    }
    let owner = vm.core.owner;
    let table = vm.get_attr(renderer, n.handlers)?;
    let ev = vm.intern(event);
    let key = vm.tuple(vec![Value::int(node), ev]);
    let entry = vm.tuple(vec![handler, owner]);
    vm.key_set(table, key, entry)?;
    vm.dom.op_id_str(OP_LISTEN, node, event);
    if !owner.is_none() && core::is_node(vm, owner) {
        let record = vm.tuple(vec![renderer, Value::int(node), ev]);
        core::push_cleanup(vm, owner, record);
    }
    Ok(())
}

/// An `unlisten` cleanup record `(renderer, node, event)`, run by `core::dispose_owned`.
pub fn run_unlisten(vm: &mut Vm, record: Value) -> PyResult<bool> {
    let items = match vm.heap.get(record) {
        Obj::Tuple(t) if t.len() == 3 => t.clone(),
        _ => return Ok(false),
    };
    let (renderer, node, ev) = (items[0], items[1], items[2]);
    let stream = vm.view.stream_cls;
    if stream.is_none() || !vm.is_instance_of(renderer, stream) || !node.is_int() {
        return Ok(false);
    }
    let n = vm.view.names;
    let table = vm.get_attr(renderer, n.handlers)?;
    let key = vm.tuple(vec![node, ev]);
    if vm.key_remove(table, key)?.is_some() {
        let event = vm.as_str(ev).unwrap_or("").to_string();
        vm.dom.op_id_str(OP_UNLISTEN, node.as_int(), &event);
    }
    Ok(true)
}

fn new_hole_effect(vm: &mut Vm, func: Value, hole: Hole) -> PyResult<Value> {
    let cls = vm.core.render_effect_cls;
    let e = core::new_effect(vm, cls, func, true);
    core::set_hole(vm, e, hole);
    core::start_effect(vm, e)?;
    Ok(e)
}

fn attr_hole(vm: &mut Vm, renderer: Value, node: i32, kind: AttrKind, name: String, value: Value) -> PyResult<()> {
    let hole = Hole { renderer, parent: 0, marker: 0, current: Vec::new(), text: 0, node, attr: Some((kind, name)) };
    new_hole_effect(vm, value, hole)?;
    Ok(())
}

fn mount_hole(vm: &mut Vm, renderer: Value, parent: i32, accessor: Value, marker: i32) -> PyResult<()> {
    let hole = Hole { renderer, parent, marker, current: Vec::new(), text: 0, node: 0, attr: None };
    new_hole_effect(vm, accessor, hole)?;
    Ok(())
}

// -- the hole effects' native halves ------------------------------------------------------------------

/// The compute of a child hole, inside the tracked scope: the accessor's value, resolved to
/// a text (a str) or to nodes (a list of ids), with the view module's `_current_renderer`
/// set meanwhile so control flow builds with this renderer.
pub fn hole_compute(vm: &mut Vm, e: Value, renderer: Value, accessor: Value) -> PyResult {
    let module = vm.view.view_module;
    let key = vm.view.names.current_renderer;
    let dict = vm.module_dict(module);
    let saved = vm.dict_get(dict, key).unwrap_or(Value::NONE);
    vm.dict_set(dict, key, renderer);
    let r = (|| -> PyResult {
        let value = vm.call(accessor, &[], &[])?;
        if value.is_int() || value.is_float() || (value.is_obj() && matches!(vm.heap.get(value), Obj::Str(_) | Obj::Int(_))) {
            let s = vm.str_of(value)?;
            return Ok(vm.string(s));
        }
        let mut ids = Vec::new();
        normalize(vm, e, value, renderer, &mut ids)?;
        let items: Vec<Value> = ids.into_iter().map(Value::int).collect();
        Ok(vm.list(items))
    })();
    vm.dict_set(dict, key, saved);
    r
}

/// `_normalize`: a hole's value to node ids, running callables tracked, building elements.
fn normalize(vm: &mut Vm, e: Value, value: Value, renderer: Value, out: &mut Vec<i32>) -> PyResult<()> {
    if value.is_none() || value.is_bool() {
        return Ok(());
    }
    let n = vm.view.names;
    if value.is_obj() {
        let cls = vm.type_of(value);
        if cls == vm.view.mounted_cls {
            let nodes = vm.get_attr(value, n.nodes)?;
            for v in vm.collect_iter(nodes)? {
                out.push(vm.as_i64(v).unwrap_or(0) as i32);
            }
            return Ok(());
        }
        if cls == vm.view.element_cls || cls == vm.view.text_cls {
            let f = vm.view.build_nodes_py;
            let nodes = vm.call(f, &[value, renderer], &[])?;
            for v in vm.collect_iter(nodes)? {
                out.push(vm.as_i64(v).unwrap_or(0) as i32);
            }
            return Ok(());
        }
        match vm.heap.get(value) {
            Obj::List(_) | Obj::Tuple(_) => {
                for item in vm.collect_iter(value)? {
                    normalize(vm, e, item, renderer, out)?;
                }
                return Ok(());
            }
            _ => {}
        }
        if core::callable(vm, value) {
            let v = vm.call(value, &[], &[])?;
            return normalize(vm, e, v, renderer, out);
        }
    }
    let s = vm.str_of(value)?;
    let t = vm.dom.alloc(1);
    vm.dom.u8(OP_CREATE_TEXT);
    vm.dom.u32(t);
    vm.dom.str(&s);
    out.push(t as i32);
    Ok(())
}

/// The apply of a hole effect: an attribute write, or the insert rules for a child hole.
pub fn hole_apply(vm: &mut Vm, e: Value, value: Value, prev: Value) -> PyResult<()> {
    let (attr, parent, marker, current, text) = {
        let h = core::hole(vm, e);
        (h.attr.clone(), h.parent, h.marker, h.current.clone(), h.text)
    };
    if let Some((kind, name)) = attr {
        let node = core::hole(vm, e).node;
        return set_kind(vm, node, kind, &name, value);
    }
    if value.is_obj() && matches!(vm.heap.get(value), Obj::Str(_)) {
        let s = vm.as_str(value).unwrap_or("").to_string();
        if text != 0 {
            let same = prev.is_obj() && matches!(vm.heap.get(prev), Obj::Str(_)) && vm.as_str(prev) == Some(s.as_str());
            if !same {
                vm.dom.op_id_str(OP_SET_TEXT, text, &s);
            }
            return Ok(());
        }
        let node = vm.dom.alloc(1) as i32;
        vm.dom.u8(OP_CREATE_TEXT);
        vm.dom.u32(node as u32);
        vm.dom.str(&s);
        if !current.is_empty() {
            reconcile(vm, parent, &current, &[node], marker);
        } else {
            vm.dom.u8(OP_INSERT);
            vm.dom.i32(parent);
            vm.dom.i32(node);
            vm.dom.i32(marker);
        }
        let h = core::hole(vm, e);
        h.current = vec![node];
        h.text = node;
        return Ok(());
    }
    let new: Vec<i32> = vm.collect_iter(value)?.into_iter().map(|v| vm.as_i64(v).unwrap_or(0) as i32).collect();
    core::hole(vm, e).text = 0;
    if !current.is_empty() {
        reconcile(vm, parent, &current, &new, marker);
    } else {
        for &node in &new {
            vm.dom.u8(OP_INSERT);
            vm.dom.i32(parent);
            vm.dom.i32(node);
            vm.dom.i32(marker);
        }
    }
    core::hole(vm, e).current = new;
    Ok(())
}

/// `_reconcile`: make the nodes before `marker` be exactly `new`, moving what exists.
fn reconcile(vm: &mut Vm, parent: i32, current: &[i32], new: &[i32], marker: i32) {
    if current == new {
        return;
    }
    let mut position: HashMap<i32, usize> = HashMap::with_capacity(new.len());
    for (i, &n) in new.iter().enumerate() {
        position.insert(n, i);
    }
    let mut kept: Vec<usize> = Vec::new();
    for &node in current {
        match position.get(&node) {
            Some(&i) => kept.push(i),
            None => {
                vm.dom.u8(OP_REMOVE);
                vm.dom.i32(parent);
                vm.dom.i32(node);
            }
        }
    }
    let stay = lis(&kept);
    let mut anchor = marker;
    for i in (0..new.len()).rev() {
        let node = new[i];
        if stay.contains(&i) {
            anchor = node;
            continue;
        }
        vm.dom.u8(OP_INSERT);
        vm.dom.i32(parent);
        vm.dom.i32(node);
        vm.dom.i32(anchor);
        anchor = node;
    }
}

/// Values of a longest strictly increasing subsequence (patience sorting), as a set.
fn lis(seq: &[usize]) -> std::collections::HashSet<usize> {
    let mut out = std::collections::HashSet::new();
    if seq.is_empty() {
        return out;
    }
    let mut tails: Vec<usize> = Vec::new();
    let mut prev: Vec<isize> = vec![-1; seq.len()];
    for (i, &value) in seq.iter().enumerate() {
        let (mut lo, mut hi) = (0usize, tails.len());
        while lo < hi {
            let mid = (lo + hi) / 2;
            if seq[tails[mid]] < value {
                lo = mid + 1;
            } else {
                hi = mid;
            }
        }
        if lo > 0 {
            prev[i] = tails[lo - 1] as isize;
        }
        if lo == tails.len() {
            tails.push(i);
        } else {
            tails[lo] = i;
        }
    }
    let mut i = *tails.last().unwrap() as isize;
    while i != -1 {
        out.insert(seq[i as usize]);
        i = prev[i as usize];
    }
    out
}

/// `on_screen` for a hole effect: the marker (or the element) is connected.
pub fn hole_on_screen(vm: &mut Vm, e: Value) -> PyResult<bool> {
    let (node, marker, attr) = {
        let h = core::hole(vm, e);
        (h.node, h.marker, h.attr.is_some())
    };
    let id = if attr { node } else { marker };
    vm.dom_flush()?;
    let hooks = vm.js()?;
    Ok((hooks.dom_query)(6, id) != 0)
}

// -- setup --------------------------------------------------------------------------------------------

fn f_setup(vm: &mut Vm, _a: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    for &(k, v) in kwargs {
        let key = vm.as_str(k).unwrap_or("").to_string();
        match key.as_str() {
            "Element" => vm.view.element_cls = v,
            "Text" => vm.view.text_cls = v,
            "Mounted" => vm.view.mounted_cls = v,
            "StreamRenderer" => vm.view.stream_cls = v,
            "module" => vm.view.view_module = v,
            "build_template" => vm.view.build_template_py = v,
            "apply_attr" => vm.view.apply_attr_py = v,
            "listen" => vm.view.listen_py = v,
            "build_nodes" => vm.view.build_nodes_py = v,
            other => return Err(vm.type_error(format!("_view.setup(): unknown keyword '{other}'"))),
        }
    }
    Ok(Value::NONE)
}

pub fn install_module(vm: &mut Vm) -> PyResult {
    ViewNames::fill(vm);
    let m = vm.new_module("_view");
    let d = vm.module_dict(m);
    let f = vm.native("setup", f_setup);
    vm.dict_set_str(d, "setup", f);
    let f = vm.native("build_template", f_build_template);
    vm.dict_set_str(d, "build_template", f);
    vm.dict_set_str(d, "available", Value::bool(vm.js_hooks.is_some()));
    Ok(m)
}
