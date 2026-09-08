//! The reactive graph as VM types: `Owner`, `Signal`, `Memo`, `Effect`, `RenderEffect`, and the
//! scheduling around them (`RUNTIME.md` §3.8). The semantics are `frontage/reactive.py`'s,
//! line for line; that file keeps the Python implementation for CPython and stays the
//! specification. What is rare stays in Python and reaches in through the attributes a node
//! exposes (`_state`, `_observers`, `_urgent`, …) and the hooks `setup` installs: transitions,
//! `Optimistic`, the async half of `Memo`, prerender and hydration registries, the debug
//! warnings.
//!
//! Every node is one heap object, `Obj::Node`, traced by the collector like any other; a
//! Python subclass (`Optimistic(Signal)`) is the same object with another class and, when it
//! needs one, a dict.

use crate::dict::PyDict;
use crate::object::{Builtin, Obj};
use crate::value::Value;
use crate::vm::{PyResult, Vm};
use std::collections::HashSet;

pub const CLEAN: u8 = 0;
pub const CHECK: u8 = 1;
pub const DIRTY: u8 = 2;
const FLUSH_LIMIT: u32 = 100_000;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Owner,
    Signal,
    Memo,
    Effect,
}

pub struct Node {
    pub class: Value,
    pub kind: Kind,
    pub dict: Option<Box<PyDict>>,
    // -- owner
    pub parent: Value,
    pub owned: Vec<Value>,
    pub cleanups: Vec<Value>,
    pub context: Value,
    pub disposed: bool,
    pub name: Value,
    // -- source (Signal, Memo)
    pub value: Value,
    pub equal: Value,
    pub observers: Vec<Value>,
    pub observer_slots: Vec<u32>,
    // -- computation (Memo, Effect)
    pub func: Value,
    pub sources: Vec<Value>,
    pub slots: Vec<u32>,
    pub source_set: Option<Box<HashSet<u32>>>,
    pub state: u8,
    pub queued: bool,
    pub not_ready: bool,
    pub pure: bool,
    pub render: bool,
    pub urgent: bool,
    pub target: Value,
    // -- effect
    pub effect: Value,
    pub cleanup: Value,
    pub parked: Value,
    // -- memo, the async half (Python-managed; a Signal, a Signal, a list)
    pub loading: Value,
    pub error: Value,
    pub scopes: Value,
}

impl Node {
    fn blank(class: Value, kind: Kind) -> Node {
        Node {
            class,
            kind,
            dict: None,
            parent: Value::NONE,
            owned: Vec::new(),
            cleanups: Vec::new(),
            context: Value::NONE,
            disposed: false,
            name: Value::NONE,
            value: Value::UNDEF,
            equal: Value::NONE,
            observers: Vec::new(),
            observer_slots: Vec::new(),
            func: Value::NONE,
            sources: Vec::new(),
            slots: Vec::new(),
            source_set: None,
            state: DIRTY,
            queued: false,
            not_ready: false,
            pure: kind == Kind::Memo,
            render: false,
            urgent: false,
            target: Value::NONE,
            effect: Value::NONE,
            cleanup: Value::NONE,
            parked: Value::UNDEF,
            loading: Value::NONE,
            error: Value::NONE,
            scopes: Value::NONE,
        }
    }

    pub fn trace(&self, visit: &mut impl FnMut(Value)) {
        visit(self.class);
        if let Some(d) = &self.dict {
            d.trace(visit);
        }
        visit(self.parent);
        self.owned.iter().for_each(|&v| visit(v));
        self.cleanups.iter().for_each(|&v| visit(v));
        visit(self.context);
        visit(self.name);
        visit(self.value);
        visit(self.equal);
        self.observers.iter().for_each(|&v| visit(v));
        visit(self.func);
        self.sources.iter().for_each(|&v| visit(v));
        visit(self.target);
        visit(self.effect);
        visit(self.cleanup);
        visit(self.parked);
        visit(self.loading);
        visit(self.error);
        visit(self.scopes);
    }
}

macro_rules! core_names {
    ($($field:ident = $text:expr),* $(,)?) => {
        #[derive(Default)]
        pub struct CoreNames { $(pub $field: Value,)* }
        impl CoreNames {
            fn fill(vm: &mut Vm) {
                $( let v = vm.intern($text); vm.core.n.$field = v; )*
            }
        }
    };
}

core_names! {
    parent = "_parent", owned = "_owned", cleanups = "_cleanups", context = "_context",
    disposed = "_disposed", name = "name", value = "_value", equal = "_equal",
    observers = "_observers", fn_ = "_fn", sources = "_sources", state = "_state",
    queued = "_queued", not_ready = "_not_ready", pure = "_pure", render = "_render",
    urgent = "_urgent", target = "_target", effect = "_effect", cleanup = "_cleanup",
    parked = "_parked", loading = "_loading", error = "_error", scopes = "_scopes",
    observer_slots = "_observer_slots", slots = "_slots",
    saved = "_saved", deferred = "_deferred", default = "default", handle = "handle",
    add = "add", remove = "remove", append = "append", start = "_start",
    read_async = "_read_async", release = "_release", dispose = "dispose",
    committed = "_committed",
}

/// The module state of `reactive.py`, in the VM.
#[derive(Default)]
pub struct Core {
    pub n: CoreNames,
    pub owner: Value,
    pub listener: Value,
    pub batch_depth: u32,
    pub render_queue: Vec<Value>,
    pub effect_queue: Vec<Value>,
    pub flushing: bool,
    pub untracking: u32,
    pub transition: Value,
    pub debug: bool,
    pub async_tasks: u32,
    pub unset: Value,
    pub not_ready_cls: Value,
    pub errors_ctx: Value,
    pub loading_ctx: Value,
    pub hook_untracked_read: Value,
    pub hook_tracked_write: Value,
    pub hook_memo_created: Value,
    pub owner_cls: Value,
    pub signal_cls: Value,
    pub memo_cls: Value,
    pub effect_cls: Value,
    pub render_effect_cls: Value,
}

impl Core {
    pub fn new() -> Core {
        let n = Value::NONE;
        Core {
            owner: n,
            listener: n,
            transition: n,
            debug: true,
            unset: n,
            not_ready_cls: n,
            errors_ctx: n,
            loading_ctx: n,
            hook_untracked_read: n,
            hook_tracked_write: n,
            hook_memo_created: n,
            owner_cls: n,
            signal_cls: n,
            memo_cls: n,
            effect_cls: n,
            render_effect_cls: n,
            ..Default::default()
        }
    }
    pub fn trace(&self, visit: &mut impl FnMut(Value)) {
        for v in [
            self.owner,
            self.listener,
            self.transition,
            self.unset,
            self.not_ready_cls,
            self.errors_ctx,
            self.loading_ctx,
            self.hook_untracked_read,
            self.hook_tracked_write,
            self.hook_memo_created,
            self.owner_cls,
            self.signal_cls,
            self.memo_cls,
            self.effect_cls,
            self.render_effect_cls,
        ] {
            visit(v);
        }
        self.render_queue.iter().for_each(|&v| visit(v));
        self.effect_queue.iter().for_each(|&v| visit(v));
    }
}

