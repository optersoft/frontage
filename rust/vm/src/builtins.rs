//! The `builtins` module: the builtin types and their methods, the builtin functions, the
//! exception hierarchy, and construction of builtin types.

use crate::code::CmpOp;
use crate::dict::PyDict;
use crate::object::*;
use crate::value::Value;
use crate::vm::{PyResult, Vm};

// -- argument helpers ----------------------------------------------------------------------------

pub fn arg(vm: &mut Vm, args: &[Value], i: usize, fname: &str) -> PyResult {
    match args.get(i) {
        Some(&v) => Ok(v),
        None => Err(vm.type_error(format!("{fname}() missing required argument (pos {})", i + 1))),
    }
}
pub fn opt(args: &[Value], i: usize) -> Option<Value> {
    args.get(i).copied()
}
pub fn kwarg(vm: &Vm, kwargs: &[(Value, Value)], name: &str) -> Option<Value> {
    kwargs.iter().find(|(k, _)| vm.as_str(*k) == Some(name)).map(|(_, v)| *v)
}
pub fn no_kwargs(vm: &mut Vm, kwargs: &[(Value, Value)], fname: &str) -> PyResult<()> {
    if let Some((k, _)) = kwargs.first() {
        let s = vm.as_str(*k).unwrap_or("?").to_string();
        return Err(vm.type_error(format!("{fname}() got an unexpected keyword argument '{s}'")));
    }
    Ok(())
}
fn check_args(vm: &mut Vm, args: &[Value], min: usize, max: usize, fname: &str) -> PyResult<()> {
    if args.len() < min || args.len() > max {
        return Err(vm.type_error(if min == max {
            format!("{fname}() takes exactly {min} argument{} ({} given)", if min == 1 { "" } else { "s" }, args.len())
        } else {
            format!("{fname}() takes from {min} to {max} arguments ({} given)", args.len())
        }));
    }
    Ok(())
}
/// The receiver of a method call, checked to be the expected object kind.
fn this_str(vm: &mut Vm, args: &[Value], fname: &str) -> PyResult<String> {
    let v = arg(vm, args, 0, fname)?;
    vm.expect_str(v, "self")
}
fn this_list(vm: &mut Vm, args: &[Value], fname: &str) -> PyResult<Value> {
    let v = arg(vm, args, 0, fname)?;
    if v.is_obj() && matches!(vm.heap.get(v), Obj::List(_)) {
        return Ok(v);
    }
    Err(vm.type_error(format!("descriptor '{fname}' requires a 'list' object")))
}
fn this_dict(vm: &mut Vm, args: &[Value], fname: &str) -> PyResult<Value> {
    let v = arg(vm, args, 0, fname)?;
    if v.is_obj() && matches!(vm.heap.get(v), Obj::Dict(_)) {
        return Ok(v);
    }
    Err(vm.type_error(format!("descriptor '{fname}' requires a 'dict' object")))
}
fn this_set(vm: &mut Vm, args: &[Value], fname: &str) -> PyResult<Value> {
    let v = arg(vm, args, 0, fname)?;
    if v.is_obj() && matches!(vm.heap.get(v), Obj::Set(_) | Obj::FrozenSet(_)) {
        return Ok(v);
    }
    Err(vm.type_error(format!("descriptor '{fname}' requires a 'set' object")))
}
fn list_items(vm: &Vm, list: Value) -> Vec<Value> {
    match vm.heap.get(list) {
        Obj::List(v) | Obj::Tuple(v) => v.clone(),
        _ => vec![],
    }
}
fn set_keys(vm: &Vm, set: Value) -> Vec<Value> {
    match vm.heap.get(set) {
        Obj::Set(d) | Obj::FrozenSet(d) => d.keys().collect(),
        _ => vec![],
    }
}

// -- installation ----------------------------------------------------------------------------------

pub fn new_class_pub(vm: &mut Vm, name: &str, kind: Option<Builtin>, bases: &[Value]) -> Value {
    new_class(vm, name, kind, bases)
}

fn new_class(vm: &mut Vm, name: &str, kind: Option<Builtin>, bases: &[Value]) -> Value {
    let name_v = vm.intern(name);
    let module = vm.intern("builtins");
    let placeholder = Class { name: name_v, bases: bases.to_vec(), mro: Vec::new(), dict: PyDict::new(), builtin: kind, version: 0, module, cache: core::cell::RefCell::new([(Value::UNDEF, Value::UNDEF); 32]), cache_epoch: Default::default() };
    let cls = vm.heap.alloc_pinned(Obj::Class(Box::new(placeholder)));
    let mut mro = vec![cls];
    // Single inheritance among builtins: chain the first base's MRO.
    if let Some(&b) = bases.first() {
        if let Obj::Class(c) = vm.heap.get(b) {
            mro.extend(c.mro.iter().copied());
        }
    }
    if let Obj::Class(c) = vm.heap.get_mut(cls) {
        c.mro = mro;
    }
    cls
}

pub fn add_method(vm: &mut Vm, cls: Value, name: &'static str, f: NativeFn) {
    let key = vm.intern(name);
    let nf = vm.native(name, f);
    if let Obj::Class(c) = vm.heap.get_mut(cls) {
        let mut d = core::mem::take(&mut c.dict);
        d.set(&vm.heap, key, nf);
        if let Obj::Class(c) = vm.heap.get_mut(cls) {
            c.dict = d;
        }
    }
}
fn add_attr(vm: &mut Vm, cls: Value, name: &str, v: Value) {
    let key = vm.intern(name);
    if let Obj::Class(c) = vm.heap.get_mut(cls) {
        let mut d = core::mem::take(&mut c.dict);
        d.set(&vm.heap, key, v);
        if let Obj::Class(c) = vm.heap.get_mut(cls) {
            c.dict = d;
        }
    }
}
fn add_builtin(vm: &mut Vm, name: &'static str, f: NativeFn) {
    let nf = vm.native(name, f);
    let b = vm.builtins;
    vm.dict_set_str(b, name, nf);
}

