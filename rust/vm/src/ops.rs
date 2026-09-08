//! The operator protocol: arithmetic, comparison, truth, containment, subscripts, iteration,
//! `repr`/`str`. Fast paths for the builtin types, dunder dispatch for instances.

use crate::code::{BinOp, CmpOp, UnOp};
use crate::dict::PyDict;
use crate::object::*;
use crate::value::Value;
use crate::vm::{PyResult, Vm};

impl Vm {
    // -- types ---------------------------------------------------------------------------------

    pub fn type_of(&self, v: Value) -> Value {
        if v.is_int() {
            return self.t.int;
        }
        if v.is_float() {
            return self.t.float;
        }
        if v.is_bool() {
            return self.t.bool_;
        }
        if v.is_none() {
            return self.t.none_type;
        }
        if v.is_undef() {
            return self.t.none_type;
        }
        match self.heap.get(v) {
            Obj::Node(n) => n.class,
            Obj::Str(_) => self.t.str_,
            Obj::Int(_) => self.t.int,
            Obj::List(_) => self.t.list,
            Obj::Tuple(_) => self.t.tuple,
            Obj::Dict(_) => self.t.dict,
            Obj::Set(_) => self.t.set,
            Obj::FrozenSet(_) => self.t.frozenset,
            Obj::Bytes(_) => self.t.bytes,
            Obj::ByteArray(_) => self.t.bytearray,
            Obj::Func(_) => self.t.function,
            Obj::Native(_) => self.t.builtin_function,
            Obj::Bound { func, .. } => {
                if matches!(self.heap.get(*func), Obj::Func(_)) {
                    self.t.method
                } else {
                    self.t.builtin_function
                }
            }
            Obj::Class(c) => {
                if c.meta.is_none() {
                    self.t.type_
                } else {
                    c.meta
                }
            }
            Obj::Instance(i) => i.class,
            Obj::Module(_) => self.t.module,
            Obj::Exc(e) => e.class,
            Obj::Cell(_) => self.t.cell,
            Obj::Range { .. } => self.t.range,
            Obj::Slice { .. } => self.t.slice,
            Obj::Property { .. } => self.t.property,
            Obj::StaticMethod(_) => self.t.staticmethod,
            Obj::ClassMethod(_) => self.t.classmethod,
            Obj::Iter(_) => self.t.iterator,
            Obj::Generator(g) => {
                if g.is_coroutine {
                    self.t.coroutine
                } else {
                    self.t.generator
                }
            }
            Obj::Template { .. } => self.t.template,
            Obj::Interpolation { .. } => self.t.interpolation,
            Obj::Code(_) => self.t.code,
            Obj::Super { .. } => self.t.super_,
            Obj::Js(_) => self.t.js_object,
            Obj::NotImplemented => self.t.not_implemented_type,
            Obj::Ellipsis => self.t.ellipsis_type,
            Obj::Free => self.t.none_type,
        }
    }
    pub fn class_name(&self, cls: Value) -> String {
        if !cls.is_obj() {
            return "?".into();
        }
        match self.heap.get(cls) {
            Obj::Class(c) => self.as_str(c.name).unwrap_or("?").to_string(),
            _ => "?".into(),
        }
    }
    pub fn type_name(&self, v: Value) -> String {
        let t = self.type_of(v);
        self.class_name(t)
    }
    pub fn is_instance_of(&self, v: Value, cls: Value) -> bool {
        let t = self.type_of(v);
        self.class_matches(t, cls)
    }

    // -- arithmetic -------------------------------------------------------------------------------

    pub fn binary_op(&mut self, op: BinOp, a: Value, b: Value) -> PyResult {
        // ints (bools count as ints)
        if let (Some(x), Some(y)) = (self.as_i64(a), self.as_i64(b)) {
            if !(a.is_float() || b.is_float()) {
                return self.int_op(op, x, y);
            }
        }
        if let (Some(x), Some(y)) = (self.as_f64(a), self.as_f64(b)) {
            if !(a.is_obj() && !matches!(self.heap.get(a), Obj::Int(_))) && !(b.is_obj() && !matches!(self.heap.get(b), Obj::Int(_))) {
                return self.float_op(op, x, y);
            }
        }
        if a.is_obj() && b.is_obj() {
            match (self.heap.get(a), self.heap.get(b), op) {
                (Obj::Str(x), Obj::Str(y), BinOp::Add) => {
                    let mut s = String::with_capacity(x.s.len() + y.s.len());
                    s.push_str(&x.s);
                    s.push_str(&y.s);
                    return Ok(self.string(s));
                }
                (Obj::List(x), Obj::List(y), BinOp::Add) => {
                    let mut v = x.clone();
                    v.extend_from_slice(y);
                    return Ok(self.list(v));
                }
                (Obj::Tuple(x), Obj::Tuple(y), BinOp::Add) => {
                    let mut v = x.clone();
                    v.extend_from_slice(y);
                    return Ok(self.tuple(v));
                }
                (Obj::Bytes(x), Obj::Bytes(y), BinOp::Add) => {
                    let mut v = x.clone();
                    v.extend_from_slice(y);
                    return Ok(self.heap.alloc(Obj::Bytes(v)));
                }
                (Obj::Dict(x), Obj::Dict(y), BinOp::Or) => {
                    let mut d = x.clone_shallow();
                    let items: Vec<(Value, Value)> = y.items().collect();
                    for (k, v) in items {
                        d.set(&self.heap, k, v);
                    }
                    return Ok(self.dict(d));
                }
                (Obj::Set(_), Obj::Set(_), BinOp::Or | BinOp::And | BinOp::Sub | BinOp::Xor)
                | (Obj::FrozenSet(_), Obj::FrozenSet(_), BinOp::Or | BinOp::And | BinOp::Sub | BinOp::Xor)
                | (Obj::Set(_), Obj::FrozenSet(_), BinOp::Or | BinOp::And | BinOp::Sub | BinOp::Xor)
                | (Obj::FrozenSet(_), Obj::Set(_), BinOp::Or | BinOp::And | BinOp::Sub | BinOp::Xor) => return self.set_op(op, a, b),
                (Obj::Str(_), _, BinOp::Mod) => return self.percent_format(a, b),
                _ => {}
            }
        }
        if op == BinOp::Mul {
            if let Some(n) = self.as_i64(b) {
                if a.is_obj() {
                    if let Some(r) = self.repeat(a, n) {
                        return Ok(r);
                    }
                }
            }
            if let Some(n) = self.as_i64(a) {
                if b.is_obj() {
                    if let Some(r) = self.repeat(b, n) {
                        return Ok(r);
                    }
                }
            }
        }
        if op == BinOp::Mod && a.is_obj() {
            if let Obj::Str(_) = self.heap.get(a) {
                return self.percent_format(a, b);
            }
        }
        // dunders
        let (fwd, rev) = self.binop_names(op);
        if let Some(r) = self.try_dunder(a, fwd, b)? {
            return Ok(r);
        }
        if let Some(r) = self.try_dunder(b, rev, a)? {
            return Ok(r);
        }
        let (ta, tb) = (self.type_name(a), self.type_name(b));
        Err(self.type_error(format!("unsupported operand type(s) for {}: '{}' and '{}'", op.symbol(), ta, tb)))
    }

    fn repeat(&mut self, seq: Value, n: i64) -> Option<Value> {
        let n = n.max(0) as usize;
        match self.heap.get(seq) {
            Obj::Str(s) => {
                let r = s.s.repeat(n);
                Some(self.string(r))
            }
            Obj::List(v) => {
                let mut out = Vec::with_capacity(v.len() * n);
                for _ in 0..n {
                    out.extend_from_slice(v);
                }
                Some(self.list(out))
            }
            Obj::Tuple(v) => {
                let mut out = Vec::with_capacity(v.len() * n);
                for _ in 0..n {
                    out.extend_from_slice(v);
                }
                Some(self.tuple(out))
            }
            Obj::Bytes(v) => {
                let out = v.repeat(n);
                Some(self.heap.alloc(Obj::Bytes(out)))
            }
            _ => None,
        }
    }

    fn binop_names(&self, op: BinOp) -> (Value, Value) {
        let n = &self.n;
        match op {
            BinOp::Add => (n.add, n.radd),
            BinOp::Sub => (n.sub, n.rsub),
            BinOp::Mul => (n.mul, n.rmul),
            BinOp::TrueDiv => (n.truediv, n.rtruediv),
            BinOp::FloorDiv => (n.floordiv, n.rfloordiv),
            BinOp::Mod => (n.mod_, n.rmod),
            BinOp::Pow => (n.pow, n.rpow),
            BinOp::And => (n.and, n.rand),
            BinOp::Or => (n.or, n.ror),
            BinOp::Xor => (n.xor, n.rxor),
            BinOp::LShift => (n.lshift, n.lshift),
            BinOp::RShift => (n.rshift, n.rshift),
            BinOp::MatMul => (n.matmul, n.matmul),
        }
    }

