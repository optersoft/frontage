//! The standard modules the runtime carries: `sys`, `math`, `time`, `json`, `random` in Rust;
//! `io`, `traceback`, `functools`, `collections`, `typing`, `string.templatelib` as Python
//! source compiled on first import (precompiled into the framework archive in the browser).

use crate::builtins::{arg, kwarg, opt};
use crate::dict::PyDict;
use crate::object::*;
use crate::value::Value;
use crate::vm::{PyResult, Vm};

pub fn install(vm: &mut Vm) {
    vm.builtin_modules.insert("sys", mod_sys);
    vm.builtin_modules.insert("_core", crate::core::install_module);
    vm.builtin_modules.insert("_dom", crate::dom::install_module);
    vm.builtin_modules.insert("_view", crate::view::install_module);
    vm.builtin_modules.insert("math", mod_math);
    vm.builtin_modules.insert("time", mod_time);
    vm.builtin_modules.insert("json", mod_json);
    vm.builtin_modules.insert("random", mod_random);
    vm.builtin_modules.insert("_frontage", mod_frontage);
    vm.builtin_modules.insert("gc", mod_gc);
    for (name, _) in PY_MODULES {
        vm.builtin_modules.insert(name, mod_python);
    }
}

fn add_fn(vm: &mut Vm, dict: Value, name: &'static str, f: NativeFn) {
    let nf = vm.native(name, f);
    vm.dict_set_str(dict, name, nf);
}

fn module_with(vm: &mut Vm, name: &str) -> (Value, Value) {
    let m = vm.new_module(name);
    let d = vm.module_dict(m);
    (m, d)
}

// -- sys ----------------------------------------------------------------------------------------

fn mod_sys(vm: &mut Vm) -> PyResult {
    let (m, d) = module_with(vm, "sys");
    let platform = vm.str("frontage");
    vm.dict_set_str(d, "platform", platform);
    let impl_cls_name = vm.str("implementation");
    let impl_mod = vm.intern("sys");
    let impl_ns = vm.dict(PyDict::new());
    let impl_cls = vm.make_class(impl_cls_name, vec![], impl_ns, impl_mod)?;
    let implementation = vm.call(impl_cls, &[], &[])?;
    let n = vm.str("frontage");
    let name_key = vm.intern("name");
    vm.set_attr(implementation, name_key, n)?;
    let ver = vec![Value::int(0), Value::int(0), Value::int(1)];
    let ver = vm.tuple(ver);
    let vk = vm.intern("version");
    vm.set_attr(implementation, vk, ver)?;
    vm.dict_set_str(d, "implementation", implementation);
    let vi = vec![Value::int(3), Value::int(14), Value::int(0)];
    let vi = vm.tuple(vi);
    vm.dict_set_str(d, "version_info", vi);
    let v = vm.str("3.14.0 (frontage)");
    vm.dict_set_str(d, "version", v);
    let modules = vm.modules;
    vm.dict_set_str(d, "modules", modules);
    let items: Vec<Value> = vm.argv.clone().iter().map(|a| vm.str(a)).collect();
    let argv = vm.list(items);
    vm.dict_set_str(d, "argv", argv);
    let path = vm.list(vec![]);
    vm.dict_set_str(d, "path", path);
    let maxsize = vm.int(i64::MAX);
    vm.dict_set_str(d, "maxsize", maxsize);
    vm.dict_set_str(d, "byteorder", vm.n.empty);
    let little = vm.str("little");
    vm.dict_set_str(d, "byteorder", little);
    add_fn(vm, d, "print_exception", sys_print_exception);
    add_fn(vm, d, "exc_info", sys_exc_info);
    add_fn(vm, d, "exit", sys_exit);
    add_fn(vm, d, "getrecursionlimit", sys_getrecursionlimit);
    add_fn(vm, d, "setrecursionlimit", sys_setrecursionlimit);
    add_fn(vm, d, "intern", sys_intern);
    add_fn(vm, d, "getsizeof", sys_getsizeof);
    // stdout / stderr: objects with `write`.
    for (attr, which) in [("stdout", 1), ("stderr", 2)] {
        let cls_name = vm.str("TextStream");
        let ns = vm.dict(PyDict::new());
        let cls = vm.make_class(cls_name, vec![], ns, impl_mod)?;
        crate::builtins::add_method(vm, cls, "write", if which == 1 { stream_write_out } else { stream_write_err });
        crate::builtins::add_method(vm, cls, "flush", stream_flush);
        let obj = vm.call(cls, &[], &[])?;
        vm.dict_set_str(d, attr, obj);
    }
    Ok(m)
}
fn stream_write_out(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = arg(vm, args, 1, "write")?;
    let s = vm.expect_str(s, "text")?;
    vm.host.write_stdout(&s);
    Ok(vm.int(s.len() as i64))
}
fn stream_write_err(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = arg(vm, args, 1, "write")?;
    let s = vm.expect_str(s, "text")?;
    vm.host.write_stderr(&s);
    Ok(vm.int(s.len() as i64))
}
fn stream_flush(_vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::NONE)
}
fn sys_print_exception(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let e = arg(vm, args, 0, "print_exception")?;
    let text = vm.format_exception(e);
    match opt(args, 1) {
        Some(file) if !file.is_none() => {
            let w = vm.intern("write");
            let m = vm.get_attr(file, w)?;
            let s = vm.string(text);
            vm.call(m, &[s], &[])?;
        }
        _ => vm.host.write_stderr(&text),
    }
    Ok(Value::NONE)
}
fn sys_exc_info(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let e = vm.current_exception();
    let t = if e.is_none() { Value::NONE } else { vm.type_of(e) };
    Ok(vm.tuple(vec![t, e, Value::NONE]))
}
fn sys_exit(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let c = vm.t.system_exit;
    let e = vm.exception(c, "");
    if let Some(&code) = args.first() {
        if let Obj::Exc(x) = vm.heap.get_mut(e) {
            x.args = vec![code];
        }
    }
    Err(e)
}
fn sys_getrecursionlimit(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(vm.int(vm.max_depth as i64))
}
fn sys_setrecursionlimit(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let n = arg(vm, args, 0, "setrecursionlimit")?;
    let n = vm.expect_int(n, "limit")?;
    vm.max_depth = n.clamp(10, 5000) as u32;
    Ok(Value::NONE)
}
fn sys_intern(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = arg(vm, args, 0, "intern")?;
    let s = vm.expect_str(s, "string")?;
    Ok(vm.intern(&s))
}
fn sys_getsizeof(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(vm.int(16))
}

