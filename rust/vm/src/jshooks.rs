//! The seam between the VM and a JavaScript host.
//!
//! A JavaScript value the Python side holds is `Obj::Js(handle)`: an index into a table the
//! glue keeps. Every operation on one goes through these hooks, installed by the browser
//! build (`frontage-web`); the native runtime has none, and `import js` fails there with an
//! `ImportError`, which is what `frontage.runtime` uses to tell the two apart.
//!
//! Values cross in *slots*: 16 bytes — a tag and a payload — written into linear memory by
//! whichever side is sending. Strings cross as UTF-8 bytes in linear memory; JavaScript
//! objects cross as handles; `None`/`undefined`/`null`, booleans and numbers cross inline;
//! a Python dict, list or tuple crosses as a tree the glue turns into a plain object or an
//! array (what `to_js` promises).

use crate::object::Obj;
use crate::value::Value;
use crate::vm::{PyResult, Vm};

pub const TAG_UNDEFINED: u32 = 0;
pub const TAG_NULL: u32 = 1;
pub const TAG_BOOL: u32 = 2;
pub const TAG_NUMBER: u32 = 3;
pub const TAG_STRING: u32 = 4;
pub const TAG_HANDLE: u32 = 5;
pub const TAG_TREE: u32 = 6;
pub const TAG_BIGINT: u32 = 7;
/// A Python object passed by pin: the glue makes a function calling back into the VM.
pub const TAG_PIN: u32 = 8;

/// The handle of `globalThis`.
pub const GLOBAL: u32 = 0;
pub const UNDEFINED_HANDLE: u32 = u32::MAX;

#[repr(C)]
#[derive(Clone, Copy, Default)]
pub struct Slot {
    pub tag: u32,
    pub aux: u32,
    pub payload: u64,
}

impl Slot {
    pub fn number(f: f64) -> Slot {
        Slot { tag: TAG_NUMBER, aux: 0, payload: f.to_bits() }
    }
    pub fn handle(h: u32) -> Slot {
        Slot { tag: TAG_HANDLE, aux: 0, payload: h as u64 }
    }
    pub fn bool(b: bool) -> Slot {
        Slot { tag: TAG_BOOL, aux: 0, payload: b as u64 }
    }
    pub fn string(ptr: *const u8, len: usize) -> Slot {
        Slot { tag: TAG_STRING, aux: len as u32, payload: ptr as usize as u64 }
    }
    pub fn as_f64(&self) -> f64 {
        f64::from_bits(self.payload)
    }
    pub fn as_handle(&self) -> u32 {
        self.payload as u32
    }
}

/// What the browser build supplies. Each takes the VM so it can allocate results.
pub struct JsHooks {
    /// `obj.name`
    pub get: fn(&mut Vm, u32, &str) -> PyResult<Slot>,
    pub set: fn(&mut Vm, u32, &str, Slot) -> PyResult<()>,
    /// `func.call(this, …)`; `this` may be `UNDEFINED_HANDLE`.
    pub call: fn(&mut Vm, u32, u32, &[Slot]) -> PyResult<Slot>,
    /// `new ctor(…)`
    pub new: fn(&mut Vm, u32, &[Slot]) -> PyResult<Slot>,
    pub index: fn(&mut Vm, u32, Slot) -> PyResult<Slot>,
    pub set_index: fn(&mut Vm, u32, Slot, Slot) -> PyResult<()>,
    /// `length`, or -1 when the object has none.
    pub len: fn(&mut Vm, u32) -> i32,
    pub truthy: fn(&mut Vm, u32) -> bool,
    /// `String(obj)`
    pub str: fn(&mut Vm, u32) -> PyResult<String>,
    /// The type tag of an object: "function", "array", "object", "promise", "error", "date"…
    pub kind: fn(&mut Vm, u32) -> String,
    /// A JavaScript function that calls the pinned Python callable.
    pub make_proxy: fn(&mut Vm, u32) -> u32,
    /// Handles the collector freed.
    pub release: fn(&[u32]),
    /// `a === b`
    pub same: fn(u32, u32) -> bool,
    /// The DOM op stream (`dom.rs`): execute a buffer of operations.
    pub dom_flush: fn(&[u8]),
    /// A question about a node: `(kind, id)` → an id, a node type, or a flag (`dom.rs`).
    pub dom_query: fn(u32, i32) -> i64,
    /// The JavaScript node for an id, as a handle (`UNDEFINED_HANDLE` if none).
    pub dom_node: fn(i32) -> u32,
    /// The id of a node that came from JavaScript, registered on first sight.
    pub dom_id_of: fn(u32) -> u32,
}

