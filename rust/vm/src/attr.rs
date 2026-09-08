//! Attributes and classes: lookup through the MRO, descriptors (`property`, functions,
//! `staticmethod`, `classmethod`), `__getattr__`/`__setattr__`, class creation with C3
//! linearisation, and instantiation.

use crate::dict::PyDict;
use crate::object::*;
use crate::value::Value;
use crate::vm::{PyResult, Vm};

impl Vm {
    /// Look `name` up on a class through its MRO, raw (no binding).
    pub fn class_lookup(&self, cls: Value, name: Value) -> Option<Value> {
        if !cls.is_obj() {
            return None;
        }
        let c = match self.heap.get(cls) {
            Obj::Class(c) => c,
            _ => return None,
        };
        let slot = cache_slot(name);
        if c.cache_epoch.get() == self.class_epoch {
            let (k, v) = c.cache.borrow()[slot];
            if k == name {
                return if v.is_undef() { None } else { Some(v) };
            }
        } else {
            *c.cache.borrow_mut() = [(Value::UNDEF, Value::UNDEF); 32];
            c.cache_epoch.set(self.class_epoch);
        }
        let mut found = None;
        for &m in &c.mro {
            if let Obj::Class(mc) = self.heap.get(m) {
                if let Some(v) = mc.dict.get(&self.heap, name) {
                    found = Some(v);
                    break;
                }
            }
        }
        c.cache.borrow_mut()[slot] = (name, found.unwrap_or(Value::UNDEF));
        found
    }

    /// The raw attribute of a value's type, for calling with the value as first argument.
    pub fn lookup_method(&self, v: Value, name: Value) -> Option<Value> {
        let t = self.type_of(v);
        match self.class_lookup(t, name) {
            Some(m) => match self.heap.get(m) {
                Obj::StaticMethod(f) => Some(*f),
                Obj::Property { .. } | Obj::ClassMethod(_) => None,
                _ => Some(m),
            },
            None => None,
        }
    }