    /// Call `obj.<name>(other)` if the type defines it; `None` for absent or `NotImplemented`.
    pub fn try_dunder(&mut self, obj: Value, name: Value, other: Value) -> PyResult<Option<Value>> {
        if !obj.is_obj() || !matches!(self.heap.get(obj), Obj::Instance(_) | Obj::Exc(_) | Obj::Node(_)) {
            return Ok(None);
        }
        match self.lookup_method(obj, name) {
            Some(m) => {
                let r = self.call(m, &[obj, other], &[])?;
                if r.is_obj() && matches!(self.heap.get(r), Obj::NotImplemented) {
                    return Ok(None);
                }
                Ok(Some(r))
            }
            None => Ok(None),
        }
    }

    pub fn inplace_op(&mut self, op: BinOp, a: Value, b: Value) -> PyResult {
        if a.is_obj() {
            match (self.heap.get(a), op) {
                (Obj::List(_), BinOp::Add) => {
                    let items = self.collect_iter(b)?;
                    if let Obj::List(l) = self.heap.get_mut(a) {
                        l.extend(items);
                    }
                    return Ok(a);
                }
                (Obj::List(_), BinOp::Mul) => {
                    let n = self.expect_int(b, "can't multiply sequence by non-int")?.max(0) as usize;
                    if let Obj::List(l) = self.heap.get_mut(a) {
                        let base = l.clone();
                        l.clear();
                        for _ in 0..n {
                            l.extend_from_slice(&base);
                        }
                    }
                    return Ok(a);
                }
                (Obj::Dict(_), BinOp::Or) => {
                    let items = self.mapping_items(b)?;
                    for (k, v) in items {
                        self.dict_set(a, k, v);
                    }
                    return Ok(a);
                }
                (Obj::Set(_), BinOp::Or | BinOp::And | BinOp::Sub | BinOp::Xor) => {
                    let r = self.set_op(op, a, b)?;
                    let d = match self.heap.take(r) {
                        Obj::Set(d) => d,
                        o => {
                            self.heap.put(r, o);
                            return Ok(r);
                        }
                    };
                    self.heap.put(r, Obj::Free);
                    self.heap.put(a, Obj::Set(d));
                    return Ok(a);
                }
                (Obj::Instance(_), _) => {
                    let name = match op {
                        BinOp::Add => self.n.iadd,
                        BinOp::Sub => self.n.isub,
                        BinOp::Mul => self.n.imul,
                        BinOp::Or => self.n.ior,
                        BinOp::And => self.n.iand,
                        _ => Value::UNDEF,
                    };
                    if !name.is_undef() {
                        if let Some(r) = self.try_dunder(a, name, b)? {
                            return Ok(r);
                        }
                    }
                }
                _ => {}
            }
        }
        self.binary_op(op, a, b)
    }

    fn int_op(&mut self, op: BinOp, x: i64, y: i64) -> PyResult {
        let r = match op {
            BinOp::Add => x.checked_add(y),
            BinOp::Sub => x.checked_sub(y),
            BinOp::Mul => x.checked_mul(y),
            BinOp::TrueDiv => {
                if y == 0 {
                    return Err(self.zero_division("division by zero"));
                }
                return Ok(Value::float(x as f64 / y as f64));
            }
            BinOp::FloorDiv => {
                if y == 0 {
                    return Err(self.zero_division("integer division or modulo by zero"));
                }
                Some(x.div_euclid(y) - if (x.rem_euclid(y) != 0) && (y < 0) { 1 } else { 0 })
            }
            BinOp::Mod => {
                if y == 0 {
                    return Err(self.zero_division("integer modulo by zero"));
                }
                let m = x.rem_euclid(y);
                Some(if y < 0 && m != 0 { m + y } else { m })
            }
            BinOp::Pow => {
                if y < 0 {
                    return Ok(Value::float((x as f64).powf(y as f64)));
                }
                let mut base = x;
                let mut exp = y as u64;
                let mut acc: i64 = 1;
                let mut ok = true;
                while exp > 0 {
                    if exp & 1 == 1 {
                        match acc.checked_mul(base) {
                            Some(v) => acc = v,
                            None => {
                                ok = false;
                                break;
                            }
                        }
                    }
                    exp >>= 1;
                    if exp > 0 {
                        match base.checked_mul(base) {
                            Some(v) => base = v,
                            None => {
                                ok = false;
                                break;
                            }
                        }
                    }
                }
                if ok {
                    Some(acc)
                } else {
                    None
                }
            }
            BinOp::LShift => {
                if y < 0 {
                    return Err(self.value_error("negative shift count"));
                }
                if y >= 63 {
                    if x == 0 {
                        Some(0)
                    } else {
                        None
                    }
                } else {
                    x.checked_shl(y as u32).filter(|r| (r >> y) == x)
                }
            }
            BinOp::RShift => {
                if y < 0 {
                    return Err(self.value_error("negative shift count"));
                }
                Some(if y >= 63 { if x < 0 { -1 } else { 0 } } else { x >> y })
            }
            BinOp::And => Some(x & y),
            BinOp::Or => Some(x | y),
            BinOp::Xor => Some(x ^ y),
            BinOp::MatMul => return Err(self.type_error("unsupported operand type(s) for @: 'int' and 'int'")),
        };
        match r {
            Some(v) => Ok(self.int(v)),
            None => Err(self.overflow_error("integer result too large for this runtime (64 bits)")),
        }
    }

    fn float_op(&mut self, op: BinOp, x: f64, y: f64) -> PyResult {
        let r = match op {
            BinOp::Add => x + y,
            BinOp::Sub => x - y,
            BinOp::Mul => x * y,
            BinOp::TrueDiv => {
                if y == 0.0 {
                    return Err(self.zero_division("float division by zero"));
                }
                x / y
            }
            BinOp::FloorDiv => {
                if y == 0.0 {
                    return Err(self.zero_division("float floor division by zero"));
                }
                (x / y).floor()
            }
            BinOp::Mod => {
                if y == 0.0 {
                    return Err(self.zero_division("float modulo by zero"));
                }
                let m = x % y;
                if m != 0.0 && (m < 0.0) != (y < 0.0) {
                    m + y
                } else {
                    m
                }
            }
            BinOp::Pow => {
                if x == 0.0 && y < 0.0 {
                    return Err(self.zero_division("0.0 cannot be raised to a negative power"));
                }
                x.powf(y)
            }
            _ => {
                return Err(self.type_error(format!("unsupported operand type(s) for {}: 'float' and 'float'", op.symbol())));
            }
        };
        Ok(Value::float(r))
    }

    fn set_op(&mut self, op: BinOp, a: Value, b: Value) -> PyResult {
        let frozen = matches!(self.heap.get(a), Obj::FrozenSet(_));
        let left: Vec<Value> = match self.heap.get(a) {
            Obj::Set(d) | Obj::FrozenSet(d) => d.keys().collect(),
            _ => return Err(self.type_error("set operation on a non-set")),
        };
        let right: Vec<Value> = match self.heap.get(b) {
            Obj::Set(d) | Obj::FrozenSet(d) => d.keys().collect(),
            _ => self.collect_iter(b)?,
        };
        let mut out = PyDict::new();
        match op {
            BinOp::Or => {
                for k in left.iter().chain(right.iter()) {
                    out.set(&self.heap, *k, Value::NONE);
                }
            }
            BinOp::And => {
                let mut rd = PyDict::new();
                for k in &right {
                    rd.set(&self.heap, *k, Value::NONE);
                }
                for k in &left {
                    if rd.contains(&self.heap, *k) {
                        out.set(&self.heap, *k, Value::NONE);
                    }
                }
            }
            BinOp::Sub => {
                let mut rd = PyDict::new();
                for k in &right {
                    rd.set(&self.heap, *k, Value::NONE);
                }
                for k in &left {
                    if !rd.contains(&self.heap, *k) {
                        out.set(&self.heap, *k, Value::NONE);
                    }
                }
            }
            _ => {
                let mut ld = PyDict::new();
                for k in &left {
                    ld.set(&self.heap, *k, Value::NONE);
                }
                let mut rd = PyDict::new();
                for k in &right {
                    rd.set(&self.heap, *k, Value::NONE);
                }
                for k in &left {
                    if !rd.contains(&self.heap, *k) {
                        out.set(&self.heap, *k, Value::NONE);
                    }
                }
                for k in &right {
                    if !ld.contains(&self.heap, *k) {
                        out.set(&self.heap, *k, Value::NONE);
                    }
                }
            }
        }
        Ok(self.heap.alloc(if frozen { Obj::FrozenSet(out) } else { Obj::Set(out) }))
    }

    pub fn unary_op(&mut self, op: UnOp, a: Value) -> PyResult {
        match op {
            UnOp::Not => {
                let t = self.truthy(a)?;
                Ok(Value::bool(!t))
            }
            UnOp::Neg => {
                if let Some(i) = self.as_i64(a) {
                    if !a.is_float() {
                        return match i.checked_neg() {
                            Some(v) => Ok(self.int(v)),
                            None => Err(self.overflow_error("integer result too large")),
                        };
                    }
                }
                if a.is_float() {
                    return Ok(Value::float(-a.as_float()));
                }
                let name = self.n.neg;
                self.unary_dunder(a, name, "-")
            }
            UnOp::Pos => {
                if self.as_i64(a).is_some() || a.is_float() {
                    return Ok(if a.is_bool() { Value::int(a.as_bool() as i32) } else { a });
                }
                let name = self.n.pos;
                self.unary_dunder(a, name, "+")
            }
            UnOp::Invert => {
                if let Some(i) = self.as_i64(a) {
                    if !a.is_float() {
                        return Ok(self.int(!i));
                    }
                }
                let name = self.n.invert;
                self.unary_dunder(a, name, "~")
            }
        }
    }