// -- math ----------------------------------------------------------------------------------------

fn f64_arg(vm: &mut Vm, args: &[Value], i: usize, name: &str) -> PyResult<f64> {
    let v = arg(vm, args, i, name)?;
    match vm.as_f64(v) {
        Some(f) => Ok(f),
        None => {
            let t = vm.type_name(v);
            Err(vm.type_error(format!("must be real number, not {t}")))
        }
    }
}
macro_rules! math1 {
    ($name:ident, $f:expr) => {
        fn $name(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
            let x = f64_arg(vm, args, 0, stringify!($name))?;
            let f: fn(f64) -> f64 = $f;
            Ok(Value::float(f(x)))
        }
    };
}
math1!(m_sqrt, |x| x.sqrt());
math1!(m_exp, |x| x.exp());
math1!(m_sin, |x| x.sin());
math1!(m_cos, |x| x.cos());
math1!(m_tan, |x| x.tan());
math1!(m_asin, |x| x.asin());
math1!(m_acos, |x| x.acos());
math1!(m_atan, |x| x.atan());
math1!(m_sinh, |x| x.sinh());
math1!(m_cosh, |x| x.cosh());
math1!(m_tanh, |x| x.tanh());
math1!(m_fabs, |x| x.abs());
math1!(m_log2, |x| x.log2());
math1!(m_log10, |x| x.log10());
math1!(m_degrees, |x| x.to_degrees());
math1!(m_radians, |x| x.to_radians());
math1!(m_expm1, |x| x.exp_m1());
math1!(m_log1p, |x| x.ln_1p());

fn m_log(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let x = f64_arg(vm, args, 0, "log")?;
    if x <= 0.0 {
        return Err(vm.value_error("math domain error"));
    }
    match opt(args, 1) {
        Some(_) => {
            let b = f64_arg(vm, args, 1, "log")?;
            Ok(Value::float(x.ln() / b.ln()))
        }
        None => Ok(Value::float(x.ln())),
    }
}
fn m_pow(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let x = f64_arg(vm, args, 0, "pow")?;
    let y = f64_arg(vm, args, 1, "pow")?;
    Ok(Value::float(x.powf(y)))
}
fn m_atan2(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let y = f64_arg(vm, args, 0, "atan2")?;
    let x = f64_arg(vm, args, 1, "atan2")?;
    Ok(Value::float(y.atan2(x)))
}
fn m_hypot(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let mut acc = 0.0;
    for i in 0..args.len() {
        let x = f64_arg(vm, args, i, "hypot")?;
        acc += x * x;
    }
    Ok(Value::float(acc.sqrt()))
}
fn m_fmod(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let x = f64_arg(vm, args, 0, "fmod")?;
    let y = f64_arg(vm, args, 1, "fmod")?;
    Ok(Value::float(x % y))
}
fn m_copysign(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let x = f64_arg(vm, args, 0, "copysign")?;
    let y = f64_arg(vm, args, 1, "copysign")?;
    Ok(Value::float(x.copysign(y)))
}
fn to_int_result(vm: &mut Vm, f: f64) -> PyResult {
    if f.is_nan() {
        return Err(vm.value_error("cannot convert float NaN to integer"));
    }
    if f.is_infinite() {
        return Err(vm.overflow_error("cannot convert float infinity to integer"));
    }
    Ok(vm.int(f as i64))
}
fn m_floor(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "floor")?;
    if let Some(i) = vm.as_i64(v).filter(|_| !v.is_float()) {
        return Ok(vm.int(i));
    }
    let x = f64_arg(vm, args, 0, "floor")?;
    to_int_result(vm, x.floor())
}
fn m_ceil(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "ceil")?;
    if let Some(i) = vm.as_i64(v).filter(|_| !v.is_float()) {
        return Ok(vm.int(i));
    }
    let x = f64_arg(vm, args, 0, "ceil")?;
    to_int_result(vm, x.ceil())
}
fn m_trunc(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let x = f64_arg(vm, args, 0, "trunc")?;
    to_int_result(vm, x.trunc())
}
fn m_isnan(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let x = f64_arg(vm, args, 0, "isnan")?;
    Ok(Value::bool(x.is_nan()))
}
fn m_isinf(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let x = f64_arg(vm, args, 0, "isinf")?;
    Ok(Value::bool(x.is_infinite()))
}
fn m_isfinite(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let x = f64_arg(vm, args, 0, "isfinite")?;
    Ok(Value::bool(x.is_finite()))
}
fn m_isclose(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let a = f64_arg(vm, args, 0, "isclose")?;
    let b = f64_arg(vm, args, 1, "isclose")?;
    let rel = kwarg(vm, kwargs, "rel_tol").and_then(|v| vm.as_f64(v)).unwrap_or(1e-9);
    let abs = kwarg(vm, kwargs, "abs_tol").and_then(|v| vm.as_f64(v)).unwrap_or(0.0);
    Ok(Value::bool((a - b).abs() <= (rel * a.abs().max(b.abs())).max(abs)))
}
fn m_gcd(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let mut acc: i64 = 0;
    for &v in args {
        let mut x = vm.expect_int(v, "gcd")?.abs();
        let mut y = acc;
        while y != 0 {
            let t = x % y;
            x = y;
            y = t;
        }
        acc = x;
    }
    Ok(vm.int(acc))
}
fn m_factorial(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "factorial")?;
    let n = vm.expect_int(v, "n")?;
    if n < 0 {
        return Err(vm.value_error("factorial() not defined for negative values"));
    }
    let mut acc: i64 = 1;
    for i in 2..=n {
        acc = match acc.checked_mul(i) {
            Some(v) => v,
            None => return Err(vm.overflow_error("factorial() result too large for this runtime")),
        };
    }
    Ok(vm.int(acc))
}
fn m_fsum(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "fsum")?;
    let items = vm.collect_iter(v)?;
    // Shewchuk's exact partial sums, as CPython's fsum.
    let mut partials: Vec<f64> = Vec::new();
    for it in items {
        let mut x = vm.as_f64(it).unwrap_or(0.0);
        let mut i = 0;
        for j in 0..partials.len() {
            let mut y = partials[j];
            if x.abs() < y.abs() {
                core::mem::swap(&mut x, &mut y);
            }
            let hi = x + y;
            let lo = y - (hi - x);
            if lo != 0.0 {
                partials[i] = lo;
                i += 1;
            }
            x = hi;
        }
        partials.truncate(i);
        partials.push(x);
    }
    Ok(Value::float(partials.iter().sum()))
}