    /// `getattr(obj, name)`.
    pub fn get_attr(&mut self, obj: Value, name: Value) -> PyResult {
        if name == self.n.class {
            return Ok(self.type_of(obj));
        }
        if obj.is_obj() {
            match self.heap.get(obj) {
                Obj::Instance(_) => return self.instance_get_attr(obj, name),
                Obj::Class(_) => return self.class_get_attr(obj, name),
                Obj::Module(_) => {
                    let dict = self.module_dict(obj);
                    if let Some(v) = self.dict_get(dict, name) {
                        return Ok(v);
                    }
                    if name == self.n.dict {
                        return Ok(dict);
                    }
                    // PEP 562
                    let ga = self.n.getattr;
                    if let Some(hook) = self.dict_get(dict, ga) {
                        return self.call(hook, &[name], &[]);
                    }
                    let mname = self.module_name(obj);
                    let s = self.as_str(name).unwrap_or("?").to_string();
                    return Err(self.attribute_error(format!("module '{mname}' has no attribute '{s}'")));
                }
                Obj::Exc(_) => return self.exc_get_attr(obj, name),
                Obj::Func(_) => {
                    if let Some(v) = self.func_get_attr(obj, name) {
                        return Ok(v);
                    }
                }
                Obj::Bound { func, this } => {
                    let (func, this) = (*func, *this);
                    if name == self.n.self_ {
                        return Ok(this);
                    }
                    if name == self.n.func {
                        return Ok(func);
                    }
                    if let Some(v) = self.func_get_attr(func, name) {
                        return Ok(v);
                    }
                }
                Obj::Property { get, set, del } => {
                    let (get, set, del) = (*get, *set, *del);
                    if name == self.n.fget {
                        return Ok(get);
                    }
                    if name == self.n.fset {
                        return Ok(set);
                    }
                    if name == self.n.setter || name == self.n.getter || name == self.n.deleter {
                        // property.setter(f) → a new property
                        let which = if name == self.n.setter { 1 } else if name == self.n.getter { 0 } else { 2 };
                        let f = self.native(if which == 1 { "setter" } else if which == 0 { "getter" } else { "deleter" }, crate::builtins::property_accessor);
                        let tag = Value::int(which);
                        let holder = self.tuple(vec![obj, tag]);
                        return Ok(self.bound(f, holder));
                    }
                    let _ = del;
                }
                Obj::Super { class, this } => {
                    let (class, this) = (*class, *this);
                    return self.super_get_attr(class, this, name);
                }
                Obj::Js(_) => return crate::builtins::js_get_attr(self, obj, name),
                Obj::Template { strings, interpolations } => {
                    let (s, i) = (*strings, *interpolations);
                    if name == self.n.strings {
                        return Ok(s);
                    }
                    if name == self.n.interpolations {
                        return Ok(i);
                    }
                    if name == self.n.value {
                        // `values`: the interpolation values
                        let items = self.collect_iter(i)?;
                        let mut vals = Vec::with_capacity(items.len());
                        for it in items {
                            if let Obj::Interpolation { value, .. } = self.heap.get(it) {
                                vals.push(*value);
                            }
                        }
                        return Ok(self.tuple(vals));
                    }
                }
                Obj::Interpolation { value, expression, conversion, format_spec } => {
                    let (v, e, c, f) = (*value, *expression, *conversion, *format_spec);
                    if name == self.n.value {
                        return Ok(v);
                    }
                    if name == self.n.expression {
                        return Ok(e);
                    }
                    if name == self.n.conversion {
                        return Ok(c);
                    }
                    if name == self.n.format_spec {
                        return Ok(f);
                    }
                }
                Obj::Slice { start, stop, step } => {
                    let (a, b, c) = (*start, *stop, *step);
                    if name == self.n.start {
                        return Ok(a);
                    }
                    if name == self.n.stop {
                        return Ok(b);
                    }
                    if name == self.n.step {
                        return Ok(c);
                    }
                }
                Obj::Range { start, stop, step } => {
                    let (a, b, c) = (*start, *stop, *step);
                    if name == self.n.start {
                        return Ok(self.int(a));
                    }
                    if name == self.n.stop {
                        return Ok(self.int(b));
                    }
                    if name == self.n.step {
                        return Ok(self.int(c));
                    }
                }
                Obj::Generator(g) => {
                    if name == self.n.name {
                        return Ok(g.name);
                    }
                }
                Obj::Code(c) => {
                    let c = c.clone();
                    let s = self.as_str(name).unwrap_or("").to_string();
                    match s.as_str() {
                        "co_argcount" => return Ok(Value::int(c.argcount as i32)),
                        "co_posonlyargcount" => return Ok(Value::int(c.posonlyargcount as i32)),
                        "co_kwonlyargcount" => return Ok(Value::int(c.kwonlyargcount as i32)),
                        "co_nlocals" => return Ok(Value::int(c.nlocals() as i32)),
                        "co_varnames" => {
                            let v = c.varnames.clone();
                            return Ok(self.tuple(v));
                        }
                        "co_cellvars" => {
                            let v = c.cellvars.clone();
                            return Ok(self.tuple(v));
                        }
                        "co_freevars" => {
                            let v = c.freevars.clone();
                            return Ok(self.tuple(v));
                        }
                        "co_name" => return Ok(self.str(&c.name)),
                        "co_qualname" => return Ok(self.str(&c.qualname)),
                        "co_filename" => return Ok(self.str(&c.filename)),
                        "co_firstlineno" => return Ok(Value::int(c.firstline as i32)),
                        "co_flags" => {
                            let mut f = 0;
                            if c.flags & crate::code::FLAG_VARARGS != 0 {
                                f |= 0x04;
                            }
                            if c.flags & crate::code::FLAG_VARKW != 0 {
                                f |= 0x08;
                            }
                            if c.flags & crate::code::FLAG_GENERATOR != 0 {
                                f |= 0x20;
                            }
                            if c.flags & crate::code::FLAG_COROUTINE != 0 {
                                f |= 0x80;
                            }
                            return Ok(Value::int(f));
                        }
                        _ => {}
                    }
                }
                _ => {}
            }
        }
        // Builtin values: their type's methods, bound.
        let t = self.type_of(obj);
        if let Some(m) = self.class_lookup(t, name) {
            return self.bind_descriptor(m, obj, t);
        }
        if name == self.n.doc {
            return Ok(Value::NONE);
        }
        let tn = self.type_name(obj);
        let s = self.as_str(name).unwrap_or("?").to_string();
        Err(self.attribute_error(format!("'{tn}' object has no attribute '{s}'")))
    }

    fn module_name(&self, module: Value) -> String {
        match self.heap.get(module) {
            Obj::Module(m) => self.as_str(m.name).unwrap_or("?").to_string(),
            _ => "?".into(),
        }
    }

