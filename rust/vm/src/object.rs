//! Heap objects.
//!
//! Every Python value that does not fit in a `Value` is one of these, held in the heap's
//! arena and addressed by index. Strings are UTF-8 with their code-point length and an ASCII
//! flag cached; dicts keep insertion order by layout.

use crate::code::Code;
use crate::dict::PyDict;
use crate::value::Value;
use std::rc::Rc;

pub struct PyStr {
    pub s: Box<str>,
    pub hash: u64,
    pub chars: u32,
    pub ascii: bool,
}

impl PyStr {
    pub fn new(s: &str) -> PyStr {
        let ascii = s.is_ascii();
        let chars = if ascii { s.len() } else { s.chars().count() } as u32;
        PyStr { s: s.into(), hash: str_hash(s), chars, ascii }
    }
    pub fn from_string(s: String) -> PyStr {
        let ascii = s.is_ascii();
        let chars = if ascii { s.len() } else { s.chars().count() } as u32;
        let hash = str_hash(&s);
        PyStr { s: s.into_boxed_str(), hash, chars, ascii }
    }
    pub fn len(&self) -> usize {
        self.chars as usize
    }
    /// Byte offset of code point `i` (0 ≤ i ≤ len), O(1) for ASCII.
    pub fn byte_at(&self, i: usize) -> usize {
        if self.ascii {
            i
        } else {
            self.s.char_indices().nth(i).map(|(b, _)| b).unwrap_or(self.s.len())
        }
    }
    pub fn char_at(&self, i: usize) -> Option<char> {
        if self.ascii {
            self.s.as_bytes().get(i).map(|&b| b as char)
        } else {
            self.s.chars().nth(i)
        }
    }
    pub fn slice(&self, start: usize, end: usize) -> &str {
        let (b0, b1) = (self.byte_at(start), self.byte_at(end));
        &self.s[b0..b1]
    }
}

/// FNV-1a over the bytes; stable across runs, which the prerenderer's ids need.
pub fn str_hash(s: &str) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for &b in s.as_bytes() {
        h ^= b as u64;
        h = h.wrapping_mul(0x0100_0000_01b3);
    }
    h
}

pub type NativeFn = fn(&mut crate::vm::Vm, &[Value], &[(Value, Value)]) -> Result<Value, Value>;

pub struct Native {
    pub name: &'static str,
    pub f: NativeFn,
}