fn mod_math(vm: &mut Vm) -> PyResult {
    let (m, d) = module_with(vm, "math");
    vm.dict_set_str(d, "pi", Value::float(core::f64::consts::PI));
    vm.dict_set_str(d, "e", Value::float(core::f64::consts::E));
    vm.dict_set_str(d, "tau", Value::float(core::f64::consts::TAU));
    vm.dict_set_str(d, "inf", Value::float(f64::INFINITY));
    vm.dict_set_str(d, "nan", Value::float(f64::NAN));
    for (name, f) in [
        ("sqrt", m_sqrt as NativeFn),
        ("exp", m_exp),
        ("expm1", m_expm1),
        ("log", m_log),
        ("log1p", m_log1p),
        ("log2", m_log2),
        ("log10", m_log10),
        ("pow", m_pow),
        ("sin", m_sin),
        ("cos", m_cos),
        ("tan", m_tan),
        ("asin", m_asin),
        ("acos", m_acos),
        ("atan", m_atan),
        ("atan2", m_atan2),
        ("sinh", m_sinh),
        ("cosh", m_cosh),
        ("tanh", m_tanh),
        ("hypot", m_hypot),
        ("fabs", m_fabs),
        ("fmod", m_fmod),
        ("copysign", m_copysign),
        ("floor", m_floor),
        ("ceil", m_ceil),
        ("trunc", m_trunc),
        ("isnan", m_isnan),
        ("isinf", m_isinf),
        ("isfinite", m_isfinite),
        ("isclose", m_isclose),
        ("gcd", m_gcd),
        ("factorial", m_factorial),
        ("degrees", m_degrees),
        ("radians", m_radians),
        ("fsum", m_fsum),
    ] {
        add_fn(vm, d, name, f);
    }
    Ok(m)
}

// -- time ----------------------------------------------------------------------------------------

fn t_time(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::float(vm.host.time_s()))
}
fn t_monotonic(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::float(vm.host.now_ms() / 1000.0))
}
fn t_ticks_ms(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let ms = vm.host.now_ms() as i64;
    Ok(vm.int(ms))
}
fn t_ticks_us(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let us = (vm.host.now_ms() * 1000.0) as i64;
    Ok(vm.int(us))
}
fn t_ticks_diff(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let a = arg(vm, args, 0, "ticks_diff")?;
    let b = arg(vm, args, 1, "ticks_diff")?;
    let (a, b) = (vm.expect_int(a, "a")?, vm.expect_int(b, "b")?);
    Ok(vm.int(a - b))
}
fn t_sleep(_vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::NONE)
}
fn mod_time(vm: &mut Vm) -> PyResult {
    let (m, d) = module_with(vm, "time");
    for (name, f) in [("time", t_time as NativeFn), ("monotonic", t_monotonic), ("perf_counter", t_monotonic), ("ticks_ms", t_ticks_ms), ("ticks_us", t_ticks_us), ("ticks_diff", t_ticks_diff), ("sleep", t_sleep)] {
        add_fn(vm, d, name, f);
    }
    Ok(m)
}

// -- random ------------------------------------------------------------------------------------

fn r_random(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let r = vm.host.random_u64();
    Ok(Value::float((r >> 11) as f64 / (1u64 << 53) as f64))
}
fn r_randint(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let a = arg(vm, args, 0, "randint")?;
    let b = arg(vm, args, 1, "randint")?;
    let (a, b) = (vm.expect_int(a, "a")?, vm.expect_int(b, "b")?);
    if b < a {
        return Err(vm.value_error("empty range for randint"));
    }
    let span = (b - a + 1) as u64;
    let r = vm.host.random_u64() % span;
    Ok(vm.int(a + r as i64))
}
fn r_randrange(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let a = arg(vm, args, 0, "randrange")?;
    let a = vm.expect_int(a, "start")?;
    let (start, stop) = match opt(args, 1) {
        Some(b) => (a, vm.expect_int(b, "stop")?),
        None => (0, a),
    };
    if stop <= start {
        return Err(vm.value_error("empty range for randrange()"));
    }
    let r = vm.host.random_u64() % ((stop - start) as u64);
    Ok(vm.int(start + r as i64))
}
fn r_choice(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let seq = arg(vm, args, 0, "choice")?;
    let items = vm.collect_iter(seq)?;
    if items.is_empty() {
        return Err(vm.index_error("Cannot choose from an empty sequence"));
    }
    let i = (vm.host.random_u64() % items.len() as u64) as usize;
    Ok(items[i])
}
fn r_shuffle(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let l = arg(vm, args, 0, "shuffle")?;
    let mut items = vm.collect_iter(l)?;
    for i in (1..items.len()).rev() {
        let j = (vm.host.random_u64() % (i as u64 + 1)) as usize;
        items.swap(i, j);
    }
    if let Obj::List(v) = vm.heap.get_mut(l) {
        *v = items;
    }
    Ok(Value::NONE)
}
fn r_uniform(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let a = f64_arg(vm, args, 0, "uniform")?;
    let b = f64_arg(vm, args, 1, "uniform")?;
    let r = (vm.host.random_u64() >> 11) as f64 / (1u64 << 53) as f64;
    Ok(Value::float(a + (b - a) * r))
}
fn r_seed(_vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::NONE)
}
fn mod_random(vm: &mut Vm) -> PyResult {
    let (m, d) = module_with(vm, "random");
    for (name, f) in [("random", r_random as NativeFn), ("randint", r_randint), ("randrange", r_randrange), ("choice", r_choice), ("shuffle", r_shuffle), ("uniform", r_uniform), ("seed", r_seed)] {
        add_fn(vm, d, name, f);
    }
    Ok(m)
}

