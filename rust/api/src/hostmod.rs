//! `_host`: the seam a Rust event completes a Python future through (`API.md` §4.3).
//!
//! The browser has this already and it is plain Python: `jsffi._await` makes an asyncio
//! future, hands the promise two callbacks, and returns it. The server's version is the same
//! shape with tokio in JavaScript's place, and with none of the machinery Granian needs for
//! the same job — no `call_soon_threadsafe`, no context copy across a lock, no GIL token,
//! because the future, the coroutine and the VM are all on this one thread.
//!
//! `sleep` is the whole module for now, and it exists to prove the shape. The consumers are
//! §6.4's native modules: `_http` over reqwest, `_turso`, `_fs`.
//!
//! **A pending future is rooted in the module's own `_pending` dict**, never in a Rust map: a
//! `Value` the collector cannot see is a `Value` that can be freed while a timer still holds
//! it. The Rust side holds only deadlines and integer tokens.

use frontage_vm::dict::PyDict;
use frontage_vm::value::Value;
use frontage_vm::vm::{PyResult, Vm};
use std::cell::RefCell;

thread_local! {
    /// (deadline in seconds on the host clock, token). One VM per thread, so this and the
    /// VM's `_pending` dict describe the same set.
    static TIMERS: RefCell<Vec<(f64, u64)>> = const { RefCell::new(Vec::new()) };
    static NEXT: RefCell<u64> = const { RefCell::new(1) };
}

pub fn install(vm: &mut Vm) {
    vm.builtin_modules.insert("_host", init);
}

fn init(vm: &mut Vm) -> PyResult {
    let m = vm.new_module("_host");
    let d = vm.module_dict(m);
    let pending = vm.dict(PyDict::new());
    vm.dict_set_str(d, "_pending", pending);
    let f = vm.native("sleep", h_sleep);
    vm.dict_set_str(d, "sleep", f);
    Ok(m)
}

fn now(vm: &Vm) -> f64 {
    vm.host.now_ms() / 1000.0
}

fn pending_dict(vm: &mut Vm) -> PyResult<Value> {
    let m = vm.import_module("_host")?;
    let d = vm.module_dict(m);
    match vm.dict_get_str(d, "_pending") {
        Some(p) => Ok(p),
        None => Err(vm.runtime_error("_host._pending is missing")),
    }
}

/// `await _host.sleep(seconds)`: an asyncio future a tokio deadline settles.
fn h_sleep(vm: &mut Vm, args: &[Value], _kwargs: &[(Value, Value)]) -> PyResult {
    let secs = match args.first().and_then(|v| vm.as_f64(*v)) {
        Some(s) => s,
        None => return Err(vm.type_error("sleep(seconds)")),
    };
    let aio = vm.import_module("asyncio")?;
    let get_loop = {
        let k = vm.intern("get_event_loop");
        vm.get_attr(aio, k)?
    };
    let lp = vm.call(get_loop, &[], &[])?;
    let create = {
        let k = vm.intern("create_future");
        vm.get_attr(lp, k)?
    };
    let fut = vm.call(create, &[], &[])?;
    let token = NEXT.with(|n| {
        let mut n = n.borrow_mut();
        *n += 1;
        *n
    });
    let pending = pending_dict(vm)?;
    let key = vm.int(token as i64);
    vm.dict_set(pending, key, fut);
    let deadline = now(vm) + secs.max(0.0);
    TIMERS.with(|t| t.borrow_mut().push((deadline, token)));
    Ok(fut)
}

/// Settle every future whose deadline has passed. Called by the pump, before the loop's turn.
///
/// ⚠ **This does not report the next deadline, and that separation is the fix for a real
/// bug.** A turn of the event loop can *create* host timers — a task that first runs during
/// `run_once` and immediately awaits `_host.sleep` is exactly that — so a delay measured
/// before the turn misses them and the pump reports "nothing scheduled". Ask `next_delay`
/// after the turn instead.
pub fn expire(vm: &mut Vm) -> PyResult<()> {
    let at = now(vm);
    let due: Vec<u64> = TIMERS.with(|t| {
        let mut timers = t.borrow_mut();
        let mut due = Vec::new();
        timers.retain(|(deadline, token)| {
            if *deadline <= at {
                due.push(*token);
                false
            } else {
                true
            }
        });
        due
    });
    if !due.is_empty() {
        let pending = pending_dict(vm)?;
        let set_result = vm.intern("set_result");
        for token in due {
            let key = vm.int(token as i64);
            if let Some(fut) = vm.dict_remove(pending, key) {
                let f = vm.get_attr(fut, set_result)?;
                vm.call(f, &[Value::NONE], &[])?;
            }
        }
    }
    Ok(())
}

/// How long until the earliest host timer that has not fired, or `None` if there is none.
/// Read *after* the loop's turn; see the warning on `expire`.
pub fn next_delay(vm: &Vm) -> Option<f64> {
    let at = now(vm);
    let next = TIMERS.with(|t| t.borrow().iter().map(|(d, _)| *d).fold(f64::INFINITY, f64::min));
    if next.is_finite() {
        Some((next - at).max(0.0))
    } else {
        None
    }
}
