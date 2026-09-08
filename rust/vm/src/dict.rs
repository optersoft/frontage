//! An insertion-ordered hash map over `Value`s: CPython's compact layout — an index table
//! into an entries array — so iteration order is a property of the layout, not a feature.
//!
//! Hashing and key equality need the heap (a string's bytes live there), so they are free
//! functions over `&Heap`, and a dict that lives *in* the heap is taken out of its slot for
//! the duration of an operation (`Heap::take`/`put`). Keys are the builtin hashable types
//! plus identity for everything else; a user `__hash__`/`__eq__` on a key is a later feature.

use crate::heap::Heap;
use crate::object::Obj;
use crate::value::Value;

const EMPTY: u32 = u32::MAX;
const DELETED: u32 = u32::MAX - 1;

#[derive(Clone, Copy)]
pub struct Entry {
    pub hash: u64,
    pub key: Value,
    pub value: Value,
}

#[derive(Default)]
pub struct PyDict {
    entries: Vec<Entry>,
    indices: Vec<u32>,
    used: usize,
    /// Bumped on every insertion, replacement or removal; caches key on it.
    pub version: u32,
}

impl PyDict {
    pub fn new() -> PyDict {
        PyDict::default()
    }
    pub fn with_capacity(n: usize) -> PyDict {
        let mut d = PyDict::default();
        if n > 0 {
            d.entries.reserve(n);
            let cap = (n * 3 / 2 + 1).next_power_of_two().max(8);
            d.indices = vec![EMPTY; cap];
        }
        d
    }
    pub fn len(&self) -> usize {
        self.used
    }
    pub fn is_empty(&self) -> bool {
        self.used == 0
    }
    pub fn clear(&mut self) {
        self.version = self.version.wrapping_add(1);
        self.entries.clear();
        self.indices.clear();
        self.used = 0;
    }

    fn lookup(&self, heap: &Heap, hash: u64, key: Value) -> Result<usize, usize> {
        // Ok(entry index) or Err(index-table slot to insert at).
        if self.indices.is_empty() {
            return Err(usize::MAX);
        }
        let mask = self.indices.len() - 1;
        let mut i = (hash as usize) & mask;
        let mut perturb = hash;
        let mut first_deleted = None;
        loop {
            match self.indices[i] {
                EMPTY => return Err(first_deleted.unwrap_or(i)),
                DELETED => {
                    if first_deleted.is_none() {
                        first_deleted = Some(i);
                    }
                }
                e => {
                    let entry = &self.entries[e as usize];
                    if entry.key == key || (entry.hash == hash && keys_equal(heap, entry.key, key)) {
                        return Ok(e as usize);
                    }
                }
            }
            perturb >>= 5;
            i = (i * 5 + 1 + perturb as usize) & mask;
        }
    }

    fn grow(&mut self) {
        let cap = ((self.used + 1) * 3 / 2 + 1).next_power_of_two().max(8);
        let live: Vec<Entry> = self.entries.iter().filter(|e| !e.key.is_undef()).copied().collect();
        self.entries = live;
        self.indices = vec![EMPTY; cap];
        let mask = cap - 1;
        for (n, e) in self.entries.iter().enumerate() {
            let mut i = (e.hash as usize) & mask;
            let mut perturb = e.hash;
            while self.indices[i] != EMPTY {
                perturb >>= 5;
                i = (i * 5 + 1 + perturb as usize) & mask;
            }
            self.indices[i] = n as u32;
        }
    }