fn node(vm: &Vm, v: Value) -> &Node {
    match vm.heap.get(v) {
        Obj::Node(n) => n,
        _ => panic!("not a node"),
    }
}
fn node_mut(vm: &mut Vm, v: Value) -> &mut Node {
    match vm.heap.get_mut(v) {
        Obj::Node(n) => n,
        _ => panic!("not a node"),
    }
}
pub fn is_node(vm: &Vm, v: Value) -> bool {
    v.is_obj() && matches!(vm.heap.get(v), Obj::Node(_))
}
pub fn kind_of(vm: &Vm, v: Value) -> Option<Kind> {
    if v.is_obj() {
        if let Obj::Node(n) = vm.heap.get(v) {
            return Some(n.kind);
        }
    }
    None
}

fn is_unset(vm: &Vm, v: Value) -> bool {
    v.is_undef() || v == vm.core.unset
}

/// A method on a node found through its class (a native one, or a Python override).
fn call_method(vm: &mut Vm, obj: Value, name: Value, args: &[Value]) -> PyResult {
    let f = vm.get_attr(obj, name)?;
    vm.call(f, args, &[])
}

// -- ownership ---------------------------------------------------------------------------------

fn owner_attach(vm: &mut Vm, obj: Value, parent: Value) {
    node_mut(vm, obj).parent = parent;
    if !parent.is_none() && is_node(vm, parent) {
        node_mut(vm, parent).owned.push(obj);
    }
}

/// Values taken out of a node and used across calls into Python stay reachable meanwhile:
/// the collector sees `vm.roots`, not Rust locals.
fn rooted<R>(vm: &mut Vm, values: &[Value], f: impl FnOnce(&mut Vm) -> R) -> R {
    let mark = vm.roots.len();
    vm.roots.extend_from_slice(values);
    let r = f(vm);
    vm.roots.truncate(mark);
    r
}

fn dispose_owned(vm: &mut Vm, obj: Value) -> PyResult<()> {
    let owned = core::mem::take(&mut node_mut(vm, obj).owned);
    if !owned.is_empty() {
        rooted(vm, &owned, |vm| -> PyResult<()> {
            for &child in owned.iter().rev() {
                if is_node(vm, child) {
                    node_mut(vm, child).parent = Value::NONE; // already being removed
                    dispose(vm, child)?;
                } else {
                    let p = vm.core.n.parent;
                    vm.set_attr(child, p, Value::NONE)?;
                    let d = vm.core.n.dispose;
                    call_method(vm, child, d, &[])?;
                }
            }
            Ok(())
        })?;
    }
    let cleanups = core::mem::take(&mut node_mut(vm, obj).cleanups);
    if !cleanups.is_empty() {
        rooted(vm, &cleanups, |vm| -> PyResult<()> {
            for &f in cleanups.iter().rev() {
                vm.call(f, &[], &[])?;
            }
            Ok(())
        })?;
    }
    Ok(())
}

/// `dispose()` as the native classes define it; a Python subclass that overrides `dispose`
/// is called through its method instead (see `dispose_owned`).
pub fn dispose(vm: &mut Vm, obj: Value) -> PyResult<()> {
    let n = node_mut(vm, obj);
    if n.disposed {
        return Ok(());
    }
    let kind = n.kind;
    if kind == Kind::Effect {
        run_cleanup(vm, obj)?;
    }
    if kind == Kind::Memo {
        // The transition and the navigation waiting on an async run stop waiting.
        let rel = vm.core.n.release;
        let has = node(vm, obj).loading != Value::NONE || node(vm, obj).dict.as_ref().map(|d| d.len() > 0).unwrap_or(false);
        if has {
            if let Ok(f) = vm.get_attr(obj, rel) {
                vm.call(f, &[], &[])?;
            }
        }
    }
    if kind == Kind::Memo || kind == Kind::Effect {
        clear_sources(vm, obj);
    }
    node_mut(vm, obj).disposed = true;
    dispose_owned(vm, obj)?;
    let parent = node(vm, obj).parent;
    if !parent.is_none() && is_node(vm, parent) {
        let owned = &mut node_mut(vm, parent).owned;
        if let Some(i) = owned.iter().position(|&c| c == obj) {
            owned.remove(i);
        }
    }
    node_mut(vm, obj).parent = Value::NONE;
    Ok(())
}

pub fn lookup(vm: &mut Vm, owner: Value, ctx: Value) -> PyResult {
    let mut owner = owner;
    while !owner.is_none() {
        let (context, parent) = if is_node(vm, owner) {
            let n = node(vm, owner);
            (n.context, n.parent)
        } else {
            let c = vm.core.n.context;
            let p = vm.core.n.parent;
            (vm.get_attr(owner, c)?, vm.get_attr(owner, p)?)
        };
        if !context.is_none() {
            if let Some(v) = vm.key_get(context, ctx)? {
                return Ok(v);
            }
        }
        owner = parent;
    }
    let d = vm.core.n.default;
    vm.get_attr(ctx, d)
}

pub fn route_error(vm: &mut Vm, owner: Value, exc: Value) -> PyResult<()> {
    let errors = vm.core.errors_ctx;
    let scope = lookup(vm, owner, errors)?;
    if scope.is_none() {
        return Err(exc);
    }
    let h = vm.core.n.handle;
    call_method(vm, scope, h, &[exc])?;
    Ok(())
}

// -- batching and scheduling -----------------------------------------------------------------

pub fn begin_batch(vm: &mut Vm) {
    vm.core.batch_depth += 1;
}

pub fn end_batch(vm: &mut Vm) -> PyResult<()> {
    vm.core.batch_depth -= 1;
    if vm.core.batch_depth == 0 {
        flush(vm)?;
    }
    Ok(())
}

