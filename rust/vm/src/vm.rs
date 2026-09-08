//! The virtual machine: frames, the bytecode loop, calls, exceptions, generators, imports.
//!
//! Errors are values: every operation returns `Result<_, Value>` where the `Err` is the
//! exception object. A raise unwinds through handler tables; nothing is `setjmp`. Python
//! calling Python pushes a frame and stays in the same loop; native code calling Python
//! runs a nested loop until that frame returns.
//!
//! One value stack serves every frame: a frame's locals are a window of it and its operand
//! stack grows above them, so a call allocates nothing, and a positional call's arguments
//! are already in place when the callee starts. A suspended generator keeps its window in
//! its own vector and puts it back on resume.

use crate::code::*;
use crate::dict::PyDict;
use crate::heap::Heap;
use crate::host::Host;
use crate::object::*;
use crate::value::Value;
use std::collections::HashMap;
use std::rc::Rc;

pub type PyResult<T = Value> = Result<T, Value>;
pub type CompileFn = fn(&mut Vm, &str, &str) -> Result<Rc<Code>, String>;

pub struct Frame {
    pub code: Rc<Code>,
    pub pc: u32,
    /// Where the locals start on the shared stack.
    pub base: usize,
    /// Where the operand stack starts: `base + nlocals`.
    pub sp0: usize,
    pub cells: Vec<Value>,
    /// The module's dict.
    pub globals: Value,
    /// The namespace dict of a module or class body; `UNDEF` in a function.
    pub namespace: Value,
    pub func: Value,
    pub handling_base: usize,
    /// A suspended generator's locals and operand stack.
    pub saved: Vec<Value>,
    /// Stack slots below `base` that belong to this call (the callee, for an in-place call).
    pub below: usize,
    /// A class call's `__init__` frame: the return value is local 0, the instance.
    pub returns_self: bool,
}

impl Frame {
    /// The values a frame owns outside the shared stack (a suspended one owns its window).
    pub fn trace(&self, visit: &mut impl FnMut(Value)) {
        self.cells.iter().for_each(|&v| visit(v));
        self.saved.iter().for_each(|&v| visit(v));
        visit(self.globals);
        visit(self.namespace);
        visit(self.func);
        trace_code(&self.code, visit);
    }
    pub fn line(&self) -> u32 {
        self.code.line_at(self.pc.saturating_sub(1))
    }
}

pub enum Exit {
    Return(Value),
    Yield(Value, Box<Frame>),
}

/// The builtin classes, by field.
#[derive(Default)]
pub struct Types {
    pub object: Value,
    pub type_: Value,
    pub int: Value,
    pub bool_: Value,
    pub float: Value,
    pub str_: Value,
    pub bytes: Value,
    pub bytearray: Value,
    pub list: Value,
    pub tuple: Value,
    pub dict: Value,
    pub set: Value,
    pub frozenset: Value,
    pub none_type: Value,
    pub function: Value,
    pub module: Value,
    pub range: Value,
    pub slice: Value,
    pub property: Value,
    pub staticmethod: Value,
    pub classmethod: Value,
    pub generator: Value,
    pub coroutine: Value,
    pub template: Value,
    pub interpolation: Value,
    pub iterator: Value,
    pub cell: Value,
    pub not_implemented_type: Value,
    pub ellipsis_type: Value,
    pub code: Value,
    pub js_object: Value,
    pub super_: Value,
    pub builtin_function: Value,
    pub method: Value,
    // exceptions
    pub base_exception: Value,
    pub exception: Value,
    pub type_error: Value,
    pub value_error: Value,
    pub key_error: Value,
    pub index_error: Value,
    pub attribute_error: Value,
    pub runtime_error: Value,
    pub not_implemented_error: Value,
    pub stop_iteration: Value,
    pub stop_async_iteration: Value,
    pub zero_division_error: Value,
    pub arithmetic_error: Value,
    pub lookup_error: Value,
    pub name_error: Value,
    pub unbound_local_error: Value,
    pub import_error: Value,
    pub module_not_found_error: Value,
    pub assertion_error: Value,
    pub overflow_error: Value,
    pub os_error: Value,
    pub unicode_error: Value,
    pub recursion_error: Value,
    pub timeout_error: Value,
    pub generator_exit: Value,
    pub syntax_error: Value,
    pub cancelled_error: Value,
    pub keyboard_interrupt: Value,
    pub system_exit: Value,
    pub warning: Value,
    pub deprecation_warning: Value,
    pub user_warning: Value,
}

macro_rules! names {
    ($($field:ident = $text:expr),* $(,)?) => {
        #[derive(Default)]
        pub struct Names { $(pub $field: Value,)* }
        impl Names {
            fn fill(vm: &mut Vm) {
                $( let v = vm.intern($text); vm.n.$field = v; )*
            }
        }
    };
}

names! {
    init = "__init__", new = "__new__", call = "__call__", getattr = "__getattr__",
    getattribute = "__getattribute__", setattr = "__setattr__", delattr = "__delattr__",
    repr = "__repr__", str_ = "__str__", format = "__format__", eq = "__eq__", ne = "__ne__",
    lt = "__lt__", le = "__le__", gt = "__gt__", ge = "__ge__", hash = "__hash__",
    bool_ = "__bool__", len = "__len__", getitem = "__getitem__", setitem = "__setitem__",
    delitem = "__delitem__", contains = "__contains__", iter = "__iter__", next = "__next__",
    reversed = "__reversed__", enter = "__enter__", exit = "__exit__", aenter = "__aenter__",
    aexit = "__aexit__", await_ = "__await__", aiter = "__aiter__", anext = "__anext__",
    add = "__add__", radd = "__radd__", sub = "__sub__", rsub = "__rsub__", mul = "__mul__",
    rmul = "__rmul__", truediv = "__truediv__", rtruediv = "__rtruediv__", floordiv = "__floordiv__",
    rfloordiv = "__rfloordiv__", mod_ = "__mod__", rmod = "__rmod__", pow = "__pow__", rpow = "__rpow__",
    matmul = "__matmul__", neg = "__neg__", pos = "__pos__", invert = "__invert__", and = "__and__",
    rand = "__rand__", or = "__or__", ror = "__ror__", xor = "__xor__", rxor = "__rxor__",
    lshift = "__lshift__", rshift = "__rshift__", iadd = "__iadd__", isub = "__isub__", imul = "__imul__",
    ior = "__ior__", iand = "__iand__", index = "__index__", int_ = "__int__", float_ = "__float__",
    missing = "__missing__", name = "__name__", qualname = "__qualname__", module = "__module__",
    doc = "__doc__", class = "__class__", dict = "__dict__", classcell = "__classcell__",
    mro = "__mro__", bases = "__bases__", package = "__package__", file = "__file__",
    all = "__all__", slots = "__slots__", path = "__path__", builtins = "__builtins__",
    traceback = "__traceback__", cause = "__cause__", context = "__context__",
    suppress_context = "__suppress_context__", self_ = "__self__", func = "__func__",
    code = "__code__", defaults = "__defaults__", closure = "__closure__", globals = "__globals__",
    wrapped = "__wrapped__", main = "__main__", args = "args", keys = "keys", get = "get",
    send = "send", throw = "throw", close = "close", value = "value", strings = "strings",
    interpolations = "interpolations", expression = "expression", conversion = "conversion",
    format_spec = "format_spec", start = "start", stop = "stop", step = "step", fget = "fget",
    fset = "fset", setter = "setter", getter = "getter", deleter = "deleter", spec = "__spec__",
    loader = "__loader__", empty = "", object_ = "object", set_name = "__set_name__",
    init_subclass = "__init_subclass__", with_traceback = "with_traceback",
    class_getitem = "__class_getitem__", init_module = "__init__.py",
}

pub struct Vm {
    pub heap: Heap,
    pub host: Box<dyn Host>,
    pub frames: Vec<Frame>,
    /// The one value stack: every live frame's locals and operands.
    pub stack: Vec<Value>,
    interned: HashMap<Box<str>, Value>,
    /// `sys.modules`, a real dict.
    pub modules: Value,
    /// The `builtins` module's dict.
    pub builtins: Value,
    pub t: Types,
    pub n: Names,
    /// Exceptions being handled, innermost last.
    pub handling: Vec<Value>,
    /// Temporary roots for native code that calls back into Python.
    pub roots: Vec<Value>,
    pub compiler: Option<CompileFn>,
    pub builtin_modules: HashMap<&'static str, fn(&mut Vm) -> PyResult<Value>>,
    pub depth: u32,
    pub max_depth: u32,
    /// Python objects JavaScript holds, by pin.
    pub js_pins: Vec<Value>,
    /// The value a finished sub-iterator returned to `YieldFrom`.
    pub delegate_result: Value,
    /// The name a Python-source builtin module is being loaded under.
    pub pending_module: Option<String>,
    /// Scratch for `keys.rs`: which container kind was taken out of the heap.
    pub map_kind: u8,
    /// `sys.argv`.
    pub argv: Vec<String>,
    /// The JavaScript bridge, when there is one (the browser build installs it).
    pub js_hooks: Option<&'static crate::jshooks::JsHooks>,
    /// True in the browser: `asyncio.run` schedules and returns; the glue pumps the loop.
    pub browser: bool,
    /// Bumped whenever any class attribute changes; class-level lookups cache on it.
    pub class_epoch: u32,
    /// The sampling profiler, on while `Some`: `_frontage.profile_start()`.
    pub prof: Option<Box<Profile>>,
    /// Closing unreachable generators after a collection; not re-entered.
    pub finalizing: bool,
    /// The reactive graph's module state (`core.rs`).
    pub core: crate::core::Core,
    /// The DOM op stream (`dom.rs`).
    pub dom: crate::dom::DomStream,
    /// The view layer's native state (`view.rs`).
    pub view: crate::view::ViewState,
    /// Some class overrides `__getattribute__`: instance lookups must check for it.
    pub getattribute_overridden: bool,
}