    /// Entry index of `key` with a known hash (builtin equality only).
    pub fn find_hashed(&self, heap: &Heap, hash: u64, key: Value) -> Option<usize> {
        self.lookup(heap, hash, key).ok()
    }
    /// Every live entry whose hash equals `hash`, as `(entry index, key)`.
    pub fn candidates(&self, hash: u64) -> Vec<(usize, Value)> {
        self.entries.iter().enumerate().filter(|(_, e)| !e.key.is_undef() && e.hash == hash).map(|(i, e)| (i, e.key)).collect()
    }
    pub fn value_at(&self, i: usize) -> Option<Value> {
        self.entries.get(i).filter(|e| !e.key.is_undef()).map(|e| e.value)
    }
    pub fn set_at(&mut self, i: usize, value: Value) {
        self.version = self.version.wrapping_add(1);
        if let Some(e) = self.entries.get_mut(i) {
            e.value = value;
        }
    }
    pub fn remove_at(&mut self, i: usize) -> Option<Value> {
        self.version = self.version.wrapping_add(1);
        let e = self.entries.get(i)?;
        if e.key.is_undef() {
            return None;
        }
        let (hash, key) = (e.hash, e.key);
        let mask = self.indices.len() - 1;
        let mut slot = (hash as usize) & mask;
        let mut perturb = hash;
        while self.indices[slot] != i as u32 {
            perturb >>= 5;
            slot = (slot * 5 + 1 + perturb as usize) & mask;
        }
        self.indices[slot] = DELETED;
        let old = self.entries[i].value;
        self.entries[i].key = Value::UNDEF;
        self.entries[i].value = Value::UNDEF;
        self.used -= 1;
        let _ = key;
        Some(old)
    }
    pub fn get(&self, heap: &Heap, key: Value) -> Option<Value> {
        let hash = hash_value(heap, key)?;
        self.get_hashed(heap, hash, key)
    }
    pub fn get_hashed(&self, heap: &Heap, hash: u64, key: Value) -> Option<Value> {
        match self.lookup(heap, hash, key) {
            Ok(e) => Some(self.entries[e].value),
            Err(_) => None,
        }
    }
    pub fn contains(&self, heap: &Heap, key: Value) -> bool {
        self.get(heap, key).is_some()
    }
    /// Insert or replace. Returns the previous value.
    pub fn set(&mut self, heap: &Heap, key: Value, value: Value) -> Option<Value> {
        let hash = hash_value(heap, key).expect("unhashable key reached PyDict::set");
        self.set_hashed(heap, hash, key, value)
    }
    pub fn set_hashed(&mut self, heap: &Heap, hash: u64, key: Value, value: Value) -> Option<Value> {
        self.version = self.version.wrapping_add(1);
        match self.lookup(heap, hash, key) {
            Ok(e) => Some(core::mem::replace(&mut self.entries[e].value, value)),
            Err(slot) => {
                if slot == usize::MAX || self.entries.len() + 1 > self.indices.len() * 2 / 3 {
                    self.grow();
                    return self.set_hashed(heap, hash, key, value);
                }
                self.indices[slot] = self.entries.len() as u32;
                self.entries.push(Entry { hash, key, value });
                self.used += 1;
                None
            }
        }
    }
    pub fn remove(&mut self, heap: &Heap, key: Value) -> Option<Value> {
        self.version = self.version.wrapping_add(1);
        let hash = hash_value(heap, key)?;
        let e = self.lookup(heap, hash, key).ok()?;
        // Find the index slot pointing at e and tombstone it.
        let mask = self.indices.len() - 1;
        let mut i = (hash as usize) & mask;
        let mut perturb = hash;
        while self.indices[i] != e as u32 {
            perturb >>= 5;
            i = (i * 5 + 1 + perturb as usize) & mask;
        }
        self.indices[i] = DELETED;
        let old = self.entries[e].value;
        self.entries[e].key = Value::UNDEF;
        self.entries[e].value = Value::UNDEF;
        self.used -= 1;
        Some(old)
    }
    /// Remove the last inserted item, for `popitem`.
    pub fn pop_last(&mut self, heap: &Heap) -> Option<(Value, Value)> {
        let e = self.entries.iter().rposition(|e| !e.key.is_undef())?;
        let (k, v) = (self.entries[e].key, self.entries[e].value);
        self.remove(heap, k);
        Some((k, v))
    }
    /// Entries in insertion order; `at` walks the raw entry array so a mutation during
    /// iteration does not lose the place.
    pub fn entry_at(&self, at: usize) -> Option<(usize, Value, Value)> {
        let mut i = at;
        while i < self.entries.len() {
            let e = &self.entries[i];
            if !e.key.is_undef() {
                return Some((i + 1, e.key, e.value));
            }
            i += 1;
        }
        None
    }
    pub fn keys(&self) -> impl Iterator<Item = Value> + '_ {
        self.entries.iter().filter(|e| !e.key.is_undef()).map(|e| e.key)
    }
    pub fn items(&self) -> impl Iterator<Item = (Value, Value)> + '_ {
        self.entries.iter().filter(|e| !e.key.is_undef()).map(|e| (e.key, e.value))
    }
    pub fn values(&self) -> impl Iterator<Item = Value> + '_ {
        self.entries.iter().filter(|e| !e.key.is_undef()).map(|e| e.value)
    }
    pub fn trace(&self, visit: &mut impl FnMut(Value)) {
        for e in &self.entries {
            if !e.key.is_undef() {
                visit(e.key);
                visit(e.value);
            }
        }
    }
    pub fn clone_shallow(&self) -> PyDict {
        PyDict { entries: self.entries.clone(), indices: self.indices.clone(), used: self.used, version: 0 }
    }
}