// -- json ------------------------------------------------------------------------------------------

fn mod_json(vm: &mut Vm) -> PyResult {
    let (m, d) = module_with(vm, "json");
    add_fn(vm, d, "loads", json_loads);
    add_fn(vm, d, "dumps", json_dumps);
    let err_name = vm.str("JSONDecodeError");
    let ns = vm.dict(PyDict::new());
    let base = vm.t.value_error;
    let modname = vm.intern("json");
    let err = vm.make_class(err_name, vec![base], ns, modname)?;
    vm.dict_set_str(d, "JSONDecodeError", err);
    Ok(m)
}

struct JsonParser<'a> {
    s: &'a [u8],
    i: usize,
}

impl<'a> JsonParser<'a> {
    fn ws(&mut self) {
        while self.i < self.s.len() && matches!(self.s[self.i], b' ' | b'\n' | b'\r' | b'\t') {
            self.i += 1;
        }
    }
    fn err(&self, vm: &mut Vm, msg: &str) -> Value {
        let c = vm.interned_lookup("JSONDecodeError").unwrap_or(vm.t.value_error);
        let cls = vm.dict_get_str(vm.modules, "json").and_then(|m| {
            let d = vm.module_dict(m);
            vm.dict_get(d, c)
        });
        let cls = cls.unwrap_or(vm.t.value_error);
        vm.exception(cls, format!("{msg}: char {}", self.i))
    }
    fn value(&mut self, vm: &mut Vm, depth: u32) -> PyResult {
        if depth > 200 {
            return Err(self.err(vm, "too deeply nested"));
        }
        self.ws();
        if self.i >= self.s.len() {
            return Err(self.err(vm, "Expecting value"));
        }
        match self.s[self.i] {
            b'{' => {
                self.i += 1;
                let mut d = PyDict::new();
                self.ws();
                if self.i < self.s.len() && self.s[self.i] == b'}' {
                    self.i += 1;
                    return Ok(vm.dict(d));
                }
                loop {
                    self.ws();
                    if self.i >= self.s.len() || self.s[self.i] != b'"' {
                        return Err(self.err(vm, "Expecting property name enclosed in double quotes"));
                    }
                    let k = self.string(vm)?;
                    self.ws();
                    if self.i >= self.s.len() || self.s[self.i] != b':' {
                        return Err(self.err(vm, "Expecting ':' delimiter"));
                    }
                    self.i += 1;
                    let v = self.value(vm, depth + 1)?;
                    d.set(&vm.heap, k, v);
                    self.ws();
                    if self.i < self.s.len() && self.s[self.i] == b',' {
                        self.i += 1;
                        continue;
                    }
                    if self.i < self.s.len() && self.s[self.i] == b'}' {
                        self.i += 1;
                        return Ok(vm.dict(d));
                    }
                    return Err(self.err(vm, "Expecting ',' delimiter"));
                }
            }
            b'[' => {
                self.i += 1;
                let mut items = Vec::new();
                self.ws();
                if self.i < self.s.len() && self.s[self.i] == b']' {
                    self.i += 1;
                    return Ok(vm.list(items));
                }
                loop {
                    let v = self.value(vm, depth + 1)?;
                    items.push(v);
                    self.ws();
                    if self.i < self.s.len() && self.s[self.i] == b',' {
                        self.i += 1;
                        continue;
                    }
                    if self.i < self.s.len() && self.s[self.i] == b']' {
                        self.i += 1;
                        return Ok(vm.list(items));
                    }
                    return Err(self.err(vm, "Expecting ',' delimiter"));
                }
            }
            b'"' => self.string(vm),
            b't' if self.s[self.i..].starts_with(b"true") => {
                self.i += 4;
                Ok(Value::TRUE)
            }
            b'f' if self.s[self.i..].starts_with(b"false") => {
                self.i += 5;
                Ok(Value::FALSE)
            }
            b'n' if self.s[self.i..].starts_with(b"null") => {
                self.i += 4;
                Ok(Value::NONE)
            }
            b'-' | b'0'..=b'9' => {
                let start = self.i;
                if self.s[self.i] == b'-' {
                    self.i += 1;
                }
                while self.i < self.s.len() && self.s[self.i].is_ascii_digit() {
                    self.i += 1;
                }
                let mut is_float = false;
                if self.i < self.s.len() && self.s[self.i] == b'.' {
                    is_float = true;
                    self.i += 1;
                    while self.i < self.s.len() && self.s[self.i].is_ascii_digit() {
                        self.i += 1;
                    }
                }
                if self.i < self.s.len() && matches!(self.s[self.i], b'e' | b'E') {
                    is_float = true;
                    self.i += 1;
                    if self.i < self.s.len() && matches!(self.s[self.i], b'+' | b'-') {
                        self.i += 1;
                    }
                    while self.i < self.s.len() && self.s[self.i].is_ascii_digit() {
                        self.i += 1;
                    }
                }
                let text = core::str::from_utf8(&self.s[start..self.i]).unwrap_or("0");
                if !is_float {
                    if let Ok(n) = text.parse::<i64>() {
                        return Ok(vm.int(n));
                    }
                }
                match text.parse::<f64>() {
                    Ok(f) => Ok(Value::float(f)),
                    Err(_) => Err(self.err(vm, "Invalid number")),
                }
            }
            _ => Err(self.err(vm, "Expecting value")),
        }
    }
    fn string(&mut self, vm: &mut Vm) -> PyResult {
        self.i += 1; // opening quote
        let mut out = String::new();
        loop {
            if self.i >= self.s.len() {
                return Err(self.err(vm, "Unterminated string starting at"));
            }
            let c = self.s[self.i];
            match c {
                b'"' => {
                    self.i += 1;
                    return Ok(vm.string(out));
                }
                b'\\' => {
                    self.i += 1;
                    if self.i >= self.s.len() {
                        return Err(self.err(vm, "Unterminated string"));
                    }
                    let e = self.s[self.i];
                    self.i += 1;
                    match e {
                        b'"' => out.push('"'),
                        b'\\' => out.push('\\'),
                        b'/' => out.push('/'),
                        b'b' => out.push('\u{8}'),
                        b'f' => out.push('\u{c}'),
                        b'n' => out.push('\n'),
                        b'r' => out.push('\r'),
                        b't' => out.push('\t'),
                        b'u' => {
                            let hex = |p: &mut Self, vm: &mut Vm| -> PyResult<u32> {
                                if p.i + 4 > p.s.len() {
                                    return Err(p.err(vm, "Invalid \\uXXXX escape"));
                                }
                                let h = core::str::from_utf8(&p.s[p.i..p.i + 4]).unwrap_or("");
                                p.i += 4;
                                u32::from_str_radix(h, 16).map_err(|_| p.err(vm, "Invalid \\uXXXX escape"))
                            };
                            let mut cp = hex(self, vm)?;
                            if (0xd800..0xdc00).contains(&cp) && self.s[self.i..].starts_with(b"\\u") {
                                self.i += 2;
                                let lo = hex(self, vm)?;
                                cp = 0x10000 + ((cp - 0xd800) << 10) + (lo - 0xdc00);
                            }
                            out.push(char::from_u32(cp).unwrap_or('\u{fffd}'));
                        }
                        _ => return Err(self.err(vm, "Invalid \\escape")),
                    }
                }
                _ => {
                    // copy a run of plain bytes
                    let start = self.i;
                    while self.i < self.s.len() && self.s[self.i] != b'"' && self.s[self.i] != b'\\' {
                        self.i += 1;
                    }
                    out.push_str(&String::from_utf8_lossy(&self.s[start..self.i]));
                }
            }
        }
    }
}