    /// Bind a class attribute to an instance: functions become bound methods, properties are
    /// read, static and class methods unwrap.
    fn bind_descriptor(&mut self, attr: Value, obj: Value, cls: Value) -> PyResult {
        if !attr.is_obj() {
            return Ok(attr);
        }
        match self.heap.get(attr) {
            Obj::Func(_) | Obj::Native(_) => Ok(self.bound(attr, obj)),
            Obj::Property { get, .. } => {
                let get = *get;
                if get.is_none() {
                    return Err(self.attribute_error("property has no getter"));
                }
                self.call(get, &[obj], &[])
            }
            Obj::StaticMethod(f) => Ok(*f),
            Obj::ClassMethod(f) => {
                let f = *f;
                Ok(self.bound(f, cls))
            }
            _ => Ok(attr),
        }
    }

    fn instance_get_attr(&mut self, obj: Value, name: Value) -> PyResult {
        let cls = match self.heap.get(obj) {
            Obj::Instance(i) => i.class,
            _ => unreachable!(),
        };
        // `__getattribute__` overridden: it sees everything.
        let ga = self.n.getattribute;
        if let Some(hook) = if self.getattribute_overridden { self.class_lookup(cls, ga) } else { None } {
            if matches!(self.heap.get(hook), Obj::Func(_)) {
                return match self.call(hook, &[obj, name], &[]) {
                    Ok(v) => Ok(v),
                    Err(e) => {
                        let ae = self.t.attribute_error;
                        if self.exc_matches(e, ae) {
                            let g = self.n.getattr;
                            if let Some(fallback) = self.class_lookup(cls, g) {
                                return self.call(fallback, &[obj, name], &[]);
                            }
                        }
                        Err(e)
                    }
                };
            }
        }
        let meta = self.class_lookup(cls, name);
        // Data descriptors first.
        if let Some(m) = meta {
            if let Obj::Property { get, .. } = self.heap.get(m) {
                let get = *get;
                if get.is_none() {
                    return Err(self.attribute_error("unreadable attribute"));
                }
                return self.call(get, &[obj], &[]);
            }
        }
        if let Obj::Instance(i) = self.heap.get(obj) {
            if let Some(v) = i.dict.get(&self.heap, name) {
                return Ok(v);
            }
        }
        if name == self.n.dict {
            return self.instance_dict_object(obj);
        }
        if let Some(m) = meta {
            return self.bind_descriptor(m, obj, cls);
        }
        let g = self.n.getattr;
        if let Some(hook) = self.class_lookup(cls, g) {
            return self.call(hook, &[obj, name], &[]);
        }
        let tn = self.class_name(cls);
        let s = self.as_str(name).unwrap_or("?").to_string();
        Err(self.attribute_error(format!("'{tn}' object has no attribute '{s}'")))
    }

    /// `obj.__dict__`: a snapshot dict (writes to it do not reach the instance).
    fn instance_dict_object(&mut self, obj: Value) -> PyResult {
        let d = match self.heap.get(obj) {
            Obj::Instance(i) => i.dict.clone_shallow(),
            _ => PyDict::new(),
        };
        Ok(self.dict(d))
    }

    fn class_get_attr(&mut self, cls: Value, name: Value) -> PyResult {
        let n = &self.n;
        if name == n.name {
            if let Obj::Class(c) = self.heap.get(cls) {
                return Ok(c.name);
            }
        }
        if name == n.qualname {
            if let Obj::Class(c) = self.heap.get(cls) {
                return Ok(c.name);
            }
        }
        if name == n.mro {
            if let Obj::Class(c) = self.heap.get(cls) {
                let mro = c.mro.clone();
                return Ok(self.tuple(mro));
            }
        }
        if name == n.bases {
            if let Obj::Class(c) = self.heap.get(cls) {
                let bases = c.bases.clone();
                return Ok(self.tuple(bases));
            }
        }
        if name == n.module {
            if let Obj::Class(c) = self.heap.get(cls) {
                return Ok(c.module);
            }
        }
        if name == n.dict {
            if let Obj::Class(c) = self.heap.get(cls) {
                let d = c.dict.clone_shallow();
                return Ok(self.dict(d));
            }
        }
        if let Some(m) = self.class_lookup(cls, name) {
            return match self.heap.get(m) {
                Obj::StaticMethod(f) => Ok(*f),
                Obj::ClassMethod(f) => {
                    let f = *f;
                    Ok(self.bound(f, cls))
                }
                _ => Ok(m),
            };
        }
        // Attributes of `type` itself (`mro()`, `__subclasses__`…), bound to the class.
        let t = self.t.type_;
        if let Some(m) = self.class_lookup(t, name) {
            if matches!(self.heap.get(m), Obj::Native(_) | Obj::Func(_)) {
                return Ok(self.bound(m, cls));
            }
            return Ok(m);
        }
        if name == n.doc {
            return Ok(Value::NONE);
        }
        let cn = self.class_name(cls);
        let s = self.as_str(name).unwrap_or("?").to_string();
        Err(self.attribute_error(format!("type object '{cn}' has no attribute '{s}'")))
    }

