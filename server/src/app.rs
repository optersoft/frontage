//! The VM side: load a Python module, hold its routes, run one handler to completion.
//!
//! One `App` is one `Vm`, and a `Vm` is not `Send` — the design, not a limitation
//! (`PLAN.md` §4.1). Every worker thread owns one, they share nothing, and no lock exists
//! anywhere because there is nothing to lock.
//!
//! **Values held in Rust between calls must be rooted.** The collector is precise and traces
//! the stack, the frames, the module table and `vm.roots`; a `Value` in a Rust local is
//! reachable from none of those. Anything held across a call into Python is pushed onto
//! `vm.roots` and truncated back after, or kept in a Python dict that is itself rooted —
//! which is what `coros` and `waits` are.
//!
//! **A coroutine is driven here rather than by an asyncio `Task`.** The protocol is the one
//! `Task._step` implements: `send(None)`, a `StopIteration` means the answer, a yielded
//! `Future` means suspend. Doing it in Rust costs no Task object, no `call_soon` and no
//! callback per step, and — the part that matters for §4.4 — **a handler that never suspends
//! never touches the loop at all**.

use crate::hostmod;
use frontage_vm::dict::PyDict;
use frontage_vm::host::StdHost;
use frontage_vm::object::Obj;
use frontage_vm::value::Value;
use frontage_vm::vm::Vm;
use std::path::PathBuf;

pub struct App {
    vm: Vm,
    /// Path to handler, in declaration order. Two routes at the spike, so a linear scan is
    /// the whole router; a real one arrives with the surface in `PLAN.md` §6.2.
    routes: Vec<(String, Value)>,
    /// `asyncio.get_event_loop().run_once`, bound once.
    run_once: Value,
    /// token to the suspended coroutine, and token to the future it waits on. Python dicts
    /// rather than Rust maps, because a `Value` in a Rust map is invisible to the collector.
    coros: Value,
    waits: Value,
    next_token: u64,
    n_done: Value,
}

/// What a handler answered: bytes and the content type to send them with.
pub struct Answer {
    pub body: Vec<u8>,
    pub content_type: &'static str,
}

/// A handler either finished inside the one call, or suspended and needs the loop pumped.
pub enum Started {
    Done(Answer),
    Running(u64),
}

/// What one `poll` did. **`Advanced` is not a detail:** it says the coroutine was resumed and
/// may have awaited something new, which makes any delay measured before the poll stale. A
/// caller that treats "nothing scheduled" as a deadlock has to know the difference, or a
/// handler with two awaits in a row is declared stuck between them. It was.
pub enum Poll {
    Done(Answer),
    Advanced,
    Blocked,
}

enum Progress {
    Done(Answer),
    /// The coroutine yielded this future and is waiting on it.
    Waiting(Value),
}

fn fault(vm: &mut Vm, exc: Value) -> String {
    vm.format_exception(exc)
}

impl App {
    /// Import `module` from `dir` and read its `ROUTES` table.
    pub fn load(dir: PathBuf, module: &str) -> Result<App, String> {
        let mut vm = Vm::new(Box::new(StdHost::new(vec![dir])));
        frontage_compile::install(&mut vm);
        hostmod::install(&mut vm);
        let m = match vm.import_module(module) {
            Ok(m) => m,
            Err(exc) => return Err(fault(&mut vm, exc)),
        };
        // The module sits in `vm.modules`, so it and every handler it names stay reachable:
        // the values below need no root of their own.
        let key = vm.intern("ROUTES");
        let table = match vm.get_attr(m, key) {
            Ok(t) => t,
            Err(exc) => return Err(fault(&mut vm, exc)),
        };
        let pairs = match vm.take_dict_snapshot(table) {
            Ok(p) => p,
            Err(exc) => return Err(fault(&mut vm, exc)),
        };
        let mut routes = Vec::with_capacity(pairs.len());
        for (k, v) in pairs {
            match vm.as_str(k) {
                Some(s) => routes.push((s.to_owned(), v)),
                None => return Err("ROUTES: every key must be a string".into()),
            }
        }
        if routes.is_empty() {
            return Err(format!("{module}.ROUTES is empty"));
        }

        let run_once = match Self::bind_run_once(&mut vm) {
            Ok(v) => v,
            Err(exc) => return Err(fault(&mut vm, exc)),
        };
        let coros = vm.dict(PyDict::new());
        let waits = vm.dict(PyDict::new());
        // Permanent roots, at the bottom of the stack: every per-call `truncate` marks above
        // these, so they are never popped.
        vm.roots.push(run_once);
        vm.roots.push(coros);
        vm.roots.push(waits);
        let n_done = vm.intern("done");
        Ok(App { vm, routes, run_once, coros, waits, next_token: 1, n_done })
    }

    fn bind_run_once(vm: &mut Vm) -> Result<Value, Value> {
        let aio = vm.import_module("asyncio")?;
        let k = vm.intern("get_event_loop");
        let get_loop = vm.get_attr(aio, k)?;
        let lp = vm.call(get_loop, &[], &[])?;
        let k = vm.intern("run_once");
        vm.get_attr(lp, k)
    }

    pub fn paths(&self) -> Vec<String> {
        self.routes.iter().map(|(p, _)| p.clone()).collect()
    }

    /// Call the handler for `path` with the request body. `None` when nothing matches, which
    /// the caller turns into a 404.
    pub fn start(&mut self, path: &str, body: &[u8]) -> Option<Result<Started, String>> {
        let handler = self.routes.iter().find(|(p, _)| p == path).map(|(_, h)| *h)?;
        Some(self.begin(handler, body))
    }