fn json_loads(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "loads")?;
    let text: String = match vm.as_str(v) {
        Some(s) => s.to_string(),
        None => match vm.heap.get(v) {
            Obj::Bytes(b) | Obj::ByteArray(b) => String::from_utf8_lossy(b).into_owned(),
            _ => {
                let t = vm.type_name(v);
                return Err(vm.type_error(format!("the JSON object must be str, bytes or bytearray, not {t}")));
            }
        },
    };
    let mut p = JsonParser { s: text.as_bytes(), i: 0 };
    let r = p.value(vm, 0)?;
    p.ws();
    if p.i < p.s.len() {
        return Err(p.err(vm, "Extra data"));
    }
    Ok(r)
}

fn json_escape(s: &str, out: &mut String, ensure_ascii: bool) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c if ensure_ascii && (c as u32) > 0x7e => {
                let mut buf = [0u16; 2];
                for u in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{:04x}", u));
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

struct DumpOpts {
    indent: Option<usize>,
    sort_keys: bool,
    ensure_ascii: bool,
    item_sep: String,
    key_sep: String,
    default: Value,
}

fn json_dump_value(vm: &mut Vm, v: Value, out: &mut String, o: &DumpOpts, level: usize) -> PyResult<()> {
    if v.is_none() {
        out.push_str("null");
        return Ok(());
    }
    if v.is_bool() {
        out.push_str(if v.as_bool() { "true" } else { "false" });
        return Ok(());
    }
    if v.is_int() {
        out.push_str(&v.as_int().to_string());
        return Ok(());
    }
    if v.is_float() {
        let f = v.as_float();
        if f.is_nan() {
            out.push_str("NaN");
        } else if f.is_infinite() {
            out.push_str(if f > 0.0 { "Infinity" } else { "-Infinity" });
        } else {
            out.push_str(&crate::format::float_repr(f));
        }
        return Ok(());
    }
    let newline = |out: &mut String, level: usize| {
        if let Some(n) = o.indent {
            out.push('\n');
            out.push_str(&" ".repeat(n * level));
        }
    };
    match vm.heap.get(v) {
        Obj::Str(s) => {
            json_escape(&s.s, out, o.ensure_ascii);
            Ok(())
        }
        Obj::Int(i) => {
            out.push_str(&i.to_string());
            Ok(())
        }
        Obj::List(items) | Obj::Tuple(items) => {
            let items = items.clone();
            if items.is_empty() {
                out.push_str("[]");
                return Ok(());
            }
            out.push('[');
            for (i, it) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(&o.item_sep);
                }
                newline(out, level + 1);
                json_dump_value(vm, *it, out, o, level + 1)?;
            }
            newline(out, level);
            out.push(']');
            Ok(())
        }
        Obj::Dict(d) => {
            let mut items: Vec<(Value, Value)> = d.items().collect();
            if items.is_empty() {
                out.push_str("{}");
                return Ok(());
            }
            let mut keyed: Vec<(String, Value)> = Vec::with_capacity(items.len());
            for (k, val) in items.drain(..) {
                let ks = if let Some(s) = vm.as_str(k) {
                    s.to_string()
                } else if k.is_none() {
                    "null".into()
                } else if k.is_bool() {
                    if k.as_bool() { "true" } else { "false" }.into()
                } else if vm.as_f64(k).is_some() {
                    vm.str_of(k)?
                } else {
                    let t = vm.type_name(k);
                    return Err(vm.type_error(format!("keys must be str, int, float, bool or None, not {t}")));
                };
                keyed.push((ks, val));
            }
            if o.sort_keys {
                keyed.sort_by(|a, b| a.0.cmp(&b.0));
            }
            out.push('{');
            for (i, (k, val)) in keyed.iter().enumerate() {
                if i > 0 {
                    out.push_str(&o.item_sep);
                }
                newline(out, level + 1);
                json_escape(k, out, o.ensure_ascii);
                out.push_str(&o.key_sep);
                json_dump_value(vm, *val, out, o, level + 1)?;
            }
            newline(out, level);
            out.push('}');
            Ok(())
        }
        _ => {
            if !o.default.is_none() {
                let r = vm.call(o.default, &[v], &[])?;
                return json_dump_value(vm, r, out, o, level);
            }
            let t = vm.type_name(v);
            Err(vm.type_error(format!("Object of type {t} is not JSON serializable")))
        }
    }
}