    fn exc_get_attr(&mut self, obj: Value, name: Value) -> PyResult {
        let n = &self.n;
        let (class, dict_hit) = match self.heap.get(obj) {
            Obj::Exc(e) => (e.class, e.dict.get(&self.heap, name)),
            _ => unreachable!(),
        };
        if let Some(v) = dict_hit {
            return Ok(v);
        }
        if name == n.args {
            let args = match self.heap.get(obj) {
                Obj::Exc(e) => e.args.clone(),
                _ => vec![],
            };
            return Ok(self.tuple(args));
        }
        if name == n.traceback {
            return Ok(Value::NONE);
        }
        if name == n.cause {
            if let Obj::Exc(e) = self.heap.get(obj) {
                return Ok(e.cause);
            }
        }
        if name == n.context {
            if let Obj::Exc(e) = self.heap.get(obj) {
                return Ok(e.context);
            }
        }
        if name == n.suppress_context {
            if let Obj::Exc(e) = self.heap.get(obj) {
                return Ok(Value::bool(e.suppress_context));
            }
        }
        if name == n.value {
            // StopIteration.value
            if let Obj::Exc(e) = self.heap.get(obj) {
                return Ok(e.args.first().copied().unwrap_or(Value::NONE));
            }
        }
        if let Some(m) = self.class_lookup(class, name) {
            return self.bind_descriptor(m, obj, class);
        }
        let g = self.n.getattr;
        if let Some(hook) = self.class_lookup(class, g) {
            return self.call(hook, &[obj, name], &[]);
        }
        let tn = self.class_name(class);
        let s = self.as_str(name).unwrap_or("?").to_string();
        Err(self.attribute_error(format!("'{tn}' object has no attribute '{s}'")))
    }

    fn func_get_attr(&mut self, func: Value, name: Value) -> Option<Value> {
        let n = &self.n;
        if let Obj::Func(f) = self.heap.get(func) {
            if let Some(a) = &f.attrs {
                if let Some(v) = a.get(&self.heap, name) {
                    return Some(v);
                }
            }
            if name == n.name {
                return Some(f.name);
            }
            if name == n.qualname {
                return Some(f.qualname);
            }
            if name == n.doc {
                return Some(f.code.consts.first().copied().filter(|c| self.as_str(*c).is_some() && f.code.flags & crate::code::FLAG_NAMESPACE == 0 && false).unwrap_or(Value::NONE));
            }
            if name == n.module {
                let g = f.globals;
                let key = self.n.name;
                return Some(self.dict_get(g, key).unwrap_or(Value::NONE));
            }
            if name == n.defaults {
                let d = f.defaults.clone();
                return Some(if d.is_empty() { Value::NONE } else { self.tuple(d) });
            }
            if name == n.globals {
                return Some(f.globals);
            }
            if name == n.code {
                let c = f.code.clone();
                return Some(self.heap.alloc(Obj::Code(c)));
            }
            if name == n.closure {
                let c = f.closure.clone();
                return Some(if c.is_empty() { Value::NONE } else { self.tuple(c) });
            }
            if name == n.dict {
                let d = f.attrs.as_ref().map(|a| a.clone_shallow()).unwrap_or_default();
                return Some(self.dict(d));
            }
        }
        if let Obj::Native(nf) = self.heap.get(func) {
            if name == n.name || name == n.qualname {
                let s = nf.name;
                return Some(self.intern(s));
            }
            if name == n.doc || name == n.module {
                return Some(Value::NONE);
            }
        }
        None
    }