    fn unary_dunder(&mut self, a: Value, name: Value, sym: &str) -> PyResult {
        if let Some(m) = self.lookup_method(a, name) {
            return self.call(m, &[a], &[]);
        }
        let t = self.type_name(a);
        Err(self.type_error(format!("bad operand type for unary {sym}: '{t}'")))
    }

    // -- comparison ---------------------------------------------------------------------------------

    pub fn compare(&mut self, op: CmpOp, a: Value, b: Value) -> PyResult {
        if matches!(op, CmpOp::Eq | CmpOp::Ne) {
            if let Some(eq) = self.builtin_equality(a, b)? {
                return Ok(Value::bool(eq == (op == CmpOp::Eq)));
            }
        }
        if let Some(ord) = self.builtin_ordering(a, b)? {
            return Ok(Value::bool(match op {
                CmpOp::Lt => ord == core::cmp::Ordering::Less,
                CmpOp::Le => ord != core::cmp::Ordering::Greater,
                CmpOp::Gt => ord == core::cmp::Ordering::Greater,
                CmpOp::Ge => ord != core::cmp::Ordering::Less,
                CmpOp::Eq => ord == core::cmp::Ordering::Equal,
                CmpOp::Ne => ord != core::cmp::Ordering::Equal,
            }));
        }
        // Unordered builtins: equality by structure, everything else unsupported.
        if let Some(eq) = self.builtin_equality(a, b)? {
            return match op {
                CmpOp::Eq => Ok(Value::bool(eq)),
                CmpOp::Ne => Ok(Value::bool(!eq)),
                _ => {
                    let (ta, tb) = (self.type_name(a), self.type_name(b));
                    Err(self.type_error(format!("'{}' not supported between instances of '{}' and '{}'", op.symbol(), ta, tb)))
                }
            };
        }
        // Dunders.
        let (fwd, rev) = match op {
            CmpOp::Lt => (self.n.lt, self.n.gt),
            CmpOp::Le => (self.n.le, self.n.ge),
            CmpOp::Gt => (self.n.gt, self.n.lt),
            CmpOp::Ge => (self.n.ge, self.n.le),
            CmpOp::Eq => (self.n.eq, self.n.eq),
            CmpOp::Ne => (self.n.ne, self.n.ne),
        };
        if let Some(r) = self.try_dunder(a, fwd, b)? {
            return Ok(r);
        }
        if let Some(r) = self.try_dunder(b, rev, a)? {
            return Ok(r);
        }
        match op {
            CmpOp::Eq => Ok(Value::bool(self.is_same(a, b))),
            CmpOp::Ne => {
                // `!=` falls back to `not __eq__`.
                let eqn = self.n.eq;
                if let Some(r) = self.try_dunder(a, eqn, b)? {
                    let t = self.truthy(r)?;
                    return Ok(Value::bool(!t));
                }
                Ok(Value::bool(!self.is_same(a, b)))
            }
            _ => {
                let (ta, tb) = (self.type_name(a), self.type_name(b));
                Err(self.type_error(format!("'{}' not supported between instances of '{}' and '{}'", op.symbol(), ta, tb)))
            }
        }
    }

    /// `a == b` as a bool.
    pub fn eq(&mut self, a: Value, b: Value) -> PyResult<bool> {
        if a == b {
            return Ok(true);
        }
        let r = self.compare(CmpOp::Eq, a, b)?;
        self.truthy(r)
    }

    fn builtin_ordering(&mut self, a: Value, b: Value) -> PyResult<Option<core::cmp::Ordering>> {
        use core::cmp::Ordering;
        let a_num = self.as_f64(a).filter(|_| !a.is_obj() || matches!(self.heap.get(a), Obj::Int(_)));
        let b_num = self.as_f64(b).filter(|_| !b.is_obj() || matches!(self.heap.get(b), Obj::Int(_)));
        if let (Some(x), Some(y)) = (a_num, b_num) {
            if let (Some(i), Some(j)) = (self.as_i64(a), self.as_i64(b)) {
                if !a.is_float() && !b.is_float() {
                    return Ok(Some(i.cmp(&j)));
                }
            }
            return Ok(x.partial_cmp(&y).or(Some(Ordering::Less)).map(|o| if x.is_nan() || y.is_nan() { Ordering::Greater } else { o }).filter(|_| !(x.is_nan() || y.is_nan())).or({
                // NaN: every ordered comparison is false; equality false.
                None
            }));
        }
        if !(a.is_obj() && b.is_obj()) {
            return Ok(None);
        }
        // Strings, bytes, lists, tuples: lexicographic.
        let kind = |o: &Obj| match o {
            Obj::Str(_) => 1,
            Obj::Bytes(_) | Obj::ByteArray(_) => 2,
            Obj::List(_) => 3,
            Obj::Tuple(_) => 4,
            _ => 0,
        };
        let (ka, kb) = (kind(self.heap.get(a)), kind(self.heap.get(b)));
        if ka == 0 || ka != kb {
            return Ok(None);
        }
        match (self.heap.get(a), self.heap.get(b)) {
            (Obj::Str(x), Obj::Str(y)) => return Ok(Some(x.s.as_bytes().cmp(y.s.as_bytes()))),
            (Obj::Bytes(x), Obj::Bytes(y)) | (Obj::ByteArray(x), Obj::ByteArray(y)) => return Ok(Some(x.cmp(y))),
            _ => {}
        }
        let xs: Vec<Value> = match self.heap.get(a) {
            Obj::List(v) | Obj::Tuple(v) => v.clone(),
            _ => unreachable!(),
        };
        let ys: Vec<Value> = match self.heap.get(b) {
            Obj::List(v) | Obj::Tuple(v) => v.clone(),
            _ => unreachable!(),
        };
        for (x, y) in xs.iter().zip(ys.iter()) {
            if self.eq(*x, *y)? {
                continue;
            }
            // First differing element decides; it must be orderable.
            let lt = self.compare(CmpOp::Lt, *x, *y)?;
            return Ok(Some(if self.truthy(lt)? { Ordering::Less } else { Ordering::Greater }));
        }
        Ok(Some(xs.len().cmp(&ys.len())))
    }

    fn builtin_equality(&mut self, a: Value, b: Value) -> PyResult<Option<bool>> {
        if a.is_none() || b.is_none() {
            return Ok(Some(a == b));
        }
        // Numbers: exact for ints, by value across int/float/bool.
        let is_num = |vm: &Vm, v: Value| v.is_int() || v.is_float() || v.is_bool() || (v.is_obj() && matches!(vm.heap.get(v), Obj::Int(_)));
        if is_num(self, a) && is_num(self, b) {
            if !a.is_float() && !b.is_float() {
                return Ok(Some(self.as_i64(a) == self.as_i64(b)));
            }
            return Ok(Some(self.as_f64(a) == self.as_f64(b)));
        }
        if a.is_float() && b.is_float() {
            return Ok(Some(a.as_float() == b.as_float()));
        }
        if !(a.is_obj() && b.is_obj()) {
            if a.is_obj() || b.is_obj() {
                // number vs object: only an instance could answer
                let o = if a.is_obj() { a } else { b };
                if matches!(self.heap.get(o), Obj::Instance(_)) {
                    return Ok(None);
                }
                return Ok(Some(false));
            }
            return Ok(Some(a == b));
        }
        match (self.heap.get(a), self.heap.get(b)) {
            (Obj::Dict(x), Obj::Dict(y)) => {
                if x.len() != y.len() {
                    return Ok(Some(false));
                }
                let items: Vec<(Value, Value)> = x.items().collect();
                for (k, v) in items {
                    let other = match self.heap.get(b) {
                        Obj::Dict(y) => y.get(&self.heap, k),
                        _ => None,
                    };
                    match other {
                        Some(w) => {
                            if !self.eq(v, w)? {
                                return Ok(Some(false));
                            }
                        }
                        None => return Ok(Some(false)),
                    }
                }
                Ok(Some(true))
            }
            (Obj::Set(x), Obj::Set(y)) | (Obj::FrozenSet(x), Obj::FrozenSet(y)) | (Obj::Set(x), Obj::FrozenSet(y)) | (Obj::FrozenSet(x), Obj::Set(y)) => {
                Ok(Some(x.len() == y.len() && x.keys().all(|k| y.contains(&self.heap, k))))
            }
            (Obj::Range { start: s1, stop: e1, step: p1 }, Obj::Range { start: s2, stop: e2, step: p2 }) => Ok(Some(s1 == s2 && e1 == e2 && p1 == p2)),
            (Obj::Slice { start: s1, stop: e1, step: p1 }, Obj::Slice { start: s2, stop: e2, step: p2 }) => {
                let (s1, e1, p1, s2, e2, p2) = (*s1, *e1, *p1, *s2, *e2, *p2);
                Ok(Some(self.eq(s1, s2)? && self.eq(e1, e2)? && self.eq(p1, p2)?))
            }
            (Obj::Instance(_), _) | (_, Obj::Instance(_)) | (Obj::Exc(_), _) | (_, Obj::Exc(_)) | (Obj::Node(_), _) | (_, Obj::Node(_)) => Ok(None),
            (Obj::Str(x), Obj::Str(y)) => Ok(Some(x.hash == y.hash && x.s == y.s)),
            (Obj::List(_), Obj::List(_)) | (Obj::Tuple(_), Obj::Tuple(_)) => {
                let xs: Vec<Value> = match self.heap.get(a) {
                    Obj::List(v) | Obj::Tuple(v) => v.clone(),
                    _ => unreachable!(),
                };
                let ys: Vec<Value> = match self.heap.get(b) {
                    Obj::List(v) | Obj::Tuple(v) => v.clone(),
                    _ => unreachable!(),
                };
                if xs.len() != ys.len() {
                    return Ok(Some(false));
                }
                for (x, y) in xs.iter().zip(ys.iter()) {
                    if !self.eq(*x, *y)? {
                        return Ok(Some(false));
                    }
                }
                Ok(Some(true))
            }
            (Obj::Bytes(x), Obj::Bytes(y)) | (Obj::ByteArray(x), Obj::ByteArray(y)) | (Obj::Bytes(x), Obj::ByteArray(y)) | (Obj::ByteArray(x), Obj::Bytes(y)) => Ok(Some(x == y)),
            (Obj::Str(_), _) | (_, Obj::Str(_)) | (Obj::List(_), _) | (_, Obj::List(_)) | (Obj::Tuple(_), _) | (_, Obj::Tuple(_)) => Ok(Some(false)),
            _ => Ok(Some(a == b)),
        }
    }