fn flush(vm: &mut Vm) -> PyResult<()> {
    if vm.core.flushing {
        return Ok(());
    }
    vm.core.flushing = true;
    let mut runs: u32 = 0;
    let (mut ri, mut ei) = (0usize, 0usize);
    let r = (|| -> PyResult<()> {
        loop {
            // The consumed prefix is dropped now and then, so a long flush (an effect that
            // re-queues itself up to the limit) does not make every collection trace it.
            if ri >= 4096 {
                vm.core.render_queue.drain(..ri);
                ri = 0;
            }
            if ei >= 4096 {
                vm.core.effect_queue.drain(..ei);
                ei = 0;
            }
            let effect = if ri < vm.core.render_queue.len() {
                ri += 1;
                vm.core.render_queue[ri - 1]
            } else if ei < vm.core.effect_queue.len() {
                ei += 1;
                vm.core.effect_queue[ei - 1]
            } else {
                break;
            };
            let n = node_mut(vm, effect);
            n.queued = false;
            if !n.disposed {
                if n.state == DIRTY {
                    run(vm, effect)?;
                } else {
                    update_if_necessary(vm, effect)?;
                }
            }
            runs += 1;
            if runs > FLUSH_LIMIT {
                return Err(vm.runtime_error(format!(
                    "reactive update loop: more than {FLUSH_LIMIT} effect runs in one batch. An effect is writing a signal it also reads, or a Resource is being created inside a hole."
                )));
            }
        }
        Ok(())
    })();
    vm.core.render_queue.clear();
    vm.core.effect_queue.clear();
    vm.core.flushing = false;
    r?;
    if vm.dom_pending() {
        vm.dom_flush()?;
    }
    Ok(())
}

fn queue(vm: &mut Vm, effect: Value) {
    let n = node_mut(vm, effect);
    n.queued = true;
    let render = n.render;
    if render {
        vm.core.render_queue.push(effect);
    } else {
        vm.core.effect_queue.push(effect);
    }
}

pub fn mark(vm: &mut Vm, obj: Value, state: u8) {
    let n = node_mut(vm, obj);
    if n.state >= state {
        return;
    }
    n.state = state;
    if n.pure {
        let observers = n.observers.clone();
        for o in observers {
            mark(vm, o, CHECK);
        }
    } else if !n.queued {
        queue(vm, obj);
    }
}

fn notify(vm: &mut Vm, source: Value) -> PyResult<()> {
    begin_batch(vm);
    let observers = node(vm, source).observers.clone();
    for o in observers {
        mark(vm, o, DIRTY);
    }
    end_batch(vm)
}

// -- sources and dependencies ----------------------------------------------------------------

fn same(vm: &mut Vm, equal: Value, a: Value, b: Value) -> PyResult<bool> {
    if equal.is_none() {
        vm.eq(a, b)
    } else {
        let r = vm.call(equal, &[a, b], &[])?;
        vm.truthy(r)
    }
}

pub fn track(vm: &mut Vm, comp: Value, source: Value) {
    let key = source.as_obj() as u32;
    {
        let c = node_mut(vm, comp);
        let known = match &c.source_set {
            Some(set) => set.contains(&key),
            None => c.sources.iter().any(|&s| s == source),
        };
        if known {
            return;
        }
        if c.source_set.is_none() && c.sources.len() >= 8 {
            let mut set = HashSet::with_capacity(32);
            for s in &c.sources {
                set.insert(s.as_obj() as u32);
            }
            c.source_set = Some(Box::new(set));
        }
        if let Some(set) = &mut c.source_set {
            set.insert(key);
        }
    }
    let nobs = node(vm, source).observers.len() as u32;
    let c = node_mut(vm, comp);
    c.slots.push(nobs);
    c.sources.push(source);
    let slot = (c.sources.len() - 1) as u32;
    let s = node_mut(vm, source);
    s.observers.push(comp);
    s.observer_slots.push(slot);
}

fn clear_sources(vm: &mut Vm, comp: Value) {
    let c = node_mut(vm, comp);
    if c.sources.is_empty() {
        return;
    }
    let sources = core::mem::take(&mut c.sources);
    let slots = core::mem::take(&mut c.slots);
    c.source_set = None;
    for i in 0..sources.len() {
        let source = sources[i];
        let index = slots[i] as usize;
        let s = node_mut(vm, source);
        let last = s.observers.pop().unwrap();
        let last_slot = s.observer_slots.pop().unwrap();
        if index < s.observers.len() {
            s.observers[index] = last;
            s.observer_slots[index] = last_slot;
            node_mut(vm, last).slots[last_slot as usize] = index as u32;
        }
    }
}

// -- computations ------------------------------------------------------------------------------

/// Run `fn` tracked, as owner and listener; `Ok(None)` when NotReady or an error ended it.
fn compute(vm: &mut Vm, comp: Value) -> PyResult<Option<Value>> {
    {
        let n = node(vm, comp);
        if !n.owned.is_empty() || !n.cleanups.is_empty() {
            dispose_owned(vm, comp)?;
        }
    }
    if !node(vm, comp).sources.is_empty() {
        clear_sources(vm, comp);
    }
    let (saved_owner, saved_listener) = (vm.core.owner, vm.core.listener);
    vm.core.owner = comp;
    vm.core.listener = comp;
    node_mut(vm, comp).not_ready = false;
    let f = node(vm, comp).func;
    let r = rooted(vm, &[saved_owner, saved_listener], |vm| vm.call(f, &[], &[]));
    vm.core.owner = saved_owner;
    vm.core.listener = saved_listener;
    match r {
        Ok(v) => Ok(Some(v)),
        Err(e) => {
            let nr = vm.core.not_ready_cls;
            if !nr.is_none() && vm.exc_matches(e, nr) {
                node_mut(vm, comp).not_ready = true;
                return Ok(None);
            }
            let parent = node(vm, comp).parent;
            route_error(vm, parent, e)?;
            Ok(None)
        }
    }
}

fn run(vm: &mut Vm, comp: Value) -> PyResult<()> {
    match node(vm, comp).kind {
        Kind::Memo => memo_run(vm, comp),
        Kind::Effect => effect_run(vm, comp),
        _ => Ok(()),
    }
}

pub fn update_if_necessary(vm: &mut Vm, comp: Value) -> PyResult<()> {
    let n = node(vm, comp);
    if n.disposed {
        return Ok(());
    }
    if n.state == CHECK {
        let sources = n.sources.clone();
        rooted(vm, &sources, |vm| -> PyResult<()> {
            for &s in &sources {
                if kind_of(vm, s) == Some(Kind::Memo) {
                    update_if_necessary(vm, s)?;
                }
            }
            Ok(())
        })?;
        let n = node_mut(vm, comp);
        if n.state == CHECK {
            n.state = CLEAN;
        }
    }
    if node(vm, comp).state == DIRTY {
        run(vm, comp)?;
    }
    Ok(())
}

fn is_coroutine_like(vm: &Vm, v: Value) -> bool {
    v.is_obj() && matches!(vm.heap.get(v), Obj::Generator(_))
}