    /// `setattr(obj, name, value)`.
    pub fn set_attr(&mut self, obj: Value, name: Value, value: Value) -> PyResult<()> {
        if !obj.is_obj() {
            let t = self.type_name(obj);
            let s = self.as_str(name).unwrap_or("?").to_string();
            return Err(self.attribute_error(format!("'{t}' object has no attribute '{s}' and no __dict__ for setting new attributes")));
        }
        match self.heap.get(obj) {
            Obj::Instance(i) => {
                let cls = i.class;
                let sa = self.n.setattr;
                if let Some(hook) = self.class_lookup(cls, sa) {
                    if matches!(self.heap.get(hook), Obj::Func(_)) {
                        self.call(hook, &[obj, name, value], &[])?;
                        return Ok(());
                    }
                }
                self.instance_set_attr_direct(obj, name, value)
            }
            Obj::Exc(_) => {
                if let Obj::Exc(e) = self.heap.get_mut(obj) {
                    let mut d = core::mem::take(&mut e.dict);
                    d.set(&self.heap, name, value);
                    if let Obj::Exc(e) = self.heap.get_mut(obj) {
                        e.dict = d;
                    }
                }
                Ok(())
            }
            Obj::Class(_) => {
                if let Obj::Class(c) = self.heap.get_mut(obj) {
                    let mut d = core::mem::take(&mut c.dict);
                    d.set(&self.heap, name, value);
                    if let Obj::Class(c) = self.heap.get_mut(obj) {
                        c.dict = d;
                        c.version = c.version.wrapping_add(1);
                    }
                }
                self.class_epoch = self.class_epoch.wrapping_add(1);
                if name == self.n.getattribute {
                    self.getattribute_overridden = true;
                }
                Ok(())
            }
            Obj::Module(_) => {
                let dict = self.module_dict(obj);
                self.dict_set(dict, name, value);
                Ok(())
            }
            Obj::Func(_) => {
                if let Obj::Func(f) = self.heap.get_mut(obj) {
                    if name == self.n.name {
                        f.name = value;
                        return Ok(());
                    }
                    if name == self.n.qualname {
                        f.qualname = value;
                        return Ok(());
                    }
                    let mut attrs = f.attrs.take().unwrap_or_default();
                    attrs.set(&self.heap, name, value);
                    if let Obj::Func(f) = self.heap.get_mut(obj) {
                        f.attrs = Some(attrs);
                    }
                }
                Ok(())
            }
            Obj::Js(_) => crate::builtins::js_set_attr(self, obj, name, value),
            _ => {
                let t = self.type_name(obj);
                let s = self.as_str(name).unwrap_or("?").to_string();
                Err(self.attribute_error(format!("'{t}' object has no attribute '{s}' and no __dict__ for setting new attributes")))
            }
        }
    }

    /// `object.__setattr__`: property setters, then the instance dict.
    pub fn instance_set_attr_direct(&mut self, obj: Value, name: Value, value: Value) -> PyResult<()> {
        let cls = match self.heap.get(obj) {
            Obj::Instance(i) => i.class,
            _ => return Err(self.type_error("object.__setattr__ on a non-instance")),
        };
        if let Some(m) = self.class_lookup(cls, name) {
            if let Obj::Property { set, .. } = self.heap.get(m) {
                let set = *set;
                if set.is_none() {
                    let s = self.as_str(name).unwrap_or("?").to_string();
                    let cn = self.class_name(cls);
                    return Err(self.attribute_error(format!("property '{s}' of '{cn}' object has no setter")));
                }
                self.call(set, &[obj, value], &[])?;
                return Ok(());
            }
        }
        if let Obj::Instance(i) = self.heap.get_mut(obj) {
            let mut d = core::mem::take(&mut i.dict);
            d.set(&self.heap, name, value);
            if let Obj::Instance(i) = self.heap.get_mut(obj) {
                i.dict = d;
            }
        }
        Ok(())
    }