fn json_dumps(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "dumps")?;
    let indent = match kwarg(vm, kwargs, "indent") {
        Some(i) if !i.is_none() => Some(vm.as_i64(i).unwrap_or(0).max(0) as usize),
        _ => None,
    };
    let sort_keys = match kwarg(vm, kwargs, "sort_keys") {
        Some(s) => vm.truthy(s)?,
        None => false,
    };
    let ensure_ascii = match kwarg(vm, kwargs, "ensure_ascii") {
        Some(s) => vm.truthy(s)?,
        None => true,
    };
    let (mut item_sep, mut key_sep) = (if indent.is_some() { "," } else { ", " }.to_string(), ": ".to_string());
    if let Some(seps) = kwarg(vm, kwargs, "separators") {
        let parts = vm.collect_iter(seps)?;
        if parts.len() == 2 {
            item_sep = vm.expect_str(parts[0], "separator")?;
            key_sep = vm.expect_str(parts[1], "separator")?;
        }
    }
    let default = kwarg(vm, kwargs, "default").unwrap_or(Value::NONE);
    let o = DumpOpts { indent, sort_keys, ensure_ascii, item_sep, key_sep, default };
    let mut out = String::new();
    json_dump_value(vm, v, &mut out, &o, 0)?;
    Ok(vm.string(out))
}

// -- _frontage: what the framework's Python asks the runtime for directly -------------------------

fn fr_collect(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let n = vm.collect();
    Ok(vm.int(n as i64))
}
fn fr_heap_len(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(vm.int(vm.heap.len() as i64))
}
fn fr_format_exception(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let e = arg(vm, args, 0, "format_exception")?;
    let s = vm.format_exception(e);
    Ok(vm.string(s))
}
fn fr_sleep_ms(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let ms = f64_arg(vm, args, 0, "sleep_ms")?;
    vm.host.sleep_ms(ms);
    Ok(Value::NONE)
}
fn fr_monotonic(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::float(vm.host.now_ms() / 1000.0))
}
fn fr_profile_start(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let now = vm.host.now_ms();
    vm.prof = Some(Box::new(crate::vm::Profile { last: now, ..Default::default() }));
    Ok(Value::NONE)
}
/// Stop, and return `[(name, file, line, exclusive_ms, inclusive_ms), …]` sorted by
/// exclusive time, largest first.
fn fr_profile_stop(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let prof = match vm.prof.take() {
        Some(p) => p,
        None => return Ok(vm.list(Vec::new())),
    };
    let mut rows: Vec<crate::vm::ProfileRow> = prof.rows.values().cloned().collect();
    rows.sort_by(|a, b| b.exclusive.partial_cmp(&a.exclusive).unwrap_or(core::cmp::Ordering::Equal));
    let mut out = Vec::with_capacity(rows.len());
    for r in rows {
        let name = vm.str(&r.name);
        let file = vm.str(&r.file);
        let t = vm.tuple(vec![name, file, Value::int(r.line as i32), Value::float(r.exclusive), Value::float(r.inclusive)]);
        out.push(t);
    }
    Ok(vm.list(out))
}
/// `run_module_as_main(name)`: the module's bytecode the host holds, run as `__main__` — a
/// dev swap's last step.
fn fr_run_module_as_main(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "run_module_as_main")?;
    let name = vm.expect_str(v, "name")?;
    let bytes = match vm.host.find_module_code(&name) {
        Some(b) => b,
        None => return Err(vm.import_error(format!("No module named '{name}'"))),
    };
    let code = match crate::fbc::load(vm, &bytes) {
        Ok(c) => c,
        Err(msg) => return Err(vm.import_error(format!("bad bytecode for '{name}': {msg}"))),
    };
    let filename = code.filename.to_string();
    vm.run_main(code, &filename)?;
    Ok(Value::NONE)
}
fn mod_frontage(vm: &mut Vm) -> PyResult {
    let (m, d) = module_with(vm, "_frontage");
    add_fn(vm, d, "run_module_as_main", fr_run_module_as_main);
    add_fn(vm, d, "profile_start", fr_profile_start);
    add_fn(vm, d, "profile_stop", fr_profile_stop);
    add_fn(vm, d, "sleep_ms", fr_sleep_ms);
    add_fn(vm, d, "monotonic", fr_monotonic);
    vm.dict_set_str(d, "browser", Value::bool(vm.browser));
    add_fn(vm, d, "collect", fr_collect);
    add_fn(vm, d, "heap_len", fr_heap_len);
    add_fn(vm, d, "format_exception", fr_format_exception);
    Ok(m)
}

// -- gc -------------------------------------------------------------------------------------------