pub struct Func {
    pub code: Rc<Code>,
    /// The module's globals dict.
    pub globals: Value,
    pub defaults: Vec<Value>,
    pub kwdefaults: Vec<(Value, Value)>,
    /// Cell objects, in `code.freevars` order.
    pub closure: Vec<Value>,
    pub name: Value,
    pub qualname: Value,
    /// `__doc__`, a rewritten `__name__`, anything an app hangs on a function.
    pub attrs: Option<Box<PyDict>>,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Builtin {
    Object,
    Type,
    Int,
    Bool,
    Float,
    Str,
    Bytes,
    ByteArray,
    List,
    Tuple,
    Dict,
    Set,
    FrozenSet,
    NoneType,
    Function,
    Module,
    Range,
    Slice,
    Property,
    StaticMethod,
    ClassMethod,
    BaseException,
    Template,
    Interpolation,
    Generator,
    Coroutine,
    Cell,
    Iterator,
    NotImplementedType,
    EllipsisType,
}

pub struct Class {
    pub name: Value,
    pub bases: Vec<Value>,
    pub mro: Vec<Value>,
    pub dict: PyDict,
    pub builtin: Option<Builtin>,
    /// Bumped on every attribute change; inline caches key on it.
    pub version: u32,
    pub module: Value,
    /// MRO lookups already answered, `(name, attribute or UNDEF for a miss)`; valid while
    /// `cache_epoch` equals the VM's `class_epoch`.
    pub cache: core::cell::RefCell<[(Value, Value); 32]>,
    pub cache_epoch: core::cell::Cell<u32>,
}

/// The slot a name hashes to in a class's direct-mapped cache.
#[inline]
pub fn cache_slot(name: Value) -> usize {
    let i = name.0 as u32 as usize;
    (i ^ (i >> 5) ^ (i >> 10)) & 31
}

pub struct Instance {
    pub class: Value,
    pub dict: PyDict,
}

pub struct Module {
    pub name: Value,
    /// The globals: a dict object, so `globals()` hands out the real thing.
    pub dict: Value,
}

pub struct Exc {
    pub class: Value,
    pub args: Vec<Value>,
    /// `(code name, filename, line)` innermost last, as frames unwound.
    pub traceback: Vec<(Value, Value, u32)>,
    pub cause: Value,
    pub context: Value,
    pub suppress_context: bool,
    pub dict: PyDict,
}

pub enum Iter {
    List { list: Value, at: usize },
    Tuple { tuple: Value, at: usize },
    Str { s: Value, byte: usize },
    Bytes { b: Value, at: usize },
    Range { cur: i64, stop: i64, step: i64 },
    DictKeys { dict: Value, at: usize },
    DictValues { dict: Value, at: usize },
    DictItems { dict: Value, at: usize },
    Set { set: Value, at: usize },
    Enumerate { inner: Value, count: i64 },
    Zip { iters: Vec<Value> },
    Map { func: Value, iters: Vec<Value> },
    Filter { func: Value, inner: Value },
    Reversed { seq: Value, at: usize },
    /// `iter(callable, sentinel)`.
    Callable { func: Value, sentinel: Value },
    Done,
}

/// A suspended frame: a generator, a coroutine, or an async generator.
pub struct Generator {
    pub frame: Option<Box<crate::vm::Frame>>,
    pub running: bool,
    pub finished: bool,
    pub is_coroutine: bool,
    pub name: Value,
}

pub enum Obj {
    /// A swept slot, or one whose payload is temporarily taken out.
    Free,
    Str(PyStr),
    /// An int that does not fit the 32-bit payload.
    Int(i64),
    List(Vec<Value>),
    Tuple(Vec<Value>),
    Dict(PyDict),
    Set(PyDict),
    FrozenSet(PyDict),
    Bytes(Vec<u8>),
    ByteArray(Vec<u8>),
    Func(Box<Func>),
    Native(Native),
    Bound { func: Value, this: Value },
    Class(Box<Class>),
    Instance(Instance),
    Module(Module),
    Exc(Box<Exc>),
    Cell(Value),
    Range { start: i64, stop: i64, step: i64 },
    Slice { start: Value, stop: Value, step: Value },
    Property { get: Value, set: Value, del: Value },
    StaticMethod(Value),
    ClassMethod(Value),
    Iter(Iter),
    Generator(Generator),
    Template { strings: Value, interpolations: Value },
    Interpolation { value: Value, expression: Value, conversion: Value, format_spec: Value },
    Code(Rc<Code>),
    /// `super(cls, obj)`.
    Super { class: Value, this: Value },
    /// A JavaScript object, by handle in the host's table.
    Js(u32),
    NotImplemented,
    Ellipsis,
}

impl Obj {
    pub fn kind(&self) -> &'static str {
        match self {
            Obj::Free => "free",
            Obj::Str(_) => "str",
            Obj::Int(_) => "int",
            Obj::List(_) => "list",
            Obj::Tuple(_) => "tuple",
            Obj::Dict(_) => "dict",
            Obj::Set(_) => "set",
            Obj::FrozenSet(_) => "frozenset",
            Obj::Bytes(_) => "bytes",
            Obj::ByteArray(_) => "bytearray",
            Obj::Func(_) => "function",
            Obj::Native(_) => "builtin_function_or_method",
            Obj::Bound { .. } => "method",
            Obj::Class(_) => "type",
            Obj::Instance(_) => "object",
            Obj::Module(_) => "module",
            Obj::Exc(_) => "exception",
            Obj::Cell(_) => "cell",
            Obj::Range { .. } => "range",
            Obj::Slice { .. } => "slice",
            Obj::Property { .. } => "property",
            Obj::StaticMethod(_) => "staticmethod",
            Obj::ClassMethod(_) => "classmethod",
            Obj::Iter(_) => "iterator",
            Obj::Generator(g) => {
                if g.is_coroutine {
                    "coroutine"
                } else {
                    "generator"
                }
            }
            Obj::Template { .. } => "Template",
            Obj::Interpolation { .. } => "Interpolation",
            Obj::Code(_) => "code",
            Obj::Super { .. } => "super",
            Obj::Js(_) => "JsObject",
            Obj::NotImplemented => "NotImplementedType",
            Obj::Ellipsis => "ellipsis",
        }
    }