impl Vm {
    pub fn new(host: Box<dyn Host>) -> Vm {
        let mut vm = Vm {
            heap: Heap::new(),
            host,
            frames: Vec::with_capacity(64),
            stack: Vec::with_capacity(4096),
            interned: HashMap::with_capacity(1024),
            modules: Value::UNDEF,
            builtins: Value::UNDEF,
            t: Types::default(),
            n: Names::default(),
            handling: Vec::new(),
            roots: Vec::new(),
            compiler: None,
            builtin_modules: HashMap::new(),
            depth: 0,
            max_depth: 600,
            js_pins: Vec::new(),
            delegate_result: Value::NONE,
            pending_module: None,
            map_kind: 0,
            argv: Vec::new(),
            js_hooks: None,
            browser: false,
            class_epoch: 1,
            prof: None,
            finalizing: false,
            core: crate::core::Core::new(),
            dom: crate::dom::DomStream::new(),
            view: Default::default(),
            getattribute_overridden: false,
        };
        Names::fill(&mut vm);
        vm.modules = vm.heap.alloc_pinned(Obj::Dict(PyDict::new()));
        crate::builtins::install(&mut vm);
        crate::modules::install(&mut vm);
        vm
    }

    // -- allocation and interning ------------------------------------------------------

    pub fn interned_ref(&self) -> &HashMap<Box<str>, Value> {
        &self.interned
    }
    pub fn intern(&mut self, s: &str) -> Value {
        if let Some(&v) = self.interned.get(s) {
            return v;
        }
        let v = self.heap.alloc_pinned(Obj::Str(PyStr::new(s)));
        self.interned.insert(s.into(), v);
        v
    }
    pub fn str(&mut self, s: &str) -> Value {
        if s.len() <= 1 {
            return self.intern(s);
        }
        self.heap.alloc(Obj::Str(PyStr::new(s)))
    }
    pub fn string(&mut self, s: String) -> Value {
        if s.len() <= 1 {
            return self.intern(&s);
        }
        self.heap.alloc(Obj::Str(PyStr::from_string(s)))
    }
    pub fn int(&mut self, i: i64) -> Value {
        if i >= i32::MIN as i64 && i <= i32::MAX as i64 {
            Value::int(i as i32)
        } else {
            self.heap.alloc(Obj::Int(i))
        }
    }
    pub fn list(&mut self, items: Vec<Value>) -> Value {
        self.heap.alloc(Obj::List(items))
    }
    pub fn tuple(&mut self, items: Vec<Value>) -> Value {
        self.heap.alloc(Obj::Tuple(items))
    }
    pub fn dict(&mut self, d: PyDict) -> Value {
        self.heap.alloc(Obj::Dict(d))
    }
    pub fn native(&mut self, name: &'static str, f: NativeFn) -> Value {
        self.heap.alloc_pinned(Obj::Native(Native { name, f }))
    }
    pub fn bound(&mut self, func: Value, this: Value) -> Value {
        self.heap.alloc(Obj::Bound { func, this })
    }
    pub fn cell(&mut self, v: Value) -> Value {
        self.heap.alloc(Obj::Cell(v))
    }

    /// The `str` behind a value, if it is one.
    pub fn as_str(&self, v: Value) -> Option<&str> {
        if !v.is_obj() {
            return None;
        }
        match self.heap.get(v) {
            Obj::Str(s) => Some(&s.s),
            _ => None,
        }
    }
    pub fn expect_str(&mut self, v: Value, what: &str) -> PyResult<String> {
        match self.as_str(v) {
            Some(s) => Ok(s.to_string()),
            None => {
                let t = self.type_name(v);
                Err(self.type_error(format!("{what} must be str, not {t}")))
            }
        }
    }
    /// An int as i64 (bools count), or None.
    pub fn as_i64(&self, v: Value) -> Option<i64> {
        if v.is_int() {
            Some(v.as_int() as i64)
        } else if v.is_bool() {
            Some(v.as_bool() as i64)
        } else if v.is_obj() {
            match self.heap.get(v) {
                Obj::Int(i) => Some(*i),
                _ => None,
            }
        } else {
            None
        }
    }
    pub fn expect_int(&mut self, v: Value, what: &str) -> PyResult<i64> {
        match self.as_i64(v) {
            Some(i) => Ok(i),
            None => {
                if let Some(idx) = self.index_of(v)? {
                    return Ok(idx);
                }
                let t = self.type_name(v);
                Err(self.type_error(format!("{what} must be an integer, not {t}")))
            }
        }
    }
    /// `__index__` on an instance, else None.
    pub fn index_of(&mut self, v: Value) -> PyResult<Option<i64>> {
        if v.is_obj() && matches!(self.heap.get(v), Obj::Instance(_)) {
            let name = self.n.index;
            if let Some(m) = self.lookup_method(v, name) {
                let r = self.call(m, &[v], &[])?;
                return Ok(self.as_i64(r));
            }
        }
        Ok(None)
    }
    pub fn as_f64(&self, v: Value) -> Option<f64> {
        if v.is_float() {
            Some(v.as_float())
        } else {
            self.as_i64(v).map(|i| i as f64)
        }
    }

    // -- errors --------------------------------------------------------------------------

    pub fn exception(&mut self, class: Value, msg: impl Into<String>) -> Value {
        let msg: String = msg.into();
        let args = if msg.is_empty() { vec![] } else { vec![self.string(msg)] };
        self.heap.alloc(Obj::Exc(Box::new(Exc {
            class,
            args,
            traceback: Vec::new(),
            cause: Value::NONE,
            context: Value::NONE,
            suppress_context: false,
            dict: PyDict::new(),
        })))
    }
    pub fn type_error(&mut self, msg: impl Into<String>) -> Value {
        let c = self.t.type_error;
        self.exception(c, msg)
    }
    pub fn value_error(&mut self, msg: impl Into<String>) -> Value {
        let c = self.t.value_error;
        self.exception(c, msg)
    }
    pub fn attribute_error(&mut self, msg: impl Into<String>) -> Value {
        let c = self.t.attribute_error;
        self.exception(c, msg)
    }
    pub fn index_error(&mut self, msg: impl Into<String>) -> Value {
        let c = self.t.index_error;
        self.exception(c, msg)
    }
    pub fn key_error(&mut self, key: Value) -> Value {
        let c = self.t.key_error;
        let e = self.exception(c, "");
        if let Obj::Exc(x) = self.heap.get_mut(e) {
            x.args = vec![key];
        }
        e
    }
    pub fn name_error(&mut self, name: Value) -> Value {
        let s = self.as_str(name).unwrap_or("?").to_string();
        let c = self.t.name_error;
        self.exception(c, format!("name '{s}' is not defined"))
    }
    pub fn runtime_error(&mut self, msg: impl Into<String>) -> Value {
        let c = self.t.runtime_error;
        self.exception(c, msg)
    }
    pub fn zero_division(&mut self, msg: &str) -> Value {
        let c = self.t.zero_division_error;
        self.exception(c, msg)
    }
    pub fn overflow_error(&mut self, msg: &str) -> Value {
        let c = self.t.overflow_error;
        self.exception(c, msg)
    }
    pub fn stop_iteration(&mut self, value: Value) -> Value {
        let c = self.t.stop_iteration;
        let e = self.exception(c, "");
        if !value.is_none() {
            if let Obj::Exc(x) = self.heap.get_mut(e) {
                x.args = vec![value];
            }
        }
        e
    }
    pub fn not_implemented_error(&mut self, msg: impl Into<String>) -> Value {
        let c = self.t.not_implemented_error;
        self.exception(c, msg)
    }
    pub fn import_error(&mut self, msg: impl Into<String>) -> Value {
        let c = self.t.module_not_found_error;
        self.exception(c, msg)
    }

    pub fn is_exception(&self, v: Value) -> bool {
        v.is_obj() && matches!(self.heap.get(v), Obj::Exc(_))
    }
    /// `isinstance(exc, class)` for an exception object against a class or a tuple of classes.
    pub fn exc_matches(&self, exc: Value, class: Value) -> bool {
        let exc_class = match self.heap.get(exc) {
            Obj::Exc(e) => e.class,
            _ => return false,
        };
        self.class_matches(exc_class, class)
    }
    pub fn class_matches(&self, cls: Value, target: Value) -> bool {
        match self.heap.get(target) {
            Obj::Tuple(items) => items.iter().any(|&t| self.class_matches(cls, t)),
            Obj::Class(_) => self.is_subclass(cls, target),
            _ => false,
        }
    }
    pub fn is_subclass(&self, cls: Value, base: Value) -> bool {
        if cls == base {
            return true;
        }
        match self.heap.get(cls) {
            Obj::Class(c) => c.mro.iter().any(|&m| m == base),
            _ => false,
        }
    }

    // -- roots and collection -------------------------------------------------------------

    #[inline]
    pub fn maybe_collect(&mut self) {
        if !self.heap.should_collect() {
            return;
        }
        self.collect();
    }
    pub fn collect(&mut self) -> usize {
        let mut roots: Vec<Value> = Vec::with_capacity(self.stack.len() + 1024);
        roots.extend(self.stack.iter().copied());
        for f in &self.frames {
            f.trace(&mut |v| roots.push(v));
        }
        roots.push(self.modules);
        roots.push(self.builtins);
        roots.extend(self.handling.iter().copied());
        roots.extend(self.roots.iter().copied());
        roots.extend(self.js_pins.iter().copied());
        self.core.trace(&mut |v| roots.push(v));
        self.view.trace(&mut |v| roots.push(v));
        let (freed, doomed) = self.heap.collect(roots);
        // Generators nobody reaches: `close()` each, so its `finally` runs, as CPython does
        // when the last reference goes. They are freed at the next collection.
        if !doomed.is_empty() && !self.finalizing {
            self.finalizing = true;
            for g in doomed {
                if let Err(e) = crate::builtins::generator_close(self, g) {
                    let text = self.format_exception(e);
                    self.host.write_stderr(&format!("Exception ignored while closing a generator:\n{text}"));
                }
            }
            self.finalizing = false;
        }
        if !self.heap.freed_js.is_empty() {
            let handles = core::mem::take(&mut self.heap.freed_js);
            if let Some(h) = self.js_hooks {
                (h.release)(&handles);
            }
        }
        freed
    }

    // -- frames and calls ----------------------------------------------------------------------