    pub fn is_same(&self, a: Value, b: Value) -> bool {
        if a == b {
            return true;
        }
        if let (Some(x), Some(y)) = (self.js_handle(a), self.js_handle(b)) {
            if let Some(h) = self.js_hooks {
                return (h.same)(x, y);
            }
        }
        // Two boxed ints of the same value are `is`-equal in CPython only by accident; here
        // small ints are values, so `x is 5` behaves as CPython's cached small ints do.
        false
    }

    // -- truth, length, containment -------------------------------------------------------------

    pub fn truthy(&mut self, v: Value) -> PyResult<bool> {
        if v.is_bool() {
            return Ok(v.as_bool());
        }
        if v.is_int() {
            return Ok(v.as_int() != 0);
        }
        if v.is_float() {
            return Ok(v.as_float() != 0.0);
        }
        if v.is_none() {
            return Ok(false);
        }
        match self.heap.get(v) {
            Obj::Str(s) => Ok(!s.s.is_empty()),
            Obj::Int(i) => Ok(*i != 0),
            Obj::List(l) => Ok(!l.is_empty()),
            Obj::Tuple(t) => Ok(!t.is_empty()),
            Obj::Dict(d) | Obj::Set(d) | Obj::FrozenSet(d) => Ok(!d.is_empty()),
            Obj::Bytes(b) | Obj::ByteArray(b) => Ok(!b.is_empty()),
            Obj::Range { start, stop, step } => Ok(range_len(*start, *stop, *step) > 0),
            Obj::Js(h) => {
                let h = *h;
                let hooks = self.js()?;
                Ok((hooks.truthy)(self, h))
            }
            Obj::Instance(_) | Obj::Node(_) => {
                let name = self.n.bool_;
                if let Some(m) = self.lookup_method(v, name) {
                    let r = self.call(m, &[v], &[])?;
                    if !r.is_bool() {
                        return Err(self.type_error("__bool__ should return bool"));
                    }
                    return Ok(r.as_bool());
                }
                let name = self.n.len;
                if let Some(m) = self.lookup_method(v, name) {
                    let r = self.call(m, &[v], &[])?;
                    return Ok(self.as_i64(r).unwrap_or(1) != 0);
                }
                Ok(true)
            }
            _ => Ok(true),
        }
    }

    /// Length without dunders: builtin containers only.
    pub fn len_of(&self, v: Value) -> Option<usize> {
        if !v.is_obj() {
            return None;
        }
        match self.heap.get(v) {
            Obj::Str(s) => Some(s.len()),
            Obj::List(l) => Some(l.len()),
            Obj::Tuple(t) => Some(t.len()),
            Obj::Dict(d) | Obj::Set(d) | Obj::FrozenSet(d) => Some(d.len()),
            Obj::Bytes(b) | Obj::ByteArray(b) => Some(b.len()),
            Obj::Range { start, stop, step } => Some(range_len(*start, *stop, *step) as usize),
            _ => None,
        }
    }
    pub fn len(&mut self, v: Value) -> PyResult<usize> {
        if let Some(n) = self.len_of(v) {
            return Ok(n);
        }
        if let Some(h) = self.js_handle(v) {
            let hooks = self.js()?;
            let n = (hooks.len)(self, h);
            if n >= 0 {
                return Ok(n as usize);
            }
            return Err(self.type_error("JavaScript object has no length"));
        }
        let name = self.n.len;
        if let Some(m) = self.lookup_method(v, name) {
            let r = self.call(m, &[v], &[])?;
            return match self.as_i64(r) {
                Some(n) if n >= 0 => Ok(n as usize),
                Some(_) => Err(self.value_error("__len__() should return >= 0")),
                None => Err(self.type_error("'__len__' should return an int")),
            };
        }
        let t = self.type_name(v);
        Err(self.type_error(format!("object of type '{t}' has no len()")))
    }

    pub fn contains(&mut self, container: Value, item: Value) -> PyResult<bool> {
        if container.is_obj() {
            match self.heap.get(container) {
                Obj::Str(s) => {
                    return match self.as_str(item) {
                        Some(needle) => Ok(s.s.contains(needle)),
                        None => {
                            let t = self.type_name(item);
                            Err(self.type_error(format!("'in <string>' requires string as left operand, not {t}")))
                        }
                    };
                }
                Obj::Dict(_) | Obj::Set(_) | Obj::FrozenSet(_) => {
                    return self.key_contains(container, item);
                }
                Obj::List(v) | Obj::Tuple(v) => {
                    let items = v.clone();
                    for x in items {
                        if self.eq(x, item)? {
                            return Ok(true);
                        }
                    }
                    return Ok(false);
                }
                Obj::Bytes(b) | Obj::ByteArray(b) => {
                    if let Some(i) = self.as_i64(item) {
                        return Ok(b.contains(&(i as u8)));
                    }
                    if let Obj::Bytes(needle) = self.heap.get(item) {
                        return Ok(needle.is_empty() || b.windows(needle.len()).any(|w| w == needle.as_slice()));
                    }
                    return Ok(false);
                }
                Obj::Range { start, stop, step } => {
                    let (start, stop, step) = (*start, *stop, *step);
                    return Ok(match self.as_i64(item) {
                        Some(i) if !item.is_float() => {
                            if step > 0 {
                                i >= start && i < stop && (i - start) % step == 0
                            } else {
                                i <= start && i > stop && (start - i) % (-step) == 0
                            }
                        }
                        _ => false,
                    });
                }
                Obj::Instance(_) => {
                    let name = self.n.contains;
                    if let Some(m) = self.lookup_method(container, name) {
                        let r = self.call(m, &[container, item], &[])?;
                        return self.truthy(r);
                    }
                }
                _ => {}
            }
        }
        // Fall back to iteration.
        let it = self.get_iter(container)?;
        self.roots.push(it);
        let r = loop {
            match self.iter_next(it) {
                Ok(Some(x)) => match self.eq(x, item) {
                    Ok(true) => break Ok(true),
                    Ok(false) => {}
                    Err(e) => break Err(e),
                },
                Ok(None) => break Ok(false),
                Err(e) => break Err(e),
            }
        };
        self.roots.pop();
        r
    }

    // -- subscripts -----------------------------------------------------------------------------------

    pub fn get_item(&mut self, obj: Value, key: Value) -> PyResult {
        if !obj.is_obj() {
            let t = self.type_name(obj);
            return Err(self.type_error(format!("'{t}' object is not subscriptable")));
        }
        match self.heap.get(obj) {
            Obj::List(_) | Obj::Tuple(_) | Obj::Str(_) | Obj::Bytes(_) | Obj::ByteArray(_) | Obj::Range { .. } => {
                if key.is_obj() && matches!(self.heap.get(key), Obj::Slice { .. }) {
                    return self.get_slice(obj, key);
                }
                let n = self.len_of(obj).unwrap_or(0);
                let i = self.expect_index(key, n, obj)?;
                match self.heap.get(obj) {
                    Obj::List(v) | Obj::Tuple(v) => Ok(v[i]),
                    Obj::Str(s) => {
                        let c = s.char_at(i).unwrap();
                        let mut buf = [0u8; 4];
                        Ok(self.str(c.encode_utf8(&mut buf)))
                    }
                    Obj::Bytes(b) | Obj::ByteArray(b) => Ok(Value::int(b[i] as i32)),
                    Obj::Range { start, step, .. } => Ok(self.int(start + step * i as i64)),
                    _ => unreachable!(),
                }
            }
            Obj::Dict(_) => match self.key_get(obj, key)? {
                Some(v) => Ok(v),
                None => Err(self.key_error(key)),
            },
            Obj::Instance(_) | Obj::Exc(_) | Obj::Node(_) => {
                let name = self.n.getitem;
                match self.lookup_method(obj, name) {
                    Some(m) => self.call(m, &[obj, key], &[]),
                    None => {
                        let t = self.type_name(obj);
                        Err(self.type_error(format!("'{t}' object is not subscriptable")))
                    }
                }
            }
            Obj::Class(_) => {
                // `list[int]` and friends in a runtime expression: the class itself.
                let name = self.n.class_getitem;
                if let Some(m) = self.class_lookup(obj, name) {
                    return self.call(m, &[obj, key], &[]);
                }
                Ok(obj)
            }
            Obj::Js(_) => crate::builtins::js_get_item(self, obj, key),
            _ => {
                let t = self.type_name(obj);
                Err(self.type_error(format!("'{t}' object is not subscriptable")))
            }
        }
    }