fn memo_run(vm: &mut Vm, memo: Value) -> PyResult<()> {
    let old = node(vm, memo).value;
    node_mut(vm, memo).state = CLEAN;
    let new = match compute(vm, memo)? {
        Some(v) => v,
        None => return Ok(()),
    };
    vm.roots.push(new);
    let r = (|| -> PyResult<()> {
        let scopes = node(vm, memo).scopes;
        if !scopes.is_none() && node(vm, memo).loading.is_none() && vm.len_of(scopes).unwrap_or(0) > 0 {
            let waiting = vm.collect_iter(scopes)?;
            let empty = vm.list(Vec::new());
            node_mut(vm, memo).scopes = empty;
            let rm = vm.core.n.remove;
            rooted(vm, &waiting, |vm| -> PyResult<()> {
                for &scope in &waiting {
                    call_method(vm, scope, rm, &[memo])?;
                }
                Ok(())
            })?;
        }
        if is_coroutine_like(vm, new) {
            let st = vm.core.n.start;
            call_method(vm, memo, st, &[new])?;
            return Ok(());
        }
        let equal = node(vm, memo).equal;
        if is_unset(vm, old) || !same(vm, equal, old, new)? {
            node_mut(vm, memo).value = new;
            let reader = vm.core.listener;
            let observers = node(vm, memo).observers.clone();
            let first = is_unset(vm, old);
            for o in observers {
                if first && o == reader {
                    continue;
                }
                mark(vm, o, DIRTY);
            }
            let _ = &old;
        }
        Ok(())
    })();
    vm.roots.pop();
    r
}

pub fn memo_call(vm: &mut Vm, memo: Value) -> PyResult {
    let listener = vm.core.listener;
    if !listener.is_none() {
        track(vm, listener, memo);
    }
    if node(vm, memo).state != CLEAN {
        update_if_necessary(vm, memo)?;
    }
    if node(vm, memo).not_ready {
        // The reader waits too, under its own Loading boundary.
        let owner = vm.core.owner;
        let lc = vm.core.loading_ctx;
        let scope = lookup(vm, owner, lc)?;
        if !scope.is_none() {
            let scopes = memo_scopes(vm, memo);
            if !vm.contains(scopes, scope)? {
                vm.list_push(scopes, scope);
                let refreshing = Value::bool(!is_unset(vm, node(vm, memo).value));
                let add = vm.core.n.add;
                call_method(vm, scope, add, &[memo, refreshing])?;
            }
        }
        let nr = vm.core.not_ready_cls;
        let exc = vm.call(nr, &[], &[])?;
        return Err(exc);
    }
    if !node(vm, memo).loading.is_none() {
        let ra = vm.core.n.read_async;
        return call_method(vm, memo, ra, &[]);
    }
    Ok(node(vm, memo).value)
}

/// The memo's `_scopes` list, made on first use.
fn memo_scopes(vm: &mut Vm, memo: Value) -> Value {
    let s = node(vm, memo).scopes;
    if s.is_none() {
        let l = vm.list(Vec::new());
        node_mut(vm, memo).scopes = l;
        l
    } else {
        s
    }
}

fn effect_run(vm: &mut Vm, e: Value) -> PyResult<()> {
    node_mut(vm, e).state = CLEAN;
    let value = match compute(vm, e)? {
        Some(v) => v,
        None => return Ok(()),
    };
    let t = vm.core.transition;
    if !t.is_none() {
        let n = node(vm, e);
        if n.render && !n.urgent && on_screen(vm, e)? {
            let n = node_mut(vm, e);
            n.parked = value;
            n.queued = true;
            let d = vm.core.n.deferred;
            let deferred = vm.get_attr(t, d)?;
            vm.list_push(deferred, e);
            return Ok(());
        }
    }
    apply(vm, e, value)
}

fn on_screen(vm: &mut Vm, e: Value) -> PyResult<bool> {
    let target = node(vm, e).target;
    if target.is_none() {
        return Ok(true);
    }
    let r = vm.call(target, &[], &[])?;
    vm.truthy(r)
}

fn apply(vm: &mut Vm, e: Value, value: Value) -> PyResult<()> {
    let effect = node(vm, e).effect;
    if !effect.is_none() {
        if !node(vm, e).cleanup.is_none() {
            run_cleanup(vm, e)?;
        }
        let prev = node(vm, e).value;
        let prev = if is_unset(vm, prev) { Value::NONE } else { prev };
        let saved = vm.core.listener;
        vm.core.listener = Value::NONE;
        vm.core.untracking += 1;
        vm.roots.push(value);
        let r = vm.call(effect, &[value, prev], &[]);
        vm.roots.pop();
        vm.core.untracking -= 1;
        vm.core.listener = saved;
        let result = r?;
        if callable(vm, result) {
            node_mut(vm, e).cleanup = result;
        }
    }
    node_mut(vm, e).value = value;
    Ok(())
}

fn run_cleanup(vm: &mut Vm, e: Value) -> PyResult<()> {
    let c = core::mem::replace(&mut node_mut(vm, e).cleanup, Value::NONE);
    if !c.is_none() {
        rooted(vm, &[c], |vm| vm.call(c, &[], &[]))?;
    }
    Ok(())
}

fn commit_parked(vm: &mut Vm, e: Value) -> PyResult<()> {
    let parked = core::mem::replace(&mut node_mut(vm, e).parked, Value::UNDEF);
    let n = node_mut(vm, e);
    n.queued = false;
    if n.disposed {
        return Ok(());
    }
    if n.state != CLEAN || parked.is_undef() {
        if node(vm, e).state == CLEAN {
            mark(vm, e, DIRTY);
        }
        if !node(vm, e).queued {
            node_mut(vm, e).queued = true;
            vm.core.render_queue.push(e);
        }
        return Ok(());
    }
    apply(vm, e, parked)
}

pub fn callable(vm: &Vm, v: Value) -> bool {
    if !v.is_obj() {
        return false;
    }
    match vm.heap.get(v) {
        Obj::Func(_) | Obj::Native(_) | Obj::Bound { .. } | Obj::Class(_) | Obj::StaticMethod(_) | Obj::Js(_) => true,
        Obj::Node(n) => matches!(n.kind, Kind::Signal | Kind::Memo),
        Obj::Instance(_) => {
            let c = vm.n.call;
            vm.lookup_method(v, c).is_some()
        }
        _ => false,
    }
}

// -- signals -----------------------------------------------------------------------------------

pub fn signal_call(vm: &mut Vm, sig: Value) -> PyResult {
    let listener = vm.core.listener;
    if !listener.is_none() {
        track(vm, listener, sig);
    } else if vm.core.debug && vm.core.async_tasks > 0 && vm.core.untracking == 0 {
        let h = vm.core.hook_untracked_read;
        if !h.is_none() {
            vm.call(h, &[sig], &[])?;
        }
    }
    Ok(node(vm, sig).value)
}