pub fn install(vm: &mut Vm) {
    let object = new_class(vm, "object", Some(Builtin::Object), &[]);
    vm.t.object = object;
    let type_ = new_class(vm, "type", Some(Builtin::Type), &[object]);
    vm.t.type_ = type_;
    macro_rules! ty {
        ($field:ident, $name:expr, $kind:expr) => {{
            let c = new_class(vm, $name, Some($kind), &[object]);
            vm.t.$field = c;
            c
        }};
    }
    let int = ty!(int, "int", Builtin::Int);
    let bool_ = new_class(vm, "bool", Some(Builtin::Bool), &[int]);
    vm.t.bool_ = bool_;
    ty!(float, "float", Builtin::Float);
    ty!(str_, "str", Builtin::Str);
    ty!(bytes, "bytes", Builtin::Bytes);
    ty!(bytearray, "bytearray", Builtin::ByteArray);
    ty!(list, "list", Builtin::List);
    ty!(tuple, "tuple", Builtin::Tuple);
    ty!(dict, "dict", Builtin::Dict);
    ty!(set, "set", Builtin::Set);
    ty!(frozenset, "frozenset", Builtin::FrozenSet);
    ty!(none_type, "NoneType", Builtin::NoneType);
    ty!(function, "function", Builtin::Function);
    ty!(module, "module", Builtin::Module);
    ty!(range, "range", Builtin::Range);
    ty!(slice, "slice", Builtin::Slice);
    ty!(property, "property", Builtin::Property);
    ty!(staticmethod, "staticmethod", Builtin::StaticMethod);
    ty!(classmethod, "classmethod", Builtin::ClassMethod);
    ty!(generator, "generator", Builtin::Generator);
    ty!(coroutine, "coroutine", Builtin::Coroutine);
    ty!(template, "Template", Builtin::Template);
    ty!(interpolation, "Interpolation", Builtin::Interpolation);
    ty!(iterator, "iterator", Builtin::Iterator);
    ty!(cell, "cell", Builtin::Cell);
    ty!(not_implemented_type, "NotImplementedType", Builtin::NotImplementedType);
    ty!(ellipsis_type, "ellipsis", Builtin::EllipsisType);
    ty!(code, "code", Builtin::Function);
    ty!(js_object, "JsObject", Builtin::Object);
    ty!(super_, "super", Builtin::Object);
    ty!(builtin_function, "builtin_function_or_method", Builtin::Function);
    ty!(method, "method", Builtin::Function);

    // Exceptions.
    let base_exception = new_class(vm, "BaseException", Some(Builtin::BaseException), &[object]);
    vm.t.base_exception = base_exception;
    macro_rules! exc {
        ($field:ident, $name:expr, $base:expr) => {{
            let c = new_class(vm, $name, Some(Builtin::BaseException), &[$base]);
            vm.t.$field = c;
            c
        }};
    }
    let exception = exc!(exception, "Exception", base_exception);
    exc!(system_exit, "SystemExit", base_exception);
    exc!(keyboard_interrupt, "KeyboardInterrupt", base_exception);
    exc!(generator_exit, "GeneratorExit", base_exception);
    exc!(type_error, "TypeError", exception);
    exc!(value_error, "ValueError", exception);
    let lookup = exc!(lookup_error, "LookupError", exception);
    exc!(key_error, "KeyError", lookup);
    exc!(index_error, "IndexError", lookup);
    exc!(attribute_error, "AttributeError", exception);
    let runtime = exc!(runtime_error, "RuntimeError", exception);
    exc!(not_implemented_error, "NotImplementedError", runtime);
    exc!(recursion_error, "RecursionError", runtime);
    exc!(stop_iteration, "StopIteration", exception);
    exc!(stop_async_iteration, "StopAsyncIteration", exception);
    let arith = exc!(arithmetic_error, "ArithmeticError", exception);
    exc!(zero_division_error, "ZeroDivisionError", arith);
    exc!(overflow_error, "OverflowError", arith);
    let name_error = exc!(name_error, "NameError", exception);
    exc!(unbound_local_error, "UnboundLocalError", name_error);
    let import_error = exc!(import_error, "ImportError", exception);
    exc!(module_not_found_error, "ModuleNotFoundError", import_error);
    exc!(assertion_error, "AssertionError", exception);
    let os_error = exc!(os_error, "OSError", exception);
    exc!(timeout_error, "TimeoutError", os_error);
    exc!(unicode_error, "UnicodeError", value_error_of(vm));
    exc!(syntax_error, "SyntaxError", exception);
    exc!(cancelled_error, "CancelledError", base_exception);
    let warning = exc!(warning, "Warning", exception);
    exc!(deprecation_warning, "DeprecationWarning", warning);
    exc!(user_warning, "UserWarning", warning);

    // The module dict.
    let bdict = vm.heap.alloc_pinned(Obj::Dict(PyDict::new()));
    vm.builtins = bdict;
    let bmod = vm.new_module("builtins");
    if let Obj::Module(m) = vm.heap.get_mut(bmod) {
        m.dict = bdict;
    }
    let key = vm.intern("__name__");
    let nm = vm.intern("builtins");
    vm.dict_set(bdict, key, nm);
    let modules = vm.modules;
    vm.dict_set(modules, nm, bmod);

    for (name, cls) in [
        ("object", vm.t.object),
        ("type", vm.t.type_),
        ("int", vm.t.int),
        ("bool", vm.t.bool_),
        ("float", vm.t.float),
        ("str", vm.t.str_),
        ("bytes", vm.t.bytes),
        ("bytearray", vm.t.bytearray),
        ("list", vm.t.list),
        ("tuple", vm.t.tuple),
        ("dict", vm.t.dict),
        ("set", vm.t.set),
        ("frozenset", vm.t.frozenset),
        ("range", vm.t.range),
        ("slice", vm.t.slice),
        ("property", vm.t.property),
        ("staticmethod", vm.t.staticmethod),
        ("classmethod", vm.t.classmethod),
        ("super", vm.t.super_),
        ("BaseException", vm.t.base_exception),
        ("Exception", vm.t.exception),
        ("SystemExit", vm.t.system_exit),
        ("KeyboardInterrupt", vm.t.keyboard_interrupt),
        ("GeneratorExit", vm.t.generator_exit),
        ("TypeError", vm.t.type_error),
        ("ValueError", vm.t.value_error),
        ("LookupError", vm.t.lookup_error),
        ("KeyError", vm.t.key_error),
        ("IndexError", vm.t.index_error),
        ("AttributeError", vm.t.attribute_error),
        ("RuntimeError", vm.t.runtime_error),
        ("NotImplementedError", vm.t.not_implemented_error),
        ("RecursionError", vm.t.recursion_error),
        ("StopIteration", vm.t.stop_iteration),
        ("StopAsyncIteration", vm.t.stop_async_iteration),
        ("ArithmeticError", vm.t.arithmetic_error),
        ("ZeroDivisionError", vm.t.zero_division_error),
        ("OverflowError", vm.t.overflow_error),
        ("NameError", vm.t.name_error),
        ("UnboundLocalError", vm.t.unbound_local_error),
        ("ImportError", vm.t.import_error),
        ("ModuleNotFoundError", vm.t.module_not_found_error),
        ("AssertionError", vm.t.assertion_error),
        ("OSError", vm.t.os_error),
        ("IOError", vm.t.os_error),
        ("TimeoutError", vm.t.timeout_error),
        ("UnicodeError", vm.t.unicode_error),
        ("UnicodeDecodeError", vm.t.unicode_error),
        ("UnicodeEncodeError", vm.t.unicode_error),
        ("SyntaxError", vm.t.syntax_error),
        ("CancelledError", vm.t.cancelled_error),
        ("GeneratorExit", vm.t.generator_exit),
        ("Warning", vm.t.warning),
        ("DeprecationWarning", vm.t.deprecation_warning),
        ("UserWarning", vm.t.user_warning),
    ] {
        vm.dict_set_str(bdict, name, cls);
    }
    let ni = vm.heap.alloc_pinned(Obj::NotImplemented);
    vm.dict_set_str(bdict, "NotImplemented", ni);
    let el = vm.heap.alloc_pinned(Obj::Ellipsis);
    vm.dict_set_str(bdict, "Ellipsis", el);
    vm.dict_set_str(bdict, "None", Value::NONE);
    vm.dict_set_str(bdict, "True", Value::TRUE);
    vm.dict_set_str(bdict, "False", Value::FALSE);
    vm.dict_set_str(bdict, "__debug__", Value::TRUE);

    // Functions.
    add_builtin(vm, "print", b_print);
    add_builtin(vm, "len", b_len);
    add_builtin(vm, "repr", b_repr);
    add_builtin(vm, "ascii", b_ascii);
    add_builtin(vm, "isinstance", b_isinstance);
    add_builtin(vm, "issubclass", b_issubclass);
    add_builtin(vm, "getattr", b_getattr);
    add_builtin(vm, "setattr", b_setattr);
    add_builtin(vm, "hasattr", b_hasattr);
    add_builtin(vm, "delattr", b_delattr);
    add_builtin(vm, "callable", b_callable);
    add_builtin(vm, "id", b_id);
    add_builtin(vm, "hash", b_hash);
    add_builtin(vm, "sorted", b_sorted);
    add_builtin(vm, "sum", b_sum);
    add_builtin(vm, "min", b_min);
    add_builtin(vm, "max", b_max);
    add_builtin(vm, "abs", b_abs);
    add_builtin(vm, "round", b_round);
    add_builtin(vm, "enumerate", b_enumerate);
    add_builtin(vm, "zip", b_zip);
    add_builtin(vm, "map", b_map);
    add_builtin(vm, "filter", b_filter);
    add_builtin(vm, "any", b_any);
    add_builtin(vm, "all", b_all);
    add_builtin(vm, "iter", b_iter);
    add_builtin(vm, "next", b_next);
    add_builtin(vm, "reversed", b_reversed);
    add_builtin(vm, "chr", b_chr);
    add_builtin(vm, "ord", b_ord);
    add_builtin(vm, "format", b_format);
    add_builtin(vm, "divmod", b_divmod);
    add_builtin(vm, "pow", b_pow);
    add_builtin(vm, "hex", b_hex);
    add_builtin(vm, "oct", b_oct);
    add_builtin(vm, "bin", b_bin);
    add_builtin(vm, "globals", b_globals);
    add_builtin(vm, "compile", b_compile);
    add_builtin(vm, "exec", b_exec);
    add_builtin(vm, "vars", b_vars);
    add_builtin(vm, "dir", b_dir);
    add_builtin(vm, "__import__", b_import);
    add_builtin(vm, "__build_class__", b_build_class);

    // object
    add_method(vm, object, "__init__", object_init);
    add_method(vm, object, "__repr__", object_repr);
    add_method(vm, object, "__str__", object_str);
    add_method(vm, object, "__format__", object_format);
    add_method(vm, object, "__eq__", object_eq);
    add_method(vm, object, "__ne__", object_ne);
    add_method(vm, object, "__hash__", object_hash);
    add_method(vm, object, "__setattr__", object_setattr);
    add_method(vm, object, "__getattribute__", object_getattribute);
    add_method(vm, object, "__delattr__", object_delattr);
    add_method(vm, object, "__init_subclass__", object_init_subclass);
    add_method(vm, type_, "mro", type_mro);
    add_method(vm, base_exception, "__init__", exc_init);
    add_method(vm, base_exception, "with_traceback", exc_with_traceback);
    add_method(vm, base_exception, "add_note", exc_add_note);

    // str
    let s = vm.t.str_;
    for (name, f) in [
        ("join", str_join as NativeFn),
        ("split", str_split),
        ("rsplit", str_rsplit),
        ("strip", str_strip),
        ("lstrip", str_lstrip),
        ("rstrip", str_rstrip),
        ("replace", str_replace),
        ("startswith", str_startswith),
        ("endswith", str_endswith),
        ("find", str_find),
        ("rfind", str_rfind),
        ("index", str_index),
        ("rindex", str_rindex),
        ("count", str_count),
        ("lower", str_lower),
        ("upper", str_upper),
        ("title", str_title),
        ("capitalize", str_capitalize),
        ("swapcase", str_swapcase),
        ("casefold", str_lower),
        ("isdigit", str_isdigit),
        ("isascii", str_isascii),
        ("isdecimal", str_isdigit),
        ("isnumeric", str_isdigit),
        ("isalpha", str_isalpha),
        ("isalnum", str_isalnum),
        ("isspace", str_isspace),
        ("isupper", str_isupper),
        ("islower", str_islower),
        ("isidentifier", str_isidentifier),
        ("format", str_format),
        ("format_map", str_format_map),
        ("partition", str_partition),
        ("rpartition", str_rpartition),
        ("splitlines", str_splitlines),
        ("encode", str_encode),
        ("zfill", str_zfill),
        ("center", str_center),
        ("ljust", str_ljust),
        ("rjust", str_rjust),
        ("removeprefix", str_removeprefix),
        ("removesuffix", str_removesuffix),
        ("expandtabs", str_expandtabs),
        ("__getitem__", generic_getitem),
        ("__len__", generic_len),
        ("__contains__", generic_contains),
        ("__hash__", object_hash),
        ("__eq__", generic_eq),
        ("__lt__", generic_lt),
        ("__add__", generic_add),
        ("__mul__", generic_mul),
        ("__mod__", generic_mod),
        ("__iter__", generic_iter),
    ] {
        add_method(vm, s, name, f);
    }
    // list
    let l = vm.t.list;
    for (name, f) in [
        ("append", list_append as NativeFn),
        ("extend", list_extend),
        ("insert", list_insert),
        ("pop", list_pop),
        ("remove", list_remove),
        ("index", list_index),
        ("count", list_count),
        ("clear", list_clear),
        ("copy", list_copy),
        ("reverse", list_reverse),
        ("sort", list_sort),
        ("__getitem__", generic_getitem),
        ("__setitem__", generic_setitem),
        ("__delitem__", generic_delitem),
        ("__len__", generic_len),
        ("__contains__", generic_contains),
        ("__iter__", generic_iter),
        ("__eq__", generic_eq),
        ("__add__", generic_add),
        ("__mul__", generic_mul),
    ] {
        add_method(vm, l, name, f);
    }
    let t = vm.t.tuple;
    for (name, f) in [("index", list_index as NativeFn), ("count", list_count), ("__getitem__", generic_getitem), ("__len__", generic_len), ("__contains__", generic_contains), ("__iter__", generic_iter), ("__eq__", generic_eq), ("__hash__", object_hash), ("__add__", generic_add), ("__mul__", generic_mul)] {
        add_method(vm, t, name, f);
    }
    // dict
    let d = vm.t.dict;
    for (name, f) in [
        ("get", dict_get as NativeFn),
        ("keys", dict_keys),
        ("values", dict_values),
        ("items", dict_items),
        ("pop", dict_pop),
        ("popitem", dict_popitem),
        ("setdefault", dict_setdefault),
        ("update", dict_update),
        ("clear", dict_clear),
        ("copy", dict_copy),
        ("fromkeys", dict_fromkeys),
        ("__getitem__", generic_getitem),
        ("__setitem__", generic_setitem),
        ("__delitem__", generic_delitem),
        ("__len__", generic_len),
        ("__contains__", generic_contains),
        ("__iter__", generic_iter),
        ("__eq__", generic_eq),
        ("__or__", generic_or),
    ] {
        add_method(vm, d, name, f);
    }
    for cls in [vm.t.set, vm.t.frozenset] {
        for (name, f) in [
            ("add", set_add as NativeFn),
            ("remove", set_remove),
            ("discard", set_discard),
            ("pop", set_pop),
            ("clear", set_clear),
            ("copy", set_copy),
            ("update", set_update),
            ("union", set_union),
            ("intersection", set_intersection),
            ("difference", set_difference),
            ("symmetric_difference", set_symmetric_difference),
            ("issubset", set_issubset),
            ("issuperset", set_issuperset),
            ("isdisjoint", set_isdisjoint),
            ("__len__", generic_len),
            ("__contains__", generic_contains),
            ("__iter__", generic_iter),
            ("__eq__", generic_eq),
            ("__or__", generic_or),
        ] {
            add_method(vm, cls, name, f);
        }
    }
    let i = vm.t.int;
    add_method(vm, i, "bit_length", int_bit_length);
    add_method(vm, i, "to_bytes", int_to_bytes);
    add_method(vm, i, "__index__", int_index);
    add_method(vm, i, "__int__", int_index);
    add_method(vm, i, "__hash__", object_hash);
    add_method(vm, i, "__eq__", generic_eq);
    add_method(vm, i, "__lt__", generic_lt);
    add_method(vm, i, "__add__", generic_add);
    add_method(vm, i, "__sub__", generic_sub);
    add_method(vm, i, "__mul__", generic_mul);
    add_method(vm, i, "__neg__", generic_neg);
    let f = vm.t.float;
    add_method(vm, f, "is_integer", float_is_integer);
    add_method(vm, f, "__hash__", object_hash);
    add_method(vm, f, "__eq__", generic_eq);
    add_method(vm, f, "__lt__", generic_lt);
    add_method(vm, f, "__add__", generic_add);
    add_method(vm, f, "__sub__", generic_sub);
    add_method(vm, f, "__mul__", generic_mul);
    add_method(vm, f, "__neg__", generic_neg);
    let b = vm.t.bytes;
    add_method(vm, b, "decode", bytes_decode);
    add_method(vm, b, "hex", bytes_hex);
    add_method(vm, b, "__len__", generic_len);
    add_method(vm, b, "__getitem__", generic_getitem);
    let ba = vm.t.bytearray;
    add_method(vm, ba, "decode", bytes_decode);
    add_method(vm, ba, "hex", bytes_hex);
    add_method(vm, ba, "append", bytearray_append);
    add_method(vm, ba, "extend", bytearray_extend);
    add_method(vm, ba, "__len__", generic_len);
    let g = vm.t.generator;
    add_method(vm, g, "send", gen_send);
    add_method(vm, g, "throw", gen_throw);
    add_method(vm, g, "close", gen_close);
    add_method(vm, g, "__next__", gen_next);
    add_method(vm, g, "__iter__", generic_iter);
    let c = vm.t.coroutine;
    add_method(vm, c, "send", gen_send);
    add_method(vm, c, "throw", gen_throw);
    add_method(vm, c, "close", gen_close);
    add_method(vm, c, "__await__", generic_iter);
    let it = vm.t.iterator;
    add_method(vm, it, "__next__", gen_next);
    add_method(vm, it, "__iter__", generic_iter);
    let none = vm.t.none_type;
    add_method(vm, none, "__bool__", none_bool);
    let _ = add_attr;
}

fn value_error_of(vm: &Vm) -> Value {
    vm.t.value_error
}

// -- construction of builtin types ------------------------------------------------------------

