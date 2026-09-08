//! The heap: an arena of objects addressed by index, and a precise mark-sweep collector.
//!
//! Collection runs only at the VM's safe points (`Vm::maybe_collect`), never inside an
//! allocation, so native code may hold values across an `alloc` without rooting them — but
//! not across a call back into Python, which may reach a safe point. The roots are exact:
//! every live frame, the module table, the interned strings, the pinned constants, and the
//! handles JavaScript holds.

use crate::object::Obj;
use crate::value::Value;

pub struct Heap {
    slots: Vec<Obj>,
    marks: Vec<bool>,
    free: Vec<u32>,
    /// Objects allocated since the last collection.
    pub since_gc: usize,
    pub threshold: usize,
    /// Collect at every safe point (tests: a missing root shows up at once).
    pub stress: bool,
    /// `gc.disable()` turns automatic collection off; `collect()` still works.
    pub enabled: bool,
    /// Never swept: constants, interned strings, builtins.
    pub pinned: Vec<Value>,
    pub collections: usize,
    /// JavaScript handles whose objects were swept; the bridge releases them.
    pub freed_js: Vec<u32>,
}

impl Heap {
    pub fn new() -> Heap {
        let mut slots = Vec::with_capacity(4096);
        slots.push(Obj::Free); // index 0: what `get` returns for a value that is not an object
        Heap {
            slots,
            marks: Vec::new(),
            free: Vec::new(),
            since_gc: 0,
            threshold: 20_000,
            stress: false,
            enabled: true,
            pinned: Vec::new(),
            collections: 0,
            freed_js: Vec::new(),
        }
    }

    #[inline]
    pub fn alloc(&mut self, o: Obj) -> Value {
        self.since_gc += 1;
        if let Some(i) = self.free.pop() {
            self.slots[i as usize] = o;
            Value::obj(i)
        } else {
            let i = self.slots.len() as u32;
            self.slots.push(o);
            Value::obj(i)
        }
    }
    /// Allocate and pin: never collected.
    pub fn alloc_pinned(&mut self, o: Obj) -> Value {
        let v = self.alloc(o);
        self.pinned.push(v);
        v
    }
    #[inline]
    pub fn get(&self, v: Value) -> &Obj {
        if !v.is_obj() {
            return &self.slots[0];
        }
        &self.slots[v.as_obj() as usize]
    }
    #[inline]
    pub fn get_mut(&mut self, v: Value) -> &mut Obj {
        debug_assert!(v.is_obj(), "not a heap value: {:?}", v);
        &mut self.slots[v.as_obj() as usize]
    }
    /// Take an object out of its slot to operate on it with the heap borrowed immutably;
    /// `put` it back before anything can observe the slot.
    #[inline]
    pub fn take(&mut self, v: Value) -> Obj {
        core::mem::replace(self.get_mut(v), Obj::Free)
    }
    #[inline]
    pub fn put(&mut self, v: Value, o: Obj) {
        *self.get_mut(v) = o;
    }
    pub fn len(&self) -> usize {
        self.slots.len() - self.free.len()
    }
    pub fn should_collect(&self) -> bool {
        self.enabled && (self.stress || self.since_gc >= self.threshold)
    }

    /// Mark from `roots`, sweep everything else.
    pub fn collect(&mut self, roots: impl IntoIterator<Item = Value>) -> usize {
        self.marks.clear();
        self.marks.resize(self.slots.len(), false);
        let mut stack: Vec<Value> = Vec::with_capacity(1024);
        for v in self.pinned.iter().copied().chain(roots) {
            if v.is_obj() {
                stack.push(v);
            }
        }
        while let Some(v) = stack.pop() {
            let i = v.as_obj() as usize;
            if self.marks[i] {
                continue;
            }
            self.marks[i] = true;
            self.slots[i].trace(|child| {
                if child.is_obj() && !self.marks[child.as_obj() as usize] {
                    stack.push(child);
                }
            });
        }
        let mut freed = 0;
        for i in 1..self.slots.len() {
            if !self.marks[i] && !matches!(self.slots[i], Obj::Free) {
                if let Obj::Js(h) = self.slots[i] {
                    if h != 0 {
                        self.freed_js.push(h);
                    }
                }
                self.slots[i] = Obj::Free;
                self.free.push(i as u32);
                freed += 1;
            }
        }
        self.since_gc = 0;
        self.collections += 1;
        // Grow the threshold with the live set, so a big heap is not collected constantly.
        let live = self.slots.len() - self.free.len();
        self.threshold = (live / 2).max(20_000);
        freed
    }
}

impl Default for Heap {
    fn default() -> Self {
        Heap::new()
    }
}