fn signal_set(vm: &mut Vm, sig: Value, value: Value, check: bool) -> PyResult {
    let (equal, old) = {
        let n = node(vm, sig);
        (n.equal, n.value)
    };
    if same(vm, equal, old, value)? {
        return Ok(Value::FALSE);
    }
    if check && vm.core.debug && !vm.core.listener.is_none() {
        let h = vm.core.hook_tracked_write;
        if !h.is_none() {
            let l = vm.core.listener;
            vm.call(h, &[l], &[])?;
        }
    }
    node_mut(vm, sig).value = value;
    notify(vm, sig)?;
    Ok(Value::TRUE)
}

// -- the Python surface -------------------------------------------------------------------------

fn this(vm: &mut Vm, args: &[Value], kind: &str) -> PyResult<Value> {
    match args.first() {
        Some(&v) if is_node(vm, v) => Ok(v),
        _ => Err(vm.type_error(format!("expected a {kind}"))),
    }
}
fn kw<'a>(vm: &Vm, kwargs: &'a [(Value, Value)], name: &str) -> Option<Value> {
    for (k, v) in kwargs {
        if vm.as_str(*k) == Some(name) {
            return Some(*v);
        }
    }
    None
}

fn owner_init(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Owner")?;
    let parent = match args.get(1).copied().or_else(|| kw(vm, kwargs, "parent")) {
        Some(p) if !is_unset(vm, p) => p,
        _ => vm.core.owner,
    };
    owner_attach(vm, obj, parent);
    Ok(Value::NONE)
}

fn signal_init(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Signal")?;
    let value = match args.get(1) {
        Some(&v) => v,
        None => kw(vm, kwargs, "value").ok_or_else(|| vm.type_error("Signal() missing 1 required positional argument: 'value'"))?,
    };
    let equal = args.get(2).copied().or_else(|| kw(vm, kwargs, "equal")).unwrap_or(Value::NONE);
    let n = node_mut(vm, obj);
    n.value = value;
    n.equal = equal;
    Ok(Value::NONE)
}

fn comp_init(vm: &mut Vm, obj: Value, f: Value) {
    let parent = vm.core.owner;
    owner_attach(vm, obj, parent);
    let n = node_mut(vm, obj);
    n.func = f;
    n.state = DIRTY;
    n.queued = false;
}

fn memo_init(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Memo")?;
    let f = match args.get(1) {
        Some(&v) => v,
        None => kw(vm, kwargs, "fn").ok_or_else(|| vm.type_error("Memo() missing 1 required positional argument: 'fn'"))?,
    };
    let equal = args.get(2).copied().or_else(|| kw(vm, kwargs, "equal")).unwrap_or(Value::NONE);
    comp_init(vm, obj, f);
    let n = node_mut(vm, obj);
    n.equal = equal;
    n.value = Value::UNDEF;
    n.pure = true;
    let h = vm.core.hook_memo_created;
    if !h.is_none() {
        vm.call(h, &[obj], &[])?;
    }
    Ok(Value::NONE)
}

fn effect_init(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Effect")?;
    let f = match args.get(1) {
        Some(&v) => v,
        None => kw(vm, kwargs, "compute").ok_or_else(|| vm.type_error("Effect() missing 1 required positional argument: 'compute'"))?,
    };
    let effect = args.get(2).copied().or_else(|| kw(vm, kwargs, "effect")).unwrap_or(Value::NONE);
    let target = args.get(3).copied().or_else(|| kw(vm, kwargs, "target")).unwrap_or(Value::NONE);
    comp_init(vm, obj, f);
    let n = node_mut(vm, obj);
    n.effect = effect;
    n.target = target;
    n.value = Value::UNDEF;
    // A fresh effect is DIRTY and queued; with no batch open it runs before the constructor returns.
    queue(vm, obj);
    if vm.core.batch_depth == 0 && !vm.core.flushing {
        begin_batch(vm);
        end_batch(vm)?;
    }
    Ok(Value::NONE)
}