pub fn construct_builtin(vm: &mut Vm, cls: Value, kind: Builtin, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    match kind {
        Builtin::Object => {
            if cls == vm.t.super_ {
                return construct_super(vm, args);
            }
            if !args.is_empty() || !kwargs.is_empty() {
                return Err(vm.type_error("object() takes no arguments"));
            }
            Ok(vm.heap.alloc(Obj::Instance(Instance { class: cls, dict: PyDict::new() })))
        }
        Builtin::Type => {
            if args.len() == 1 {
                return Ok(vm.type_of(args[0]));
            }
            check_args(vm, args, 3, 3, "type")?;
            let name = args[0];
            let bases = vm.collect_iter(args[1])?;
            let ns = args[2];
            let snapshot = vm.take_dict_snapshot(ns)?;
            let mut d = PyDict::new();
            for (k, v) in snapshot {
                d.set(&vm.heap, k, v);
            }
            let ns2 = vm.dict(d);
            let module = vm.intern("builtins");
            vm.make_class(name, bases, ns2, module)
        }
        Builtin::Int => construct_int(vm, args, kwargs),
        Builtin::Bool => {
            let v = opt(args, 0).unwrap_or(Value::FALSE);
            Ok(Value::bool(vm.truthy(v)?))
        }
        Builtin::Float => {
            let v = match opt(args, 0) {
                None => return Ok(Value::float(0.0)),
                Some(v) => v,
            };
            if let Some(f) = vm.as_f64(v) {
                return Ok(Value::float(f));
            }
            if let Some(s) = vm.as_str(v) {
                let t = s.trim().replace('_', "");
                let parsed = match t.to_ascii_lowercase().as_str() {
                    "inf" | "+inf" | "infinity" | "+infinity" => Some(f64::INFINITY),
                    "-inf" | "-infinity" => Some(f64::NEG_INFINITY),
                    "nan" | "+nan" | "-nan" => Some(f64::NAN),
                    _ => t.parse::<f64>().ok(),
                };
                return match parsed {
                    Some(f) => Ok(Value::float(f)),
                    None => Err(vm.value_error(format!("could not convert string to float: {}", crate::format::str_repr(s)))),
                };
            }
            let fl = vm.n.float_;
            if let Some(m) = vm.lookup_method(v, fl) {
                return vm.call(m, &[v], &[]);
            }
            let t = vm.type_name(v);
            Err(vm.type_error(format!("float() argument must be a string or a real number, not '{t}'")))
        }
        Builtin::Str => {
            let v = match opt(args, 0) {
                None => return Ok(vm.n.empty),
                Some(v) => v,
            };
            if args.len() > 1 {
                // str(bytes, encoding)
                if let Obj::Bytes(b) | Obj::ByteArray(b) = vm.heap.get(v) {
                    let s = String::from_utf8_lossy(b).into_owned();
                    return Ok(vm.string(s));
                }
            }
            let s = vm.str_of(v)?;
            Ok(vm.string(s))
        }
        Builtin::List => {
            let items = match opt(args, 0) {
                Some(v) => vm.collect_iter(v)?,
                None => Vec::new(),
            };
            Ok(vm.list(items))
        }
        Builtin::Tuple => {
            let items = match opt(args, 0) {
                Some(v) => vm.collect_iter(v)?,
                None => Vec::new(),
            };
            Ok(vm.tuple(items))
        }
        Builtin::Dict => {
            let mut d = PyDict::new();
            if let Some(src) = opt(args, 0) {
                let items = if src.is_obj() && matches!(vm.heap.get(src), Obj::Dict(_)) {
                    vm.take_dict_snapshot(src)?
                } else {
                    let keys_name = vm.n.keys;
                    if vm.get_attr(src, keys_name).is_ok() {
                        vm.mapping_items(src)?
                    } else {
                        let pairs = vm.collect_iter(src)?;
                        let mut out = Vec::with_capacity(pairs.len());
                        for p in pairs {
                            let kv = vm.collect_iter(p)?;
                            if kv.len() != 2 {
                                return Err(vm.value_error("dictionary update sequence element has wrong length"));
                            }
                            out.push((kv[0], kv[1]));
                        }
                        out
                    }
                };
                let dv = vm.dict(d);
                vm.roots.push(dv);
                for (k, v) in items {
                    if let Err(e) = vm.key_set(dv, k, v) {
                        vm.roots.pop();
                        return Err(e);
                    }
                }
                vm.roots.pop();
                for &(k, v) in kwargs {
                    vm.dict_set(dv, k, v);
                }
                return Ok(dv);
            }
            for &(k, v) in kwargs {
                d.set(&vm.heap, k, v);
            }
            Ok(vm.dict(d))
        }
        Builtin::Set | Builtin::FrozenSet => {
            let sv = vm.heap.alloc(if kind == Builtin::Set { Obj::Set(PyDict::new()) } else { Obj::FrozenSet(PyDict::new()) });
            if let Some(src) = opt(args, 0) {
                vm.roots.push(sv);
                let items = vm.collect_iter(src);
                let r = items.and_then(|items| {
                    for it in items {
                        vm.key_set(sv, it, Value::NONE)?;
                    }
                    Ok(())
                });
                vm.roots.pop();
                r?;
            }
            Ok(sv)
        }
        Builtin::Bytes | Builtin::ByteArray => {
            let bytes = match opt(args, 0) {
                None => Vec::new(),
                Some(v) => {
                    if let Some(s) = vm.as_str(v) {
                        if args.len() < 2 {
                            return Err(vm.type_error("string argument without an encoding"));
                        }
                        s.as_bytes().to_vec()
                    } else if let Some(n) = vm.as_i64(v) {
                        vec![0u8; n.max(0) as usize]
                    } else if let Obj::Bytes(b) | Obj::ByteArray(b) = vm.heap.get(v) {
                        b.clone()
                    } else {
                        let items = vm.collect_iter(v)?;
                        let mut out = Vec::with_capacity(items.len());
                        for it in items {
                            match vm.as_i64(it) {
                                Some(n) if (0..256).contains(&n) => out.push(n as u8),
                                _ => return Err(vm.value_error("bytes must be in range(0, 256)")),
                            }
                        }
                        out
                    }
                }
            };
            Ok(vm.heap.alloc(if kind == Builtin::Bytes { Obj::Bytes(bytes) } else { Obj::ByteArray(bytes) }))
        }
        Builtin::NoneType => Ok(Value::NONE),
        Builtin::Range => {
            check_args(vm, args, 1, 3, "range")?;
            let a = vm.expect_int(args[0], "range")?;
            let (start, stop, step) = match args.len() {
                1 => (0, a, 1),
                2 => (a, vm.expect_int(args[1], "range")?, 1),
                _ => (a, vm.expect_int(args[1], "range")?, vm.expect_int(args[2], "range")?),
            };
            if step == 0 {
                return Err(vm.value_error("range() arg 3 must not be zero"));
            }
            Ok(vm.heap.alloc(Obj::Range { start, stop, step }))
        }
        Builtin::Slice => {
            check_args(vm, args, 1, 3, "slice")?;
            let (start, stop, step) = match args.len() {
                1 => (Value::NONE, args[0], Value::NONE),
                2 => (args[0], args[1], Value::NONE),
                _ => (args[0], args[1], args[2]),
            };
            Ok(vm.heap.alloc(Obj::Slice { start, stop, step }))
        }
        Builtin::Property => {
            let get = opt(args, 0).or_else(|| kwarg(vm, kwargs, "fget")).unwrap_or(Value::NONE);
            let set = opt(args, 1).or_else(|| kwarg(vm, kwargs, "fset")).unwrap_or(Value::NONE);
            let del = opt(args, 2).or_else(|| kwarg(vm, kwargs, "fdel")).unwrap_or(Value::NONE);
            Ok(vm.heap.alloc(Obj::Property { get, set, del }))
        }
        Builtin::StaticMethod => {
            let f = arg(vm, args, 0, "staticmethod")?;
            Ok(vm.heap.alloc(Obj::StaticMethod(f)))
        }
        Builtin::ClassMethod => {
            let f = arg(vm, args, 0, "classmethod")?;
            Ok(vm.heap.alloc(Obj::ClassMethod(f)))
        }
        Builtin::Owner | Builtin::Signal | Builtin::Memo | Builtin::Effect | Builtin::RenderEffect => crate::core::construct(vm, cls, kind, args, kwargs),
        Builtin::BaseException => {
            let exc = vm.heap.alloc(Obj::Exc(Box::new(Exc {
                class: cls,
                args: args.to_vec(),
                traceback: Vec::new(),
                cause: Value::NONE,
                context: Value::NONE,
                suppress_context: false,
                dict: PyDict::new(),
            })));
            // A user `__init__` (typically calling super().__init__) runs on the object.
            let init = vm.n.init;
            if let Some(f) = vm.class_lookup(cls, init) {
                if matches!(vm.heap.get(f), Obj::Func(_)) {
                    vm.roots.push(exc);
                    let mut all = Vec::with_capacity(args.len() + 1);
                    all.push(exc);
                    all.extend_from_slice(args);
                    let r = vm.call(f, &all, kwargs);
                    vm.roots.pop();
                    r?;
                }
            }
            Ok(exc)
        }
        Builtin::Module => {
            let name = arg(vm, args, 0, "module")?;
            let s = vm.expect_str(name, "module name")?;
            Ok(vm.new_module(&s))
        }
        Builtin::Template => {
            // Template(*args): strings and interpolations interleaved.
            let mut strings = Vec::new();
            let mut interps = Vec::new();
            let mut last_was_str = false;
            for &a in args {
                if vm.as_str(a).is_some() {
                    if last_was_str {
                        let prev = strings.pop().unwrap();
                        let joined = format!("{}{}", vm.as_str(prev).unwrap(), vm.as_str(a).unwrap());
                        strings.push(vm.string(joined));
                    } else {
                        strings.push(a);
                    }
                    last_was_str = true;
                } else {
                    if !last_was_str {
                        strings.push(vm.n.empty);
                    }
                    interps.push(a);
                    last_was_str = false;
                }
            }
            if !last_was_str {
                strings.push(vm.n.empty);
            }
            let strings = vm.tuple(strings);
            let interpolations = vm.tuple(interps);
            Ok(vm.heap.alloc(Obj::Template { strings, interpolations }))
        }
        Builtin::Interpolation => {
            let value = arg(vm, args, 0, "Interpolation")?;
            let expression = opt(args, 1).unwrap_or(vm.n.empty);
            let conversion = opt(args, 2).unwrap_or(Value::NONE);
            let format_spec = opt(args, 3).unwrap_or(vm.n.empty);
            Ok(vm.heap.alloc(Obj::Interpolation { value, expression, conversion, format_spec }))
        }
        _ => {
            let n = vm.class_name(cls);
            Err(vm.type_error(format!("cannot create '{n}' instances")))
        }
    }
}

fn construct_super(vm: &mut Vm, args: &[Value]) -> PyResult {
    check_args(vm, args, 2, 2, "super")?;
    Ok(vm.heap.alloc(Obj::Super { class: args[0], this: args[1] }))
}

fn construct_int(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let v = match opt(args, 0) {
        None => return Ok(Value::int(0)),
        Some(v) => v,
    };
    let base = match opt(args, 1).or_else(|| kwarg(vm, kwargs, "base")) {
        Some(b) => vm.expect_int(b, "base")?,
        None => 10,
    };
    if let Some(s) = vm.as_str(v).map(|s| s.to_string()) {
        return parse_int(vm, &s, base as u32);
    }
    if v.is_float() {
        let f = v.as_float();
        if f.is_nan() {
            return Err(vm.value_error("cannot convert float NaN to integer"));
        }
        if f.is_infinite() {
            return Err(vm.overflow_error("cannot convert float infinity to integer"));
        }
        return Ok(vm.int(f.trunc() as i64));
    }
    if let Some(i) = vm.as_i64(v) {
        return Ok(vm.int(i));
    }
    if let Obj::Bytes(b) | Obj::ByteArray(b) = vm.heap.get(v) {
        let s = String::from_utf8_lossy(b).into_owned();
        return parse_int(vm, &s, base as u32);
    }
    let name = vm.n.int_;
    if let Some(m) = vm.lookup_method(v, name) {
        return vm.call(m, &[v], &[]);
    }
    let idx = vm.n.index;
    if let Some(m) = vm.lookup_method(v, idx) {
        return vm.call(m, &[v], &[]);
    }
    let t = vm.type_name(v);
    Err(vm.type_error(format!("int() argument must be a string, a bytes-like object or a real number, not '{t}'")))
}

fn parse_int(vm: &mut Vm, s: &str, base: u32) -> PyResult {
    let t = s.trim().replace('_', "");
    let (neg, body) = match t.strip_prefix('-') {
        Some(r) => (true, r.to_string()),
        None => (false, t.strip_prefix('+').unwrap_or(&t).to_string()),
    };
    let lower = body.to_ascii_lowercase();
    let (base, digits) = if base == 0 {
        if let Some(r) = lower.strip_prefix("0x") {
            (16, r.to_string())
        } else if let Some(r) = lower.strip_prefix("0o") {
            (8, r.to_string())
        } else if let Some(r) = lower.strip_prefix("0b") {
            (2, r.to_string())
        } else {
            (10, lower)
        }
    } else if base == 16 {
        (16, lower.strip_prefix("0x").unwrap_or(&lower).to_string())
    } else if base == 8 {
        (8, lower.strip_prefix("0o").unwrap_or(&lower).to_string())
    } else if base == 2 {
        (2, lower.strip_prefix("0b").unwrap_or(&lower).to_string())
    } else {
        (base, lower)
    };
    match i64::from_str_radix(&digits, base) {
        Ok(n) if !digits.is_empty() => Ok(vm.int(if neg { -n } else { n })),
        _ => Err(vm.value_error(format!("invalid literal for int() with base {base}: {}", crate::format::str_repr(s)))),
    }
}

// -- builtin functions ---------------------------------------------------------------------------

