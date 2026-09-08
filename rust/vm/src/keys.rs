//! Dict and set keys through the VM: hashing that honours a user `__hash__`, equality that
//! honours a user `__eq__`, and the collector kept honest while Python runs in the middle.
//!
//! The builtin key types take the fast path inside `PyDict`. An instance whose class defines
//! `__eq__` is compared by calling it — outside any `Heap::take` window, with the container
//! still in the heap and rooted — over the candidates that share its hash.

use crate::dict::{hash_value, PyDict};
use crate::object::Obj;
use crate::value::Value;
use crate::vm::{PyResult, Vm};

impl Vm {
    /// Does this value's type define its own `__eq__` or `__hash__` in Python?
    fn user_keyed(&self, v: Value) -> (bool, Option<Value>) {
        if !v.is_obj() || !matches!(self.heap.get(v), Obj::Instance(_) | Obj::Exc(_)) {
            return (false, None);
        }
        let t = self.type_of(v);
        let eq = self.class_lookup(t, self.n.eq).filter(|m| matches!(self.heap.get(*m), Obj::Func(_)));
        let hash = self.class_lookup(t, self.n.hash).filter(|m| matches!(self.heap.get(*m), Obj::Func(_)));
        (eq.is_some(), hash)
    }

    /// `hash(v)`, raising for an unhashable value.
    pub fn hash_of(&mut self, v: Value) -> PyResult<u64> {
        let (user_eq, user_hash) = self.user_keyed(v);
        if let Some(h) = user_hash {
            let r = self.call(h, &[v], &[])?;
            return match self.as_i64(r) {
                Some(i) => Ok(i as u64),
                None => Err(self.type_error("__hash__ method should return an integer")),
            };
        }
        if user_eq {
            let t = self.type_name(v);
            return Err(self.type_error(format!("unhashable type: '{t}'")));
        }
        match hash_value(&self.heap, v) {
            Some(h) => Ok(h),
            None => {
                let t = self.type_name(v);
                Err(self.type_error(format!("unhashable type: '{t}'")))
            }
        }
    }

    fn with_map<R>(&self, container: Value, f: impl FnOnce(&PyDict) -> R) -> Option<R> {
        if !container.is_obj() {
            return None;
        }
        match self.heap.get(container) {
            Obj::Dict(d) | Obj::Set(d) | Obj::FrozenSet(d) => Some(f(d)),
            _ => None,
        }
    }

    /// `hash(key)` with the container's own wording for an unhashable key.
    fn hash_for(&mut self, container: Value, key: Value) -> PyResult<u64> {
        match self.hash_of(key) {
            Ok(h) => Ok(h),
            Err(e) => {
                let te = self.t.type_error;
                if self.exc_matches(e, te) && hash_value(&self.heap, key).is_none() {
                    let t = self.type_name(key);
                    let what = if matches!(self.heap.get(container), Obj::Dict(_)) { "a dict key" } else { "a set element" };
                    return Err(self.type_error(format!("cannot use '{t}' as {what} (unhashable type: '{t}')")));
                }
                Err(e)
            }
        }
    }

    /// The entry index of `key` in a dict or set object, or `None`.
    pub fn key_find(&mut self, container: Value, key: Value) -> PyResult<Option<usize>> {
        let hash = self.hash_for(container, key)?;
        let (user_eq, _) = self.user_keyed(key);
        if !user_eq {
            return Ok(self.with_map(container, |d| d.find_hashed(&self.heap, hash, key)).flatten());
        }
        let candidates: Vec<(usize, Value)> = self.with_map(container, |d| d.candidates(hash)).unwrap_or_default();
        for (idx, k) in candidates {
            if k == key || self.eq(k, key)? {
                return Ok(Some(idx));
            }
        }
        Ok(None)
    }

    pub fn key_get(&mut self, container: Value, key: Value) -> PyResult<Option<Value>> {
        Ok(match self.key_find(container, key)? {
            Some(i) => self.with_map(container, |d| d.value_at(i)).flatten(),
            None => None,
        })
    }

    pub fn key_contains(&mut self, container: Value, key: Value) -> PyResult<bool> {
        Ok(self.key_find(container, key)?.is_some())
    }

    /// Insert or replace `key` in a dict or set object.
    pub fn key_set(&mut self, container: Value, key: Value, value: Value) -> PyResult<()> {
        let hash = self.hash_for(container, key)?;
        if let Some(i) = self.key_find(container, key)? {
            let mut d = self.take_map(container);
            d.set_at(i, value);
            self.put_map(container, d);
            return Ok(());
        }
        let mut d = self.take_map(container);
        // A user-keyed value never matches an existing entry under `keys_equal` (identity), so
        // this inserts; a builtin key was already found absent.
        d.set_hashed(&self.heap, hash, key, value);
        self.put_map(container, d);
        Ok(())
    }

    pub fn key_remove(&mut self, container: Value, key: Value) -> PyResult<Option<Value>> {
        match self.key_find(container, key)? {
            Some(i) => {
                let mut d = self.take_map(container);
                let v = d.remove_at(i);
                self.put_map(container, d);
                Ok(v)
            }
            None => Ok(None),
        }
    }

    fn take_map(&mut self, container: Value) -> PyDict {
        match self.heap.take(container) {
            Obj::Dict(d) => {
                self.map_kind = 0;
                d
            }
            Obj::Set(d) => {
                self.map_kind = 1;
                d
            }
            Obj::FrozenSet(d) => {
                self.map_kind = 2;
                d
            }
            other => {
                self.heap.put(container, other);
                PyDict::new()
            }
        }
    }
    fn put_map(&mut self, container: Value, d: PyDict) {
        let o = match self.map_kind {
            0 => Obj::Dict(d),
            1 => Obj::Set(d),
            _ => Obj::FrozenSet(d),
        };
        self.heap.put(container, o);
    }
}