/// Python's rule that `hash(1) == hash(1.0) == hash(True)`.
fn hash_i64(i: i64) -> u64 {
    let mut h = i as u64;
    h ^= h >> 33;
    h = h.wrapping_mul(0xff51_afd7_ed55_8ccd);
    h ^= h >> 33;
    h
}

fn hash_f64(f: f64) -> u64 {
    if f.fract() == 0.0 && f.abs() < 9.2e18 {
        hash_i64(f as i64)
    } else {
        hash_i64(f.to_bits() as i64)
    }
}

/// `None` for an unhashable value (a list, a dict, a set).
pub fn hash_value(heap: &Heap, v: Value) -> Option<u64> {
    if v.is_int() {
        return Some(hash_i64(v.as_int() as i64));
    }
    if v.is_float() {
        return Some(hash_f64(v.as_float()));
    }
    if v.is_bool() {
        return Some(hash_i64(v.as_bool() as i64));
    }
    if v.is_none() {
        return Some(0x9e37_79b9);
    }
    match heap.get(v) {
        Obj::Str(s) => Some(s.hash),
        Obj::Int(i) => Some(hash_i64(*i)),
        Obj::Tuple(items) => {
            let mut h: u64 = 0x345678;
            for &x in items {
                h = (h ^ hash_value(heap, x)?).wrapping_mul(1_000_003).wrapping_add(82520);
            }
            Some(h)
        }
        Obj::FrozenSet(d) => {
            let mut h: u64 = 0;
            for k in d.keys() {
                h ^= hash_value(heap, k)?.wrapping_mul(0x9e37_79b9_7f4a_7c15);
            }
            Some(h)
        }
        Obj::Bytes(b) => Some(crate::object::str_hash(unsafe { core::str::from_utf8_unchecked(b) })),
        Obj::List(_) | Obj::Dict(_) | Obj::Set(_) | Obj::ByteArray(_) => None,
        _ => Some(hash_i64(v.as_obj() as i64 ^ 0x5bd1_e995)),
    }
}

pub fn keys_equal(heap: &Heap, a: Value, b: Value) -> bool {
    if a == b {
        return true;
    }
    // Numbers compare across representations.
    if let (Some(x), Some(y)) = (num_of(heap, a), num_of(heap, b)) {
        return x == y;
    }
    match (a.obj_index(), b.obj_index()) {
        (Some(_), Some(_)) => match (heap.get(a), heap.get(b)) {
            (Obj::Str(x), Obj::Str(y)) => x.hash == y.hash && x.s == y.s,
            (Obj::Tuple(x), Obj::Tuple(y)) => x.len() == y.len() && x.iter().zip(y).all(|(&p, &q)| keys_equal(heap, p, q)),
            (Obj::Bytes(x), Obj::Bytes(y)) => x == y,
            (Obj::FrozenSet(x), Obj::FrozenSet(y)) => x.len() == y.len() && x.keys().all(|k| y.contains(heap, k)),
            _ => false,
        },
        _ => false,
    }
}

fn num_of(heap: &Heap, v: Value) -> Option<f64> {
    if v.is_int() {
        Some(v.as_int() as f64)
    } else if v.is_float() {
        Some(v.as_float())
    } else if v.is_bool() {
        Some(v.as_bool() as i32 as f64)
    } else if let Some(_) = v.obj_index() {
        match heap.get(v) {
            Obj::Int(i) => Some(*i as f64),
            _ => None,
        }
    } else {
        None
    }
}