fn b_print(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let sep = match kwarg(vm, kwargs, "sep") {
        Some(v) if !v.is_none() => vm.expect_str(v, "sep")?,
        _ => " ".into(),
    };
    let end = match kwarg(vm, kwargs, "end") {
        Some(v) if !v.is_none() => vm.expect_str(v, "end")?,
        _ => "\n".into(),
    };
    let file = kwarg(vm, kwargs, "file").unwrap_or(Value::NONE);
    let mut out = String::new();
    for (i, &a) in args.iter().enumerate() {
        if i > 0 {
            out.push_str(&sep);
        }
        let s = vm.str_of(a)?;
        out.push_str(&s);
    }
    out.push_str(&end);
    if file.is_none() {
        vm.host.write_stdout(&out);
    } else {
        let w = vm.intern("write");
        let m = vm.get_attr(file, w)?;
        let s = vm.string(out);
        vm.call(m, &[s], &[])?;
    }
    Ok(Value::NONE)
}
fn b_len(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "len")?;
    let n = vm.len(args[0])?;
    Ok(vm.int(n as i64))
}
fn b_repr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "repr")?;
    let s = vm.repr(args[0])?;
    Ok(vm.string(s))
}
fn b_ascii(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "ascii")?;
    let s = vm.repr(args[0])?;
    let s = crate::format::ascii_escape(&s);
    Ok(vm.string(s))
}
fn b_isinstance(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "isinstance")?;
    let (v, cls) = (args[0], args[1]);
    if !cls.is_obj() || !matches!(vm.heap.get(cls), Obj::Class(_) | Obj::Tuple(_)) {
        return Err(vm.type_error("isinstance() arg 2 must be a type, a tuple of types, or a union"));
    }
    Ok(Value::bool(vm.is_instance_of(v, cls)))
}
fn b_issubclass(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "issubclass")?;
    if !args[0].is_obj() || !matches!(vm.heap.get(args[0]), Obj::Class(_)) {
        return Err(vm.type_error("issubclass() arg 1 must be a class"));
    }
    Ok(Value::bool(vm.class_matches(args[0], args[1])))
}
fn attr_name(vm: &mut Vm, v: Value) -> PyResult {
    match vm.as_str(v) {
        Some(s) => {
            let s = s.to_string();
            Ok(vm.intern(&s))
        }
        None => Err(vm.type_error("attribute name must be string")),
    }
}
fn b_getattr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 3, "getattr")?;
    let name = attr_name(vm, args[1])?;
    match vm.get_attr(args[0], name) {
        Ok(v) => Ok(v),
        Err(e) => {
            let ae = vm.t.attribute_error;
            if args.len() == 3 && vm.exc_matches(e, ae) {
                Ok(args[2])
            } else {
                Err(e)
            }
        }
    }
}
fn b_setattr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 3, 3, "setattr")?;
    let name = attr_name(vm, args[1])?;
    vm.set_attr(args[0], name, args[2])?;
    Ok(Value::NONE)
}
fn b_hasattr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "hasattr")?;
    let name = attr_name(vm, args[1])?;
    match vm.get_attr(args[0], name) {
        Ok(_) => Ok(Value::TRUE),
        Err(e) => {
            let ae = vm.t.attribute_error;
            if vm.exc_matches(e, ae) {
                Ok(Value::FALSE)
            } else {
                Err(e)
            }
        }
    }
}
fn b_delattr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "delattr")?;
    let name = attr_name(vm, args[1])?;
    vm.del_attr(args[0], name)?;
    Ok(Value::NONE)
}
fn b_callable(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "callable")?;
    let v = args[0];
    if !v.is_obj() {
        return Ok(Value::FALSE);
    }
    Ok(Value::bool(match vm.heap.get(v) {
        Obj::Func(_) | Obj::Native(_) | Obj::Bound { .. } | Obj::Class(_) | Obj::StaticMethod(_) => true,
        Obj::Instance(_) => {
            let c = vm.n.call;
            vm.lookup_method(v, c).is_some()
        }
        Obj::Js(_) => true,
        Obj::Node(n) => matches!(n.kind, crate::core::Kind::Signal | crate::core::Kind::Memo),
        _ => false,
    }))
}
fn b_id(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "id")?;
    let v = args[0];
    Ok(vm.int(if v.is_obj() { v.as_obj() as i64 + 0x1000 } else { (v.0 & 0xffff_ffff_ffff) as i64 }))
}
fn b_hash(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "hash")?;
    let v = args[0];
    if v.is_obj() && matches!(vm.heap.get(v), Obj::Instance(_)) {
        let h = vm.n.hash;
        if let Some(m) = vm.lookup_method(v, h) {
            if !vm.is_object_native(m) {
                return vm.call(m, &[v], &[]);
            }
        }
    }
    match crate::dict::hash_value(&vm.heap, v) {
        Some(h) => Ok(vm.int((h as i64) & 0x3fff_ffff_ffff_ffff)),
        None => {
            let t = vm.type_name(v);
            Err(vm.type_error(format!("unhashable type: '{t}'")))
        }
    }
}

/// Stable merge sort of the list object `list`, with a key function called once per element.
/// The items stay in the (rooted) list while comparisons run Python.
pub fn sort_values(vm: &mut Vm, list: Value, key: Value, reverse: bool) -> PyResult<()> {
    let items: Vec<Value> = match vm.heap.get(list) {
        Obj::List(l) => l.clone(),
        _ => return Err(vm.type_error("sort on a non-list")),
    };
    let n = items.len();
    let keys_list = vm.list(Vec::new());
    vm.roots.push(keys_list);
    let keys: Vec<Value> = if key.is_none() {
        items.clone()
    } else {
        let mut ks = Vec::with_capacity(n);
        for &it in items.iter() {
            let k = match vm.call(key, &[it], &[]) {
                Ok(k) => k,
                Err(e) => {
                    vm.roots.pop();
                    return Err(e);
                }
            };
            if let Obj::List(l) = vm.heap.get_mut(keys_list) {
                l.push(k);
            }
            ks.push(k);
        }
        ks
    };
    // indices sorted by key; merge sort for stability, comparisons through the VM.
    let mut idx: Vec<usize> = (0..n).collect();
    let mut buf = vec![0usize; n];
    let mut err = None;
    merge_sort(vm, &mut idx, &mut buf, &keys, reverse, &mut err);
    vm.roots.pop();
    if let Some(e) = err {
        return Err(e);
    }
    let out: Vec<Value> = idx.iter().map(|&i| items[i]).collect();
    if let Obj::List(l) = vm.heap.get_mut(list) {
        *l = out;
    }
    Ok(())
}

fn less(vm: &mut Vm, keys: &[Value], a: usize, b: usize, reverse: bool, err: &mut Option<Value>) -> bool {
    if err.is_some() {
        return false;
    }
    let (x, y) = if reverse { (keys[b], keys[a]) } else { (keys[a], keys[b]) };
    match vm.compare(CmpOp::Lt, x, y).and_then(|r| vm.truthy(r)) {
        Ok(b) => b,
        Err(e) => {
            *err = Some(e);
            false
        }
    }
}

fn merge_sort(vm: &mut Vm, idx: &mut [usize], buf: &mut [usize], keys: &[Value], reverse: bool, err: &mut Option<Value>) {
    let n = idx.len();
    if n <= 1 {
        return;
    }
    if n <= 12 {
        // insertion sort, stable
        for i in 1..n {
            let mut j = i;
            while j > 0 && less(vm, keys, idx[j], idx[j - 1], reverse, err) {
                idx.swap(j, j - 1);
                j -= 1;
            }
        }
        return;
    }
    let mid = n / 2;
    {
        let (l, r) = idx.split_at_mut(mid);
        let (bl, br) = buf.split_at_mut(mid);
        merge_sort(vm, l, bl, keys, reverse, err);
        merge_sort(vm, r, br, keys, reverse, err);
    }
    let (mut i, mut j, mut k) = (0, mid, 0);
    while i < mid && j < n {
        if less(vm, keys, idx[j], idx[i], reverse, err) {
            buf[k] = idx[j];
            j += 1;
        } else {
            buf[k] = idx[i];
            i += 1;
        }
        k += 1;
    }
    while i < mid {
        buf[k] = idx[i];
        i += 1;
        k += 1;
    }
    while j < n {
        buf[k] = idx[j];
        j += 1;
        k += 1;
    }
    idx.copy_from_slice(&buf[..n]);
}