fn gc_collect(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let n = vm.collect();
    Ok(vm.int(n as i64))
}
fn gc_enable(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    vm.heap.enabled = true;
    Ok(Value::NONE)
}
fn gc_disable(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    vm.heap.enabled = false;
    Ok(Value::NONE)
}
fn gc_isenabled(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::bool(vm.heap.enabled))
}
fn gc_get_count(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let a = vm.int(vm.heap.since_gc as i64);
    let b = vm.int(vm.heap.collections as i64);
    Ok(vm.tuple(vec![a, b, Value::int(0)]))
}
fn gc_mem(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(vm.int(vm.heap.len() as i64 * 48))
}
fn mod_gc(vm: &mut Vm) -> PyResult {
    let (m, d) = module_with(vm, "gc");
    for (name, f) in [("collect", gc_collect as NativeFn), ("enable", gc_enable), ("disable", gc_disable), ("isenabled", gc_isenabled), ("get_count", gc_get_count), ("mem_alloc", gc_mem), ("mem_free", gc_mem)] {
        add_fn(vm, d, name, f);
    }
    Ok(m)
}

// -- modules written in Python -----------------------------------------------------------------------

pub const PY_MODULES: &[(&str, &str)] = &[
    ("asyncio", include_str!("lib/asyncio.py")),
    ("html", include_str!("lib/html.py")),
    ("html.parser", include_str!("lib/html_parser.py")),
    ("re", include_str!("lib/re.py")),
    (
        "io",
        r##"
class StringIO:
    def __init__(self, initial=""):
        self._parts = [initial] if initial else []
    def write(self, s):
        self._parts.append(s)
        return len(s)
    def getvalue(self):
        return "".join(self._parts)
    def read(self):
        return self.getvalue()
    def flush(self):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

class BytesIO:
    def __init__(self, initial=b""):
        self._buf = bytearray(initial)
    def write(self, b):
        self._buf.extend(b)
        return len(b)
    def getvalue(self):
        return bytes(self._buf)
"##,
    ),
    (
        "traceback",
        r##"
import _frontage

def format_exception(exc_type, exc=None, tb=None):
    if exc is None and not isinstance(exc_type, type):
        exc = exc_type
    return [_frontage.format_exception(exc)]

def format_exc():
    import sys
    e = sys.exc_info()[1]
    return _frontage.format_exception(e) if e is not None else "NoneType: None\n"

def print_exc():
    import sys
    sys.stderr.write(format_exc())
"##,
    ),
    (
        "functools",
        r##"
def wraps(wrapped):
    def deco(f):
        try:
            f.__name__ = wrapped.__name__
            f.__doc__ = wrapped.__doc__
        except AttributeError:
            pass
        f.__wrapped__ = wrapped
        return f
    return deco

def partial(func, *args, **kwargs):
    def inner(*a, **kw):
        merged = dict(kwargs)
        merged.update(kw)
        return func(*args, *a, **merged)
    inner.func = func
    inner.args = args
    return inner

def reduce(function, iterable, *initial):
    it = iter(iterable)
    if initial:
        acc = initial[0]
    else:
        try:
            acc = next(it)
        except StopIteration:
            raise TypeError("reduce() of empty iterable with no initial value")
    for x in it:
        acc = function(acc, x)
    return acc

def lru_cache(maxsize=128):
    def deco(f):
        cache = {}
        def inner(*args):
            if args in cache:
                return cache[args]
            r = f(*args)
            cache[args] = r
            return r
        inner.cache_clear = cache.clear
        inner.__name__ = f.__name__
        inner.__wrapped__ = f
        return inner
    if callable(maxsize):
        return deco(maxsize)
    return deco

cache = lru_cache

def cmp_to_key(cmp):
    class K:
        def __init__(self, obj):
            self.obj = obj
        def __lt__(self, other):
            return cmp(self.obj, other.obj) < 0
        def __eq__(self, other):
            return cmp(self.obj, other.obj) == 0
    return K
"##,
    ),
    (
        "collections",
        r##"
class OrderedDict(dict):
    pass

class defaultdict:
    def __init__(self, default_factory=None, *args, **kwargs):
        self.default_factory = default_factory
        self._d = dict(*args, **kwargs)
    def __getitem__(self, key):
        if key not in self._d:
            if self.default_factory is None:
                raise KeyError(key)
            self._d[key] = self.default_factory()
        return self._d[key]
    def __setitem__(self, key, value):
        self._d[key] = value
    def __delitem__(self, key):
        del self._d[key]
    def __contains__(self, key):
        return key in self._d
    def __len__(self):
        return len(self._d)
    def __iter__(self):
        return iter(self._d)
    def get(self, key, default=None):
        return self._d.get(key, default)
    def keys(self):
        return self._d.keys()
    def values(self):
        return self._d.values()
    def items(self):
        return self._d.items()
    def pop(self, key, *default):
        return self._d.pop(key, *default)
    def setdefault(self, key, default=None):
        return self._d.setdefault(key, default)
    def update(self, *a, **kw):
        self._d.update(*a, **kw)
    def clear(self):
        self._d.clear()
    def __repr__(self):
        return "defaultdict(%r, %r)" % (self.default_factory, self._d)
    def __eq__(self, other):
        return self._d == (other._d if isinstance(other, defaultdict) else other)

class Counter(defaultdict):
    def __init__(self, iterable=None, **kwargs):
        super().__init__(int)
        if iterable is not None:
            self.update(iterable)
        for k, v in kwargs.items():
            self[k] = v
    def __getitem__(self, key):
        return self._d.get(key, 0)
    def update(self, iterable=None, **kwargs):
        if hasattr(iterable, "items"):
            for k, v in iterable.items():
                self[k] = self[k] + v
        elif iterable is not None:
            for x in iterable:
                self[x] = self[x] + 1
    def most_common(self, n=None):
        items = sorted(self.items(), key=lambda kv: -kv[1])
        return items if n is None else items[:n]
    def total(self):
        return sum(self.values())

class deque:
    def __init__(self, iterable=(), maxlen=None):
        self._items = list(iterable)
        self.maxlen = maxlen
        self._trim()
    def _trim(self):
        if self.maxlen is not None:
            while len(self._items) > self.maxlen:
                self._items.pop(0)
    def append(self, x):
        self._items.append(x)
        self._trim()
    def appendleft(self, x):
        self._items.insert(0, x)
        self._trim()
    def pop(self):
        return self._items.pop()
    def popleft(self):
        return self._items.pop(0)
    def extend(self, it):
        for x in it:
            self.append(x)
    def clear(self):
        self._items.clear()
    def __len__(self):
        return len(self._items)
    def __iter__(self):
        return iter(self._items)
    def __getitem__(self, i):
        return self._items[i]
    def __bool__(self):
        return bool(self._items)
    def __repr__(self):
        return "deque(%r)" % (self._items,)

def namedtuple(typename, field_names, defaults=None):
    if isinstance(field_names, str):
        field_names = field_names.replace(",", " ").split()
    fields = tuple(field_names)
    class NT:
        __slots__ = ()
        _fields = fields
        def __init__(self, *args, **kwargs):
            values = list(args)
            for name in fields[len(args):]:
                if name in kwargs:
                    values.append(kwargs[name])
                elif defaults is not None and len(fields) - fields.index(name) <= len(defaults):
                    values.append(defaults[len(defaults) - (len(fields) - fields.index(name))])
                else:
                    raise TypeError("missing argument: " + name)
            object.__setattr__(self, "_values", tuple(values))
        def __getattr__(self, name):
            if name in fields:
                return self._values[fields.index(name)]
            raise AttributeError(name)
        def __getitem__(self, i):
            return self._values[i]
        def __iter__(self):
            return iter(self._values)
        def __len__(self):
            return len(self._values)
        def __eq__(self, other):
            return tuple(self) == tuple(other)
        def __hash__(self):
            return hash(self._values)
        def _asdict(self):
            return dict(zip(fields, self._values))
        def _replace(self, **kw):
            d = self._asdict()
            d.update(kw)
            return NT(**d)
        def __repr__(self):
            return typename + "(" + ", ".join("%s=%r" % (f, v) for f, v in zip(fields, self._values)) + ")"
    NT.__name__ = typename
    return NT
"##,
    ),
    (
        "typing",
        r##"
class _Any:
    def __getitem__(self, item):
        return self
    def __call__(self, *a, **k):
        raise TypeError("typing constructs are not callable")
    def __repr__(self):
        return "typing"

Any = _Any()
Optional = Union = List = Dict = Tuple = Set = Callable = Iterable = Iterator = Sequence = Mapping = Type = Generic = Protocol = TypeVar = ClassVar = Final = Literal = Awaitable = Coroutine = Generator = _Any()
TYPE_CHECKING = False

def cast(t, v):
    return v

def overload(f):
    return f

def final(f):
    return f

def runtime_checkable(c):
    return c

class NamedTuple:
    pass
"##,
    ),
    (
        "string",
        r##"
ascii_letters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
ascii_lowercase = "abcdefghijklmnopqrstuvwxyz"
ascii_uppercase = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
digits = "0123456789"
hexdigits = "0123456789abcdefABCDEF"
whitespace = " \t\n\r\x0b\x0c"
punctuation = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
"##,
    ),
    (
        "string.templatelib",
        r##"
Template = type(t"")
Interpolation = type(t"{0}".interpolations[0])
"##,
    ),
    (
        "warnings",
        r##"
def warn(message, category=None, stacklevel=1):
    import sys
    sys.stderr.write("Warning: " + str(message) + "\n")
"##,
    ),
    (
        "abc",
        r##"
class ABC:
    pass

def abstractmethod(f):
    return f
"##,
    ),
    (
        "enum",
        r##"
class Enum:
    pass
"##,
    ),
    (
        "dataclasses",
        r##"
def dataclass(cls=None, **kw):
    def wrap(c):
        fields = [k for k in c.__dict__ if not k.startswith("_") and not callable(getattr(c, k, None))]
        annotations = getattr(c, "__annotations__", {})
        names = list(annotations) if annotations else fields
        def __init__(self, *args, **kwargs):
            for name, value in zip(names, args):
                setattr(self, name, value)
            for name in names[len(args):]:
                if name in kwargs:
                    setattr(self, name, kwargs[name])
                elif hasattr(c, name):
                    setattr(self, name, getattr(c, name))
                else:
                    raise TypeError("missing argument: " + name)
        def __repr__(self):
            return c.__name__ + "(" + ", ".join("%s=%r" % (n, getattr(self, n)) for n in names) + ")"
        def __eq__(self, other):
            return type(self) is type(other) and all(getattr(self, n) == getattr(other, n) for n in names)
        c.__init__ = __init__
        c.__repr__ = __repr__
        c.__eq__ = __eq__
        return c
    return wrap(cls) if cls is not None else wrap

def field(default=None, default_factory=None, **kw):
    return default if default_factory is None else default_factory()
"##,
    ),
];