    pub fn del_attr(&mut self, obj: Value, name: Value) -> PyResult<()> {
        if obj.is_obj() {
            match self.heap.get(obj) {
                Obj::Instance(i) => {
                    let cls = i.class;
                    let da = self.n.delattr;
                    if let Some(hook) = self.class_lookup(cls, da) {
                        if matches!(self.heap.get(hook), Obj::Func(_)) {
                            self.call(hook, &[obj, name], &[])?;
                            return Ok(());
                        }
                    }
                    if let Some(m) = self.class_lookup(cls, name) {
                        if let Obj::Property { del, .. } = self.heap.get(m) {
                            let del = *del;
                            if !del.is_none() {
                                self.call(del, &[obj], &[])?;
                                return Ok(());
                            }
                        }
                    }
                    let removed = if let Obj::Instance(i) = self.heap.get_mut(obj) {
                        let mut d = core::mem::take(&mut i.dict);
                        let r = d.remove(&self.heap, name);
                        if let Obj::Instance(i) = self.heap.get_mut(obj) {
                            i.dict = d;
                        }
                        r
                    } else {
                        None
                    };
                    if removed.is_none() {
                        let s = self.as_str(name).unwrap_or("?").to_string();
                        return Err(self.attribute_error(s));
                    }
                    return Ok(());
                }
                Obj::Class(_) => {
                    if let Obj::Class(c) = self.heap.get_mut(obj) {
                        let mut d = core::mem::take(&mut c.dict);
                        d.remove(&self.heap, name);
                        if let Obj::Class(c) = self.heap.get_mut(obj) {
                            c.dict = d;
                            c.version = c.version.wrapping_add(1);
                        }
                    }
                    self.class_epoch = self.class_epoch.wrapping_add(1);
                    return Ok(());
                }
                Obj::Module(_) => {
                    let dict = self.module_dict(obj);
                    self.dict_remove(dict, name);
                    return Ok(());
                }
                _ => {}
            }
        }
        let t = self.type_name(obj);
        let s = self.as_str(name).unwrap_or("?").to_string();
        Err(self.attribute_error(format!("'{t}' object has no attribute '{s}'")))
    }

    // -- classes ------------------------------------------------------------------------------------------

    /// C3 linearisation.
    fn compute_mro(&mut self, cls: Value, bases: &[Value]) -> PyResult<Vec<Value>> {
        let mut seqs: Vec<Vec<Value>> = Vec::new();
        for &b in bases {
            match self.heap.get(b) {
                Obj::Class(c) => seqs.push(c.mro.clone()),
                _ => return Err(self.type_error("bases must be classes")),
            }
        }
        seqs.push(bases.to_vec());
        let mut out = vec![cls];
        loop {
            seqs.retain(|s| !s.is_empty());
            if seqs.is_empty() {
                return Ok(out);
            }
            let mut picked = None;
            for s in &seqs {
                let head = s[0];
                if !seqs.iter().any(|t| t[1..].contains(&head)) {
                    picked = Some(head);
                    break;
                }
            }
            match picked {
                Some(h) => {
                    out.push(h);
                    for s in &mut seqs {
                        if s[0] == h {
                            s.remove(0);
                        }
                    }
                }
                None => return Err(self.type_error("Cannot create a consistent method resolution order (MRO)")),
            }
        }
    }

    /// `class` statement: run the body into a namespace, then make the class.
    pub fn build_class(&mut self, body: Value, name: Value, bases: Vec<Value>) -> PyResult {
        let ns = self.dict(PyDict::new());
        self.roots.push(ns);
        let globals = match self.heap.get(body) {
            Obj::Func(f) => f.globals,
            _ => Value::NONE,
        };
        let module_key = self.n.name;
        let module = self.dict_get(globals, module_key).unwrap_or(Value::NONE);
        let mk = self.n.module;
        self.dict_set(ns, mk, module);
        let qk = self.n.qualname;
        self.dict_set(ns, qk, name);
        let r = self.run_function_with_namespace(body, ns);
        self.roots.pop();
        r?;
        self.make_class(name, bases, ns, module)
    }