    /// Push a frame for `func` with `args`/`kwargs` bound: the locals go onto the shared
    /// stack, starting at `stack.len()`. On an error nothing is left on the stack.
    pub fn bind(&mut self, func: Value, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult<Frame> {
        let base = self.stack.len();
        self.stack.extend_from_slice(args);
        match self.bind_in_place(func, base, kwargs) {
            Ok(f) => Ok(f),
            Err(e) => {
                self.stack.truncate(base);
                Err(e)
            }
        }
    }

    /// Bind with the positional arguments already on the stack at `base..`.
    fn bind_in_place(&mut self, func: Value, base: usize, kwargs: &[(Value, Value)]) -> PyResult<Frame> {
        let (code, globals) = match self.heap.get(func) {
            Obj::Func(f) => (f.code.clone(), f.globals),
            _ => return Err(self.type_error("not a Python function")),
        };
        let nargs = self.stack.len() - base;
        let argcount = code.argcount as usize;
        let kwonly = code.kwonlyargcount as usize;
        let nlocals = code.nlocals();
        let simple = kwargs.is_empty() && code.flags & (FLAG_VARARGS | FLAG_VARKW) == 0;
        if simple && nargs == argcount && kwonly == 0 {
            // The common case: every parameter supplied, nothing to shuffle.
            self.stack.resize(base + nlocals, Value::UNDEF);
        } else {
            self.bind_general(func, &code, base, nargs, kwargs)?;
        }
        // Cells: cellvars (fresh, seeded from a parameter when one is captured), then freevars.
        let mut cells = Vec::new();
        if !code.cellvars.is_empty() || !code.freevars.is_empty() {
            cells.reserve(code.cellvars.len() + code.freevars.len());
            for ci in 0..code.cellvars.len() {
                let seed = code.cell_of_local.iter().find(|(_, c)| *c as usize == ci).map(|(l, _)| self.stack[base + *l as usize]).unwrap_or(Value::UNDEF);
                cells.push(self.cell(seed));
            }
            if let Obj::Func(f) = self.heap.get(func) {
                cells.extend(f.closure.iter().copied());
            }
        }
        Ok(Frame { sp0: base + nlocals, code, pc: 0, base, cells, globals, namespace: Value::UNDEF, func, handling_base: self.handling.len(), saved: Vec::new(), below: 0, returns_self: false })
    }

    fn bind_general(&mut self, func: Value, code: &Rc<Code>, base: usize, nargs: usize, kwargs: &[(Value, Value)]) -> PyResult<()> {
        let argcount = code.argcount as usize;
        let kwonly = code.kwonlyargcount as usize;
        let posonly = code.posonlyargcount as usize;
        let (ndefaults, has_kwdefaults) = match self.heap.get(func) {
            Obj::Func(f) => (f.defaults.len(), !f.kwdefaults.is_empty()),
            _ => (0, false),
        };
        let mut locals = vec![Value::UNDEF; code.nlocals()];
        let nfixed = nargs.min(argcount);
        locals[..nfixed].copy_from_slice(&self.stack[base..base + nfixed]);
        let mut slot = argcount + kwonly;
        if nargs > argcount {
            if code.flags & FLAG_VARARGS != 0 {
                let extra = self.stack[base + argcount..base + nargs].to_vec();
                locals[slot] = self.tuple(extra);
            } else {
                let name = code.name.clone();
                return Err(self.type_error(format!(
                    "{}() takes {} positional argument{} but {} were given",
                    name,
                    argcount,
                    if argcount == 1 { "" } else { "s" },
                    nargs
                )));
            }
        }
        if code.flags & FLAG_VARARGS != 0 {
            if locals[slot].is_undef() {
                locals[slot] = self.tuple(Vec::new());
            }
            slot += 1;
        }
        let mut varkw: Option<PyDict> = if code.flags & FLAG_VARKW != 0 { Some(PyDict::new()) } else { None };
        for &(k, v) in kwargs {
            let mut found = None;
            for i in posonly..argcount + kwonly {
                if code.varnames[i] == k || self.as_str(code.varnames[i]) == self.as_str(k) {
                    found = Some(i);
                    break;
                }
            }
            match found {
                Some(i) => {
                    if !locals[i].is_undef() {
                        let name = self.as_str(k).unwrap_or("?").to_string();
                        return Err(self.type_error(format!("{}() got multiple values for argument '{}'", code.name, name)));
                    }
                    locals[i] = v;
                }
                None => match &mut varkw {
                    Some(d) => {
                        d.set(&self.heap, k, v);
                    }
                    None => {
                        let name = self.as_str(k).unwrap_or("?").to_string();
                        return Err(self.type_error(format!("{}() got an unexpected keyword argument '{}'", code.name, name)));
                    }
                },
            }
        }
        if let Some(d) = varkw {
            locals[slot] = self.dict(d);
        }
        for i in 0..argcount {
            if locals[i].is_undef() {
                let from_end = argcount - i;
                if from_end <= ndefaults {
                    if let Obj::Func(f) = self.heap.get(func) {
                        locals[i] = f.defaults[ndefaults - from_end];
                    }
                } else {
                    let name = self.as_str(code.varnames[i]).unwrap_or("?").to_string();
                    return Err(self.type_error(format!("{}() missing required positional argument: '{}'", code.name, name)));
                }
            }
        }
        for i in argcount..argcount + kwonly {
            if locals[i].is_undef() {
                let mut found = Value::UNDEF;
                if has_kwdefaults {
                    if let Obj::Func(f) = self.heap.get(func) {
                        let target = self.as_str(code.varnames[i]);
                        for &(k, v) in &f.kwdefaults {
                            if self.as_str(k) == target {
                                found = v;
                            }
                        }
                    }
                }
                if found.is_undef() {
                    let name = self.as_str(code.varnames[i]).unwrap_or("?").to_string();
                    return Err(self.type_error(format!("{}() missing required keyword-only argument: '{}'", code.name, name)));
                }
                locals[i] = found;
            }
        }
        self.stack.truncate(base);
        self.stack.extend_from_slice(&locals);
        Ok(())
    }

    /// Call anything callable, from native code: runs a nested loop for Python functions.
    pub fn call(&mut self, callee: Value, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
        if !callee.is_obj() {
            let t = self.type_name(callee);
            return Err(self.type_error(format!("'{t}' object is not callable")));
        }
        match self.heap.get(callee) {
            Obj::Func(f) => {
                if f.code.is_generator() {
                    let frame = self.bind(callee, args, kwargs)?;
                    return Ok(self.suspend_new(frame, callee));
                }
                let frame = self.bind(callee, args, kwargs)?;
                self.run_nested(frame)
            }
            Obj::Native(n) => {
                let f = n.f;
                f(self, args, kwargs)
            }
            Obj::Bound { func, this } => {
                let (func, this) = (*func, *this);
                if let Some(fh) = self.js_handle(func) {
                    let th = self.js_handle(this).unwrap_or(crate::jshooks::UNDEFINED_HANDLE);
                    return self.js_call(fh, th, args);
                }
                let mut all = Vec::with_capacity(args.len() + 1);
                all.push(this);
                all.extend_from_slice(args);
                self.call(func, &all, kwargs)
            }
            Obj::Js(h) => {
                let h = *h;
                self.js_call(h, crate::jshooks::UNDEFINED_HANDLE, args)
            }
            Obj::Class(_) => self.construct(callee, args, kwargs),
            Obj::Node(_) => {
                if args.is_empty() && kwargs.is_empty() {
                    return crate::core::node_call(self, callee);
                }
                let name = self.n.call;
                let m = self.get_attr(callee, name)?;
                self.call(m, args, kwargs)
            }
            Obj::Instance(_) => {
                let name = self.n.call;
                match self.lookup_method(callee, name) {
                    Some(m) => {
                        let mut all = Vec::with_capacity(args.len() + 1);
                        all.push(callee);
                        all.extend_from_slice(args);
                        self.call(m, &all, kwargs)
                    }
                    None => {
                        let t = self.type_name(callee);
                        Err(self.type_error(format!("'{t}' object is not callable")))
                    }
                }
            }
            Obj::StaticMethod(f) => {
                let f = *f;
                self.call(f, args, kwargs)
            }
            _ => {
                let t = self.type_name(callee);
                Err(self.type_error(format!("'{t}' object is not callable")))
            }
        }
    }

    pub fn call0(&mut self, callee: Value) -> PyResult {
        self.call(callee, &[], &[])
    }
    pub fn call1(&mut self, callee: Value, a: Value) -> PyResult {
        self.call(callee, &[a], &[])
    }

    fn run_nested(&mut self, frame: Frame) -> PyResult {
        if self.depth >= self.max_depth {
            self.stack.truncate(frame.base);
            let c = self.t.recursion_error;
            return Err(self.exception(c, "maximum recursion depth exceeded"));
        }
        self.depth += 1;
        self.frames.push(frame);
        let r = self.run_frame();
        self.depth -= 1;
        match r? {
            Exit::Return(v) => Ok(v),
            Exit::Yield(..) => Err(self.runtime_error("yield outside a generator frame")),
        }
    }

    /// Run a module or class body: `code` with a namespace dict.
    pub fn run_code(&mut self, code: Rc<Code>, globals: Value, namespace: Value) -> PyResult {
        let base = self.stack.len();
        let nlocals = code.nlocals();
        self.stack.resize(base + nlocals, Value::UNDEF);
        let cells = (0..code.cellvars.len()).map(|_| self.cell(Value::UNDEF)).collect();
        let frame = Frame { sp0: base + nlocals, code, pc: 0, base, cells, globals, namespace, func: Value::UNDEF, handling_base: self.handling.len(), saved: Vec::new(), below: 0, returns_self: false };
        self.run_nested(frame)
    }

    /// Run a function's body with a namespace dict (a class body).
    pub fn run_function_with_namespace(&mut self, func: Value, namespace: Value) -> PyResult {
        let mut frame = self.bind(func, &[], &[])?;
        frame.namespace = namespace;
        self.run_nested(frame)
    }

    /// A fresh generator: the frame comes off the stack into its own window.
    fn suspend_new(&mut self, mut frame: Frame, func: Value) -> Value {
        frame.saved = self.stack.split_off(frame.base);
        let (is_coroutine, name) = match self.heap.get(func) {
            Obj::Func(f) => (f.code.flags & FLAG_COROUTINE != 0, f.name),
            _ => (false, Value::NONE),
        };
        self.heap.alloc(Obj::Generator(Generator { frame: Some(Box::new(frame)), running: false, finished: false, is_coroutine, name }))
    }

    /// Resume a generator with `sent` (or an exception to throw); `Ok(Some(v))` on a yield,
    /// `Ok(None)` when it returns (the return value goes to `ret`).
    pub fn gen_resume(&mut self, gen: Value, sent: Value, throw: Option<Value>, ret: &mut Value) -> PyResult<Option<Value>> {
        let frame = match self.heap.get_mut(gen) {
            Obj::Generator(g) => {
                if g.running {
                    return Err(self.value_error("generator already executing"));
                }
                if g.finished {
                    if let Some(exc) = throw {
                        return Err(exc);
                    }
                    *ret = Value::NONE;
                    return Ok(None);
                }
                let f = g.frame.take().expect("generator without a frame");
                g.running = true;
                f
            }
            _ => return Err(self.type_error("not a generator")),
        };
        let mut frame = *frame;
        let first = frame.pc == 0;
        if first && throw.is_none() && !sent.is_none() {
            if let Obj::Generator(g) = self.heap.get_mut(gen) {
                g.running = false;
                g.frame = Some(Box::new(frame));
            }
            return Err(self.type_error("can't send non-None value to a just-started generator"));
        }
        // Put the window back on the shared stack.
        let base = self.stack.len();
        let shift = base as isize - frame.base as isize;
        let saved = core::mem::take(&mut frame.saved);
        self.stack.extend_from_slice(&saved);
        frame.base = base;
        frame.sp0 = (frame.sp0 as isize + shift) as usize;
        frame.handling_base = self.handling.len();
        if throw.is_none() && !first {
            self.stack.push(sent);
        }
        self.depth += 1;
        self.frames.push(frame);
        let base_frames = self.frames.len();
        let r = match throw {
            Some(exc) => match self.unwind(exc, base_frames) {
                Ok(()) => self.run_frame_from(base_frames),
                Err(e) => Err(e),
            },
            None => self.run_frame_from(base_frames),
        };
        self.depth -= 1;
        self.gen_finish(gen, r, ret)
    }

    fn gen_finish(&mut self, gen: Value, r: PyResult<Exit>, ret: &mut Value) -> PyResult<Option<Value>> {
        match r {
            Ok(Exit::Yield(v, frame)) => {
                if let Obj::Generator(g) = self.heap.get_mut(gen) {
                    g.running = false;
                    g.frame = Some(frame);
                }
                Ok(Some(v))
            }
            Ok(Exit::Return(v)) => {
                if let Obj::Generator(g) = self.heap.get_mut(gen) {
                    g.running = false;
                    g.finished = true;
                }
                *ret = v;
                Ok(None)
            }
            Err(e) => {
                if let Obj::Generator(g) = self.heap.get_mut(gen) {
                    g.running = false;
                    g.finished = true;
                }
                Err(e)
            }
        }
    }

    // -- the loop -------------------------------------------------------------------------------

    /// Run the top frame until it returns or yields.
    pub fn run_frame(&mut self) -> PyResult<Exit> {
        let base = self.frames.len();
        self.run_frame_from(base)
    }

    /// One instruction under the profiler: every 64th, the time since the last sample goes to
    /// the running code (exclusive) and to every code on the frame stack (inclusive).
    #[inline(never)]
    fn profile_tick(&mut self, top: *const Code) {
        let now_needed = {
            let p = self.prof.as_mut().unwrap();
            p.counter = p.counter.wrapping_add(1);
            p.counter & 63 == 0
        };
        if !now_needed {
            return;
        }
        let now = self.host.now_ms();
        let p = self.prof.as_mut().unwrap();
        let dt = now - p.last;
        p.last = now;
        p.samples += 1;
        p.record(top, dt, true);
        let mut seen: Vec<*const Code> = Vec::with_capacity(self.frames.len());
        for f in &self.frames {
            let c = &*f.code as *const Code;
            if !seen.contains(&c) {
                seen.push(c);
                p.record(c, dt, false);
            }
        }
    }

    fn run_frame_from(&mut self, base: usize) -> PyResult<Exit> {
        loop {
            // The frame's code, base and pc live in locals across instructions that stay in
            // the frame; a call or a return refreshes them.
            let fi = self.frames.len() - 1;
            let (code_ptr, fbase, mut pc) = {
                let f = &self.frames[fi];
                (&*f.code as *const Code, f.base, f.pc)
            };
            let code: &Code = unsafe { &*code_ptr };
            let flow = loop {
                if self.prof.is_some() {
                    self.profile_tick(code_ptr);
                }
                match self.step(fi, fbase, code, &mut pc) {
                    Ok(Flow::Next) => {
                        if self.frames.len() != fi + 1 {
                            break Ok(Flow::Next);
                        }
                    }
                    other => {
                        // errors and exits need the frame's pc for handlers and tracebacks
                        if let Some(f) = self.frames.get_mut(fi) {
                            f.pc = pc;
                        }
                        break other;
                    }
                }
            };
            match flow {
                Ok(Flow::Next) => {}
                Ok(Flow::Return(v)) => {
                    let f = self.frames.pop().expect("return without a frame");
                    let v = if f.returns_self { self.stack[f.base] } else { v };
                    self.stack.truncate(f.base - f.below);
                    self.handling.truncate(f.handling_base);
                    if self.frames.len() < base {
                        return Ok(Exit::Return(v));
                    }
                    self.stack.push(v);
                }
                Ok(Flow::Yield(v)) => {
                    let mut f = self.frames.pop().expect("yield without a frame");
                    f.saved = self.stack.split_off(f.base);
                    self.handling.truncate(f.handling_base);
                    debug_assert!(self.frames.len() + 1 == base);
                    return Ok(Exit::Yield(v, Box::new(f)));
                }
                Err(exc) => self.unwind(exc, base)?,
            }
        }
    }

    /// Find a handler for `exc` from the top frame down to `base`; leaves the machine ready to
    /// continue at the handler, or returns the exception when it escapes `base`.
    fn unwind(&mut self, exc: Value, base: usize) -> PyResult<()> {
        let mut exc = exc;
        if !self.is_exception(exc) {
            exc = self.type_error("exceptions must derive from BaseException");
        }
        loop {
            let frame = self.frames.last_mut().expect("unwinding with no frame");
            let pc = frame.pc.saturating_sub(1);
            let entry = (frame.func, frame.code.filename.clone(), frame.code.line_at(pc), frame.code.name.clone());
            if let Some(h) = frame.code.handler_for(pc).copied() {
                let sp0 = frame.sp0;
                frame.pc = h.target;
                let hb = frame.handling_base;
                self.stack.truncate(sp0 + h.depth as usize);
                self.stack.push(exc);
                self.record_traceback(exc, &entry);
                self.handling.truncate(hb + h.hdepth as usize);
                self.handling.push(exc);
                return Ok(());
            }
            self.record_traceback(exc, &entry);
            let f = self.frames.pop().unwrap();
            self.stack.truncate(f.base - f.below);
            self.handling.truncate(f.handling_base);
            if self.frames.len() < base {
                return Err(exc);
            }
        }
    }

    fn record_traceback(&mut self, exc: Value, entry: &(Value, Rc<str>, u32, String)) {
        let (func, filename, line, name) = entry;
        let fname = self.str(filename);
        let cname = if func.is_obj() {
            match self.heap.get(*func) {
                Obj::Func(f) => f.name,
                _ => self.str(name),
            }
        } else {
            self.str(name)
        };
        if let Obj::Exc(e) = self.heap.get_mut(exc) {
            if e.traceback.last().map(|t| t.2 == *line && t.0 == cname).unwrap_or(false) {
                return;
            }
            e.traceback.push((cname, fname, *line));
        }
    }

    /// The exception being handled, or None.
    pub fn current_exception(&self) -> Value {
        self.handling.last().copied().unwrap_or(Value::NONE)
    }

    /// Set `__context__` on a freshly raised exception.
    fn chain_context(&mut self, exc: Value) {
        let cur = self.current_exception();
        if cur.is_none() || cur == exc {
            return;
        }
        if let Obj::Exc(e) = self.heap.get_mut(exc) {
            if e.context.is_none() {
                e.context = cur;
            }
        }
    }

    #[inline(always)]
    fn step(&mut self, fi: usize, base: usize, code: &Code, pc: &mut u32) -> PyResult<Flow> {
        let instr = code.instrs[*pc as usize];
        *pc += 1;
        let arg = instr.arg;
        macro_rules! frame {
            () => {
                self.frames[fi]
            };
        }
        macro_rules! pop {
            () => {
                self.stack.pop().unwrap()
            };
        }
        macro_rules! push {
            ($v:expr) => {{
                let v = $v;
                self.stack.push(v)
            }};
        }
        macro_rules! top {
            () => {
                *self.stack.last().unwrap()
            };
        }
        match instr.op {
            Op::Nop => {}
            Op::Pop => {
                pop!();
            }
            Op::Dup => push!(top!()),
            Op::Dup2 => {
                let n = self.stack.len();
                let (a, b) = (self.stack[n - 2], self.stack[n - 1]);
                self.stack.push(a);
                self.stack.push(b);
            }
            Op::Rot2 => {
                let n = self.stack.len();
                self.stack.swap(n - 1, n - 2);
            }
            Op::Rot3 => {
                let n = self.stack.len();
                let t = self.stack[n - 1];
                self.stack[n - 1] = self.stack[n - 2];
                self.stack[n - 2] = self.stack[n - 3];
                self.stack[n - 3] = t;
            }
            Op::LoadConst => {
                let v = code.consts[arg as usize];
                self.stack.push(v);
            }
            Op::LoadFast => {
                let v = self.stack[base + arg as usize];
                if v.is_undef() {
                    let name = code.varnames[arg as usize];
                    let s = self.as_str(name).unwrap_or("?").to_string();
                    let c = self.t.unbound_local_error;
                    return Err(self.exception(c, format!("cannot access local variable '{s}' where it is not associated with a value")));
                }
                self.stack.push(v);
            }
            Op::StoreFast => {
                let v = pop!();
                self.stack[base + arg as usize] = v;
            }
            Op::DeleteFast => self.stack[base + arg as usize] = Value::UNDEF,
            Op::LoadDeref => {
                let cell = frame!().cells[arg as usize];
                let v = match self.heap.get(cell) {
                    Obj::Cell(v) => *v,
                    _ => Value::UNDEF,
                };
                if v.is_undef() {
                    let name = if (arg as usize) < code.cellvars.len() { code.cellvars[arg as usize] } else { code.freevars[arg as usize - code.cellvars.len()] };
                    let s = self.as_str(name).unwrap_or("?").to_string();
                    let c = self.t.name_error;
                    return Err(self.exception(c, format!("cannot access free variable '{s}' where it is not associated with a value in enclosing scope")));
                }
                push!(v);
            }
            Op::StoreDeref => {
                let v = pop!();
                let cell = frame!().cells[arg as usize];
                *self.heap.get_mut(cell) = Obj::Cell(v);
            }
            Op::LoadClosure => {
                let cell = frame!().cells[arg as usize];
                self.stack.push(cell);
            }
            Op::LoadGlobal => {
                let globals = frame!().globals;
                let b = self.builtins;
                let (gv, bv) = (self.dict_version(globals), self.dict_version(b));
                let site = *pc as usize - 1;
                {
                    let cache = code.gcache.borrow();
                    if let Some(&(cg, cb, v)) = cache.get(site) {
                        if cg == gv && cb == bv && !v.is_undef() {
                            drop(cache);
                            push!(v);
                            return Ok(Flow::Next);
                        }
                    }
                }
                let name = code.names[arg as usize];
                let v = self.load_global(globals, name)?;
                {
                    let mut cache = code.gcache.borrow_mut();
                    if cache.is_empty() {
                        cache.resize(code.instrs.len(), (0, 0, Value::UNDEF));
                    }
                    cache[site] = (gv, bv, v);
                }
                push!(v);
            }
            Op::StoreGlobal => {
                let name = code.names[arg as usize];
                let globals = frame!().globals;
                let v = pop!();
                self.dict_set(globals, name, v);
            }
            Op::DeleteGlobal => {
                let name = code.names[arg as usize];
                let globals = frame!().globals;
                if self.dict_remove(globals, name).is_none() {
                    return Err(self.name_error(name));
                }
            }
            Op::LoadName => {
                let name = code.names[arg as usize];
                let (ns, globals) = (frame!().namespace, frame!().globals);
                let v = match self.dict_get(ns, name) {
                    Some(v) => v,
                    None => self.load_global(globals, name)?,
                };
                push!(v);
            }
            Op::StoreName => {
                let name = code.names[arg as usize];
                let ns = frame!().namespace;
                let v = pop!();
                self.dict_set(ns, name, v);
            }
            Op::DeleteName => {
                let name = code.names[arg as usize];
                let ns = frame!().namespace;
                if self.dict_remove(ns, name).is_none() {
                    return Err(self.name_error(name));
                }
            }
            Op::LoadAttr => {
                self.frames[fi].pc = *pc;
                let name = code.names[arg as usize];
                let obj = pop!();
                let v = self.get_attr(obj, name)?;
                push!(v);
            }
            Op::LoadMethod => {
                self.frames[fi].pc = *pc;
                let name = code.names[arg as usize];
                let obj = pop!();
                let (a, b) = self.load_method(obj, name)?;
                push!(a);
                push!(b);
            }
            Op::StoreAttr => {
                let name = code.names[arg as usize];
                let obj = pop!();
                let v = pop!();
                self.set_attr(obj, name, v)?;
            }
            Op::DeleteAttr => {
                let name = code.names[arg as usize];
                let obj = pop!();
                self.del_attr(obj, name)?;
            }
            Op::LoadSubscr => {
                let key = pop!();
                let obj = pop!();
                let v = self.get_item(obj, key)?;
                push!(v);
            }
            Op::StoreSubscr => {
                let key = pop!();
                let obj = pop!();
                let v = pop!();
                self.set_item(obj, key, v)?;
            }
            Op::DeleteSubscr => {
                let key = pop!();
                let obj = pop!();
                self.del_item(obj, key)?;
            }
            Op::BinaryOp => {
                let b = pop!();
                let a = pop!();
                let v = if a.is_int() && b.is_int() && arg == BinOp::Add as u32 {
                    match a.as_int().checked_add(b.as_int()) {
                        Some(r) => Value::int(r),
                        None => self.binary_op(BinOp::Add, a, b)?,
                    }
                } else {
                    self.binary_op(BinOp::from_u32(arg), a, b)?
                };
                push!(v);
            }
            Op::InplaceOp => {
                let b = pop!();
                let a = pop!();
                let v = self.inplace_op(BinOp::from_u32(arg), a, b)?;
                push!(v);
            }
            Op::UnaryOp => {
                let a = pop!();
                let v = self.unary_op(UnOp::from_u32(arg), a)?;
                push!(v);
            }
            Op::CompareOp => {
                let b = pop!();
                let a = pop!();
                let v = if a.is_int() && b.is_int() {
                    let (x, y) = (a.as_int(), b.as_int());
                    Value::bool(match CmpOp::from_u32(arg) {
                        CmpOp::Lt => x < y,
                        CmpOp::Le => x <= y,
                        CmpOp::Eq => x == y,
                        CmpOp::Ne => x != y,
                        CmpOp::Gt => x > y,
                        CmpOp::Ge => x >= y,
                    })
                } else {
                    self.compare(CmpOp::from_u32(arg), a, b)?
                };
                push!(v);
            }
            Op::IsOp => {
                let b = pop!();
                let a = pop!();
                let same = self.is_same(a, b);
                push!(Value::bool(same != (arg == 1)));
            }
            Op::ContainsOp => {
                let container = pop!();
                let item = pop!();
                let r = self.contains(container, item)?;
                push!(Value::bool(r != (arg == 1)));
            }
            Op::Jump => {
                let back = arg < *pc;
                *pc = arg;
                if back {
                    self.maybe_collect();
                }
            }
            Op::JumpIfFalse => {
                let v = pop!();
                let t = if v.is_bool() { v.as_bool() } else { self.truthy(v)? };
                if !t {
                    *pc = arg;
                }
            }
            Op::JumpIfTrue => {
                let v = pop!();
                let t = if v.is_bool() { v.as_bool() } else { self.truthy(v)? };
                if t {
                    *pc = arg;
                }
            }
            Op::JumpIfFalseOrPop => {
                let v = top!();
                if !self.truthy(v)? {
                    *pc = arg;
                } else {
                    pop!();
                }
            }
            Op::JumpIfTrueOrPop => {
                let v = top!();
                if self.truthy(v)? {
                    *pc = arg;
                } else {
                    pop!();
                }
            }
            Op::GetIter => {
                let v = pop!();
                let it = self.get_iter(v)?;
                push!(it);
            }
            Op::ForIter => {
                let it = top!();
                // ranges and lists inline: no state taken out, nothing that runs Python
                if it.is_obj() {
                    let fast = match self.heap.get_mut(it) {
                        Obj::Iter(Iter::Range { cur, stop, step }) => {
                            if (*step > 0 && *cur < *stop) || (*step < 0 && *cur > *stop) {
                                let v = *cur;
                                *cur += *step;
                                Some(Some(v))
                            } else {
                                Some(None)
                            }
                        }
                        _ => None,
                    };
                    if let Some(r) = fast {
                        match r {
                            Some(v) => {
                                let v = self.int(v);
                                push!(v);
                            }
                            None => {
                                pop!();
                                *pc = arg;
                            }
                        }
                        return Ok(Flow::Next);
                    }
                    let list_step = match self.heap.get(it) {
                        Obj::Iter(Iter::List { list, at }) => Some((*list, *at)),
                        _ => None,
                    };
                    if let Some((list, at)) = list_step {
                        let item = match self.heap.get(list) {
                            Obj::List(v) if at < v.len() => Some(v[at]),
                            _ => None,
                        };
                        match item {
                            Some(v) => {
                                if let Obj::Iter(Iter::List { at, .. }) = self.heap.get_mut(it) {
                                    *at += 1;
                                }
                                push!(v);
                            }
                            None => {
                                pop!();
                                *pc = arg;
                            }
                        }
                        return Ok(Flow::Next);
                    }
                }
                self.frames[fi].pc = *pc;
                match self.iter_next(it)? {
                    Some(v) => push!(v),
                    None => {
                        pop!();
                        *pc = arg;
                    }
                }
            }
            Op::Call => {
                self.frames[fi].pc = *pc;
                let n = arg as usize;
                let len = self.stack.len();
                let callee = self.stack[len - n - 1];
                return self.do_call(callee, Value::UNDEF, len - n, len - n - 1, &[]);
            }
            Op::CallMethod => {
                self.frames[fi].pc = *pc;
                let n = arg as usize;
                let len = self.stack.len();
                let this = self.stack[len - n - 1];
                let callee = self.stack[len - n - 2];
                if this.is_undef() {
                    // [attr, UNDEF, args…]: drop the placeholder and call the attribute
                    self.stack.remove(len - n - 1);
                    return self.do_call(callee, Value::UNDEF, len - n - 1, len - n - 2, &[]);
                }
                return self.do_call(callee, this, len - n, len - n - 2, &[]);
            }
            Op::CallKw => {
                self.frames[fi].pc = *pc;
                let names = pop!();
                let n = arg as usize;
                let keys: Vec<Value> = match self.heap.get(names) {
                    Obj::Tuple(t) => t.clone(),
                    _ => vec![],
                };
                let nkw = keys.len();
                let len = self.stack.len();
                let callee = self.stack[len - n - 1];
                let kw: Vec<(Value, Value)> = keys.iter().enumerate().map(|(i, &k)| (k, self.stack[len - nkw + i])).collect();
                self.stack.truncate(len - nkw);
                return self.do_call(callee, Value::UNDEF, len - n, len - n - 1, &kw);
            }
            Op::CallEx => {
                self.frames[fi].pc = *pc;
                let kwargs = if arg & 1 != 0 { pop!() } else { Value::NONE };
                let args_tuple = pop!();
                let callee = pop!();
                let args: Vec<Value> = self.collect_iter(args_tuple)?;
                let mut kw = Vec::new();
                if !kwargs.is_none() {
                    let d = self.take_dict_snapshot(kwargs)?;
                    for (k, v) in d {
                        if self.as_str(k).is_none() {
                            return Err(self.type_error("keywords must be strings"));
                        }
                        kw.push((k, v));
                    }
                }
                self.roots.push(args_tuple);
                self.roots.push(kwargs);
                let r = self.call(callee, &args, &kw);
                self.roots.pop();
                self.roots.pop();
                push!(r?);
            }
            Op::MakeFunction => {
                let name = pop!();
                let code_v = pop!();
                let code = match self.heap.get(code_v) {
                    Obj::Code(c) => c.clone(),
                    _ => return Err(self.runtime_error("MakeFunction without a code object")),
                };
                let closure = if arg & 4 != 0 {
                    let c = pop!();
                    self.collect_iter(c)?
                } else {
                    Vec::new()
                };
                let kwdefaults = if arg & 2 != 0 {
                    let k = pop!();
                    self.take_dict_snapshot(k)?
                } else {
                    Vec::new()
                };
                let defaults = if arg & 1 != 0 {
                    let d = pop!();
                    self.collect_iter(d)?
                } else {
                    Vec::new()
                };
                let globals = frame!().globals;
                let qualname = self.string(code.qualname.clone());
                let f = self.heap.alloc(Obj::Func(Box::new(Func { code, globals, defaults, kwdefaults, closure, name, qualname, attrs: None })));
                push!(f);
            }
            Op::MakeClass => {
                // arg: the number of bases; the top bit says a keywords dict is on top.
                self.frames[fi].pc = *pc;
                let has_kw = arg & (1 << 31) != 0;
                let nbases = (arg & !(1 << 31)) as usize;
                let kw = if has_kw { pop!() } else { Value::NONE };
                let len = self.stack.len();
                let bases: Vec<Value> = self.stack[len - nbases..].to_vec();
                self.stack.truncate(len - nbases);
                let name = pop!();
                let body = pop!();
                let cls = self.build_class(body, name, bases, kw)?;
                push!(cls);
            }
            Op::BuildTuple => {
                let n = arg as usize;
                let len = self.stack.len();
                let items = self.stack.split_off(len - n);
                let v = self.tuple(items);
                push!(v);
            }
            Op::BuildList => {
                let n = arg as usize;
                let len = self.stack.len();
                let items = self.stack.split_off(len - n);
                let v = self.list(items);
                push!(v);
            }
            Op::BuildSet => {
                let n = arg as usize;
                let len = self.stack.len();
                let items = self.stack.split_off(len - n);
                let v = self.heap.alloc(Obj::Set(PyDict::new()));
                push!(v);
                for it in items {
                    self.key_set(v, it, Value::NONE)?;
                }
            }
            Op::BuildDict => {
                let n = arg as usize;
                let len = self.stack.len();
                let items = self.stack.split_off(len - 2 * n);
                let v = self.dict(PyDict::with_capacity(n));
                push!(v);
                for pair in items.chunks(2) {
                    self.key_set(v, pair[0], pair[1])?;
                }
            }
            Op::BuildSlice => {
                let step = if arg == 3 { pop!() } else { Value::NONE };
                let stop = pop!();
                let start = pop!();
                let v = self.heap.alloc(Obj::Slice { start, stop, step });
                push!(v);
            }
            Op::BuildString => {
                let n = arg as usize;
                let len = self.stack.len();
                let items = self.stack.split_off(len - n);
                let mut s = String::new();
                for it in items {
                    s.push_str(self.as_str(it).unwrap_or(""));
                }
                let v = self.string(s);
                push!(v);
            }
            Op::ListAppend => {
                let v = pop!();
                let list = self.stack[self.stack.len() - arg as usize];
                if let Obj::List(l) = self.heap.get_mut(list) {
                    l.push(v);
                }
            }
            Op::SetAdd => {
                let v = pop!();
                let set = self.stack[self.stack.len() - arg as usize];
                self.key_set(set, v, Value::NONE)?;
            }
            Op::MapAdd => {
                let v = pop!();
                let k = pop!();
                let dict = self.stack[self.stack.len() - arg as usize];
                self.key_set(dict, k, v)?;
            }
            Op::ListExtend => {
                let v = pop!();
                let list = self.stack[self.stack.len() - arg as usize];
                let items = self.collect_iter(v)?;
                if let Obj::List(l) = self.heap.get_mut(list) {
                    l.extend(items);
                }
            }
            Op::SetUpdate => {
                let v = pop!();
                let set = self.stack[self.stack.len() - arg as usize];
                let items = self.collect_iter(v)?;
                for it in items {
                    self.key_set(set, it, Value::NONE)?;
                }
            }
            Op::DictUpdate => {
                let v = pop!();
                let dict = self.stack[self.stack.len() - arg as usize];
                let items = self.mapping_items(v)?;
                for (k, val) in items {
                    self.key_set(dict, k, val)?;
                }
            }
            Op::ListToTuple => {
                let l = pop!();
                let items = self.collect_iter(l)?;
                let v = self.tuple(items);
                push!(v);
            }
            Op::UnpackSequence => {
                let seq = pop!();
                let n = arg as usize;
                let items: Vec<Value> = if seq.is_obj() {
                    match self.heap.get(seq) {
                        Obj::Tuple(v) | Obj::List(v) => v.clone(),
                        _ => self.collect_iter(seq)?,
                    }
                } else {
                    self.collect_iter(seq)?
                };
                if items.len() != n {
                    return Err(self.value_error(if items.len() > n {
                        format!("too many values to unpack (expected {n})")
                    } else {
                        format!("not enough values to unpack (expected {n}, got {})", items.len())
                    }));
                }
                for &v in items.iter().rev() {
                    self.stack.push(v);
                }
            }
            Op::UnpackEx => {
                let before = (arg & 0xffff) as usize;
                let after = (arg >> 16) as usize;
                let seq = pop!();
                let items = self.collect_iter(seq)?;
                if items.len() < before + after {
                    return Err(self.value_error(format!("not enough values to unpack (expected at least {}, got {})", before + after, items.len())));
                }
                let mid = items[before..items.len() - after].to_vec();
                let mid = self.list(mid);
                for &v in items[items.len() - after..].iter().rev() {
                    push!(v);
                }
                push!(mid);
                for &v in items[..before].iter().rev() {
                    push!(v);
                }
            }
            Op::FormatValue => {
                let spec = if arg & 4 != 0 { pop!() } else { Value::UNDEF };
                let v = pop!();
                let converted = match arg & 3 {
                    1 => {
                        let s = self.str_of(v)?;
                        self.string(s)
                    }
                    2 => {
                        let s = self.repr(v)?;
                        self.string(s)
                    }
                    3 => {
                        let s = self.repr(v)?;
                        let s = crate::format::ascii_escape(&s);
                        self.string(s)
                    }
                    _ => v,
                };
                let out = if spec.is_undef() {
                    if arg & 3 == 0 {
                        if self.as_str(converted).is_some() {
                            converted
                        } else {
                            let s = self.str_of(converted)?;
                            self.string(s)
                        }
                    } else {
                        converted
                    }
                } else {
                    let spec_s = self.as_str(spec).unwrap_or("").to_string();
                    let s = self.format_value(converted, &spec_s)?;
                    self.string(s)
                };
                push!(out);
            }
            Op::BuildInterpolation => {
                let format_spec = if arg & 4 != 0 { pop!() } else { self.n.empty };
                let value = pop!();
                let expression = pop!();
                let conversion = match arg & 3 {
                    1 => self.intern("s"),
                    2 => self.intern("r"),
                    3 => self.intern("a"),
                    _ => Value::NONE,
                };
                let v = self.heap.alloc(Obj::Interpolation { value, expression, conversion, format_spec });
                push!(v);
            }
            Op::BuildTemplate => {
                let n = arg as usize;
                let len = self.stack.len();
                let interps = self.stack.split_off(len - n);
                let strings = pop!();
                let interpolations = self.tuple(interps);
                let v = self.heap.alloc(Obj::Template { strings, interpolations });
                push!(v);
            }
            Op::Return => {
                let v = pop!();
                return Ok(Flow::Return(v));
            }
            Op::Raise => match arg {
                0 => {
                    let cur = self.current_exception();
                    if cur.is_none() {
                        return Err(self.runtime_error("No active exception to reraise"));
                    }
                    return Err(cur);
                }
                1 => {
                    let e = pop!();
                    let exc = self.make_raisable(e)?;
                    self.chain_context(exc);
                    return Err(exc);
                }
                _ => {
                    let cause = pop!();
                    let e = pop!();
                    let exc = self.make_raisable(e)?;
                    let cause = if cause.is_none() { Value::NONE } else { self.make_raisable(cause)? };
                    if let Obj::Exc(x) = self.heap.get_mut(exc) {
                        x.cause = cause;
                        x.suppress_context = true;
                    }
                    self.chain_context(exc);
                    return Err(exc);
                }
            },
            Op::Reraise => {
                let e = pop!();
                return Err(e);
            }
            Op::PopExcept => {
                let hb = frame!().handling_base;
                self.handling.truncate(hb + arg as usize);
            }
            Op::CheckExcMatch => {
                let class = pop!();
                let exc = top!();
                if !self.is_exception_class_or_tuple(class) {
                    return Err(self.type_error("catching classes that do not inherit from BaseException is not allowed"));
                }
                let m = self.exc_matches(exc, class);
                push!(Value::bool(m));
            }
            Op::WithExcept => {
                self.frames[fi].pc = *pc;
                let exc = pop!();
                let exit = pop!();
                let class = self.type_of(exc);
                let r = self.call(exit, &[class, exc, Value::NONE], &[])?;
                if self.truthy(r)? {
                    *pc = arg;
                } else {
                    return Err(exc);
                }
            }
            Op::ImportName => {
                self.frames[fi].pc = *pc;
                let name = code.names[arg as usize];
                let fromlist = pop!();
                let level = pop!();
                let globals = frame!().globals;
                let level = self.as_i64(level).unwrap_or(0) as u32;
                let m = self.import_name(name, level, fromlist, globals)?;
                push!(m);
            }
            Op::ImportFrom => {
                let name = code.names[arg as usize];
                let module = top!();
                let v = self.import_from(module, name)?;
                push!(v);
            }
            Op::ImportStar => {
                let module = pop!();
                let ns = frame!().namespace;
                self.import_star(module, ns)?;
            }
            Op::Yield => {
                let v = pop!();
                return Ok(Flow::Yield(v));
            }
            Op::YieldFrom => {
                self.frames[fi].pc = *pc;
                let sent = pop!();
                let sub = top!();
                match self.delegate_send(sub, sent)? {
                    Some(yielded) => {
                        *pc -= 1;
                        self.frames[fi].pc = *pc;
                        return Ok(Flow::Yield(yielded));
                    }
                    None => {
                        pop!();
                        let v = self.delegate_result;
                        self.delegate_result = Value::NONE;
                        push!(v);
                    }
                }
            }
            Op::GetAwaitable => {
                let v = pop!();
                let a = self.get_awaitable(v)?;
                push!(a);
            }
            Op::GetAIter => {
                let v = pop!();
                let name = self.n.aiter;
                let m = self.lookup_method(v, name);
                let it = match m {
                    Some(m) => self.call(m, &[v], &[])?,
                    None => {
                        let t = self.type_name(v);
                        return Err(self.type_error(format!("'async for' requires an object with __aiter__ method, got {t}")));
                    }
                };
                push!(it);
            }
            Op::GetANext => {
                let it = top!();
                let name = self.n.anext;
                let m = self.lookup_method(it, name);
                let aw = match m {
                    Some(m) => self.call(m, &[it], &[])?,
                    None => {
                        let t = self.type_name(it);
                        return Err(self.type_error(format!("'async for' requires an iterator with __anext__ method, got {t}")));
                    }
                };
                let aw = self.get_awaitable(aw)?;
                push!(aw);
            }
            Op::LoadBuildClass => {
                return Err(self.runtime_error("LoadBuildClass is unused"));
            }
            Op::RaiseAssert => {
                let msg = if arg == 1 { pop!() } else { Value::UNDEF };
                let c = self.t.assertion_error;
                let e = self.exception(c, "");
                if !msg.is_undef() {
                    if let Obj::Exc(x) = self.heap.get_mut(e) {
                        x.args = vec![msg];
                    }
                }
                self.chain_context(e);
                return Err(e);
            }
        }
        Ok(Flow::Next)
    }

    /// `Call`/`CallMethod`/`CallKw`: the positional arguments are `stack[first..]`, the
    /// callee just below them (below `this` too, for a method). A Python function starts in
    /// place — its arguments are its first locals — and stays in this loop.
    fn do_call(&mut self, callee: Value, this: Value, first: usize, callee_at: usize, kw: &[(Value, Value)]) -> PyResult<Flow> {
        let mut target = callee;
        let mut this = this;
        if callee.is_obj() {
            if let Obj::Bound { func, this: t } = self.heap.get(callee) {
                if matches!(self.heap.get(*func), Obj::Func(_)) {
                    target = *func;
                    this = *t;
                }
            }
        }
        if target.is_obj() {
            if let Obj::Func(f) = self.heap.get(target) {
                if !f.code.is_generator() {
                    let base = if this.is_undef() {
                        first
                    } else {
                        self.stack[first - 1] = this;
                        first - 1
                    };
                    let mut frame = match self.bind_in_place(target, base, kw) {
                        Ok(f) => f,
                        Err(e) => {
                            self.stack.truncate(callee_at);
                            return Err(e);
                        }
                    };
                    frame.below = base - callee_at;
                    if self.frames.len() as u32 + self.depth >= self.max_depth * 4 {
                        self.stack.truncate(callee_at);
                        let c = self.t.recursion_error;
                        return Err(self.exception(c, "maximum recursion depth exceeded"));
                    }
                    self.frames.push(frame);
                    self.maybe_collect();
                    return Ok(Flow::Next);
                }
            }
        }
        // A user class: allocate the instance here and run `__init__` in place.
        if this.is_undef() && kw.is_empty() && target.is_obj() {
            if let Obj::Class(c) = self.heap.get(target) {
                if c.builtin.is_none() {
                    let new = self.n.new;
                    let init = self.n.init;
                    let has_new = self.class_lookup(target, new).map(|f| matches!(self.heap.get(f), Obj::Func(_) | Obj::StaticMethod(_))).unwrap_or(false);
                    if !has_new {
                        if let Some(initf) = self.class_lookup(target, init) {
                            if matches!(self.heap.get(initf), Obj::Func(_)) && !self.is_object_init_pub(initf) {
                                let inst = self.heap.alloc(Obj::Instance(Instance { class: target, dict: PyDict::new() }));
                                self.stack[first - 1] = inst;
                                let base = first - 1;
                                let mut frame = match self.bind_in_place(initf, base, &[]) {
                                    Ok(f) => f,
                                    Err(e) => {
                                        self.stack.truncate(callee_at);
                                        return Err(e);
                                    }
                                };
                                frame.below = base - callee_at;
                                frame.returns_self = true;
                                self.frames.push(frame);
                                self.maybe_collect();
                                return Ok(Flow::Next);
                            }
                        }
                    }
                }
            }
        }
        // A signal or memo read: `count()`.
        if this.is_undef() && kw.is_empty() && self.stack.len() == first && target.is_obj() {
            if let Obj::Node(_) = self.heap.get(target) {
                let r = crate::core::node_call(self, target);
                self.stack.truncate(callee_at);
                self.stack.push(r?);
                return Ok(Flow::Next);
            }
        }
        // A JavaScript method with its receiver, from `LoadMethod`.
        if !this.is_undef() {
            if let (Some(fh), Some(th)) = (self.js_handle(target), self.js_handle(this)) {
                let args: Vec<Value> = self.stack[first..].to_vec();
                let r = self.js_call(fh, th, &args);
                self.stack.truncate(callee_at);
                self.stack.push(r?);
                return Ok(Flow::Next);
            }
        }
        let n = self.stack.len() - first + (!this.is_undef()) as usize;
        let r = if n <= 6 {
            let mut buf = [Value::UNDEF; 6];
            let mut k = 0;
            if !this.is_undef() {
                buf[0] = this;
                k = 1;
            }
            buf[k..n].copy_from_slice(&self.stack[first..]);
            // `target`, not `callee`: a bound method's receiver is already in front, and
            // `call` on the Bound would put it there a second time (an async method with
            // keywords was "got multiple values for argument").
            self.call(target, &buf[..n], kw)
        } else {
            let mut args: Vec<Value> = Vec::with_capacity(n);
            if !this.is_undef() {
                args.push(this);
            }
            args.extend_from_slice(&self.stack[first..]);
            self.call(target, &args, kw)
        };
        self.stack.truncate(callee_at);
        self.stack.push(r?);
        Ok(Flow::Next)
    }

    fn make_raisable(&mut self, e: Value) -> PyResult {
        if self.is_exception(e) {
            return Ok(e);
        }
        if e.is_obj() {
            if let Obj::Class(c) = self.heap.get(e) {
                if c.mro.contains(&self.t.base_exception) {
                    let inst = self.call(e, &[], &[])?;
                    if self.is_exception(inst) {
                        return Ok(inst);
                    }
                }
            }
        }
        Err(self.type_error("exceptions must derive from BaseException"))
    }

    fn is_exception_class_or_tuple(&self, v: Value) -> bool {
        if !v.is_obj() {
            return false;
        }
        match self.heap.get(v) {
            Obj::Class(c) => c.mro.contains(&self.t.base_exception),
            Obj::Tuple(t) => t.iter().all(|&x| self.is_exception_class_or_tuple(x)),
            _ => false,
        }
    }

    // -- globals and namespace dicts ------------------------------------------------------------

    pub fn load_global(&mut self, globals: Value, name: Value) -> PyResult {
        if let Some(v) = self.dict_get(globals, name) {
            return Ok(v);
        }
        let b = self.builtins;
        if let Some(v) = self.dict_get(b, name) {
            return Ok(v);
        }
        Err(self.name_error(name))
    }
    #[inline]
    pub fn dict_version(&self, dict: Value) -> u32 {
        match self.heap.get(dict) {
            Obj::Dict(d) => d.version,
            _ => 0,
        }
    }
    /// A dict object's lookup; `None` for a missing key or a non-dict.
    #[inline]
    pub fn dict_get(&self, dict: Value, key: Value) -> Option<Value> {
        if !dict.is_obj() {
            return None;
        }
        match self.heap.get(dict) {
            Obj::Dict(d) => d.get(&self.heap, key),
            _ => None,
        }
    }
    pub fn dict_set(&mut self, dict: Value, key: Value, value: Value) {
        let mut d = match self.heap.take(dict) {
            Obj::Dict(d) => d,
            other => {
                self.heap.put(dict, other);
                return;
            }
        };
        d.set(&self.heap, key, value);
        self.heap.put(dict, Obj::Dict(d));
    }
    pub fn dict_remove(&mut self, dict: Value, key: Value) -> Option<Value> {
        let mut d = match self.heap.take(dict) {
            Obj::Dict(d) => d,
            other => {
                self.heap.put(dict, other);
                return None;
            }
        };
        let r = d.remove(&self.heap, key);
        self.heap.put(dict, Obj::Dict(d));
        r
    }
    pub fn dict_get_str(&mut self, dict: Value, key: &str) -> Option<Value> {
        let k = self.intern(key);
        self.dict_get(dict, k)
    }
    pub fn list_push(&mut self, list: Value, v: Value) {
        if let Obj::List(items) = self.heap.get_mut(list) {
            items.push(v);
        }
    }
    pub fn class_dict_set(&mut self, cls: Value, name: Value, value: Value) {
        if let Obj::Class(c) = self.heap.get_mut(cls) {
            let mut d = core::mem::take(&mut c.dict);
            d.set(&self.heap, name, value);
            if let Obj::Class(c) = self.heap.get_mut(cls) {
                c.dict = d;
                c.version += 1;
            }
        }
        self.class_epoch += 1;
    }
    pub fn dict_set_str(&mut self, dict: Value, key: &str, value: Value) {
        let k = self.intern(key);
        self.dict_set(dict, k, value)
    }
    /// The items of a dict object, copied out.
    pub fn take_dict_snapshot(&mut self, dict: Value) -> PyResult<Vec<(Value, Value)>> {
        if dict.is_obj() {
            if let Obj::Dict(d) = self.heap.get(dict) {
                return Ok(d.items().collect());
            }
        }
        self.mapping_items(dict)
    }
    pub fn check_hashable(&mut self, v: Value) -> PyResult<()> {
        self.hash_of(v).map(|_| ())
    }

    // -- imports ------------------------------------------------------------------------------------

    fn import_name(&mut self, name: Value, level: u32, fromlist: Value, globals: Value) -> PyResult {
        let name_s = self.as_str(name).unwrap_or("").to_string();
        let absolute = if level > 0 {
            let pkg_key = self.n.package;
            let name_key = self.n.name;
            let mut package = self.dict_get(globals, pkg_key).and_then(|v| self.as_str(v).map(|s| s.to_string()));
            if package.is_none() {
                package = self.dict_get(globals, name_key).and_then(|v| self.as_str(v).map(|s| s.to_string()));
            }
            let package = package.unwrap_or_default();
            let mut parts: Vec<&str> = package.split('.').filter(|s| !s.is_empty()).collect();
            for _ in 1..level {
                if parts.pop().is_none() {
                    return Err(self.import_error("attempted relative import beyond top-level package"));
                }
            }
            let mut full = parts.join(".");
            if !name_s.is_empty() {
                if !full.is_empty() {
                    full.push('.');
                }
                full.push_str(&name_s);
            }
            if full.is_empty() {
                return Err(self.import_error("attempted relative import with no known parent package"));
            }
            full
        } else {
            name_s.clone()
        };
        let leaf = self.import_module(&absolute)?;
        let has_fromlist = !fromlist.is_none() && self.len_of(fromlist).unwrap_or(0) > 0;
        if has_fromlist || level > 0 && name_s.is_empty() {
            return Ok(leaf);
        }
        if level == 0 {
            let top = absolute.split('.').next().unwrap_or(&absolute).to_string();
            return self.import_module(&top);
        }
        Ok(leaf)
    }

    /// `sys.modules[name]` or load it, parents first.
    pub fn import_module(&mut self, name: &str) -> PyResult {
        let key = self.intern(name);
        let modules = self.modules;
        if let Some(m) = self.dict_get(modules, key) {
            return Ok(m);
        }
        let parent = name.rsplit_once('.').map(|(p, _)| p.to_string());
        let parent_mod = match &parent {
            Some(p) => Some(self.import_module(p)?),
            None => None,
        };
        let module = self.load_module(name)?;
        if let (Some(p), Some(leaf)) = (parent_mod, name.rsplit('.').next()) {
            let attr = self.intern(leaf);
            let pd = self.module_dict(p);
            self.dict_set(pd, attr, module);
        }
        Ok(module)
    }

    fn load_module(&mut self, name: &str) -> PyResult {
        let from_host = self.host.find_module_code(name).is_some();
        if !from_host {
            if let Some(init) = self.builtin_modules.get(name).copied() {
                return self.load_builtin_module(name, init);
            }
        }
        self.load_module_code(name)
    }

    fn load_builtin_module(&mut self, name: &str, init: fn(&mut Vm) -> PyResult<Value>) -> PyResult {
        self.pending_module = Some(name.to_string());
        let m = init(self)?;
        let key = self.intern(name);
        let modules = self.modules;
        self.dict_set(modules, key, m);
        Ok(m)
    }

    fn load_module_code(&mut self, name: &str) -> PyResult {
        let (code, src) = if let Some(bytes) = self.host.find_module_code(name) {
            let code = match crate::fbc::load(self, &bytes) {
                Ok(c) => c,
                Err(msg) => return Err(self.import_error(format!("bad bytecode for '{name}': {msg}"))),
            };
            let is_package = code.filename.ends_with("__init__.py");
            let filename = code.filename.to_string();
            (code, crate::host::ModuleSource { filename, source: String::new(), is_package })
        } else {
            let src = match self.host.find_module(name) {
                Some(s) => s,
                None => return Err(self.import_error(format!("No module named '{name}'"))),
            };
            let compile = match self.compiler {
                Some(c) => c,
                None => return Err(self.import_error(format!("No module named '{name}' (no compiler in this runtime)"))),
            };
            let code = match compile(self, &src.source, &src.filename) {
                Ok(c) => c,
                Err(msg) => {
                    let c = self.t.syntax_error;
                    return Err(self.exception(c, msg));
                }
            };
            (code, src)
        };
        let module = self.new_module(name);
        let dict = self.module_dict(module);
        let file = self.str(&src.filename);
        self.dict_set_str(dict, "__file__", file);
        let package = if src.is_package { name.to_string() } else { name.rsplit_once('.').map(|(p, _)| p.to_string()).unwrap_or_default() };
        let package = self.str(&package);
        self.dict_set_str(dict, "__package__", package);
        if src.is_package {
            let dir = std::path::Path::new(&src.filename).parent().map(|p| p.to_string_lossy().into_owned()).unwrap_or_default();
            let dir = self.str(&dir);
            let path = self.list(vec![dir]);
            self.dict_set_str(dict, "__path__", path);
        }
        let key = self.intern(name);
        let modules = self.modules;
        self.dict_set(modules, key, module);
        match self.run_code(code, dict, dict) {
            Ok(_) => Ok(module),
            Err(e) => {
                self.dict_remove(modules, key);
                Err(e)
            }
        }
    }

    pub fn new_module(&mut self, name: &str) -> Value {
        let name_v = self.str(name);
        let mut d = PyDict::new();
        let k = self.n.name;
        d.set(&self.heap, k, name_v);
        let dict = self.dict(d);
        let module = self.heap.alloc(Obj::Module(Module { name: name_v, dict }));
        let doc = self.n.doc;
        self.dict_set(dict, doc, Value::NONE);
        let b = self.builtins;
        let bk = self.n.builtins;
        self.dict_set(dict, bk, b);
        module
    }
    /// The globals dict object of a module.
    pub fn module_dict(&self, module: Value) -> Value {
        match self.heap.get(module) {
            Obj::Module(m) => m.dict,
            _ => Value::UNDEF,
        }
    }

    fn import_from(&mut self, module: Value, name: Value) -> PyResult {
        if let Ok(v) = self.get_attr(module, name) {
            return Ok(v);
        }
        let name_key = self.n.name;
        let dict = self.module_dict(module);
        let modname = self.dict_get(dict, name_key).and_then(|v| self.as_str(v).map(|s| s.to_string()));
        let attr = self.as_str(name).unwrap_or("").to_string();
        if let Some(m) = modname {
            let full = format!("{m}.{attr}");
            if let Ok(sub) = self.import_module(&full) {
                return Ok(sub);
            }
            return Err(self.import_error(format!("cannot import name '{attr}' from '{m}'")));
        }
        Err(self.import_error(format!("cannot import name '{attr}'")))
    }

    fn import_star(&mut self, module: Value, ns: Value) -> PyResult<()> {
        let dict = self.module_dict(module);
        let all_key = self.n.all;
        let names: Vec<Value> = match self.dict_get(dict, all_key) {
            Some(all) => self.collect_iter(all)?,
            None => match self.heap.get(dict) {
                Obj::Dict(d) => d.keys().filter(|&k| self.as_str(k).map(|s| !s.starts_with('_')).unwrap_or(false)).collect(),
                _ => vec![],
            },
        };
        for n in names {
            if let Some(v) = self.dict_get(dict, n) {
                self.dict_set(ns, n, v);
            }
        }
        Ok(())
    }

    /// Run `code` as the `__main__` module.
    pub fn run_main(&mut self, code: Rc<Code>, filename: &str) -> PyResult {
        let module = self.new_module("__main__");
        let dict = self.module_dict(module);
        let f = self.str(filename);
        self.dict_set_str(dict, "__file__", f);
        let key = self.intern("__main__");
        let modules = self.modules;
        self.dict_set(modules, key, module);
        self.run_code(code, dict, dict)
    }

    /// Run `code` in a module of its own, leaving `sys.modules` alone.
    ///
    /// `run_main` above is for the *app*: it claims `__main__`, which is what an entry is. A
    /// tool the page runs beside the app — the dev server's devtools panel — must not, or the
    /// app's own module is no longer reachable under that name and a dev swap can no longer
    /// find the state it was keeping.
    pub fn run_detached(&mut self, code: Rc<Code>, filename: &str) -> PyResult {
        let module = self.new_module(filename);
        let dict = self.module_dict(module);
        let f = self.str(filename);
        self.dict_set_str(dict, "__file__", f);
        self.run_code(code, dict, dict)
    }

    /// Format an escaped exception the way a traceback reads.
    pub fn format_exception(&mut self, exc: Value) -> String {
        let mut out = String::new();
        if !self.is_exception(exc) {
            return format!("{:?}", exc);
        }
        let (class, tb, cause, context, suppress) = match self.heap.get(exc) {
            Obj::Exc(e) => (e.class, e.traceback.clone(), e.cause, e.context, e.suppress_context),
            _ => unreachable!(),
        };
        if !cause.is_none() {
            out.push_str(&self.format_exception(cause));
            out.push_str("\nThe above exception was the direct cause of the following exception:\n\n");
        } else if !context.is_none() && !suppress {
            out.push_str(&self.format_exception(context));
            out.push_str("\nDuring handling of the above exception, another exception occurred:\n\n");
        }
        if !tb.is_empty() {
            out.push_str("Traceback (most recent call last):\n");
            for (name, file, line) in tb.iter().rev() {
                let n = self.as_str(*name).unwrap_or("?").to_string();
                let f = self.as_str(*file).unwrap_or("?").to_string();
                out.push_str(&format!("  File \"{f}\", line {line}, in {n}\n"));
            }
        }
        let cname = self.class_name(class);
        let msg = self.str_of(exc).unwrap_or_default();
        if msg.is_empty() {
            out.push_str(&cname);
        } else {
            out.push_str(&format!("{cname}: {msg}"));
        }
        out.push('\n');
        out
    }
}

pub enum Flow {
    Next,
    Return(Value),
    Yield(Value),
}

/// A sampling profile: milliseconds per code object, exclusive (it was running) and inclusive
/// (it was on the stack), keyed by the code's address; the name is kept from the first sample.
#[derive(Default)]
pub struct Profile {
    pub last: f64,
    pub counter: u32,
    pub samples: u64,
    pub rows: std::collections::HashMap<usize, ProfileRow>,
}

#[derive(Default, Clone)]
pub struct ProfileRow {
    pub name: String,
    pub file: String,
    pub line: u32,
    pub exclusive: f64,
    pub inclusive: f64,
}

impl Profile {
    fn record(&mut self, code: *const Code, dt: f64, exclusive: bool) {
        let row = self.rows.entry(code as usize).or_insert_with(|| {
            let c = unsafe { &*code };
            ProfileRow { name: c.qualname.clone(), file: c.filename.to_string(), line: c.firstline, ..Default::default() }
        });
        if exclusive {
            row.exclusive += dt;
        } else {
            row.inclusive += dt;
        }
    }
}