    fn expect_index(&mut self, key: Value, n: usize, obj: Value) -> PyResult<usize> {
        let i = match self.as_i64(key) {
            Some(i) if !key.is_float() => i,
            _ => match self.index_of(key)? {
                Some(i) => i,
                None => {
                    let (t, k) = (self.type_name(obj), self.type_name(key));
                    return Err(self.type_error(format!("{t} indices must be integers or slices, not {k}")));
                }
            },
        };
        let idx = if i < 0 { i + n as i64 } else { i };
        if idx < 0 || idx >= n as i64 {
            let msg = match self.heap.get(obj) {
                Obj::Str(_) => "string index out of range".to_string(),
                Obj::Range { .. } => "range object index out of range".to_string(),
                Obj::Bytes(_) | Obj::ByteArray(_) => "index out of range".to_string(),
                _ => format!("{} index out of range", self.type_name(obj)),
            };
            return Err(self.index_error(msg));
        }
        Ok(idx as usize)
    }

    pub fn slice_bounds(&mut self, slice: Value, n: usize) -> PyResult<(i64, i64, i64)> {
        let (start, stop, step) = match self.heap.get(slice) {
            Obj::Slice { start, stop, step } => (*start, *stop, *step),
            _ => return Err(self.type_error("expected a slice")),
        };
        let step = if step.is_none() { 1 } else { self.expect_int(step, "slice step")? };
        if step == 0 {
            return Err(self.value_error("slice step cannot be zero"));
        }
        let n = n as i64;
        let clamp = |i: i64, lo: i64, hi: i64| i.max(lo).min(hi);
        let start = if start.is_none() {
            if step > 0 {
                0
            } else {
                n - 1
            }
        } else {
            let s = self.expect_int(start, "slice start")?;
            let s = if s < 0 { s + n } else { s };
            if step > 0 {
                clamp(s, 0, n)
            } else {
                clamp(s, -1, n - 1)
            }
        };
        let stop = if stop.is_none() {
            if step > 0 {
                n
            } else {
                -1
            }
        } else {
            let e = self.expect_int(stop, "slice stop")?;
            let e = if e < 0 { e + n } else { e };
            if step > 0 {
                clamp(e, 0, n)
            } else {
                clamp(e, -1, n - 1)
            }
        };
        Ok((start, stop, step))
    }

    pub fn slice_indices(start: i64, stop: i64, step: i64) -> Vec<usize> {
        let mut out = Vec::new();
        let mut i = start;
        if step > 0 {
            while i < stop {
                out.push(i as usize);
                i += step;
            }
        } else {
            while i > stop {
                out.push(i as usize);
                i += step;
            }
        }
        out
    }

    fn get_slice(&mut self, obj: Value, slice: Value) -> PyResult {
        let n = self.len_of(obj).unwrap_or(0);
        let (start, stop, step) = self.slice_bounds(slice, n)?;
        let idx = Vm::slice_indices(start, stop, step);
        match self.heap.get(obj) {
            Obj::List(v) => {
                let out: Vec<Value> = idx.iter().map(|&i| v[i]).collect();
                Ok(self.list(out))
            }
            Obj::Tuple(v) => {
                let out: Vec<Value> = idx.iter().map(|&i| v[i]).collect();
                Ok(self.tuple(out))
            }
            Obj::Str(s) => {
                if step == 1 {
                    let out = s.slice(start as usize, (stop.max(start)) as usize).to_string();
                    return Ok(self.string(out));
                }
                let chars: Vec<char> = s.s.chars().collect();
                let out: String = idx.iter().map(|&i| chars[i]).collect();
                Ok(self.string(out))
            }
            Obj::Bytes(b) => {
                let out: Vec<u8> = idx.iter().map(|&i| b[i]).collect();
                Ok(self.heap.alloc(Obj::Bytes(out)))
            }
            Obj::ByteArray(b) => {
                let out: Vec<u8> = idx.iter().map(|&i| b[i]).collect();
                Ok(self.heap.alloc(Obj::ByteArray(out)))
            }
            Obj::Range { start: rs, step: rstep, .. } => {
                let (rs, rstep) = (*rs, *rstep);
                let new_start = rs + rstep * start;
                let new_stop = rs + rstep * stop;
                Ok(self.heap.alloc(Obj::Range { start: new_start, stop: new_stop, step: rstep * step }))
            }
            _ => Err(self.type_error("unsliceable")),
        }
    }

    pub fn set_item(&mut self, obj: Value, key: Value, value: Value) -> PyResult<()> {
        if !obj.is_obj() {
            let t = self.type_name(obj);
            return Err(self.type_error(format!("'{t}' object does not support item assignment")));
        }
        match self.heap.get(obj) {
            Obj::List(_) => {
                if key.is_obj() && matches!(self.heap.get(key), Obj::Slice { .. }) {
                    let n = self.len_of(obj).unwrap_or(0);
                    let (start, stop, step) = self.slice_bounds(key, n)?;
                    let items = self.collect_iter(value)?;
                    if step == 1 {
                        if let Obj::List(l) = self.heap.get_mut(obj) {
                            let stop = stop.max(start) as usize;
                            l.splice(start as usize..stop, items);
                        }
                        return Ok(());
                    }
                    let idx = Vm::slice_indices(start, stop, step);
                    if idx.len() != items.len() {
                        return Err(self.value_error(format!("attempt to assign sequence of size {} to extended slice of size {}", items.len(), idx.len())));
                    }
                    if let Obj::List(l) = self.heap.get_mut(obj) {
                        for (i, v) in idx.into_iter().zip(items) {
                            l[i] = v;
                        }
                    }
                    return Ok(());
                }
                let n = self.len_of(obj).unwrap_or(0);
                let i = self.expect_index(key, n, obj)?;
                if let Obj::List(l) = self.heap.get_mut(obj) {
                    l[i] = value;
                }
                Ok(())
            }
            Obj::Dict(_) => self.key_set(obj, key, value),
            Obj::ByteArray(_) => {
                let n = self.len_of(obj).unwrap_or(0);
                let i = self.expect_index(key, n, obj)?;
                let b = self.expect_int(value, "byte")?;
                if let Obj::ByteArray(v) = self.heap.get_mut(obj) {
                    v[i] = b as u8;
                }
                Ok(())
            }
            Obj::Instance(_) | Obj::Exc(_) | Obj::Node(_) => {
                let name = self.n.setitem;
                match self.lookup_method(obj, name) {
                    Some(m) => {
                        self.call(m, &[obj, key, value], &[])?;
                        Ok(())
                    }
                    None => {
                        let t = self.type_name(obj);
                        Err(self.type_error(format!("'{t}' object does not support item assignment")))
                    }
                }
            }
            Obj::Js(_) => crate::builtins::js_set_item(self, obj, key, value),
            _ => {
                let t = self.type_name(obj);
                Err(self.type_error(format!("'{t}' object does not support item assignment")))
            }
        }
    }

    pub fn del_item(&mut self, obj: Value, key: Value) -> PyResult<()> {
        if !obj.is_obj() {
            let t = self.type_name(obj);
            return Err(self.type_error(format!("'{t}' object doesn't support item deletion")));
        }
        match self.heap.get(obj) {
            Obj::List(_) => {
                let n = self.len_of(obj).unwrap_or(0);
                if key.is_obj() && matches!(self.heap.get(key), Obj::Slice { .. }) {
                    let (start, stop, step) = self.slice_bounds(key, n)?;
                    let mut idx = Vm::slice_indices(start, stop, step);
                    idx.sort_unstable();
                    if let Obj::List(l) = self.heap.get_mut(obj) {
                        for i in idx.into_iter().rev() {
                            l.remove(i);
                        }
                    }
                    return Ok(());
                }
                let i = self.expect_index(key, n, obj)?;
                if let Obj::List(l) = self.heap.get_mut(obj) {
                    l.remove(i);
                }
                Ok(())
            }
            Obj::Dict(_) => {
                if self.key_remove(obj, key)?.is_none() {
                    return Err(self.key_error(key));
                }
                Ok(())
            }
            Obj::Instance(_) => {
                let name = self.n.delitem;
                match self.lookup_method(obj, name) {
                    Some(m) => {
                        self.call(m, &[obj, key], &[])?;
                        Ok(())
                    }
                    None => {
                        let t = self.type_name(obj);
                        Err(self.type_error(format!("'{t}' object doesn't support item deletion")))
                    }
                }
            }
            _ => {
                let t = self.type_name(obj);
                Err(self.type_error(format!("'{t}' object doesn't support item deletion")))
            }
        }
    }