    /// `type(name, bases, dict)`.
    pub fn make_class(&mut self, name: Value, mut bases: Vec<Value>, ns: Value, module: Value) -> PyResult {
        if bases.is_empty() {
            bases.push(self.t.object);
        }
        let mut builtin = None;
        for &b in &bases {
            match self.heap.get(b) {
                Obj::Class(c) => {
                    if builtin.is_none() {
                        builtin = c.builtin.filter(|k| *k != Builtin::Object);
                    }
                }
                _ => return Err(self.type_error("bases must be classes")),
            }
        }
        let placeholder = Class { name, bases: bases.clone(), mro: Vec::new(), dict: PyDict::new(), builtin, version: 0, module, cache: core::cell::RefCell::new([(Value::UNDEF, Value::UNDEF); 32]), cache_epoch: Default::default() };
        let cls = self.heap.alloc(Obj::Class(Box::new(placeholder)));
        self.roots.push(cls);
        let mro = self.compute_mro(cls, &bases)?;
        let mut dict = match self.heap.take(ns) {
            Obj::Dict(d) => d,
            _ => PyDict::new(),
        };
        self.heap.put(ns, Obj::Dict(PyDict::new()));
        // `__classcell__`: the cell zero-argument `super()` reads.
        let cc = self.n.classcell;
        if let Some(cell) = dict.remove(&self.heap, cc) {
            if cell.is_obj() {
                if let Obj::Cell(_) = self.heap.get(cell) {
                    *self.heap.get_mut(cell) = Obj::Cell(cls);
                }
            }
        }
        // Plain functions named `__init_subclass__`/`__class_getitem__` are implicit classmethods.
        for special in [self.n.init_subclass, self.n.class_getitem] {
            if let Some(f) = dict.get(&self.heap, special) {
                if matches!(self.heap.get(f), Obj::Func(_)) {
                    let cm = self.heap.alloc(Obj::ClassMethod(f));
                    dict.set(&self.heap, special, cm);
                }
            }
        }
        if let Obj::Class(c) = self.heap.get_mut(cls) {
            c.mro = mro;
            c.dict = dict;
        }
        self.class_epoch = self.class_epoch.wrapping_add(1);
        let ga = self.n.getattribute;
        if let Some(m) = self.class_lookup(cls, ga) {
            if matches!(self.heap.get(m), Obj::Func(_)) {
                self.getattribute_overridden = true;
            }
        }
        // `__set_name__` on descriptors, `__init_subclass__` on the parent.
        let entries: Vec<(Value, Value)> = match self.heap.get(cls) {
            Obj::Class(c) => c.dict.items().collect(),
            _ => vec![],
        };
        let sn = self.n.set_name;
        for (k, v) in entries {
            if v.is_obj() && matches!(self.heap.get(v), Obj::Instance(_)) {
                if let Some(m) = self.lookup_method(v, sn) {
                    self.call(m, &[v, cls, k], &[])?;
                }
            }
        }
        let is = self.n.init_subclass;
        if let Some(parent) = mro_second(self, cls) {
            if let Some(hook) = self.class_lookup(parent, is) {
                let target = match self.heap.get(hook) {
                    Obj::ClassMethod(f) => Some(*f),
                    Obj::Func(_) => Some(hook),
                    _ => None,
                };
                if let Some(f) = target {
                    self.call(f, &[cls], &[])?;
                }
            }
        }
        self.roots.pop();
        Ok(cls)
    }

    /// `cls(*args, **kwargs)`.
    pub fn construct(&mut self, cls: Value, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
        let builtin = match self.heap.get(cls) {
            Obj::Class(c) => c.builtin,
            _ => return Err(self.type_error("not a class")),
        };
        if let Some(kind) = builtin {
            return crate::builtins::construct_builtin(self, cls, kind, args, kwargs);
        }
        let new = self.n.new;
        let obj = if let Some(newf) = self.class_lookup(cls, new).filter(|f| matches!(self.heap.get(*f), Obj::Func(_) | Obj::StaticMethod(_))) {
            let newf = match self.heap.get(newf) {
                Obj::StaticMethod(f) => *f,
                _ => newf,
            };
            let mut all = Vec::with_capacity(args.len() + 1);
            all.push(cls);
            all.extend_from_slice(args);
            let o = self.call(newf, &all, kwargs)?;
            if !self.is_instance_of(o, cls) {
                return Ok(o);
            }
            o
        } else {
            self.heap.alloc(Obj::Instance(Instance { class: cls, dict: PyDict::new() }))
        };
        self.roots.push(obj);
        let init = self.n.init;
        let r = match self.class_lookup(cls, init) {
            Some(f) if !self.is_object_init(f) => {
                let mut all = Vec::with_capacity(args.len() + 1);
                all.push(obj);
                all.extend_from_slice(args);
                match self.call(f, &all, kwargs) {
                    Ok(r) => {
                        if !r.is_none() {
                            let t = self.type_name(r);
                            Err(self.type_error(format!("__init__() should return None, not '{t}'")))
                        } else {
                            Ok(obj)
                        }
                    }
                    Err(e) => Err(e),
                }
            }
            _ => {
                if !args.is_empty() || !kwargs.is_empty() {
                    let cn = self.class_name(cls);
                    Err(self.type_error(format!("{cn}() takes no arguments")))
                } else {
                    Ok(obj)
                }
            }
        };
        self.roots.pop();
        r
    }