fn b_sorted(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "sorted")?;
    let items = vm.collect_iter(args[0])?;
    let key = kwarg(vm, kwargs, "key").unwrap_or(Value::NONE);
    let reverse = match kwarg(vm, kwargs, "reverse") {
        Some(v) => vm.truthy(v)?,
        None => false,
    };
    let list = vm.list(items);
    vm.roots.push(list);
    let r = sort_values(vm, list, key, reverse);
    vm.roots.pop();
    r?;
    Ok(list)
}
fn b_sum(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 2, "sum")?;
    let items = vm.collect_iter(args[0])?;
    let holder = vm.list(items.clone());
    vm.roots.push(holder);
    let mut acc = opt(args, 1).or_else(|| kwarg(vm, kwargs, "start")).unwrap_or(Value::int(0));
    for it in items {
        vm.roots.push(acc);
        let r = vm.binary_op(crate::code::BinOp::Add, acc, it);
        vm.roots.pop();
        match r {
            Ok(v) => acc = v,
            Err(e) => {
                vm.roots.pop();
                return Err(e);
            }
        }
    }
    vm.roots.pop();
    Ok(acc)
}
fn min_max(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)], want_max: bool) -> PyResult {
    let fname = if want_max { "max" } else { "min" };
    let items = if args.len() == 1 { vm.collect_iter(args[0])? } else { args.to_vec() };
    let key = kwarg(vm, kwargs, "key").unwrap_or(Value::NONE);
    let default = kwarg(vm, kwargs, "default");
    if items.is_empty() {
        return match default {
            Some(d) => Ok(d),
            None => Err(vm.value_error(format!("{fname}() iterable argument is empty"))),
        };
    }
    let holder = vm.list(items.clone());
    vm.roots.push(holder);
    let r = (|| {
        let mut best = items[0];
        let mut best_key = if key.is_none() { best } else { vm.call(key, &[best], &[])? };
        for &it in &items[1..] {
            vm.roots.push(best_key);
            let k = if key.is_none() { Ok(it) } else { vm.call(key, &[it], &[]) };
            vm.roots.pop();
            let k = k?;
            vm.roots.push(k);
            let better = if want_max { vm.compare(CmpOp::Gt, k, best_key) } else { vm.compare(CmpOp::Lt, k, best_key) };
            vm.roots.pop();
            if vm.truthy(better?)? {
                best = it;
                best_key = k;
            }
        }
        Ok(best)
    })();
    vm.roots.pop();
    r
}
fn b_min(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    min_max(vm, args, kwargs, false)
}
fn b_max(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    min_max(vm, args, kwargs, true)
}
fn b_abs(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "abs")?;
    let v = args[0];
    if v.is_float() {
        return Ok(Value::float(v.as_float().abs()));
    }
    if let Some(i) = vm.as_i64(v) {
        return Ok(vm.int(i.abs()));
    }
    let t = vm.type_name(v);
    Err(vm.type_error(format!("bad operand type for abs(): '{t}'")))
}
fn b_round(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 2, "round")?;
    let v = args[0];
    let nd = match opt(args, 1) {
        Some(n) if !n.is_none() => Some(vm.expect_int(n, "ndigits")?),
        _ => None,
    };
    if let Some(i) = vm.as_i64(v).filter(|_| !v.is_float()) {
        return Ok(match nd {
            Some(d) if d < 0 => {
                let p = 10i64.pow((-d) as u32);
                let q = (i as f64 / p as f64).round_ties_even() as i64;
                vm.int(q * p)
            }
            _ => vm.int(i),
        });
    }
    let f = match vm.as_f64(v) {
        Some(f) => f,
        None => {
            let t = vm.type_name(v);
            return Err(vm.type_error(format!("type {t} doesn't define __round__ method")));
        }
    };
    match nd {
        None => {
            let r = f.round_ties_even();
            if r.is_nan() || r.is_infinite() {
                return Err(vm.value_error("cannot convert float NaN or infinity to integer"));
            }
            Ok(vm.int(r as i64))
        }
        Some(d) if d >= 0 => {
            // Correctly rounded on the exact binary value, as CPython does: 2.675 → 2.67.
            let s = format!("{:.*}", d as usize, f);
            Ok(Value::float(s.parse().unwrap_or(f)))
        }
        Some(d) => {
            let p = 10f64.powi((-d) as i32);
            Ok(Value::float((f / p).round_ties_even() * p))
        }
    }
}
fn b_enumerate(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 2, "enumerate")?;
    let inner = vm.get_iter(args[0])?;
    let start = match opt(args, 1).or_else(|| kwarg(vm, kwargs, "start")) {
        Some(s) => vm.expect_int(s, "start")?,
        None => 0,
    };
    Ok(vm.heap.alloc(Obj::Iter(Iter::Enumerate { inner, count: start })))
}
fn b_zip(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let mut iters = Vec::with_capacity(args.len());
    for &a in args {
        iters.push(vm.get_iter(a)?);
    }
    Ok(vm.heap.alloc(Obj::Iter(Iter::Zip { iters })))
}
fn b_map(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    if args.len() < 2 {
        return Err(vm.type_error("map() must have at least two arguments."));
    }
    let mut iters = Vec::with_capacity(args.len() - 1);
    for &a in &args[1..] {
        iters.push(vm.get_iter(a)?);
    }
    Ok(vm.heap.alloc(Obj::Iter(Iter::Map { func: args[0], iters })))
}
fn b_filter(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "filter")?;
    let inner = vm.get_iter(args[1])?;
    Ok(vm.heap.alloc(Obj::Iter(Iter::Filter { func: args[0], inner })))
}
fn b_any(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "any")?;
    let it = vm.get_iter(args[0])?;
    vm.roots.push(it);
    let r = loop {
        match vm.iter_next(it) {
            Ok(Some(v)) => match vm.truthy(v) {
                Ok(true) => break Ok(Value::TRUE),
                Ok(false) => {}
                Err(e) => break Err(e),
            },
            Ok(None) => break Ok(Value::FALSE),
            Err(e) => break Err(e),
        }
    };
    vm.roots.pop();
    r
}
fn b_all(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "all")?;
    let it = vm.get_iter(args[0])?;
    vm.roots.push(it);
    let r = loop {
        match vm.iter_next(it) {
            Ok(Some(v)) => match vm.truthy(v) {
                Ok(false) => break Ok(Value::FALSE),
                Ok(true) => {}
                Err(e) => break Err(e),
            },
            Ok(None) => break Ok(Value::TRUE),
            Err(e) => break Err(e),
        }
    };
    vm.roots.pop();
    r
}
fn b_iter(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 2, "iter")?;
    if args.len() == 2 {
        return Ok(vm.heap.alloc(Obj::Iter(Iter::Callable { func: args[0], sentinel: args[1] })));
    }
    vm.get_iter(args[0])
}
fn b_next(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 2, "next")?;
    match vm.iter_next(args[0])? {
        Some(v) => Ok(v),
        None => match opt(args, 1) {
            Some(d) => Ok(d),
            None => Err(vm.stop_iteration(Value::NONE)),
        },
    }
}
fn b_reversed(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "reversed")?;
    let v = args[0];
    if v.is_obj() {
        match vm.heap.get(v) {
            Obj::List(_) | Obj::Tuple(_) | Obj::Str(_) => return Ok(vm.heap.alloc(Obj::Iter(Iter::Reversed { seq: v, at: usize::MAX }))),
            Obj::Range { start, stop, step } => {
                let (start, stop, step) = (*start, *stop, *step);
                let n = crate::ops::range_len(start, stop, step);
                let last = start + step * (n - 1);
                return Ok(vm.heap.alloc(Obj::Iter(Iter::Range { cur: last, stop: start - step, step: -step })));
            }
            Obj::Instance(_) => {
                let r = vm.n.reversed;
                if let Some(m) = vm.lookup_method(v, r) {
                    return vm.call(m, &[v], &[]);
                }
            }
            _ => {}
        }
    }
    let items = vm.collect_iter(v)?;
    let items: Vec<Value> = items.into_iter().rev().collect();
    let l = vm.list(items);
    vm.get_iter(l)
}
fn b_chr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "chr")?;
    let n = vm.expect_int(args[0], "chr")?;
    match char::from_u32(n as u32) {
        Some(c) => {
            let mut buf = [0u8; 4];
            Ok(vm.str(c.encode_utf8(&mut buf)))
        }
        None => Err(vm.value_error("chr() arg not in range(0x110000)")),
    }
}
fn b_ord(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "ord")?;
    if let Some(s) = vm.as_str(args[0]) {
        let mut it = s.chars();
        if let (Some(c), None) = (it.next(), it.next()) {
            return Ok(vm.int(c as i64));
        }
        let n = s.chars().count();
        return Err(vm.type_error(format!("ord() expected a character, but string of length {n} found")));
    }
    if let Obj::Bytes(b) = vm.heap.get(args[0]) {
        if b.len() == 1 {
            return Ok(Value::int(b[0] as i32));
        }
    }
    Err(vm.type_error("ord() expected string of length 1"))
}
fn b_format(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 2, "format")?;
    let spec = match opt(args, 1) {
        Some(s) => vm.expect_str(s, "format spec")?,
        None => String::new(),
    };
    let s = vm.format_value(args[0], &spec)?;
    Ok(vm.string(s))
}
fn b_divmod(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "divmod")?;
    let q = vm.binary_op(crate::code::BinOp::FloorDiv, args[0], args[1])?;
    let r = vm.binary_op(crate::code::BinOp::Mod, args[0], args[1])?;
    Ok(vm.tuple(vec![q, r]))
}
fn b_pow(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 3, "pow")?;
    if args.len() == 3 {
        let (b, e, m) = (vm.expect_int(args[0], "base")?, vm.expect_int(args[1], "exp")?, vm.expect_int(args[2], "mod")?);
        if m == 0 {
            return Err(vm.value_error("pow() 3rd argument cannot be 0"));
        }
        let mut result: i128 = 1;
        let mut base = (b as i128).rem_euclid(m as i128);
        let mut exp = e;
        while exp > 0 {
            if exp & 1 == 1 {
                result = (result * base).rem_euclid(m as i128);
            }
            base = (base * base).rem_euclid(m as i128);
            exp >>= 1;
        }
        return Ok(vm.int(result as i64));
    }
    vm.binary_op(crate::code::BinOp::Pow, args[0], args[1])
}
fn radix(vm: &mut Vm, args: &[Value], prefix: &str, f: fn(i64) -> String) -> PyResult {
    check_args(vm, args, 1, 1, "hex")?;
    let n = vm.expect_int(args[0], "argument")?;
    let s = format!("{}{prefix}{}", if n < 0 { "-" } else { "" }, f(n.abs()));
    Ok(vm.string(s))
}
fn b_hex(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    radix(vm, args, "0x", |n| format!("{n:x}"))
}
fn b_oct(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    radix(vm, args, "0o", |n| format!("{n:o}"))
}
fn b_bin(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    radix(vm, args, "0b", |n| format!("{n:b}"))
}
/// `compile(source, filename, mode)`: a code object, when this runtime carries the compiler
/// (the native runner, the playground's wasm); the page's runtime has none.
fn b_compile(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 3, "compile")?;
    if args[0].is_obj() && matches!(vm.heap.get(args[0]), Obj::Code(_)) {
        return Ok(args[0]);
    }
    let source = vm.expect_str(args[0], "source")?;
    let filename = match args.get(1) {
        Some(&f) => vm.str_of(f)?,
        None => "<string>".to_string(),
    };
    let compile = match vm.compiler {
        Some(c) => c,
        None => return Err(vm.runtime_error("compile(): this runtime carries no compiler (the page runs bytecode)")),
    };
    match compile(vm, &source, &filename) {
        Ok(code) => Ok(vm.heap.alloc(Obj::Code(code))),
        Err(msg) => {
            let c = vm.t.syntax_error;
            Err(vm.exception(c, msg))
        }
    }
}
/// `exec(source_or_code, globals=None, locals=None)`.
fn b_exec(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 3, "exec")?;
    let code_v = b_compile(vm, &args[..1], &[])?;
    let code = match vm.heap.get(code_v) {
        Obj::Code(c) => c.clone(),
        _ => unreachable!(),
    };
    let globals = match args.get(1) {
        Some(&g) if !g.is_none() => g,
        _ => vm.frames.last().map(|f| f.globals).unwrap_or(Value::NONE),
    };
    let locals = match args.get(2) {
        Some(&l) if !l.is_none() => l,
        _ => globals,
    };
    vm.roots.push(code_v);
    let r = vm.run_code(code, globals, locals);
    vm.roots.pop();
    r?;
    Ok(Value::NONE)
}
fn b_globals(vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(vm.frames.last().map(|f| f.globals).unwrap_or(Value::NONE))
}
fn b_vars(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    if args.is_empty() {
        return Ok(vm.frames.last().map(|f| if f.namespace.is_undef() { f.globals } else { f.namespace }).unwrap_or(Value::NONE));
    }
    let d = vm.n.dict;
    vm.get_attr(args[0], d)
}
fn b_dir(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let mut names: Vec<Value> = Vec::new();
    if let Some(&v) = args.first() {
        if v.is_obj() {
            match vm.heap.get(v) {
                Obj::Instance(i) => {
                    names.extend(i.dict.keys());
                    let cls = i.class;
                    if let Obj::Class(c) = vm.heap.get(cls) {
                        for &m in c.mro.clone().iter() {
                            if let Obj::Class(mc) = vm.heap.get(m) {
                                names.extend(mc.dict.keys());
                            }
                        }
                    }
                }
                Obj::Class(c) => {
                    for &m in c.mro.clone().iter() {
                        if let Obj::Class(mc) = vm.heap.get(m) {
                            names.extend(mc.dict.keys());
                        }
                    }
                }
                Obj::Module(_) => {
                    let d = vm.module_dict(v);
                    if let Obj::Dict(dd) = vm.heap.get(d) {
                        names.extend(dd.keys());
                    }
                }
                _ => {
                    let t = vm.type_of(v);
                    if let Obj::Class(c) = vm.heap.get(t) {
                        names.extend(c.dict.keys());
                    }
                }
            }
        }
    } else if let Some(f) = vm.frames.last() {
        let ns = if f.namespace.is_undef() { f.globals } else { f.namespace };
        if let Obj::Dict(d) = vm.heap.get(ns) {
            names.extend(d.keys());
        }
    }
    let mut strs: Vec<String> = names.iter().filter_map(|&n| vm.as_str(n).map(|s| s.to_string())).collect();
    strs.sort();
    strs.dedup();
    let items: Vec<Value> = strs.iter().map(|s| vm.str(s)).collect();
    Ok(vm.list(items))
}
fn b_import(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 5, "__import__")?;
    let name = vm.expect_str(args[0], "name")?;
    let leaf = vm.import_module(&name)?;
    let fromlist = opt(args, 3).unwrap_or(Value::NONE);
    if !fromlist.is_none() && vm.len_of(fromlist).unwrap_or(0) > 0 {
        return Ok(leaf);
    }
    let top = name.split('.').next().unwrap_or(&name).to_string();
    vm.import_module(&top)
}
fn b_build_class(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    if args.len() < 2 {
        return Err(vm.type_error("__build_class__: not enough arguments"));
    }
    vm.build_class(args[0], args[1], args[2..].to_vec())
}

// -- object, type, exceptions ---------------------------------------------------------------------------

fn object_init(_vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::NONE)
}
fn object_repr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "__repr__")?;
    let t = vm.type_name(v);
    let s = format!("<{t} object at 0x{:x}>", if v.is_obj() { v.as_obj() } else { 0 });
    Ok(vm.string(s))
}
fn object_str(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "__str__")?;
    let s = vm.repr(v)?;
    Ok(vm.string(s))
}
fn object_format(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "__format__")?;
    let spec = opt(args, 1).map(|s| vm.as_str(s).unwrap_or("").to_string()).unwrap_or_default();
    if !spec.is_empty() {
        let t = vm.type_name(v);
        return Err(vm.type_error(format!("unsupported format string passed to {t}.__format__")));
    }
    let s = vm.str_of(v)?;
    Ok(vm.string(s))
}
fn object_eq(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__eq__")?;
    if vm.is_same(args[0], args[1]) {
        return Ok(Value::TRUE);
    }
    Ok(vm.heap.alloc(Obj::NotImplemented))
}
fn object_ne(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__ne__")?;
    let eq = vm.eq(args[0], args[1])?;
    Ok(Value::bool(!eq))
}
fn object_hash(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "__hash__")?;
    match crate::dict::hash_value(&vm.heap, v) {
        Some(h) => Ok(vm.int((h as i64) & 0x3fff_ffff_ffff_ffff)),
        None => {
            let t = vm.type_name(v);
            Err(vm.type_error(format!("unhashable type: '{t}'")))
        }
    }
}
fn object_setattr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 3, 3, "__setattr__")?;
    let name = attr_name(vm, args[1])?;
    if args[0].is_obj() && matches!(vm.heap.get(args[0]), Obj::Instance(_)) {
        vm.instance_set_attr_direct(args[0], name, args[2])?;
    } else {
        vm.set_attr(args[0], name, args[2])?;
    }
    Ok(Value::NONE)
}
fn object_getattribute(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__getattribute__")?;
    let name = attr_name(vm, args[1])?;
    vm.get_attr_plain(args[0], name)
}
fn object_delattr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__delattr__")?;
    let name = attr_name(vm, args[1])?;
    if let Obj::Instance(i) = vm.heap.get_mut(args[0]) {
        let mut d = core::mem::take(&mut i.dict);
        d.remove(&vm.heap, name);
        if let Obj::Instance(i) = vm.heap.get_mut(args[0]) {
            i.dict = d;
        }
    }
    Ok(Value::NONE)
}
fn object_init_subclass(_vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::NONE)
}
fn type_mro(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let cls = arg(vm, args, 0, "mro")?;
    let mro = match vm.heap.get(cls) {
        Obj::Class(c) => c.mro.clone(),
        _ => vec![],
    };
    Ok(vm.list(mro))
}
fn exc_init(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let e = arg(vm, args, 0, "__init__")?;
    if let Obj::Exc(x) = vm.heap.get_mut(e) {
        x.args = args[1..].to_vec();
    }
    Ok(Value::NONE)
}
fn exc_with_traceback(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    arg(vm, args, 0, "with_traceback")
}
fn exc_add_note(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "add_note")?;
    Ok(Value::NONE)
}
fn none_bool(_vm: &mut Vm, _args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::FALSE)
}

impl Vm {
    pub fn is_object_native(&self, m: Value) -> bool {
        matches!(self.heap.get(m), Obj::Native(_))
    }
    /// Attribute lookup that ignores a `__getattribute__` override (what `object.__getattribute__` does).
    pub fn get_attr_plain(&mut self, obj: Value, name: Value) -> PyResult {
        if obj.is_obj() {
            if let Obj::Instance(i) = self.heap.get(obj) {
                let cls = i.class;
                if let Some(v) = i.dict.get(&self.heap, name) {
                    return Ok(v);
                }
                if let Some(m) = self.class_lookup(cls, name) {
                    return match self.heap.get(m) {
                        Obj::Func(_) | Obj::Native(_) => Ok(self.bound(m, obj)),
                        Obj::Property { get, .. } => {
                            let get = *get;
                            self.call(get, &[obj], &[])
                        }
                        Obj::StaticMethod(f) => Ok(*f),
                        Obj::ClassMethod(f) => {
                            let f = *f;
                            Ok(self.bound(f, cls))
                        }
                        _ => Ok(m),
                    };
                }
                let cn = self.class_name(cls);
                let s = self.as_str(name).unwrap_or("?").to_string();
                return Err(self.attribute_error(format!("'{cn}' object has no attribute '{s}'")));
            }
        }
        self.get_attr(obj, name)
    }
}

/// `property.setter(f)` / `.getter(f)` / `.deleter(f)`: bound to `(property, which)`.
pub fn property_accessor(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "setter")?;
    let holder = args[0];
    let (prop, which) = match vm.heap.get(holder) {
        Obj::Tuple(t) => (t[0], t[1].as_int()),
        _ => return Err(vm.type_error("bad property accessor")),
    };
    let (get, set, del) = match vm.heap.get(prop) {
        Obj::Property { get, set, del } => (*get, *set, *del),
        _ => return Err(vm.type_error("bad property accessor")),
    };
    let f = args[1];
    let (get, set, del) = match which {
        0 => (f, set, del),
        1 => (get, f, del),
        _ => (get, set, f),
    };
    Ok(vm.heap.alloc(Obj::Property { get, set, del }))
}

// -- generic dunders on builtin values (so `str.__len__(s)` and friends resolve) ----------------