    // -- iteration --------------------------------------------------------------------------------------

    pub fn get_iter(&mut self, v: Value) -> PyResult {
        if !v.is_obj() {
            let t = self.type_name(v);
            return Err(self.type_error(format!("'{t}' object is not iterable")));
        }
        let it = match self.heap.get(v) {
            Obj::List(_) => Iter::List { list: v, at: 0 },
            Obj::Tuple(_) => Iter::Tuple { tuple: v, at: 0 },
            Obj::Str(_) => Iter::Str { s: v, byte: 0 },
            Obj::Bytes(_) | Obj::ByteArray(_) => Iter::Bytes { b: v, at: 0 },
            Obj::Dict(_) => Iter::DictKeys { dict: v, at: 0 },
            Obj::Set(_) | Obj::FrozenSet(_) => Iter::Set { set: v, at: 0 },
            Obj::Range { start, stop, step } => Iter::Range { cur: *start, stop: *stop, step: *step },
            Obj::Iter(_) | Obj::Generator(_) => return Ok(v),
            Obj::Instance(_) | Obj::Exc(_) | Obj::Node(_) => {
                let name = self.n.iter;
                if let Some(m) = self.lookup_method(v, name) {
                    return self.call(m, &[v], &[]);
                }
                let gi = self.n.getitem;
                if self.lookup_method(v, gi).is_some() {
                    return Ok(self.heap.alloc(Obj::Iter(Iter::Reversed { seq: v, at: usize::MAX })));
                }
                let t = self.type_name(v);
                return Err(self.type_error(format!("'{t}' object is not iterable")));
            }
            Obj::Js(_) => return crate::builtins::js_iter(self, v),
            _ => {
                let t = self.type_name(v);
                return Err(self.type_error(format!("'{t}' object is not iterable")));
            }
        };
        Ok(self.heap.alloc(Obj::Iter(it)))
    }

    /// The next item of an iterator object, or `None` when exhausted.
    pub fn iter_next(&mut self, it: Value) -> PyResult<Option<Value>> {
        if !it.is_obj() {
            return Err(self.type_error("not an iterator"));
        }
        match self.heap.get_mut(it) {
            Obj::Iter(_) => {}
            Obj::Generator(_) => {
                let mut ret = Value::NONE;
                return self.gen_resume(it, Value::NONE, None, &mut ret);
            }
            Obj::Instance(_) => {
                let name = self.n.next;
                return match self.lookup_method(it, name) {
                    Some(m) => match self.call(m, &[it], &[]) {
                        Ok(v) => Ok(Some(v)),
                        Err(e) => {
                            let si = self.t.stop_iteration;
                            if self.exc_matches(e, si) {
                                Ok(None)
                            } else {
                                Err(e)
                            }
                        }
                    },
                    None => {
                        let t = self.type_name(it);
                        Err(self.type_error(format!("'{t}' object is not an iterator")))
                    }
                };
            }
            _ => {
                let t = self.type_name(it);
                return Err(self.type_error(format!("'{t}' object is not an iterator")));
            }
        }
        // Take the iterator state out, advance, put it back.
        let taken = self.heap.take(it);
        let base = self.roots.len();
        let mut state = match taken {
            Obj::Iter(s) => s,
            _ => unreachable!(),
        };
        // Iterators that call back into Python keep their referents rooted meanwhile.
        if matches!(state, Iter::Enumerate { .. } | Iter::Zip { .. } | Iter::Map { .. } | Iter::Filter { .. } | Iter::Callable { .. } | Iter::Reversed { .. }) {
            let o = Obj::Iter(state);
            o.trace(|v| self.roots.push(v));
            state = match o {
                Obj::Iter(s) => s,
                _ => unreachable!(),
            };
        }
        let r = self.advance(&mut state);
        self.heap.put(it, Obj::Iter(state));
        self.roots.truncate(base);
        r
    }

    fn advance(&mut self, state: &mut Iter) -> PyResult<Option<Value>> {
        Ok(match state {
            Iter::List { list, at } => match self.heap.get(*list) {
                Obj::List(v) if *at < v.len() => {
                    *at += 1;
                    Some(v[*at - 1])
                }
                _ => None,
            },
            Iter::Tuple { tuple, at } => match self.heap.get(*tuple) {
                Obj::Tuple(v) if *at < v.len() => {
                    *at += 1;
                    Some(v[*at - 1])
                }
                _ => None,
            },
            Iter::Str { s, byte } => {
                let c = match self.heap.get(*s) {
                    Obj::Str(ps) => ps.s[*byte..].chars().next(),
                    _ => None,
                };
                match c {
                    Some(c) => {
                        *byte += c.len_utf8();
                        let mut buf = [0u8; 4];
                        Some(self.str(c.encode_utf8(&mut buf)))
                    }
                    None => None,
                }
            }
            Iter::Bytes { b, at } => match self.heap.get(*b) {
                Obj::Bytes(v) | Obj::ByteArray(v) if *at < v.len() => {
                    *at += 1;
                    Some(Value::int(v[*at - 1] as i32))
                }
                _ => None,
            },
            Iter::Range { cur, stop, step } => {
                if (*step > 0 && *cur < *stop) || (*step < 0 && *cur > *stop) {
                    let v = *cur;
                    *cur += *step;
                    Some(self.int(v))
                } else {
                    None
                }
            }
            Iter::DictKeys { .. } | Iter::DictValues { .. } | Iter::DictItems { .. } => {
                let (dict, at, which) = match state {
                    Iter::DictKeys { dict, at } => (dict, at, 0),
                    Iter::DictValues { dict, at } => (dict, at, 1),
                    Iter::DictItems { dict, at } => (dict, at, 2),
                    _ => unreachable!(),
                };
                let entry = match self.heap.get(*dict) {
                    Obj::Dict(d) => d.entry_at(*at),
                    _ => None,
                };
                match entry {
                    Some((next, k, v)) => {
                        *at = next;
                        Some(match which {
                            0 => k,
                            1 => v,
                            _ => self.tuple(vec![k, v]),
                        })
                    }
                    None => None,
                }
            }
            Iter::Set { set, at } => {
                let entry = match self.heap.get(*set) {
                    Obj::Set(d) | Obj::FrozenSet(d) => d.entry_at(*at),
                    _ => None,
                };
                match entry {
                    Some((next, k, _)) => {
                        *at = next;
                        Some(k)
                    }
                    None => None,
                }
            }
            Iter::Enumerate { inner, count } => {
                let inner = *inner;
                match self.iter_next(inner)? {
                    Some(v) => {
                        let i = self.int(*count);
                        *count += 1;
                        Some(self.tuple(vec![i, v]))
                    }
                    None => None,
                }
            }
            Iter::Zip { iters } => {
                let iters = iters.clone();
                let mut items = Vec::with_capacity(iters.len());
                for it in iters {
                    match self.iter_next(it)? {
                        Some(v) => items.push(v),
                        None => return Ok(None),
                    }
                }
                if items.is_empty() {
                    None
                } else {
                    Some(self.tuple(items))
                }
            }
            Iter::Map { func, iters } => {
                let (func, iters) = (*func, iters.clone());
                let mut args = Vec::with_capacity(iters.len());
                for it in iters {
                    match self.iter_next(it)? {
                        Some(v) => args.push(v),
                        None => return Ok(None),
                    }
                }
                Some(self.call(func, &args, &[])?)
            }
            Iter::Filter { func, inner } => {
                let (func, inner) = (*func, *inner);
                loop {
                    match self.iter_next(inner)? {
                        Some(v) => {
                            let keep = if func.is_none() {
                                self.truthy(v)?
                            } else {
                                let r = self.call(func, &[v], &[])?;
                                self.truthy(r)?
                            };
                            if keep {
                                break Some(v);
                            }
                        }
                        None => break None,
                    }
                }
            }
            Iter::Reversed { seq, at } => {
                let seq = *seq;
                if *at == usize::MAX {
                    // The `__getitem__` sequence protocol, counting up from 0 (stored as MAX+k).
                    let mut i = 0usize;
                    // encode position in `at` as usize::MAX - k is impossible; use a side channel:
                    // we keep the count in the Range-like form by reusing `at` from MAX downwards.
                    i = i.wrapping_add(0);
                    let k = Value::int(i as i32);
                    let _ = k;
                }
                match self.heap.get(seq) {
                    Obj::List(v) | Obj::Tuple(v) => {
                        if *at == usize::MAX {
                            *at = v.len();
                        }
                        if *at == 0 {
                            None
                        } else {
                            *at -= 1;
                            Some(v[*at])
                        }
                    }
                    Obj::Instance(_) => {
                        // sequence protocol forward iteration
                        let name = self.n.getitem;
                        let m = self.lookup_method(seq, name);
                        let idx = if *at == usize::MAX { 0 } else { *at };
                        match m {
                            Some(m) => {
                                let k = Value::int(idx as i32);
                                match self.call(m, &[seq, k], &[]) {
                                    Ok(v) => {
                                        *at = idx + 1;
                                        Some(v)
                                    }
                                    Err(e) => {
                                        let ie = self.t.index_error;
                                        let se = self.t.stop_iteration;
                                        if self.exc_matches(e, ie) || self.exc_matches(e, se) {
                                            None
                                        } else {
                                            return Err(e);
                                        }
                                    }
                                }
                            }
                            None => None,
                        }
                    }
                    Obj::Str(s) => {
                        if *at == usize::MAX {
                            *at = s.len();
                        }
                        if *at == 0 {
                            None
                        } else {
                            *at -= 1;
                            let c = s.char_at(*at).unwrap();
                            let mut buf = [0u8; 4];
                            Some(self.str(c.encode_utf8(&mut buf)))
                        }
                    }
                    _ => None,
                }
            }
            Iter::Callable { func, sentinel } => {
                let (func, sentinel) = (*func, *sentinel);
                let v = self.call(func, &[], &[])?;
                if self.eq(v, sentinel)? {
                    *state = Iter::Done;
                    None
                } else {
                    Some(v)
                }
            }
            Iter::Done => None,
        })
    }