    fn begin(&mut self, handler: Value, body: &[u8]) -> Result<Started, String> {
        let mark = self.vm.roots.len();
        let arg = self.vm.heap.alloc(Obj::Bytes(body.to_vec()));
        self.vm.roots.push(arg);
        let called = self.vm.call(handler, &[arg], &[]);
        let out = match called {
            Ok(v) => self.after_call(v),
            Err(exc) => Err(fault(&mut self.vm, exc)),
        };
        self.vm.roots.truncate(mark);
        out
    }

    fn after_call(&mut self, value: Value) -> Result<Started, String> {
        let is_coroutine = match self.vm.heap.get(value) {
            Obj::Generator(g) => g.is_coroutine,
            _ => false,
        };
        if !is_coroutine {
            return self.answer(value).map(Started::Done);
        }
        match self.drive(value)? {
            // The common case, and the one §4.4 budgets: an `async def` that never suspends
            // costs one resume, no token, no dict and no loop turn.
            Progress::Done(a) => Ok(Started::Done(a)),
            Progress::Waiting(fut) => {
                let token = self.next_token;
                self.next_token += 1;
                let key = self.vm.int(token as i64);
                self.vm.dict_set(self.coros, key, value);
                self.vm.dict_set(self.waits, key, fut);
                Ok(Started::Running(token))
            }
        }
    }

    /// One resume of a coroutine. The value is rooted for the duration: `gen_resume` runs
    /// Python, Python can collect, and a coroutine reachable only from a Rust local is not
    /// reachable at all.
    fn drive(&mut self, coro: Value) -> Result<Progress, String> {
        let mark = self.vm.roots.len();
        self.vm.roots.push(coro);
        let mut returned = Value::NONE;
        let stepped = self.vm.gen_resume(coro, Value::NONE, None, &mut returned);
        let out = match stepped {
            Ok(None) => self.answer(returned).map(Progress::Done),
            Ok(Some(yielded)) => Ok(Progress::Waiting(yielded)),
            Err(exc) => Err(fault(&mut self.vm, exc)),
        };
        self.vm.roots.truncate(mark);
        out
    }

    /// Has the future this request waits on settled? If so, resume; if not, say so and let
    /// the caller yield to tokio.
    pub fn poll(&mut self, token: u64) -> Result<Poll, String> {
        let key = self.vm.int(token as i64);
        if let Some(fut) = self.vm.dict_get(self.waits, key) {
            let ready = match self.vm.get_attr(fut, self.n_done) {
                Ok(f) => match self.vm.call(f, &[], &[]) {
                    Ok(v) => match self.vm.truthy(v) {
                        Ok(b) => b,
                        Err(exc) => return Err(self.give_up(token, exc)),
                    },
                    Err(exc) => return Err(self.give_up(token, exc)),
                },
                Err(exc) => return Err(self.give_up(token, exc)),
            };
            if !ready {
                return Ok(Poll::Blocked);
            }
        }
        let coro = match self.vm.dict_get(self.coros, key) {
            Some(c) => c,
            None => return Err("no such request in flight".into()),
        };
        match self.drive(coro) {
            Ok(Progress::Done(a)) => {
                self.forget(token);
                Ok(Poll::Done(a))
            }
            Ok(Progress::Waiting(fut)) => {
                self.vm.dict_set(self.waits, key, fut);
                Ok(Poll::Advanced)
            }
            Err(e) => {
                self.forget(token);
                Err(e)
            }
        }
    }

    fn give_up(&mut self, token: u64, exc: Value) -> String {
        self.forget(token);
        fault(&mut self.vm, exc)
    }

    fn forget(&mut self, token: u64) {
        let key = self.vm.int(token as i64);
        self.vm.dict_remove(self.coros, key);
        self.vm.dict_remove(self.waits, key);
    }

    /// One turn of the loop: settle any `_host` future whose deadline passed, then run the
    /// asyncio loop's own turn. The answer is how long there is to wait before the next
    /// thing is due, or `None` when nothing at all is scheduled — which, with a request
    /// still in flight, means it awaited something nobody will ever complete.
    pub fn pump(&mut self) -> Result<Option<f64>, String> {
        let host_delay = match hostmod::expire(&mut self.vm) {
            Ok(d) => d,
            Err(exc) => return Err(fault(&mut self.vm, exc)),
        };
        let turned = self.vm.call(self.run_once, &[], &[]);
        let loop_delay = match turned {
            Ok(v) if v.is_none() => None,
            Ok(v) => self.vm.as_f64(v),
            Err(exc) => return Err(fault(&mut self.vm, exc)),
        };
        Ok(match (loop_delay, host_delay) {
            (Some(a), Some(b)) => Some(a.min(b)),
            (a, b) => a.or(b),
        })
    }

    /// `str` and `bytes` only, deliberately: the spike measures the transport, and a richer
    /// return type is the surface of `PLAN.md` §6.2.
    fn answer(&mut self, value: Value) -> Result<Answer, String> {
        match self.vm.heap.get(value) {
            Obj::Bytes(b) => Ok(Answer { body: b.clone(), content_type: "application/octet-stream" }),
            _ => match self.vm.as_str(value) {
                Some(s) => Ok(Answer { body: s.as_bytes().to_vec(), content_type: "text/plain; charset=utf-8" }),
                None => Err("a handler must return str or bytes".into()),
            },
        }
    }

    /// Let the collector run between requests rather than inside one.
    pub fn settle_heap(&mut self) {
        self.vm.maybe_collect();
    }
}