fn generic_getitem(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__getitem__")?;
    vm.get_item(args[0], args[1])
}
fn generic_setitem(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 3, 3, "__setitem__")?;
    vm.set_item(args[0], args[1], args[2])?;
    Ok(Value::NONE)
}
fn generic_delitem(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__delitem__")?;
    vm.del_item(args[0], args[1])?;
    Ok(Value::NONE)
}
fn generic_len(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "__len__")?;
    let n = vm.len(args[0])?;
    Ok(vm.int(n as i64))
}
fn generic_contains(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__contains__")?;
    let r = vm.contains(args[0], args[1])?;
    Ok(Value::bool(r))
}
fn generic_iter(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "__iter__")?;
    vm.get_iter(args[0])
}
fn generic_eq(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__eq__")?;
    vm.compare(CmpOp::Eq, args[0], args[1])
}
fn generic_lt(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__lt__")?;
    vm.compare(CmpOp::Lt, args[0], args[1])
}
fn generic_add(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__add__")?;
    vm.binary_op(crate::code::BinOp::Add, args[0], args[1])
}
fn generic_sub(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__sub__")?;
    vm.binary_op(crate::code::BinOp::Sub, args[0], args[1])
}
fn generic_mul(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__mul__")?;
    vm.binary_op(crate::code::BinOp::Mul, args[0], args[1])
}
fn generic_mod(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__mod__")?;
    vm.binary_op(crate::code::BinOp::Mod, args[0], args[1])
}
fn generic_or(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "__or__")?;
    vm.binary_op(crate::code::BinOp::Or, args[0], args[1])
}
fn generic_neg(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "__neg__")?;
    vm.unary_op(crate::code::UnOp::Neg, args[0])
}

// -- str -------------------------------------------------------------------------------------------------

fn str_arg(vm: &mut Vm, args: &[Value], i: usize, what: &str) -> PyResult<String> {
    let v = arg(vm, args, i, what)?;
    vm.expect_str(v, what)
}
fn opt_str(vm: &mut Vm, args: &[Value], i: usize, what: &str) -> PyResult<Option<String>> {
    match opt(args, i) {
        Some(v) if !v.is_none() => Ok(Some(vm.expect_str(v, what)?)),
        _ => Ok(None),
    }
}
fn opt_int(vm: &mut Vm, args: &[Value], i: usize, what: &str) -> PyResult<Option<i64>> {
    match opt(args, i) {
        Some(v) if !v.is_none() => Ok(Some(vm.expect_int(v, what)?)),
        _ => Ok(None),
    }
}
/// Python's `start`/`end` window over a string, in chars, as byte offsets.
fn window(s: &str, start: Option<i64>, end: Option<i64>) -> (usize, usize) {
    let n = s.chars().count() as i64;
    let clamp = |i: i64| if i < 0 { (i + n).max(0) } else { i.min(n) } as usize;
    let (a, b) = (clamp(start.unwrap_or(0)), clamp(end.unwrap_or(n)));
    let byte = |ci: usize| s.char_indices().nth(ci).map(|(b, _)| b).unwrap_or(s.len());
    (byte(a), byte(b.max(a)))
}
fn char_index_of_byte(s: &str, b: usize) -> usize {
    s[..b].chars().count()
}

fn str_join(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let sep = this_str(vm, args, "join")?;
    let it = arg(vm, args, 1, "join")?;
    let items = vm.collect_iter(it)?;
    let mut out = String::new();
    for (i, &v) in items.iter().enumerate() {
        if i > 0 {
            out.push_str(&sep);
        }
        match vm.as_str(v) {
            Some(s) => out.push_str(s),
            None => {
                let t = vm.type_name(v);
                return Err(vm.type_error(format!("sequence item {i}: expected str instance, {t} found")));
            }
        }
    }
    Ok(vm.string(out))
}
fn split_impl(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)], right: bool) -> PyResult {
    let s = this_str(vm, args, "split")?;
    let sep = match opt(args, 1).or_else(|| kwarg(vm, kwargs, "sep")) {
        Some(v) if !v.is_none() => Some(vm.expect_str(v, "sep")?),
        _ => None,
    };
    let maxsplit = match opt(args, 2).or_else(|| kwarg(vm, kwargs, "maxsplit")) {
        Some(v) => vm.expect_int(v, "maxsplit")?,
        None => -1,
    };
    let parts: Vec<String> = match sep {
        None => {
            if maxsplit < 0 {
                s.split_whitespace().map(|p| p.to_string()).collect()
            } else if right {
                let mut parts: Vec<String> = Vec::new();
                let mut rest = s.trim_end().to_string();
                for _ in 0..maxsplit {
                    match rest.trim_end().rfind(char::is_whitespace) {
                        Some(p) => {
                            let tail = rest[p..].trim_start().to_string();
                            parts.push(tail);
                            rest = rest[..p].trim_end().to_string();
                            if rest.is_empty() {
                                break;
                            }
                        }
                        None => break,
                    }
                }
                if !rest.is_empty() {
                    parts.push(rest);
                }
                parts.reverse();
                parts
            } else {
                let mut parts = Vec::new();
                let mut rest = s.trim_start();
                for _ in 0..maxsplit {
                    match rest.find(char::is_whitespace) {
                        Some(p) => {
                            parts.push(rest[..p].to_string());
                            rest = rest[p..].trim_start();
                            if rest.is_empty() {
                                break;
                            }
                        }
                        None => break,
                    }
                }
                if !rest.is_empty() || (parts.is_empty() && !s.is_empty()) {
                    parts.push(rest.to_string());
                }
                parts
            }
        }
        Some(sep) => {
            if sep.is_empty() {
                return Err(vm.value_error("empty separator"));
            }
            if maxsplit < 0 {
                s.split(sep.as_str()).map(|p| p.to_string()).collect()
            } else if right {
                let mut v: Vec<String> = s.rsplitn(maxsplit as usize + 1, sep.as_str()).map(|p| p.to_string()).collect();
                v.reverse();
                v
            } else {
                s.splitn(maxsplit as usize + 1, sep.as_str()).map(|p| p.to_string()).collect()
            }
        }
    };
    let items: Vec<Value> = parts.into_iter().map(|p| vm.string(p)).collect();
    Ok(vm.list(items))
}
fn str_split(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    split_impl(vm, args, kwargs, false)
}
fn str_rsplit(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    split_impl(vm, args, kwargs, true)
}
fn strip_impl(vm: &mut Vm, args: &[Value], left: bool, right: bool) -> PyResult {
    let s = this_str(vm, args, "strip")?;
    let chars = opt_str(vm, args, 1, "chars")?;
    let out = match chars {
        None => match (left, right) {
            (true, true) => s.trim(),
            (true, false) => s.trim_start(),
            _ => s.trim_end(),
        },
        Some(c) => {
            let set: Vec<char> = c.chars().collect();
            let f = |ch: char| set.contains(&ch);
            match (left, right) {
                (true, true) => s.trim_matches(f),
                (true, false) => s.trim_start_matches(f),
                _ => s.trim_end_matches(f),
            }
        }
    }
    .to_string();
    Ok(vm.string(out))
}
fn str_strip(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    strip_impl(vm, args, true, true)
}
fn str_lstrip(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    strip_impl(vm, args, true, false)
}
fn str_rstrip(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    strip_impl(vm, args, false, true)
}
fn str_replace(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "replace")?;
    let old = str_arg(vm, args, 1, "old")?;
    let new = str_arg(vm, args, 2, "new")?;
    let count = opt_int(vm, args, 3, "count")?.unwrap_or(-1);
    let out = if count < 0 { s.replace(&old, &new) } else { s.replacen(&old, &new, count as usize) };
    Ok(vm.string(out))
}
fn affix_matches(vm: &mut Vm, s: &str, affix: Value, ends: bool) -> PyResult<bool> {
    if let Some(a) = vm.as_str(affix) {
        return Ok(if ends { s.ends_with(a) } else { s.starts_with(a) });
    }
    if let Obj::Tuple(items) = vm.heap.get(affix) {
        for &it in items.clone().iter() {
            if affix_matches(vm, s, it, ends)? {
                return Ok(true);
            }
        }
        return Ok(false);
    }
    let t = vm.type_name(affix);
    Err(vm.type_error(format!("{} first arg must be str or a tuple of str, not {t}", if ends { "endswith" } else { "startswith" })))
}
fn str_startswith(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "startswith")?;
    let affix = arg(vm, args, 1, "startswith")?;
    let (a, b) = window(&s, opt_int(vm, args, 2, "start")?, opt_int(vm, args, 3, "end")?);
    let r = affix_matches(vm, &s[a..b], affix, false)?;
    Ok(Value::bool(r))
}
fn str_endswith(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "endswith")?;
    let affix = arg(vm, args, 1, "endswith")?;
    let (a, b) = window(&s, opt_int(vm, args, 2, "start")?, opt_int(vm, args, 3, "end")?);
    let r = affix_matches(vm, &s[a..b], affix, true)?;
    Ok(Value::bool(r))
}
fn find_impl(vm: &mut Vm, args: &[Value], right: bool, raise: bool) -> PyResult {
    let s = this_str(vm, args, "find")?;
    let sub = str_arg(vm, args, 1, "sub")?;
    let (a, b) = window(&s, opt_int(vm, args, 2, "start")?, opt_int(vm, args, 3, "end")?);
    let hay = &s[a..b];
    let pos = if right { hay.rfind(&sub) } else { hay.find(&sub) };
    match pos {
        Some(p) => Ok(vm.int(char_index_of_byte(&s, a + p) as i64)),
        None => {
            if raise {
                Err(vm.value_error("substring not found"))
            } else {
                Ok(Value::int(-1))
            }
        }
    }
}
fn str_find(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    find_impl(vm, args, false, false)
}
fn str_rfind(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    find_impl(vm, args, true, false)
}
fn str_index(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    find_impl(vm, args, false, true)
}
fn str_rindex(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    find_impl(vm, args, true, true)
}
fn str_count(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "count")?;
    let sub = str_arg(vm, args, 1, "sub")?;
    let (a, b) = window(&s, opt_int(vm, args, 2, "start")?, opt_int(vm, args, 3, "end")?);
    let hay = &s[a..b];
    let n = if sub.is_empty() { hay.chars().count() + 1 } else { hay.matches(&sub).count() };
    Ok(vm.int(n as i64))
}
fn map_str(vm: &mut Vm, args: &[Value], name: &str, f: impl Fn(&str) -> String) -> PyResult {
    let s = this_str(vm, args, name)?;
    let out = f(&s);
    Ok(vm.string(out))
}
fn str_lower(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    map_str(vm, args, "lower", |s| s.to_lowercase())
}
fn str_upper(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    map_str(vm, args, "upper", |s| s.to_uppercase())
}
fn str_title(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    map_str(vm, args, "title", |s| {
        let mut out = String::new();
        let mut start = true;
        for c in s.chars() {
            if c.is_alphabetic() {
                if start {
                    out.extend(c.to_uppercase());
                } else {
                    out.extend(c.to_lowercase());
                }
                start = false;
            } else {
                out.push(c);
                start = true;
            }
        }
        out
    })
}
fn str_capitalize(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    map_str(vm, args, "capitalize", |s| {
        let mut it = s.chars();
        match it.next() {
            Some(c) => c.to_uppercase().chain(it.flat_map(|c| c.to_lowercase())).collect(),
            None => String::new(),
        }
    })
}
fn str_swapcase(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    map_str(vm, args, "swapcase", |s| s.chars().flat_map(|c| if c.is_uppercase() { c.to_lowercase().collect::<Vec<_>>() } else { c.to_uppercase().collect() }).collect())
}
fn pred_str(vm: &mut Vm, args: &[Value], name: &str, f: impl Fn(char) -> bool) -> PyResult {
    let s = this_str(vm, args, name)?;
    Ok(Value::bool(!s.is_empty() && s.chars().all(f)))
}
fn str_isascii(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "isascii")?;
    Ok(Value::bool(s.is_ascii()))
}
fn str_isdigit(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    pred_str(vm, args, "isdigit", |c| c.is_ascii_digit())
}
fn str_isalpha(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    pred_str(vm, args, "isalpha", |c| c.is_alphabetic())
}
fn str_isalnum(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    pred_str(vm, args, "isalnum", |c| c.is_alphanumeric())
}
fn str_isspace(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    pred_str(vm, args, "isspace", |c| c.is_whitespace())
}
fn str_isupper(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "isupper")?;
    Ok(Value::bool(s.chars().any(|c| c.is_alphabetic()) && !s.chars().any(|c| c.is_lowercase())))
}
fn str_islower(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "islower")?;
    Ok(Value::bool(s.chars().any(|c| c.is_alphabetic()) && !s.chars().any(|c| c.is_uppercase())))
}
fn str_isidentifier(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "isidentifier")?;
    let mut it = s.chars();
    let ok = match it.next() {
        Some(c) => (c.is_alphabetic() || c == '_') && it.all(|c| c.is_alphanumeric() || c == '_'),
        None => false,
    };
    Ok(Value::bool(ok))
}
fn str_format(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "format")?;
    let out = crate::format::str_format(vm, &s, &args[1..], kwargs)?;
    Ok(vm.string(out))
}
fn str_format_map(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "format_map")?;
    let m = arg(vm, args, 1, "format_map")?;
    let items = vm.mapping_items(m)?;
    let out = crate::format::str_format(vm, &s, &[], &items)?;
    Ok(vm.string(out))
}
fn partition_impl(vm: &mut Vm, args: &[Value], right: bool) -> PyResult {
    let s = this_str(vm, args, "partition")?;
    let sep = str_arg(vm, args, 1, "sep")?;
    if sep.is_empty() {
        return Err(vm.value_error("empty separator"));
    }
    let pos = if right { s.rfind(&sep) } else { s.find(&sep) };
    let parts: Vec<String> = match pos {
        Some(p) => vec![s[..p].to_string(), sep.clone(), s[p + sep.len()..].to_string()],
        None => {
            if right {
                vec![String::new(), String::new(), s]
            } else {
                vec![s, String::new(), String::new()]
            }
        }
    };
    let items: Vec<Value> = parts.into_iter().map(|p| vm.string(p)).collect();
    Ok(vm.tuple(items))
}
fn str_partition(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    partition_impl(vm, args, false)
}
fn str_rpartition(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    partition_impl(vm, args, true)
}
fn str_splitlines(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "splitlines")?;
    let keep = match opt(args, 1).or_else(|| kwarg(vm, kwargs, "keepends")) {
        Some(v) => vm.truthy(v)?,
        None => false,
    };
    let mut parts = Vec::new();
    let mut start = 0;
    let bytes = s.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        let c = bytes[i];
        if c == b'\n' || c == b'\r' {
            let mut end = i + 1;
            if c == b'\r' && i + 1 < bytes.len() && bytes[i + 1] == b'\n' {
                end += 1;
            }
            let line = if keep { &s[start..end] } else { &s[start..i] };
            parts.push(vm.str(line));
            start = end;
            i = end;
        } else {
            i += 1;
        }
    }
    if start < s.len() {
        parts.push(vm.str(&s[start..]));
    }
    Ok(vm.list(parts))
}
fn str_encode(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "encode")?;
    Ok(vm.heap.alloc(Obj::Bytes(s.into_bytes())))
}
fn str_zfill(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "zfill")?;
    let width = arg(vm, args, 1, "zfill")?;
    let w = vm.expect_int(width, "width")? as usize;
    let n = s.chars().count();
    if n >= w {
        return Ok(vm.string(s));
    }
    let (sign, body) = if s.starts_with(['-', '+']) { s.split_at(1) } else { ("", s.as_str()) };
    let out = format!("{sign}{}{body}", "0".repeat(w - n));
    Ok(vm.string(out))
}
fn justify(vm: &mut Vm, args: &[Value], name: &str, align: char) -> PyResult {
    let s = this_str(vm, args, name)?;
    let width = arg(vm, args, 1, name)?;
    let w = vm.expect_int(width, "width")? as usize;
    let fill = opt_str(vm, args, 2, "fillchar")?.and_then(|f| f.chars().next()).unwrap_or(' ');
    let spec = crate::format::Spec { fill: Some(fill), align: Some(align), width: Some(w), ..Default::default() };
    let out = crate::format::format_str(&s, &spec).map_err(|e| vm.value_error(e))?;
    Ok(vm.string(out))
}
fn str_center(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    // CPython's `str.center` puts the odd space on the left when the width is odd.
    let s = this_str(vm, args, "center")?;
    let width = arg(vm, args, 1, "center")?;
    let w = vm.expect_int(width, "width")? as usize;
    let fill = opt_str(vm, args, 2, "fillchar")?.and_then(|f| f.chars().next()).unwrap_or(' ');
    let n = s.chars().count();
    if n >= w {
        return Ok(vm.string(s));
    }
    let pad = w - n;
    let left = pad / 2 + (pad & w & 1);
    let out = format!("{}{}{}", fill.to_string().repeat(left), s, fill.to_string().repeat(pad - left));
    Ok(vm.string(out))
}
fn str_ljust(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    justify(vm, args, "ljust", '<')
}
fn str_rjust(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    justify(vm, args, "rjust", '>')
}
fn str_removeprefix(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "removeprefix")?;
    let p = str_arg(vm, args, 1, "prefix")?;
    let out = s.strip_prefix(&p).unwrap_or(&s).to_string();
    Ok(vm.string(out))
}
fn str_removesuffix(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "removesuffix")?;
    let p = str_arg(vm, args, 1, "suffix")?;
    let out = s.strip_suffix(&p).unwrap_or(&s).to_string();
    Ok(vm.string(out))
}
fn str_expandtabs(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_str(vm, args, "expandtabs")?;
    let n = opt_int(vm, args, 1, "tabsize")?.unwrap_or(8) as usize;
    let mut out = String::new();
    let mut col = 0;
    for c in s.chars() {
        if c == '\t' {
            let pad = n - (col % n.max(1));
            out.push_str(&" ".repeat(pad));
            col += pad;
        } else {
            out.push(c);
            col = if c == '\n' { 0 } else { col + 1 };
        }
    }
    Ok(vm.string(out))
}