    /// Every item of an iterable, as a Vec. Lists and tuples are copied directly.
    pub fn collect_iter(&mut self, v: Value) -> PyResult<Vec<Value>> {
        if v.is_obj() {
            match self.heap.get(v) {
                Obj::List(items) | Obj::Tuple(items) => return Ok(items.clone()),
                Obj::Dict(d) => return Ok(d.keys().collect()),
                Obj::Set(d) | Obj::FrozenSet(d) => return Ok(d.keys().collect()),
                _ => {}
            }
        }
        // The partial result lives in a rooted list object: iterating may run Python (a
        // generator, an `__iter__`), and Python may collect.
        let it = self.get_iter(v)?;
        let acc = self.list(Vec::new());
        self.roots.push(it);
        self.roots.push(acc);
        let r = loop {
            match self.iter_next(it) {
                Ok(Some(x)) => {
                    if let Obj::List(l) = self.heap.get_mut(acc) {
                        l.push(x);
                    }
                }
                Ok(None) => break Ok(()),
                Err(e) => break Err(e),
            }
        };
        self.roots.pop();
        self.roots.pop();
        r?;
        Ok(match self.heap.take(acc) {
            Obj::List(l) => l,
            _ => Vec::new(),
        })
    }

    /// `(key, value)` pairs of a mapping: a dict, or anything with `keys()` and `__getitem__`.
    pub fn mapping_items(&mut self, v: Value) -> PyResult<Vec<(Value, Value)>> {
        if v.is_obj() {
            if let Obj::Dict(d) = self.heap.get(v) {
                return Ok(d.items().collect());
            }
        }
        let keys_name = self.n.keys;
        let keys_m = match self.get_attr(v, keys_name) {
            Ok(m) => m,
            Err(_) => {
                let t = self.type_name(v);
                return Err(self.type_error(format!("'{t}' object is not a mapping")));
            }
        };
        let keys = self.call(keys_m, &[], &[])?;
        let keys = self.collect_iter(keys)?;
        let kl = self.list(keys.clone());
        let acc = self.list(Vec::new());
        self.roots.push(kl);
        self.roots.push(acc);
        let mut r = Ok(());
        for k in keys {
            match self.get_item(v, k) {
                Ok(val) => {
                    let pair = self.tuple(vec![k, val]);
                    if let Obj::List(l) = self.heap.get_mut(acc) {
                        l.push(pair);
                    }
                }
                Err(e) => {
                    r = Err(e);
                    break;
                }
            }
        }
        self.roots.pop();
        self.roots.pop();
        r?;
        let pairs = match self.heap.take(acc) {
            Obj::List(l) => l,
            _ => Vec::new(),
        };
        Ok(pairs.iter().map(|&p| match self.heap.get(p) {
            Obj::Tuple(t) => (t[0], t[1]),
            _ => (Value::NONE, Value::NONE),
        }).collect())
    }

    /// `yield from` / `await`: send into the sub-iterator. `Some(v)` is a yield, `None` means
    /// it finished and `delegate_result` holds its return value.
    pub fn delegate_send(&mut self, sub: Value, sent: Value) -> PyResult<Option<Value>> {
        if sub.is_obj() {
            if let Obj::Generator(_) = self.heap.get(sub) {
                let mut ret = Value::NONE;
                let r = self.gen_resume(sub, sent, None, &mut ret)?;
                if r.is_none() {
                    self.delegate_result = ret;
                }
                return Ok(r);
            }
        }
        if !sent.is_none() {
            let send = self.n.send;
            if let Some(m) = self.lookup_method(sub, send) {
                return match self.call(m, &[sub, sent], &[]) {
                    Ok(v) => Ok(Some(v)),
                    Err(e) => {
                        let si = self.t.stop_iteration;
                        if self.exc_matches(e, si) {
                            self.delegate_result = self.exc_value(e);
                            Ok(None)
                        } else {
                            Err(e)
                        }
                    }
                };
            }
        }
        match self.iter_next(sub) {
            Ok(Some(v)) => Ok(Some(v)),
            Ok(None) => {
                self.delegate_result = Value::NONE;
                Ok(None)
            }
            Err(e) => {
                let si = self.t.stop_iteration;
                if self.exc_matches(e, si) {
                    self.delegate_result = self.exc_value(e);
                    Ok(None)
                } else {
                    Err(e)
                }
            }
        }
    }

    /// `StopIteration.value`: the first arg, or None.
    pub fn exc_value(&self, e: Value) -> Value {
        match self.heap.get(e) {
            Obj::Exc(x) => x.args.first().copied().unwrap_or(Value::NONE),
            _ => Value::NONE,
        }
    }

    pub fn get_awaitable(&mut self, v: Value) -> PyResult {
        if v.is_obj() {
            match self.heap.get(v) {
                Obj::Generator(g) if g.is_coroutine => return Ok(v),
                Obj::Generator(_) => {}
                Obj::Js(_) => {
                    let m = self.import_module("jsffi")?;
                    let key = self.intern("_await");
                    let f = self.get_attr(m, key)?;
                    return self.call(f, &[v], &[]);
                }
                Obj::Instance(_) => {
                    let name = self.n.await_;
                    if let Some(m) = self.lookup_method(v, name) {
                        return self.call(m, &[v], &[]);
                    }
                }
                _ => {}
            }
        }
        let t = self.type_name(v);
        Err(self.type_error(format!("object {t} can't be used in 'await' expression")))
    }

    // -- repr and str -----------------------------------------------------------------------------------

    pub fn repr(&mut self, v: Value) -> PyResult<String> {
        self.repr_depth(v, 0)
    }