fn mod_python(vm: &mut Vm) -> PyResult {
    // Which module was asked for? The registry maps every name here; find the one whose
    // source we need by checking which is not yet in sys.modules — the loader inserts after
    // this returns, so the caller's name is the one absent. Simpler: the loader passes the
    // name through `pending_module`.
    let name = vm.pending_module.take().unwrap_or_default();
    let source = PY_MODULES.iter().find(|(n, _)| *n == name).map(|(_, s)| *s).unwrap_or("");
    let compile = match vm.compiler {
        Some(c) => c,
        None => return Err(vm.import_error(format!("No compiler to load '{name}'"))),
    };
    let filename = format!("<frontage:{name}>");
    let code = match compile(vm, source, &filename) {
        Ok(c) => c,
        Err(msg) => {
            let c = vm.t.syntax_error;
            return Err(vm.exception(c, msg));
        }
    };
    let module = vm.new_module(&name);
    let dict = vm.module_dict(module);
    let package = name.rsplit_once('.').map(|(p, _)| p.to_string()).unwrap_or_default();
    let package = vm.str(&package);
    vm.dict_set_str(dict, "__package__", package);
    let key = vm.intern(&name);
    let modules = vm.modules;
    vm.dict_set(modules, key, module);
    if let Err(e) = vm.run_code(code, dict, dict) {
        vm.dict_remove(modules, key);
        return Err(e);
    }
    Ok(module)
}