// -- list, tuple -----------------------------------------------------------------------------------------

fn list_append(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let l = this_list(vm, args, "append")?;
    let v = arg(vm, args, 1, "append")?;
    if let Obj::List(items) = vm.heap.get_mut(l) {
        items.push(v);
    }
    Ok(Value::NONE)
}
fn list_extend(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let l = this_list(vm, args, "extend")?;
    let src = arg(vm, args, 1, "extend")?;
    let items = vm.collect_iter(src)?;
    if let Obj::List(v) = vm.heap.get_mut(l) {
        v.extend(items);
    }
    Ok(Value::NONE)
}
fn list_insert(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let l = this_list(vm, args, "insert")?;
    let i = arg(vm, args, 1, "insert")?;
    let i = vm.expect_int(i, "index")?;
    let v = arg(vm, args, 2, "insert")?;
    if let Obj::List(items) = vm.heap.get_mut(l) {
        let n = items.len() as i64;
        let idx = if i < 0 { (i + n).max(0) } else { i.min(n) } as usize;
        items.insert(idx, v);
    }
    Ok(Value::NONE)
}
fn list_pop(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let l = this_list(vm, args, "pop")?;
    let i = opt_int(vm, args, 1, "index")?;
    let n = vm.len_of(l).unwrap_or(0) as i64;
    if n == 0 {
        return Err(vm.index_error("pop from empty list"));
    }
    let idx = match i {
        None => n - 1,
        Some(i) => {
            let idx = if i < 0 { i + n } else { i };
            if idx < 0 || idx >= n {
                return Err(vm.index_error("pop index out of range"));
            }
            idx
        }
    };
    if let Obj::List(items) = vm.heap.get_mut(l) {
        return Ok(items.remove(idx as usize));
    }
    Ok(Value::NONE)
}
fn list_remove(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let l = this_list(vm, args, "remove")?;
    let v = arg(vm, args, 1, "remove")?;
    let items = list_items(vm, l);
    for (i, &x) in items.iter().enumerate() {
        if vm.eq(x, v)? {
            if let Obj::List(items) = vm.heap.get_mut(l) {
                if i < items.len() {
                    items.remove(i);
                }
            }
            return Ok(Value::NONE);
        }
    }
    Err(vm.value_error("list.remove(x): x not in list"))
}
fn list_index(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let l = arg(vm, args, 0, "index")?;
    let v = arg(vm, args, 1, "index")?;
    let start = opt_int(vm, args, 2, "start")?.unwrap_or(0);
    let items = list_items(vm, l);
    let n = items.len() as i64;
    let start = if start < 0 { (start + n).max(0) } else { start } as usize;
    for (i, &x) in items.iter().enumerate().skip(start) {
        if vm.eq(x, v)? {
            return Ok(vm.int(i as i64));
        }
    }
    let r = vm.repr(v)?;
    Err(vm.value_error(format!("{r} is not in list")))
}
fn list_count(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let l = arg(vm, args, 0, "count")?;
    let v = arg(vm, args, 1, "count")?;
    let items = list_items(vm, l);
    let mut n = 0;
    for x in items {
        if vm.eq(x, v)? {
            n += 1;
        }
    }
    Ok(vm.int(n))
}
fn list_clear(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let l = this_list(vm, args, "clear")?;
    if let Obj::List(items) = vm.heap.get_mut(l) {
        items.clear();
    }
    Ok(Value::NONE)
}
fn list_copy(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let l = this_list(vm, args, "copy")?;
    let items = list_items(vm, l);
    Ok(vm.list(items))
}
fn list_reverse(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let l = this_list(vm, args, "reverse")?;
    if let Obj::List(items) = vm.heap.get_mut(l) {
        items.reverse();
    }
    Ok(Value::NONE)
}
fn list_sort(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let l = this_list(vm, args, "sort")?;
    let key = kwarg(vm, kwargs, "key").unwrap_or(Value::NONE);
    let reverse = match kwarg(vm, kwargs, "reverse") {
        Some(v) => vm.truthy(v)?,
        None => false,
    };
    sort_values(vm, l, key, reverse)?;
    Ok(Value::NONE)
}

// -- dict ----------------------------------------------------------------------------------------------------

fn dict_get(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let d = this_dict(vm, args, "get")?;
    let key = arg(vm, args, 1, "get")?;
    Ok(vm.key_get(d, key)?.unwrap_or_else(|| opt(args, 2).unwrap_or(Value::NONE)))
}
fn dict_keys(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let d = this_dict(vm, args, "keys")?;
    let keys: Vec<Value> = match vm.heap.get(d) {
        Obj::Dict(dd) => dd.keys().collect(),
        _ => vec![],
    };
    Ok(vm.list(keys))
}
fn dict_values(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let d = this_dict(vm, args, "values")?;
    let vals: Vec<Value> = match vm.heap.get(d) {
        Obj::Dict(dd) => dd.values().collect(),
        _ => vec![],
    };
    Ok(vm.list(vals))
}
fn dict_items(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let d = this_dict(vm, args, "items")?;
    let items: Vec<(Value, Value)> = match vm.heap.get(d) {
        Obj::Dict(dd) => dd.items().collect(),
        _ => vec![],
    };
    let pairs: Vec<Value> = items.into_iter().map(|(k, v)| vm.tuple(vec![k, v])).collect();
    Ok(vm.list(pairs))
}
fn dict_pop(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let d = this_dict(vm, args, "pop")?;
    let key = arg(vm, args, 1, "pop")?;
    match vm.key_remove(d, key)? {
        Some(v) => Ok(v),
        None => match opt(args, 2) {
            Some(default) => Ok(default),
            None => Err(vm.key_error(key)),
        },
    }
}
fn dict_popitem(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let d = this_dict(vm, args, "popitem")?;
    let mut dd = match vm.heap.take(d) {
        Obj::Dict(dd) => dd,
        _ => unreachable!(),
    };
    let r = dd.pop_last(&vm.heap);
    vm.heap.put(d, Obj::Dict(dd));
    match r {
        Some((k, v)) => Ok(vm.tuple(vec![k, v])),
        None => Err(vm.key_error(Value::NONE)),
    }
}
fn dict_setdefault(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let d = this_dict(vm, args, "setdefault")?;
    let key = arg(vm, args, 1, "setdefault")?;
    if let Some(v) = vm.key_get(d, key)? {
        return Ok(v);
    }
    let default = opt(args, 2).unwrap_or(Value::NONE);
    vm.key_set(d, key, default)?;
    Ok(default)
}
fn dict_update(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let d = this_dict(vm, args, "update")?;
    if let Some(src) = opt(args, 1) {
        let items = if src.is_obj() && matches!(vm.heap.get(src), Obj::Dict(_)) {
            vm.take_dict_snapshot(src)?
        } else {
            let keys_name = vm.n.keys;
            if vm.get_attr(src, keys_name).is_ok() {
                vm.mapping_items(src)?
            } else {
                let pairs = vm.collect_iter(src)?;
                let mut out = Vec::new();
                for p in pairs {
                    let kv = vm.collect_iter(p)?;
                    if kv.len() != 2 {
                        return Err(vm.value_error("dictionary update sequence element has wrong length"));
                    }
                    out.push((kv[0], kv[1]));
                }
                out
            }
        };
        for (k, v) in items {
            vm.key_set(d, k, v)?;
        }
    }
    for &(k, v) in kwargs {
        vm.dict_set(d, k, v);
    }
    Ok(Value::NONE)
}
fn dict_clear(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let d = this_dict(vm, args, "clear")?;
    if let Obj::Dict(dd) = vm.heap.get_mut(d) {
        dd.clear();
    }
    Ok(Value::NONE)
}
fn dict_copy(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let d = this_dict(vm, args, "copy")?;
    let dd = match vm.heap.get(d) {
        Obj::Dict(dd) => dd.clone_shallow(),
        _ => PyDict::new(),
    };
    Ok(vm.dict(dd))
}
fn dict_fromkeys(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    // Called as dict.fromkeys(iterable[, value]) (unbound) or {}.fromkeys(...) (bound).
    let (keys_v, value) = if args.first().map(|&a| a.is_obj() && matches!(vm.heap.get(a), Obj::Dict(_) | Obj::Class(_))).unwrap_or(false) {
        (arg(vm, args, 1, "fromkeys")?, opt(args, 2).unwrap_or(Value::NONE))
    } else {
        (arg(vm, args, 0, "fromkeys")?, opt(args, 1).unwrap_or(Value::NONE))
    };
    let keys = vm.collect_iter(keys_v)?;
    let mut d = PyDict::new();
    for k in keys {
        vm.check_hashable(k)?;
        d.set(&vm.heap, k, value);
    }
    Ok(vm.dict(d))
}

// -- set --------------------------------------------------------------------------------------------------------