    fn repr_depth(&mut self, v: Value, depth: u32) -> PyResult<String> {
        if depth > 20 {
            return Ok("...".into());
        }
        if v.is_int() {
            return Ok(v.as_int().to_string());
        }
        if v.is_bool() {
            return Ok(if v.as_bool() { "True" } else { "False" }.into());
        }
        if v.is_none() {
            return Ok("None".into());
        }
        if v.is_float() {
            return Ok(crate::format::float_repr(v.as_float()));
        }
        if v.is_undef() {
            return Ok("<undef>".into());
        }
        match self.heap.get(v) {
            Obj::Str(s) => Ok(crate::format::str_repr(&s.s)),
            Obj::Int(i) => Ok(i.to_string()),
            Obj::List(items) => {
                let items = items.clone();
                let mut parts = Vec::with_capacity(items.len());
                for x in items {
                    parts.push(self.repr_depth(x, depth + 1)?);
                }
                Ok(format!("[{}]", parts.join(", ")))
            }
            Obj::Tuple(items) => {
                let items = items.clone();
                let mut parts = Vec::with_capacity(items.len());
                for x in items {
                    parts.push(self.repr_depth(x, depth + 1)?);
                }
                if parts.len() == 1 {
                    Ok(format!("({},)", parts[0]))
                } else {
                    Ok(format!("({})", parts.join(", ")))
                }
            }
            Obj::Dict(d) => {
                let items: Vec<(Value, Value)> = d.items().collect();
                let mut parts = Vec::with_capacity(items.len());
                for (k, val) in items {
                    let ks = self.repr_depth(k, depth + 1)?;
                    let vs = self.repr_depth(val, depth + 1)?;
                    parts.push(format!("{ks}: {vs}"));
                }
                Ok(format!("{{{}}}", parts.join(", ")))
            }
            Obj::Set(d) | Obj::FrozenSet(d) => {
                let frozen = matches!(self.heap.get(v), Obj::FrozenSet(_));
                let keys: Vec<Value> = d.keys().collect();
                if keys.is_empty() {
                    return Ok(if frozen { "frozenset()" } else { "set()" }.into());
                }
                let mut parts = Vec::with_capacity(keys.len());
                for k in keys {
                    parts.push(self.repr_depth(k, depth + 1)?);
                }
                let inner = format!("{{{}}}", parts.join(", "));
                Ok(if frozen { format!("frozenset({inner})") } else { inner })
            }
            Obj::Bytes(b) => Ok(crate::format::bytes_repr(b, "b")),
            Obj::ByteArray(b) => Ok(format!("bytearray({})", crate::format::bytes_repr(b, "b"))),
            Obj::Func(f) => {
                let name = self.as_str(f.qualname).unwrap_or("?").to_string();
                Ok(format!("<function {name} at 0x{:x}>", v.as_obj()))
            }
            Obj::Native(n) => Ok(format!("<built-in function {}>", n.name)),
            Obj::Bound { func, this } => {
                let (func, this) = (*func, *this);
                let fname = match self.heap.get(func) {
                    Obj::Func(f) => self.as_str(f.qualname).unwrap_or("?").to_string(),
                    Obj::Native(n) => n.name.to_string(),
                    _ => "?".into(),
                };
                let owner = self.repr_depth(this, depth + 1)?;
                Ok(format!("<bound method {fname} of {owner}>"))
            }
            Obj::Class(c) => {
                let name = self.as_str(c.name).unwrap_or("?").to_string();
                let module = self.as_str(c.module).unwrap_or("").to_string();
                if module.is_empty() || module == "builtins" {
                    Ok(format!("<class '{name}'>"))
                } else {
                    Ok(format!("<class '{module}.{name}'>"))
                }
            }
            Obj::Instance(_) | Obj::Node(_) => {
                let name = self.n.repr;
                if let Some(m) = self.lookup_method(v, name) {
                    if !self.is_object_default(m, "__repr__") {
                        let r = self.call(m, &[v], &[])?;
                        return match self.as_str(r) {
                            Some(s) => Ok(s.to_string()),
                            None => Err(self.type_error("__repr__ returned non-string")),
                        };
                    }
                }
                let t = self.type_name(v);
                // `<__main__.Point object at …>`: the class's module, as CPython prints it.
                let cls = self.type_of(v);
                let module = match self.heap.get(cls) {
                    Obj::Class(c) => self.as_str(c.module).unwrap_or("").to_string(),
                    _ => String::new(),
                };
                if module.is_empty() || module == "builtins" {
                    Ok(format!("<{t} object at 0x{:x}>", v.as_obj()))
                } else {
                    Ok(format!("<{module}.{t} object at 0x{:x}>", v.as_obj()))
                }
            }
            Obj::Module(m) => {
                let name = self.as_str(m.name).unwrap_or("?").to_string();
                Ok(format!("<module '{name}'>"))
            }
            Obj::Exc(e) => {
                let class = e.class;
                let name = self.n.repr;
                if let Some(m) = self.class_lookup(class, name) {
                    if matches!(self.heap.get(m), Obj::Func(_)) {
                        let r = self.call(m, &[v], &[])?;
                        return Ok(self.as_str(r).unwrap_or("").to_string());
                    }
                }
                let args = match self.heap.get(v) {
                    Obj::Exc(e) => e.args.clone(),
                    _ => vec![],
                };
                let cname = self.class_name(class);
                let mut parts = Vec::new();
                for a in args {
                    parts.push(self.repr_depth(a, depth + 1)?);
                }
                Ok(format!("{cname}({})", parts.join(", ")))
            }
            Obj::Cell(_) => Ok(format!("<cell at 0x{:x}>", v.as_obj())),
            Obj::Range { start, stop, step } => Ok(if *step == 1 { format!("range({start}, {stop})") } else { format!("range({start}, {stop}, {step})") }),
            Obj::Slice { start, stop, step } => {
                let (a, b, c) = (*start, *stop, *step);
                let (sa, sb, sc) = (self.repr_depth(a, depth + 1)?, self.repr_depth(b, depth + 1)?, self.repr_depth(c, depth + 1)?);
                Ok(format!("slice({sa}, {sb}, {sc})"))
            }
            Obj::Property { .. } => Ok(format!("<property object at 0x{:x}>", v.as_obj())),
            Obj::StaticMethod(_) => Ok(format!("<staticmethod object at 0x{:x}>", v.as_obj())),
            Obj::ClassMethod(_) => Ok(format!("<classmethod object at 0x{:x}>", v.as_obj())),
            Obj::Iter(_) => Ok(format!("<iterator object at 0x{:x}>", v.as_obj())),
            Obj::Generator(g) => {
                let kind = if g.is_coroutine { "coroutine" } else { "generator" };
                let name = self.as_str(g.name).unwrap_or("?").to_string();
                Ok(format!("<{kind} object {name} at 0x{:x}>", v.as_obj()))
            }
            Obj::Template { strings, interpolations } => {
                let (s, i) = (*strings, *interpolations);
                let (ss, is) = (self.repr_depth(s, depth + 1)?, self.repr_depth(i, depth + 1)?);
                Ok(format!("Template(strings={ss}, interpolations={is})"))
            }
            Obj::Interpolation { value, expression, conversion, format_spec } => {
                let (a, b, c, d) = (*value, *expression, *conversion, *format_spec);
                let (sa, sb, sc, sd) = (self.repr_depth(a, depth + 1)?, self.repr_depth(b, depth + 1)?, self.repr_depth(c, depth + 1)?, self.repr_depth(d, depth + 1)?);
                Ok(format!("Interpolation({sa}, {sb}, {sc}, {sd})"))
            }
            Obj::Code(c) => Ok(format!("<code object {}>", c.name)),
            Obj::Js(h) => {
                let h = *h;
                let hooks = self.js()?;
                let kind = (hooks.kind)(self, h);
                let s = (hooks.str)(self, h)?;
                Ok(if kind == "function" { format!("<JsProxy function>") } else { s })
            }
            Obj::Super { .. } => Ok("<super>".into()),
            Obj::NotImplemented => Ok("NotImplemented".into()),
            Obj::Ellipsis => Ok("Ellipsis".into()),
            Obj::Free => Ok("<free>".into()),
        }
    }

    /// True when `m` is the `object` class's own native for `name` (so instances fall through
    /// to the default repr rather than recursing).
    fn is_object_default(&self, m: Value, name: &str) -> bool {
        match self.heap.get(m) {
            Obj::Native(n) => n.name == name && {
                let key = self.interned_get(name);
                key.map(|k| self.class_lookup(self.t.object, k) == Some(m)).unwrap_or(false)
            },
            _ => false,
        }
    }
    pub fn interned_get(&self, s: &str) -> Option<Value> {
        self.interned_lookup(s)
    }

    pub fn str_of(&mut self, v: Value) -> PyResult<String> {
        if v.is_obj() {
            match self.heap.get(v) {
                Obj::Str(s) => return Ok(s.s.to_string()),
                Obj::Js(h) => {
                    let h = *h;
                    let hooks = self.js()?;
                    return (hooks.str)(self, h);
                }
                Obj::Instance(_) | Obj::Node(_) => {
                    let name = self.n.str_;
                    if let Some(m) = self.lookup_method(v, name) {
                        if !self.is_object_default(m, "__str__") {
                            let r = self.call(m, &[v], &[])?;
                            return match self.as_str(r) {
                                Some(s) => Ok(s.to_string()),
                                None => Err(self.type_error("__str__ returned non-string")),
                            };
                        }
                    }
                    return self.repr(v);
                }
                Obj::Exc(e) => {
                    let class = e.class;
                    let name = self.n.str_;
                    if let Some(m) = self.class_lookup(class, name) {
                        if matches!(self.heap.get(m), Obj::Func(_)) {
                            let r = self.call(m, &[v], &[])?;
                            return Ok(self.as_str(r).unwrap_or("").to_string());
                        }
                    }
                    let args = match self.heap.get(v) {
                        Obj::Exc(e) => e.args.clone(),
                        _ => vec![],
                    };
                    let ke = self.t.key_error;
                    if args.len() == 1 && self.exc_matches(v, ke) {
                        return self.repr(args[0]);
                    }
                    return match args.len() {
                        0 => Ok(String::new()),
                        1 => self.str_of(args[0]),
                        _ => {
                            let t = self.tuple(args);
                            self.repr(t)
                        }
                    };
                }
                _ => {}
            }
        }
        self.repr(v)
    }

    /// `format(value, spec)`.
    pub fn format_value(&mut self, v: Value, spec: &str) -> PyResult<String> {
        if v.is_obj() {
            if let Obj::Instance(_) = self.heap.get(v) {
                let name = self.n.format;
                if let Some(m) = self.lookup_method(v, name) {
                    if !self.is_object_default(m, "__format__") {
                        let s = self.str(spec);
                        let r = self.call(m, &[v, s], &[])?;
                        return self.expect_str(r, "__format__ result");
                    }
                }
                if spec.is_empty() {
                    return self.str_of(v);
                }
                let t = self.type_name(v);
                return Err(self.type_error(format!("unsupported format string passed to {t}.__format__")));
            }
        }
        crate::format::format_builtin(self, v, spec)
    }

    fn percent_format(&mut self, fmt: Value, args: Value) -> PyResult {
        let s = self.as_str(fmt).unwrap_or("").to_string();
        let out = crate::format::percent_format(self, &s, args)?;
        Ok(self.string(out))
    }
}

pub fn range_len(start: i64, stop: i64, step: i64) -> i64 {
    if step > 0 && start < stop {
        (stop - start + step - 1) / step
    } else if step < 0 && start > stop {
        (start - stop - step - 1) / (-step)
    } else {
        0
    }
}