fn m_call(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Signal")?;
    node_call(vm, obj)
}
/// `signal()` / `memo()`: the read.
pub fn node_call(vm: &mut Vm, obj: Value) -> PyResult {
    match node(vm, obj).kind {
        Kind::Signal => signal_call(vm, obj),
        Kind::Memo => memo_call(vm, obj),
        _ => {
            let t = vm.type_name(obj);
            Err(vm.type_error(format!("'{t}' object is not callable")))
        }
    }
}
fn m_value(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Signal")?;
    node_call(vm, obj)
}
fn m_peek(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Signal")?;
    if node(vm, obj).kind == Kind::Memo {
        if node(vm, obj).state != CLEAN {
            update_if_necessary(vm, obj)?;
        }
        let v = node(vm, obj).value;
        return Ok(if is_unset(vm, v) { Value::NONE } else { v });
    }
    Ok(node(vm, obj).value)
}
fn m_set(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Signal")?;
    let v = args.get(1).copied().ok_or_else(|| vm.type_error("set() takes one argument"))?;
    signal_set(vm, obj, v, true)
}
fn m_write(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Signal")?;
    let v = args.get(1).copied().ok_or_else(|| vm.type_error("_write() takes one argument"))?;
    signal_set(vm, obj, v, false)
}
fn m_update(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Signal")?;
    let f = args.get(1).copied().ok_or_else(|| vm.type_error("update() takes one argument"))?;
    let old = node(vm, obj).value;
    let v = vm.call(f, &[old], &[])?;
    // `Signal.set` through the class, so an Optimistic's override applies.
    let set = vm.intern("set");
    call_method(vm, obj, set, &[v])
}
fn m_repr(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "node")?;
    let (kind, value, disposed, name) = {
        let n = node(vm, obj);
        (n.kind, n.value, n.disposed, n.name)
    };
    let s = match kind {
        Kind::Signal => format!("Signal({})", vm.repr(value)?),
        Kind::Memo => {
            if is_unset(vm, value) {
                "Memo(<unread>)".to_string()
            } else {
                format!("Memo({})", vm.repr(value)?)
            }
        }
        Kind::Effect => format!("<{} {}>", vm.type_name(obj), if disposed { "disposed" } else { "live" }),
        Kind::Owner => {
            let label = if name.is_none() { String::new() } else { format!(" {}", vm.str_of(name)?) };
            format!("<Owner{label}{}>", if disposed { " (disposed)" } else { "" })
        }
    };
    Ok(vm.string(s))
}
fn m_dispose(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Owner")?;
    dispose(vm, obj)?;
    Ok(Value::NONE)
}
fn m_on_cleanup(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Owner")?;
    let f = args.get(1).copied().ok_or_else(|| vm.type_error("on_cleanup() takes one argument"))?;
    node_mut(vm, obj).cleanups.push(f);
    Ok(f)
}
fn m_run(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Owner")?;
    let f = args.get(1).copied().ok_or_else(|| vm.type_error("run() needs a function"))?;
    run_with_owner(vm, obj, f, &args[2..], kwargs)
}
fn m_enter(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Owner")?;
    let saved = vm.tuple(vec![vm.core.owner, vm.core.listener]);
    let key = vm.core.n.saved;
    node_set_attr(vm, obj, key, saved)?;
    vm.core.owner = obj;
    vm.core.listener = Value::NONE;
    Ok(obj)
}
fn m_exit(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Owner")?;
    let key = vm.core.n.saved;
    let saved = vm.get_attr(obj, key)?;
    let items = vm.collect_iter(saved)?;
    vm.core.owner = items.first().copied().unwrap_or(Value::NONE);
    vm.core.listener = items.get(1).copied().unwrap_or(Value::NONE);
    Ok(Value::FALSE)
}
fn m_track(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "computation")?;
    let s = args.get(1).copied().ok_or_else(|| vm.type_error("_track() takes a source"))?;
    if !is_node(vm, s) {
        return Err(vm.type_error("a source must be a Signal or a Memo"));
    }
    track(vm, obj, s);
    Ok(Value::NONE)
}
fn m_clear_sources(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "computation")?;
    clear_sources(vm, obj);
    Ok(Value::NONE)
}
fn m_update_if_necessary(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "computation")?;
    update_if_necessary(vm, obj)?;
    Ok(Value::NONE)
}
fn m_run_comp(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "computation")?;
    run(vm, obj)?;
    Ok(Value::NONE)
}
fn m_commit_parked(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Effect")?;
    commit_parked(vm, obj)?;
    Ok(Value::NONE)
}
fn m_run_cleanup(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Effect")?;
    run_cleanup(vm, obj)?;
    Ok(Value::NONE)
}
fn m_on_screen(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Effect")?;
    Ok(Value::bool(on_screen(vm, obj)?))
}
fn m_apply(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Effect")?;
    let v = args.get(1).copied().ok_or_else(|| vm.type_error("_apply() takes a value"))?;
    apply(vm, obj, v)?;
    Ok(Value::NONE)
}
fn m_loading(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Memo")?;
    let l = node(vm, obj).loading;
    if l.is_none() {
        return Ok(Value::FALSE);
    }
    let v = vm.call(l, &[], &[])?;
    Ok(Value::bool(vm.truthy(v)?))
}
fn m_error(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Memo")?;
    let e = node(vm, obj).error;
    if e.is_none() {
        return Ok(Value::NONE);
    }
    vm.call(e, &[], &[])
}
fn m_is_async(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let obj = this(vm, args, "Memo")?;
    Ok(Value::bool(!node(vm, obj).loading.is_none()))
}

// -- module functions ---------------------------------------------------------------------------

pub fn run_with_owner(vm: &mut Vm, owner: Value, f: Value, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let (so, sl) = (vm.core.owner, vm.core.listener);
    vm.core.owner = owner;
    vm.core.listener = Value::NONE;
    let r = vm.call(f, args, kwargs);
    vm.core.owner = so;
    vm.core.listener = sl;
    r
}

fn f_get_owner(vm: &mut Vm, _a: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(vm.core.owner)
}
fn f_listener(vm: &mut Vm, _a: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(vm.core.listener)
}
fn f_set_scope(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    vm.core.owner = args.first().copied().unwrap_or(Value::NONE);
    vm.core.listener = args.get(1).copied().unwrap_or(Value::NONE);
    Ok(Value::NONE)
}
fn f_run_with_owner(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    if args.len() < 2 {
        return Err(vm.type_error("run_with_owner(owner, fn, *args)"));
    }
    run_with_owner(vm, args[0], args[1], &args[2..], kwargs)
}
fn f_on_cleanup(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let f = args.first().copied().ok_or_else(|| vm.type_error("on_cleanup(fn)"))?;
    let o = vm.core.owner;
    if !o.is_none() {
        if is_node(vm, o) {
            node_mut(vm, o).cleanups.push(f);
        } else {
            let oc = vm.intern("on_cleanup");
            call_method(vm, o, oc, &[f])?;
        }
    }
    Ok(f)
}
fn f_untrack(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let f = args.first().copied().ok_or_else(|| vm.type_error("untrack(fn, *args)"))?;
    let saved = vm.core.listener;
    vm.core.listener = Value::NONE;
    vm.core.untracking += 1;
    let r = vm.call(f, &args[1..], kwargs);
    vm.core.untracking -= 1;
    vm.core.listener = saved;
    r
}
fn f_begin_batch(vm: &mut Vm, _a: &[Value], _k: &[(Value, Value)]) -> PyResult {
    begin_batch(vm);
    Ok(Value::NONE)
}
fn f_end_batch(vm: &mut Vm, _a: &[Value], _k: &[(Value, Value)]) -> PyResult {
    end_batch(vm)?;
    Ok(Value::NONE)
}
fn f_batch_depth(vm: &mut Vm, _a: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::int(vm.core.batch_depth as i32))
}
fn f_flushing(vm: &mut Vm, _a: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::bool(vm.core.flushing))
}
fn f_untracking(vm: &mut Vm, _a: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::int(vm.core.untracking as i32))
}
fn f_lookup(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    if args.len() != 2 {
        return Err(vm.type_error("lookup(owner, ctx)"));
    }
    lookup(vm, args[0], args[1])
}
fn f_route_error(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    if args.len() != 2 {
        return Err(vm.type_error("route_error(owner, exc)"));
    }
    route_error(vm, args[0], args[1])?;
    Ok(Value::NONE)
}
fn f_mark(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    if args.len() != 2 || !is_node(vm, args[0]) {
        return Err(vm.type_error("mark(node, state)"));
    }
    let s = vm.as_i64(args[1]).unwrap_or(2) as u8;
    mark(vm, args[0], s);
    Ok(Value::NONE)
}
fn f_queue_render(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let e = args.first().copied().filter(|&v| is_node(vm, v)).ok_or_else(|| vm.type_error("queue_render(effect)"))?;
    node_mut(vm, e).queued = true;
    vm.core.render_queue.push(e);
    Ok(Value::NONE)
}
fn f_transition(vm: &mut Vm, _a: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(vm.core.transition)
}
fn f_set_transition(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    vm.core.transition = args.first().copied().unwrap_or(Value::NONE);
    Ok(Value::NONE)
}
fn f_set_debug(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let v = args.first().copied().unwrap_or(Value::TRUE);
    vm.core.debug = vm.truthy(v)?;
    Ok(Value::NONE)
}
fn f_async_task(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    let d = args.first().and_then(|&v| vm.as_i64(v)).unwrap_or(0);
    vm.core.async_tasks = (vm.core.async_tasks as i64 + d).max(0) as u32;
    Ok(Value::NONE)
}
fn f_is_node(vm: &mut Vm, args: &[Value], _k: &[(Value, Value)]) -> PyResult {
    Ok(Value::bool(args.first().map(|&v| is_node(vm, v)).unwrap_or(false)))
}
/// `setup(not_ready=…, errors=…, loading=…, untracked_read=…, tracked_write=…, memo_created=…)`:
/// what `reactive.py` hands over once it has defined it. Any keyword may be omitted or None.
fn f_setup(vm: &mut Vm, _a: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    for &(k, v) in kwargs {
        let key = vm.as_str(k).unwrap_or("").to_string();
        match key.as_str() {
            "not_ready" => vm.core.not_ready_cls = v,
            "errors" => vm.core.errors_ctx = v,
            "loading" => vm.core.loading_ctx = v,
            "untracked_read" => vm.core.hook_untracked_read = v,
            "tracked_write" => vm.core.hook_tracked_write = v,
            "memo_created" => vm.core.hook_memo_created = v,
            other => return Err(vm.type_error(format!("setup(): unknown keyword '{other}'"))),
        }
    }
    Ok(Value::NONE)
}