impl Vm {
    pub fn js(&mut self) -> PyResult<&'static JsHooks> {
        match self.js_hooks {
            Some(h) => Ok(h),
            None => Err(self.runtime_error("no JavaScript host in this runtime")),
        }
    }

    pub fn js_handle(&self, v: Value) -> Option<u32> {
        if !v.is_obj() {
            return None;
        }
        match self.heap.get(v) {
            Obj::Js(h) => Some(*h),
            _ => None,
        }
    }

    /// Wrap a handle as a Python value.
    pub fn js_object(&mut self, h: u32) -> Value {
        self.heap.alloc(Obj::Js(h))
    }

    /// Encode a Python value for JavaScript. Strings point at their UTF-8 bytes in the heap,
    /// valid until the next allocation — encode everything before the call, then call.
    pub fn to_slot(&mut self, v: Value, trees: &mut Vec<Vec<u8>>) -> PyResult<Slot> {
        if v.is_none() || v.is_undef() {
            return Ok(Slot { tag: TAG_UNDEFINED, aux: 0, payload: 0 });
        }
        if v.is_bool() {
            return Ok(Slot::bool(v.as_bool()));
        }
        if v.is_int() {
            return Ok(Slot::number(v.as_int() as f64));
        }
        if v.is_float() {
            return Ok(Slot::number(v.as_float()));
        }
        match self.heap.get(v) {
            Obj::Int(i) => Ok(Slot::number(*i as f64)),
            Obj::Str(s) => Ok(Slot::string(s.s.as_ptr(), s.s.len())),
            Obj::Js(h) => Ok(Slot::handle(*h)),
            Obj::Bound { func, this } => {
                // a bound JavaScript method passed along (rare): pass the function
                let (f, t) = (*func, *this);
                if let (Some(fh), Some(_)) = (self.js_handle(f), self.js_handle(t)) {
                    return Ok(Slot::handle(fh));
                }
                let pin = self.pin(v);
                Ok(Slot { tag: TAG_PIN, aux: 0, payload: pin as u64 })
            }
            Obj::Func(_) | Obj::Native(_) | Obj::Instance(_) => {
                // A callable passed without `create_proxy`: proxied for this call. (The
                // pin lives until the proxy is destroyed; event handlers should use
                // `create_proxy` and release it on cleanup.)
                let pin = self.pin(v);
                Ok(Slot { tag: TAG_PIN, aux: 0, payload: pin as u64 })
            }
            Obj::List(_) | Obj::Tuple(_) | Obj::Dict(_) => {
                let mut buf = Vec::with_capacity(256);
                self.encode_tree(v, &mut buf, 0)?;
                trees.push(buf);
                let b = trees.last().unwrap();
                Ok(Slot { tag: TAG_TREE, aux: b.len() as u32, payload: b.as_ptr() as usize as u64 })
            }
            Obj::Bytes(b) | Obj::ByteArray(b) => Ok(Slot { tag: TAG_STRING, aux: b.len() as u32 | 0x8000_0000, payload: b.as_ptr() as usize as u64 }),
            _ => {
                let t = self.type_name(v);
                Err(self.type_error(format!("cannot pass a '{t}' to JavaScript")))
            }
        }
    }

    /// A tree: tag byte, then per kind. Strings: u32 len + bytes. Lists: u32 n + items.
    /// Dicts: u32 n + (key string, value) pairs. Handles: u32. Numbers: f64. Pins: u32.
    fn encode_tree(&mut self, v: Value, out: &mut Vec<u8>, depth: u32) -> PyResult<()> {
        if depth > 64 {
            return Err(self.value_error("object too deeply nested for JavaScript"));
        }
        if v.is_none() || v.is_undef() {
            out.push(0);
        } else if v.is_bool() {
            out.push(1);
            out.push(v.as_bool() as u8);
        } else if v.is_int() {
            out.push(2);
            out.extend_from_slice(&(v.as_int() as f64).to_le_bytes());
        } else if v.is_float() {
            out.push(2);
            out.extend_from_slice(&v.as_float().to_le_bytes());
        } else {
            match self.heap.get(v) {
                Obj::Int(i) => {
                    out.push(2);
                    out.extend_from_slice(&(*i as f64).to_le_bytes());
                }
                Obj::Str(s) => {
                    out.push(3);
                    out.extend_from_slice(&(s.s.len() as u32).to_le_bytes());
                    out.extend_from_slice(s.s.as_bytes());
                }
                Obj::Js(h) => {
                    out.push(4);
                    out.extend_from_slice(&h.to_le_bytes());
                }
                Obj::List(items) | Obj::Tuple(items) => {
                    let items = items.clone();
                    out.push(5);
                    out.extend_from_slice(&(items.len() as u32).to_le_bytes());
                    for it in items {
                        self.encode_tree(it, out, depth + 1)?;
                    }
                }
                Obj::Dict(d) => {
                    let items: Vec<(Value, Value)> = d.items().collect();
                    out.push(6);
                    out.extend_from_slice(&(items.len() as u32).to_le_bytes());
                    for (k, val) in items {
                        let ks = self.str_of(k)?;
                        out.extend_from_slice(&(ks.len() as u32).to_le_bytes());
                        out.extend_from_slice(ks.as_bytes());
                        self.encode_tree(val, out, depth + 1)?;
                    }
                }
                Obj::Func(_) | Obj::Native(_) | Obj::Bound { .. } | Obj::Instance(_) => {
                    let pin = self.pin(v);
                    out.push(7);
                    out.extend_from_slice(&pin.to_le_bytes());
                }
                _ => {
                    let t = self.type_name(v);
                    return Err(self.type_error(format!("cannot pass a '{t}' to JavaScript")));
                }
            }
        }
        Ok(())
    }

    /// Decode a slot the glue filled.
    pub fn from_slot(&mut self, s: Slot) -> PyResult {
        Ok(match s.tag {
            TAG_UNDEFINED | TAG_NULL => Value::NONE,
            TAG_BOOL => Value::bool(s.payload & 1 == 1),
            TAG_NUMBER => {
                let f = s.as_f64();
                if f.fract() == 0.0 && f.abs() < 2147483648.0 {
                    Value::int(f as i32)
                } else {
                    Value::float(f)
                }
            }
            TAG_BIGINT => self.int(s.payload as i64),
            TAG_STRING => {
                // the glue wrote the bytes with `alloc`; take them back
                let (ptr, len) = (s.payload as usize as *mut u8, s.aux as usize);
                let bytes = unsafe { Vec::from_raw_parts(ptr, len, len.max(1)) };
                let text = String::from_utf8_lossy(&bytes).into_owned();
                self.string(text)
            }
            TAG_HANDLE => self.js_object(s.as_handle()),
            TAG_PIN => self.js_pins.get(s.payload as usize).copied().unwrap_or(Value::NONE),
            _ => Value::NONE,
        })
    }

    /// Keep a Python object alive for JavaScript; the index is what crosses.
    pub fn pin(&mut self, v: Value) -> u32 {
        if let Some(i) = self.js_pins.iter().position(|&p| p == v) {
            return i as u32;
        }
        if let Some(i) = self.js_pins.iter().position(|&p| p.is_undef()) {
            self.js_pins[i] = v;
            return i as u32;
        }
        self.js_pins.push(v);
        self.js_pins.len() as u32 - 1
    }
    pub fn unpin(&mut self, pin: u32) {
        if let Some(slot) = self.js_pins.get_mut(pin as usize) {
            *slot = Value::UNDEF;
        }
    }

    /// Call a JavaScript function handle with Python arguments.
    pub fn js_call(&mut self, func: u32, this: u32, args: &[Value]) -> PyResult {
        let hooks = self.js()?;
        let mut trees = Vec::new();
        let mut slots = Vec::with_capacity(args.len());
        for &a in args {
            slots.push(self.to_slot(a, &mut trees)?);
        }
        let r = (hooks.call)(self, func, this, &slots)?;
        self.from_slot(r)
    }
}