    fn is_object_init(&self, f: Value) -> bool {
        let key = self.n.init;
        self.class_lookup(self.t.object, key) == Some(f)
    }
    pub fn is_object_init_pub(&self, f: Value) -> bool {
        self.is_object_init(f)
    }

    pub fn interned_lookup(&self, s: &str) -> Option<Value> {
        self.interned_ref().get(s).copied()
    }
}

impl Vm {
    /// `super(class, this).name`: the MRO of `type(this)` after `class`, bound to `this`.
    fn super_get_attr(&mut self, class: Value, this: Value, name: Value) -> PyResult {
        let start_type = if this.is_obj() && matches!(self.heap.get(this), Obj::Class(_)) { this } else { self.type_of(this) };
        let mro: Vec<Value> = match self.heap.get(start_type) {
            Obj::Class(c) => c.mro.clone(),
            _ => vec![],
        };
        let pos = mro.iter().position(|&m| m == class).map(|p| p + 1).unwrap_or(0);
        for &m in &mro[pos..] {
            let hit = match self.heap.get(m) {
                Obj::Class(c) => c.dict.get(&self.heap, name),
                _ => None,
            };
            if let Some(attr) = hit {
                return match self.heap.get(attr) {
                    Obj::Func(_) | Obj::Native(_) => Ok(self.bound(attr, this)),
                    Obj::StaticMethod(f) => Ok(*f),
                    Obj::ClassMethod(f) => {
                        let f = *f;
                        Ok(self.bound(f, start_type))
                    }
                    Obj::Property { get, .. } => {
                        let get = *get;
                        self.call(get, &[this], &[])
                    }
                    _ => Ok(attr),
                };
            }
        }
        let s = self.as_str(name).unwrap_or("?").to_string();
        Err(self.attribute_error(format!("'super' object has no attribute '{s}'")))
    }
}

fn mro_second(vm: &Vm, cls: Value) -> Option<Value> {
    match vm.heap.get(cls) {
        Obj::Class(c) => c.mro.get(1).copied(),
        _ => None,
    }
}

impl Vm {
    /// `LoadMethod`: `(callable, receiver)` when `name` is a plain function on the receiver's
    /// type — the call passes the receiver itself, no bound-method object — else
    /// `(attribute, UNDEF)`.
    pub fn load_method(&mut self, obj: Value, name: Value) -> PyResult<(Value, Value)> {
        if obj.is_obj() {
            match self.heap.get(obj) {
                Obj::Instance(i) => {
                    let cls = i.class;
                    if !self.getattribute_overridden {
                        // instance dict shadows a plain function; a property wins over both
                        let meta = self.class_lookup(cls, name);
                        let shadowed = i.dict.get(&self.heap, name);
                        if let Some(m) = meta {
                            if let Obj::Func(_) | Obj::Native(_) = self.heap.get(m) {
                                if shadowed.is_none() {
                                    return Ok((m, obj));
                                }
                            }
                        }
                        if let Some(v) = shadowed {
                            return Ok((v, Value::UNDEF));
                        }
                    }
                }
                Obj::Js(_) => {
                    if let Some(pair) = crate::builtins::js_load_method(self, obj, name)? {
                        return Ok(pair);
                    }
                }
                Obj::Class(_) | Obj::Module(_) | Obj::Super { .. } | Obj::Exc(_) => {}
                _ => {
                    // builtin values: the type's native, unbound
                    let t = self.type_of(obj);
                    if let Some(m) = self.class_lookup(t, name) {
                        if let Obj::Func(_) | Obj::Native(_) = self.heap.get(m) {
                            return Ok((m, obj));
                        }
                    }
                }
            }
        } else {
            let t = self.type_of(obj);
            if let Some(m) = self.class_lookup(t, name) {
                if let Obj::Func(_) | Obj::Native(_) = self.heap.get(m) {
                    return Ok((m, obj));
                }
            }
        }
        let v = self.get_attr(obj, name)?;
        Ok((v, Value::UNDEF))
    }
}