// -- attributes -----------------------------------------------------------------------------------

pub fn node_get_attr(vm: &mut Vm, obj: Value, name: Value) -> PyResult {
    let n = &vm.core.n;
    // The fields the Python half reads.
    if name == n.state {
        return Ok(Value::int(node(vm, obj).state as i32));
    }
    if name == n.value {
        let v = node(vm, obj).value;
        return Ok(if v.is_undef() { vm.core.unset } else { v });
    }
    if name == n.parent {
        return Ok(node(vm, obj).parent);
    }
    if name == n.disposed {
        return Ok(Value::bool(node(vm, obj).disposed));
    }
    if name == n.queued {
        return Ok(Value::bool(node(vm, obj).queued));
    }
    if name == n.observers {
        let v = node(vm, obj).observers.clone();
        return Ok(vm.list(v));
    }
    if name == n.owned {
        let v = node(vm, obj).owned.clone();
        return Ok(vm.list(v));
    }
    if name == n.cleanups {
        let v = node(vm, obj).cleanups.clone();
        return Ok(vm.list(v));
    }
    if name == n.sources {
        let v = node(vm, obj).sources.clone();
        return Ok(vm.list(v));
    }
    if name == n.observer_slots || name == n.slots {
        let nd = node(vm, obj);
        let v: Vec<Value> = (if name == n.slots { &nd.slots } else { &nd.observer_slots }).iter().map(|&i| Value::int(i as i32)).collect();
        return Ok(vm.list(v));
    }
    if name == n.context {
        return Ok(node(vm, obj).context);
    }
    if name == n.name {
        return Ok(node(vm, obj).name);
    }
    if name == n.equal {
        return Ok(node(vm, obj).equal);
    }
    if name == n.fn_ {
        return Ok(node(vm, obj).func);
    }
    if name == n.not_ready {
        return Ok(Value::bool(node(vm, obj).not_ready));
    }
    if name == n.pure {
        return Ok(Value::bool(node(vm, obj).pure));
    }
    if name == n.render {
        return Ok(Value::bool(node(vm, obj).render));
    }
    if name == n.urgent {
        return Ok(Value::bool(node(vm, obj).urgent));
    }
    if name == n.target {
        return Ok(node(vm, obj).target);
    }
    if name == n.effect {
        return Ok(node(vm, obj).effect);
    }
    if name == n.cleanup {
        return Ok(node(vm, obj).cleanup);
    }
    if name == n.parked {
        let v = node(vm, obj).parked;
        return Ok(if v.is_undef() { vm.core.unset } else { v });
    }
    if name == n.loading {
        return Ok(node(vm, obj).loading);
    }
    if name == n.error {
        return Ok(node(vm, obj).error);
    }
    if name == n.scopes {
        return Ok(memo_scopes(vm, obj));
    }
    let (class, hit) = {
        let nd = node(vm, obj);
        (nd.class, nd.dict.as_ref().and_then(|d| d.get(&vm.heap, name)))
    };
    if let Some(v) = hit {
        return Ok(v);
    }
    if let Some(m) = vm.class_lookup(class, name) {
        return vm.bind_descriptor(m, obj, class);
    }
    let g = vm.n.getattr;
    if let Some(hook) = vm.class_lookup(class, g) {
        return vm.call(hook, &[obj, name], &[]);
    }
    let tn = vm.class_name(class);
    let s = vm.as_str(name).unwrap_or("?").to_string();
    Err(vm.attribute_error(format!("'{tn}' object has no attribute '{s}'")))
}

pub fn node_set_attr(vm: &mut Vm, obj: Value, name: Value, value: Value) -> PyResult<()> {
    let n = &vm.core.n;
    macro_rules! bool_field {
        ($f:ident) => {{
            let b = vm.truthy(value)?;
            node_mut(vm, obj).$f = b;
            return Ok(());
        }};
    }
    if name == n.state {
        let s = vm.as_i64(value).unwrap_or(0) as u8;
        node_mut(vm, obj).state = s;
        return Ok(());
    }
    if name == n.value {
        node_mut(vm, obj).value = if value == vm.core.unset { Value::UNDEF } else { value };
        return Ok(());
    }
    if name == n.parent {
        node_mut(vm, obj).parent = value;
        return Ok(());
    }
    if name == n.queued {
        bool_field!(queued);
    }
    if name == n.disposed {
        bool_field!(disposed);
    }
    if name == n.urgent {
        bool_field!(urgent);
    }
    if name == n.not_ready {
        bool_field!(not_ready);
    }
    if name == n.render {
        bool_field!(render);
    }
    if name == n.pure {
        bool_field!(pure);
    }
    if name == n.context {
        node_mut(vm, obj).context = value;
        return Ok(());
    }
    if name == n.name {
        node_mut(vm, obj).name = value;
        return Ok(());
    }
    if name == n.target {
        node_mut(vm, obj).target = value;
        return Ok(());
    }
    if name == n.fn_ {
        node_mut(vm, obj).func = value;
        return Ok(());
    }
    if name == n.effect {
        node_mut(vm, obj).effect = value;
        return Ok(());
    }
    if name == n.cleanup {
        node_mut(vm, obj).cleanup = value;
        return Ok(());
    }
    if name == n.equal {
        node_mut(vm, obj).equal = value;
        return Ok(());
    }
    if name == n.parked {
        node_mut(vm, obj).parked = if value == vm.core.unset { Value::UNDEF } else { value };
        return Ok(());
    }
    if name == n.loading {
        node_mut(vm, obj).loading = value;
        return Ok(());
    }
    if name == n.error {
        node_mut(vm, obj).error = value;
        return Ok(());
    }
    if name == n.scopes {
        node_mut(vm, obj).scopes = value;
        return Ok(());
    }
    // Anything else lives in the node's dict (a subclass's fields, `_hydrated`, `_saved`).
    let mut d = node_mut(vm, obj).dict.take().unwrap_or_default();
    d.set(&vm.heap, name, value);
    node_mut(vm, obj).dict = Some(d);
    Ok(())
}