fn set_mut(vm: &mut Vm, set: Value, f: impl FnOnce(&crate::heap::Heap, &mut PyDict)) {
    let mut d = match vm.heap.take(set) {
        Obj::Set(d) => d,
        other => {
            vm.heap.put(set, other);
            return;
        }
    };
    f(&vm.heap, &mut d);
    vm.heap.put(set, Obj::Set(d));
}
fn set_add(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_set(vm, args, "add")?;
    let v = arg(vm, args, 1, "add")?;
    vm.key_set(s, v, Value::NONE)?;
    Ok(Value::NONE)
}
fn set_remove(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_set(vm, args, "remove")?;
    let v = arg(vm, args, 1, "remove")?;
    if vm.key_remove(s, v)?.is_none() {
        return Err(vm.key_error(v));
    }
    Ok(Value::NONE)
}
fn set_discard(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_set(vm, args, "discard")?;
    let v = arg(vm, args, 1, "discard")?;
    vm.key_remove(s, v)?;
    Ok(Value::NONE)
}
fn set_pop(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_set(vm, args, "pop")?;
    let first = set_keys(vm, s).first().copied();
    match first {
        Some(v) => {
            set_mut(vm, s, |h, d| {
                d.remove(h, v);
            });
            Ok(v)
        }
        None => Err(vm.key_error(Value::NONE)),
    }
}
fn set_clear(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_set(vm, args, "clear")?;
    set_mut(vm, s, |_, d| d.clear());
    Ok(Value::NONE)
}
fn set_copy(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_set(vm, args, "copy")?;
    let d = match vm.heap.get(s) {
        Obj::Set(d) | Obj::FrozenSet(d) => d.clone_shallow(),
        _ => PyDict::new(),
    };
    Ok(vm.heap.alloc(Obj::Set(d)))
}
fn set_update(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_set(vm, args, "update")?;
    for &src in &args[1..] {
        let items = vm.collect_iter(src)?;
        for it in &items {
            vm.check_hashable(*it)?;
        }
        set_mut(vm, s, |h, d| {
            for it in items {
                d.set(h, it, Value::NONE);
            }
        });
    }
    Ok(Value::NONE)
}
fn set_binop(vm: &mut Vm, args: &[Value], name: &str, op: crate::code::BinOp) -> PyResult {
    let s = this_set(vm, args, name)?;
    let mut acc = s;
    for &other in &args[1..] {
        let other = if other.is_obj() && matches!(vm.heap.get(other), Obj::Set(_) | Obj::FrozenSet(_)) {
            other
        } else {
            let items = vm.collect_iter(other)?;
            let mut d = PyDict::new();
            for it in items {
                vm.check_hashable(it)?;
                d.set(&vm.heap, it, Value::NONE);
            }
            vm.heap.alloc(Obj::Set(d))
        };
        vm.roots.push(acc);
        let r = vm.binary_op(op, acc, other);
        vm.roots.pop();
        acc = r?;
    }
    if acc == s {
        return set_copy(vm, args, &[]);
    }
    Ok(acc)
}
fn set_union(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    set_binop(vm, args, "union", crate::code::BinOp::Or)
}
fn set_intersection(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    set_binop(vm, args, "intersection", crate::code::BinOp::And)
}
fn set_difference(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    set_binop(vm, args, "difference", crate::code::BinOp::Sub)
}
fn set_symmetric_difference(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    set_binop(vm, args, "symmetric_difference", crate::code::BinOp::Xor)
}
fn set_issubset(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_set(vm, args, "issubset")?;
    let other = arg(vm, args, 1, "issubset")?;
    let others = vm.collect_iter(other)?;
    let mut od = PyDict::new();
    for o in others {
        vm.check_hashable(o)?;
        od.set(&vm.heap, o, Value::NONE);
    }
    Ok(Value::bool(set_keys(vm, s).iter().all(|&k| od.contains(&vm.heap, k))))
}
fn set_issuperset(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_set(vm, args, "issuperset")?;
    let other = arg(vm, args, 1, "issuperset")?;
    let others = vm.collect_iter(other)?;
    for o in others {
        if !vm.contains(s, o)? {
            return Ok(Value::FALSE);
        }
    }
    Ok(Value::TRUE)
}
fn set_isdisjoint(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let s = this_set(vm, args, "isdisjoint")?;
    let other = arg(vm, args, 1, "isdisjoint")?;
    let others = vm.collect_iter(other)?;
    for o in others {
        if vm.contains(s, o)? {
            return Ok(Value::FALSE);
        }
    }
    Ok(Value::TRUE)
}

// -- int, float, bytes, generators ------------------------------------------------------------------------------

fn int_bit_length(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "bit_length")?;
    let i = vm.expect_int(v, "self")?;
    Ok(vm.int(64 - i.unsigned_abs().leading_zeros() as i64))
}
fn int_to_bytes(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "to_bytes")?;
    let i = vm.expect_int(v, "self")?;
    let length = match opt(args, 1).or_else(|| kwarg(vm, kwargs, "length")) {
        Some(l) => vm.expect_int(l, "length")? as usize,
        None => 1,
    };
    let big = match opt(args, 2).or_else(|| kwarg(vm, kwargs, "byteorder")) {
        Some(b) => vm.as_str(b) != Some("little"),
        None => true,
    };
    let bytes = i.to_le_bytes();
    let mut out: Vec<u8> = bytes[..length.min(8)].to_vec();
    out.resize(length, if i < 0 { 0xff } else { 0 });
    if big {
        out.reverse();
    }
    Ok(vm.heap.alloc(Obj::Bytes(out)))
}
fn int_index(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "__index__")?;
    let i = vm.expect_int(v, "self")?;
    Ok(vm.int(i))
}
fn float_is_integer(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "is_integer")?;
    Ok(Value::bool(vm.as_f64(v).map(|f| f.fract() == 0.0).unwrap_or(false)))
}
fn bytes_decode(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "decode")?;
    let s = match vm.heap.get(v) {
        Obj::Bytes(b) | Obj::ByteArray(b) => String::from_utf8_lossy(b).into_owned(),
        _ => return Err(vm.type_error("decode on a non-bytes")),
    };
    Ok(vm.string(s))
}
fn bytes_hex(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "hex")?;
    let s = match vm.heap.get(v) {
        Obj::Bytes(b) | Obj::ByteArray(b) => b.iter().map(|x| format!("{x:02x}")).collect::<String>(),
        _ => return Err(vm.type_error("hex on a non-bytes")),
    };
    Ok(vm.string(s))
}
fn bytearray_append(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "append")?;
    let b = arg(vm, args, 1, "append")?;
    let b = vm.expect_int(b, "byte")?;
    if let Obj::ByteArray(bytes) = vm.heap.get_mut(v) {
        bytes.push(b as u8);
    }
    Ok(Value::NONE)
}
fn bytearray_extend(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "extend")?;
    let src = arg(vm, args, 1, "extend")?;
    let items: Vec<u8> = match vm.heap.get(src) {
        Obj::Bytes(b) | Obj::ByteArray(b) => b.clone(),
        _ => {
            let items = vm.collect_iter(src)?;
            let mut out = Vec::new();
            for it in items {
                out.push(vm.expect_int(it, "byte")? as u8);
            }
            out
        }
    };
    if let Obj::ByteArray(bytes) = vm.heap.get_mut(v) {
        bytes.extend(items);
    }
    Ok(Value::NONE)
}
fn gen_send(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 2, "send")?;
    let mut ret = Value::NONE;
    match vm.gen_resume(args[0], args[1], None, &mut ret)? {
        Some(v) => Ok(v),
        None => Err(vm.stop_iteration(ret)),
    }
}
fn gen_next(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "__next__")?;
    match vm.iter_next(args[0])? {
        Some(v) => Ok(v),
        None => Err(vm.stop_iteration(Value::NONE)),
    }
}
fn gen_throw(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 2, 4, "throw")?;
    let exc = vm.make_raisable_pub(args[1])?;
    let mut ret = Value::NONE;
    match vm.gen_resume(args[0], Value::NONE, Some(exc), &mut ret)? {
        Some(v) => Ok(v),
        None => Err(vm.stop_iteration(ret)),
    }
}
fn gen_close(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    check_args(vm, args, 1, 1, "close")?;
    let g = args[0];
    let finished = match vm.heap.get(g) {
        Obj::Generator(gen) => gen.finished || gen.frame.as_ref().map(|f| f.pc == 0).unwrap_or(true),
        _ => return Err(vm.type_error("close on a non-generator")),
    };
    if finished {
        if let Obj::Generator(gen) = vm.heap.get_mut(g) {
            gen.finished = true;
            gen.frame = None;
        }
        return Ok(Value::NONE);
    }
    let ge = vm.t.generator_exit;
    let exc = vm.exception(ge, "");
    let mut ret = Value::NONE;
    match vm.gen_resume(g, Value::NONE, Some(exc), &mut ret) {
        Ok(Some(_)) => Err(vm.runtime_error("generator ignored GeneratorExit")),
        Ok(None) => Ok(Value::NONE),
        Err(e) => {
            let si = vm.t.stop_iteration;
            if vm.exc_matches(e, ge) || vm.exc_matches(e, si) {
                Ok(Value::NONE)
            } else {
                Err(e)
            }
        }
    }
}

impl Vm {
    pub fn make_raisable_pub(&mut self, e: Value) -> PyResult {
        if self.is_exception(e) {
            return Ok(e);
        }
        if e.is_obj() && matches!(self.heap.get(e), Obj::Class(_)) {
            return self.call(e, &[], &[]);
        }
        Err(self.type_error("exceptions must derive from BaseException"))
    }
}

// -- JavaScript objects: filled in by the browser glue ------------------------------------------------------

pub fn js_get_attr(vm: &mut Vm, obj: Value, name: Value) -> PyResult {
    let h = vm.js_handle(obj).unwrap();
    let s = vm.as_str(name).unwrap_or("").to_string();
    let hooks = vm.js()?;
    if s == "new" {
        // `Ctor.new(args)`: a constructor call bound to this object
        let f = vm.native("new", js_new_native);
        return Ok(vm.bound(f, obj));
    }
    let slot = (hooks.get)(vm, h, &s)?;
    if slot.tag == crate::jshooks::TAG_UNDEFINED {
        // `undefined` for a missing attribute is an AttributeError, so `getattr(x, "y", d)`
        // and `hasattr` behave; an attribute that is really `undefined` reads as None
        // through subscripting.
        return Err(vm.attribute_error(format!("JavaScript object has no attribute '{s}'")));
    }
    let is_function = slot.tag == crate::jshooks::TAG_HANDLE && slot.aux == 1;
    let v = vm.from_slot(slot)?;
    // A function read off an object is a method: calling it uses the object as `this`.
    if is_function {
        return Ok(vm.bound(v, obj));
    }
    Ok(v)
}

/// `LoadMethod` on a JavaScript object: `(function, receiver)` with no bound-method object.
pub fn js_load_method(vm: &mut Vm, obj: Value, name: Value) -> PyResult<Option<(Value, Value)>> {
    let h = vm.js_handle(obj).unwrap();
    let s = vm.as_str(name).unwrap_or("").to_string();
    if s == "new" {
        return Ok(None);
    }
    let hooks = vm.js()?;
    let slot = (hooks.get)(vm, h, &s)?;
    if slot.tag == crate::jshooks::TAG_HANDLE && slot.aux == 1 {
        let f = vm.from_slot(slot)?;
        return Ok(Some((f, obj)));
    }
    if slot.tag == crate::jshooks::TAG_UNDEFINED {
        return Err(vm.attribute_error(format!("JavaScript object has no attribute '{s}'")));
    }
    let v = vm.from_slot(slot)?;
    Ok(Some((v, Value::UNDEF)))
}
fn js_new_native(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let ctor = vm.js_handle(args[0]).unwrap();
    let hooks = vm.js()?;
    let mut trees = Vec::new();
    let mut slots = Vec::new();
    for &a in &args[1..] {
        slots.push(vm.to_slot(a, &mut trees)?);
    }
    let r = (hooks.new)(vm, ctor, &slots)?;
    vm.from_slot(r)
}
pub fn js_set_attr(vm: &mut Vm, obj: Value, name: Value, value: Value) -> PyResult<()> {
    let h = vm.js_handle(obj).unwrap();
    let s = vm.as_str(name).unwrap_or("").to_string();
    let hooks = vm.js()?;
    let mut trees = Vec::new();
    let slot = vm.to_slot(value, &mut trees)?;
    (hooks.set)(vm, h, &s, slot)
}
pub fn js_get_item(vm: &mut Vm, obj: Value, key: Value) -> PyResult {
    let h = vm.js_handle(obj).unwrap();
    let hooks = vm.js()?;
    let mut trees = Vec::new();
    let k = vm.to_slot(key, &mut trees)?;
    let r = (hooks.index)(vm, h, k)?;
    vm.from_slot(r)
}
pub fn js_set_item(vm: &mut Vm, obj: Value, key: Value, value: Value) -> PyResult<()> {
    let h = vm.js_handle(obj).unwrap();
    let hooks = vm.js()?;
    let mut trees = Vec::new();
    let k = vm.to_slot(key, &mut trees)?;
    let v = vm.to_slot(value, &mut trees)?;
    (hooks.set_index)(vm, h, k, v)
}
pub fn js_iter(vm: &mut Vm, obj: Value) -> PyResult {
    // Arrays and array-likes: by index. Anything else: `Array.from(obj)` through the global.
    let h = vm.js_handle(obj).unwrap();
    let hooks = vm.js()?;
    let n = (hooks.len)(vm, h);
    let items = if n >= 0 {
        let mut items = Vec::with_capacity(n as usize);
        for i in 0..n {
            let r = (hooks.index)(vm, h, crate::jshooks::Slot::number(i as f64))?;
            let v = vm.from_slot(r)?;
            items.push(v);
        }
        items
    } else {
        let g = vm.js_object(crate::jshooks::GLOBAL);
        let arr = vm.intern("Array");
        let array = vm.get_attr(g, arr)?;
        let from = vm.intern("from");
        let f = vm.get_attr(array, from)?;
        let a = vm.call(f, &[obj], &[])?;
        return js_iter(vm, a);
    };
    let l = vm.list(items);
    vm.get_iter(l)
}