    /// Every value this object holds, for the collector.
    pub fn trace(&self, mut visit: impl FnMut(Value)) {
        match self {
            Obj::Free | Obj::Str(_) | Obj::Int(_) | Obj::Bytes(_) | Obj::ByteArray(_) | Obj::Native(_) => {}
            Obj::Range { .. } | Obj::Js(_) | Obj::NotImplemented | Obj::Ellipsis => {}
            Obj::List(v) | Obj::Tuple(v) => v.iter().for_each(|&x| visit(x)),
            Obj::Dict(d) | Obj::Set(d) | Obj::FrozenSet(d) => d.trace(&mut visit),
            Obj::Func(f) => {
                visit(f.globals);
                visit(f.name);
                visit(f.qualname);
                f.defaults.iter().for_each(|&x| visit(x));
                f.kwdefaults.iter().for_each(|&(k, v)| {
                    visit(k);
                    visit(v)
                });
                f.closure.iter().for_each(|&x| visit(x));
                if let Some(a) = &f.attrs {
                    a.trace(&mut visit);
                }
                trace_code(&f.code, &mut visit);
            }
            Obj::Bound { func, this } | Obj::Super { class: func, this } => {
                visit(*func);
                visit(*this)
            }
            Obj::Class(c) => {
                visit(c.name);
                visit(c.module);
                c.bases.iter().for_each(|&x| visit(x));
                c.mro.iter().for_each(|&x| visit(x));
                c.dict.trace(&mut visit);
                // the cache holds attributes that are also in some MRO dict, so it roots nothing new
            }
            Obj::Instance(i) => {
                visit(i.class);
                i.dict.trace(&mut visit);
            }
            Obj::Module(m) => {
                visit(m.name);
                visit(m.dict);
            }
            Obj::Exc(e) => {
                visit(e.class);
                visit(e.cause);
                visit(e.context);
                e.args.iter().for_each(|&x| visit(x));
                e.traceback.iter().for_each(|&(n, f, _)| {
                    visit(n);
                    visit(f)
                });
                e.dict.trace(&mut visit);
            }
            Obj::Cell(v) => visit(*v),
            Obj::Slice { start, stop, step } => {
                visit(*start);
                visit(*stop);
                visit(*step)
            }
            Obj::Property { get, set, del } => {
                visit(*get);
                visit(*set);
                visit(*del)
            }
            Obj::StaticMethod(v) | Obj::ClassMethod(v) => visit(*v),
            Obj::Iter(it) => match it {
                Iter::List { list: v, .. }
                | Iter::Tuple { tuple: v, .. }
                | Iter::Str { s: v, .. }
                | Iter::Bytes { b: v, .. }
                | Iter::DictKeys { dict: v, .. }
                | Iter::DictValues { dict: v, .. }
                | Iter::DictItems { dict: v, .. }
                | Iter::Set { set: v, .. }
                | Iter::Reversed { seq: v, .. } => visit(*v),
                Iter::Enumerate { inner, .. } => visit(*inner),
                Iter::Zip { iters } => iters.iter().for_each(|&x| visit(x)),
                Iter::Map { func, iters } => {
                    visit(*func);
                    iters.iter().for_each(|&x| visit(x))
                }
                Iter::Filter { func, inner } => {
                    visit(*func);
                    visit(*inner)
                }
                Iter::Callable { func, sentinel } => {
                    visit(*func);
                    visit(*sentinel)
                }
                Iter::Range { .. } | Iter::Done => {}
            },
            Obj::Generator(g) => {
                visit(g.name);
                if let Some(f) = &g.frame {
                    f.trace(&mut visit);
                }
            }
            Obj::Template { strings, interpolations } => {
                visit(*strings);
                visit(*interpolations)
            }
            Obj::Interpolation { value, expression, conversion, format_spec } => {
                visit(*value);
                visit(*expression);
                visit(*conversion);
                visit(*format_spec)
            }
            Obj::Code(c) => trace_code(c, &mut visit),
        }
    }
}

pub fn trace_code(code: &Code, visit: &mut impl FnMut(Value)) {
    code.consts.iter().for_each(|&x| visit(x));
    code.names.iter().for_each(|&x| visit(x));
    code.varnames.iter().for_each(|&x| visit(x));
    code.cellvars.iter().for_each(|&x| visit(x));
    code.freevars.iter().for_each(|&x| visit(x));
    for n in &code.nested {
        trace_code(n, visit);
    }
}