// -- construction and installation ---------------------------------------------------------------

pub fn construct(vm: &mut Vm, cls: Value, kind: Builtin, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let k = match kind {
        Builtin::Owner => Kind::Owner,
        Builtin::Signal => Kind::Signal,
        Builtin::Memo => Kind::Memo,
        Builtin::Effect | Builtin::RenderEffect => Kind::Effect,
        _ => unreachable!(),
    };
    let mut n = Node::blank(cls, k);
    n.render = kind == Builtin::RenderEffect;
    let obj = vm.heap.alloc(Obj::Node(Box::new(n)));
    vm.roots.push(obj);
    let init = vm.n.init;
    let r = match vm.class_lookup(cls, init) {
        Some(f) => {
            let mut all = Vec::with_capacity(args.len() + 1);
            all.push(obj);
            all.extend_from_slice(args);
            vm.call(f, &all, kwargs).map(|_| obj)
        }
        None => Ok(obj),
    };
    vm.roots.pop();
    r
}

pub fn install_module(vm: &mut Vm) -> PyResult {
    use crate::builtins::{add_method, new_class_pub};
    CoreNames::fill(vm);
    let m = vm.new_module("_core");
    let d = vm.module_dict(m);
    // The sentinel `_UNSET`: one object, compared by identity.
    let unset_cls = new_class_pub(vm, "_Unset", None, &[vm.t.object]);
    let unset = vm.construct(unset_cls, &[], &[])?;
    vm.core.unset = unset;
    vm.dict_set_str(d, "UNSET", unset);

    let object = vm.t.object;
    let owner = new_class_pub(vm, "Owner", Some(Builtin::Owner), &[object]);
    let signal = new_class_pub(vm, "Signal", Some(Builtin::Signal), &[object]);
    let memo = new_class_pub(vm, "Memo", Some(Builtin::Memo), &[owner]);
    let effect = new_class_pub(vm, "Effect", Some(Builtin::Effect), &[owner]);
    let render = new_class_pub(vm, "RenderEffect", Some(Builtin::RenderEffect), &[effect]);
    vm.core.owner_cls = owner;
    vm.core.signal_cls = signal;
    vm.core.memo_cls = memo;
    vm.core.effect_cls = effect;
    vm.core.render_effect_cls = render;

    add_method(vm, owner, "__init__", owner_init);
    add_method(vm, owner, "dispose", m_dispose);
    add_method(vm, owner, "on_cleanup", m_on_cleanup);
    add_method(vm, owner, "run", m_run);
    add_method(vm, owner, "__enter__", m_enter);
    add_method(vm, owner, "__exit__", m_exit);
    add_method(vm, owner, "__repr__", m_repr);
    add_method(vm, owner, "_dispose_owned", |vm, a, _| {
        let o = this(vm, a, "Owner")?;
        dispose_owned(vm, o)?;
        Ok(Value::NONE)
    });

    add_method(vm, signal, "__init__", signal_init);
    add_method(vm, signal, "__call__", m_call);
    add_method(vm, signal, "peek", m_peek);
    add_method(vm, signal, "set", m_set);
    add_method(vm, signal, "_write", m_write);
    add_method(vm, signal, "update", m_update);
    add_method(vm, signal, "__repr__", m_repr);
    let getter = vm.native("value", m_value);
    let prop = vm.heap.alloc(Obj::Property { get: getter, set: Value::NONE, del: Value::NONE });
    let value_name = vm.intern("value");
    vm.class_dict_set(signal, value_name, prop);
    vm.class_dict_set(memo, value_name, prop);

    for cls in [memo, effect] {
        add_method(vm, cls, "_track", m_track);
        add_method(vm, cls, "_clear_sources", m_clear_sources);
        add_method(vm, cls, "_update_if_necessary", m_update_if_necessary);
        add_method(vm, cls, "_run", m_run_comp);
        add_method(vm, cls, "__repr__", m_repr);
    }
    add_method(vm, memo, "__init__", memo_init);
    add_method(vm, memo, "__call__", m_call);
    add_method(vm, memo, "peek", m_peek);
    add_method(vm, memo, "loading", m_loading);
    add_method(vm, memo, "error", m_error);
    add_method(vm, memo, "is_async", m_is_async);
    add_method(vm, effect, "__init__", effect_init);
    add_method(vm, effect, "_apply", m_apply);
    add_method(vm, effect, "_commit_parked", m_commit_parked);
    add_method(vm, effect, "_run_cleanup", m_run_cleanup);
    add_method(vm, effect, "_on_screen", m_on_screen);

    for (name, cls) in [("Owner", owner), ("Signal", signal), ("Memo", memo), ("Effect", effect), ("RenderEffect", render)] {
        vm.dict_set_str(d, name, cls);
    }
    let fns: &[(&'static str, crate::object::NativeFn)] = &[
        ("get_owner", f_get_owner),
        ("listener", f_listener),
        ("set_scope", f_set_scope),
        ("run_with_owner", f_run_with_owner),
        ("on_cleanup", f_on_cleanup),
        ("untrack", f_untrack),
        ("begin_batch", f_begin_batch),
        ("end_batch", f_end_batch),
        ("batch_depth", f_batch_depth),
        ("flushing", f_flushing),
        ("untracking", f_untracking),
        ("lookup", f_lookup),
        ("route_error", f_route_error),
        ("mark", f_mark),
        ("queue_render", f_queue_render),
        ("transition", f_transition),
        ("set_transition", f_set_transition),
        ("set_debug", f_set_debug),
        ("async_task", f_async_task),
        ("is_node", f_is_node),
        ("setup", f_setup),
    ];
    for &(name, f) in fns {
        let nf = vm.native(name, f);
        vm.dict_set_str(d, name, nf);
    }
    vm.dict_set_str(d, "CLEAN", Value::int(0));
    vm.dict_set_str(d, "CHECK", Value::int(1));
    vm.dict_set_str(d, "DIRTY", Value::int(2));
    Ok(m)
}
