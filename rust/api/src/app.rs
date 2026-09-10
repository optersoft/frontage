//! The VM side: load the app module, and run one request to completion.
//!
//! One `App` is one `Vm`, and a `Vm` is not `Send` — the design, not a limitation
//! (`API.md` §4.1). Every worker thread owns one, they share nothing, and no lock exists
//! anywhere because there is nothing to lock.
//!
//! **Values held in Rust between calls must be rooted.** The collector is precise and traces
//! the stack, the frames, the module table and `vm.roots`; a `Value` in a Rust local is
//! reachable from none of those. Anything held across a call into Python is pushed onto
//! `vm.roots` and truncated back after, or kept in a Python dict that is itself rooted —
//! which is what `coros` and `waits` are.
//!
//! **The app is `frontage_api.App`, and this file calls exactly one thing on it.** `App.handle`
//! takes a scope and answers `(status, headers, body)`; matching, conversion, validation and
//! the response rules are all Python on the far side of that single call, which is what
//! §4.4's budget means in practice. What Rust owns is the socket, the parse and the body.
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
use std::collections::HashMap;
use std::path::PathBuf;

pub struct App {
    vm: Vm,
    /// `app.handle`, bound once: the single entry per request.
    handle: Value,
    /// What the app declares it serves, for the startup banner only.
    routes: Vec<String>,
    /// `asyncio.get_event_loop().run_once`, bound once.
    run_once: Value,
    /// token to the suspended coroutine, and token to the future it waits on. Python dicts
    /// rather than Rust maps, because a `Value` in a Rust map is invisible to the collector.
    coros: Value,
    waits: Value,
    /// token to a `frontage_api.Chunks` still being pulled from.
    streams: Value,
    /// Set by `drive_chunk` when a chunk coroutine suspended, consumed by the caller that
    /// registers it. One at a time, because a chunk is pulled and parked before the next.
    pending_wait: Option<Value>,
    /// What each in-flight token is. Plain data, no `Value`s, so no rooting to think about.
    kinds: HashMap<u32, Kind>,
    /// ⚠ **`u32`, and that is load-bearing.** `vm.int` keeps an `i32` in the value itself and
    /// puts anything larger on the heap, and a heap `Value` held across a call that runs
    /// Python can be collected under it. A token is used as a dict key on both sides of
    /// `drive`, so a token that never leaves `i32` range makes that whole class of bug
    /// impossible rather than unlikely.
    next_token: u32,
    n_done: Value,
}

/// What the app answered: a whole body, or a source to pull pieces from.
pub struct Answer {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Body,
}

pub enum Body {
    Whole(Vec<u8>),
    /// A `frontage_api.Chunks`, registered under this token. The server pulls with
    /// `chunk_next` until it answers `None`, then calls `forget_stream`.
    Stream(u32),
}

/// A handler either finished inside the one call, or suspended and needs the loop pumped.
pub enum Started {
    Done(Answer),
    Running(u32),
}

/// A token is either a request being finished or a chunk being fetched, and `poll` has to
/// know which because the two read their result differently: a request answers a 3-tuple, a
/// chunk answers bytes or `None`.
#[derive(Clone, Copy, PartialEq)]
pub enum Kind {
    Request,
    Chunk,
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
    /// Import `module` from `dir` and bind the `App` it defines.
    ///
    /// `stress` collects at every safe point, the way `fpy --stress` does. It is how the
    /// rooting in this file is actually tested rather than reasoned about: a `Value` held in
    /// a Rust local across a call into Python is invisible to the collector, and under
    /// stress that mistake fails immediately instead of once a month in production.
    pub fn load(dir: PathBuf, module: &str, search: &[PathBuf], stress: bool) -> Result<App, String> {
        let mut path = vec![dir];
        path.extend(search.iter().cloned());
        let mut vm = Vm::new(Box::new(StdHost::new(path)));
        vm.heap.stress = stress;
        frontage_compile::install(&mut vm);
        hostmod::install(&mut vm);
        let m = match vm.import_module(module) {
            Ok(m) => m,
            Err(exc) => return Err(fault(&mut vm, exc)),
        };
        // The module sits in `vm.modules`, so it and the `App` it names stay reachable.
        let key = vm.intern("app");
        let app = match vm.get_attr(m, key) {
            Ok(a) => a,
            Err(_) => return Err(format!("{module} defines no `app`: it must be a frontage_api.App")),
        };
        let key = vm.intern("handle");
        let handle = match vm.get_attr(app, key) {
            Ok(h) => h,
            Err(_) => return Err(format!("{module}.app has no `handle`: it must be a frontage_api.App")),
        };
        // ⚠ **Rooted here, on the line after it exists, and not one call later.** A bound
        // method is freshly allocated and reachable from nothing but this local; `describe`
        // and `bind_run_once` below both run Python, and Python collects. Pushing these four
        // at the end instead of as they appear is a use-after-free that only shows under
        // `--stress`, where it showed as `TypeError: 'list' object is not callable` — the
        // slot reused by something else. Permanent roots, at the bottom of the stack: every
        // per-call `truncate` marks above them, so they are never popped.
        vm.roots.push(handle);
        let routes = Self::describe(&mut vm, app);

        let run_once = match Self::bind_run_once(&mut vm) {
            Ok(v) => v,
            Err(exc) => return Err(fault(&mut vm, exc)),
        };
        vm.roots.push(run_once);
        let coros = vm.dict(PyDict::new());
        vm.roots.push(coros);
        let waits = vm.dict(PyDict::new());
        vm.roots.push(waits);
        let streams = vm.dict(PyDict::new());
        vm.roots.push(streams);
        let n_done = vm.intern("done");
        Ok(App { vm, handle, routes, run_once, coros, waits, streams, pending_wait: None, kinds: HashMap::new(), next_token: 1, n_done })
    }

    /// `["GET /trips/{id}", ...]` for the banner. Best effort: a failure here is cosmetic.
    fn describe(vm: &mut Vm, app: Value) -> Vec<String> {
        let mut out = Vec::new();
        let router = match vm.intern("router") {
            k => match vm.get_attr(app, k) {
                Ok(r) => r,
                Err(_) => return out,
            },
        };
        let routes = {
            let k = vm.intern("routes");
            match vm.get_attr(router, k) {
                Ok(r) => r,
                Err(_) => return out,
            }
        };
        let items: Vec<Value> = match vm.heap.get(routes) {
            Obj::List(items) => items.clone(),
            _ => return out,
        };
        for route in items {
            let method = {
                let k = vm.intern("method");
                vm.get_attr(route, k).ok().and_then(|v| vm.as_str(v).map(|s| s.to_owned()))
            };
            let path = {
                let k = vm.intern("path");
                vm.get_attr(route, k).ok().and_then(|v| vm.as_str(v).map(|s| s.to_owned()))
            };
            if let (Some(m), Some(p)) = (method, path) {
                out.push(format!("{m} {p}"));
            }
        }
        out
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
        self.routes.clone()
    }

    /// One request: build the scope, and enter Python once.
    pub fn start(&mut self, method: &str, path: &str, query: &str, body: &[u8]) -> Result<Started, String> {
        let mark = self.vm.roots.len();
        let scope = self.vm.dict(PyDict::new());
        self.vm.roots.push(scope);
        let m = self.vm.str(method);
        self.vm.dict_set_str(scope, "method", m);
        let p = self.vm.str(path);
        self.vm.dict_set_str(scope, "path", p);
        let q = self.vm.str(query);
        self.vm.dict_set_str(scope, "query_string", q);
        let b = self.vm.heap.alloc(Obj::Bytes(body.to_vec()));
        self.vm.dict_set_str(scope, "body", b);
        let called = self.vm.call(self.handle, &[scope], &[]);
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
        match self.drive_kind(value, Kind::Request)? {
            // The common case, and the one §4.4 budgets: an `async def` that never suspends
            // costs one resume, no token, no dict and no loop turn.
            Progress::Done(a) => Ok(Started::Done(a)),
            Progress::Waiting(fut) => {
                let token = self.next_token;
                self.next_token = self.next_token.wrapping_add(1).max(1);
                // Registering roots both: until these two lines run, the coroutine and the
                // future it waits on are reachable from Rust locals only, which the collector
                // cannot see. Nothing between here and there may call into Python.
                let key = self.vm.int(token as i64);
                self.vm.dict_set(self.coros, key, value);
                self.vm.dict_set(self.waits, key, fut);
                self.kinds.insert(token, Kind::Request);
                Ok(Started::Running(token))
            }
        }
    }

    /// One resume of a coroutine. The value is rooted for the duration: `gen_resume` runs
    /// Python, Python can collect, and a coroutine reachable only from a Rust local is not
    /// reachable at all.
    fn drive_kind(&mut self, coro: Value, kind: Kind) -> Result<Progress, String> {
        let mark = self.vm.roots.len();
        self.vm.roots.push(coro);
        let mut returned = Value::NONE;
        let stepped = self.vm.gen_resume(coro, Value::NONE, None, &mut returned);
        let out = match stepped {
            Ok(None) => match kind {
                Kind::Request => self.answer(returned).map(Progress::Done),
                Kind::Chunk => self.chunk(returned).map(Progress::Done),
            },
            Ok(Some(yielded)) => Ok(Progress::Waiting(yielded)),
            Err(exc) => Err(fault(&mut self.vm, exc)),
        };
        self.vm.roots.truncate(mark);
        out
    }

    /// Has the future this request waits on settled? If so, resume; if not, say so and let
    /// the caller yield to tokio.
    pub fn poll(&mut self, token: u32) -> Result<Poll, String> {
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
        let kind = self.kinds.get(&token).copied().unwrap_or(Kind::Request);
        match self.drive_kind(coro, kind) {
            Ok(Progress::Done(a)) => {
                self.forget(token);
                Ok(Poll::Done(a))
            }
            Ok(Progress::Waiting(fut)) => {
                // `drive` ran Python, so re-derive the key rather than reuse the one from
                // the top of this function.
                let key = self.vm.int(token as i64);
                self.vm.dict_set(self.waits, key, fut);
                Ok(Poll::Advanced)
            }
            Err(e) => {
                self.forget(token);
                Err(e)
            }
        }
    }

    fn give_up(&mut self, token: u32, exc: Value) -> String {
        self.forget(token);
        fault(&mut self.vm, exc)
    }

    fn forget(&mut self, token: u32) {
        let key = self.vm.int(token as i64);
        self.vm.dict_remove(self.coros, key);
        self.vm.dict_remove(self.waits, key);
        self.kinds.remove(&token);
    }

    /// One turn of the loop: settle any `_host` future whose deadline passed, then run the
    /// asyncio loop's own turn. The answer is how long there is to wait before the next
    /// thing is due, or `None` when nothing at all is scheduled — which, with a request
    /// still in flight, means it awaited something nobody will ever complete.
    pub fn pump(&mut self) -> Result<Option<f64>, String> {
        if let Err(exc) = hostmod::expire(&mut self.vm) {
            return Err(fault(&mut self.vm, exc));
        }
        let turned = self.vm.call(self.run_once, &[], &[]);
        let loop_delay = match turned {
            Ok(v) if v.is_none() => None,
            Ok(v) => self.vm.as_f64(v),
            Err(exc) => return Err(fault(&mut self.vm, exc)),
        };
        // ⚠ After the turn, not before: `run_once` can start a task that immediately awaits
        // `_host.sleep`, and a deadline read beforehand would miss it and call the request
        // deadlocked. That is what it did.
        let host_delay = hostmod::next_delay(&self.vm);
        Ok(match (loop_delay, host_delay) {
            (Some(a), Some(b)) => Some(a.min(b)),
            (a, b) => a.or(b),
        })
    }

    /// `App.handle` answers `(status, headers, body)`. Anything else is the app's bug, and
    /// saying so precisely is worth more than a generic 500.
    ///
    /// A body that is neither `bytes` nor `str` is a chunk source (`frontage_api.Stream`):
    /// it is registered under a token and the server pulls from it. That is the only signal
    /// — there is no flag — because a `Chunks` is the one thing a handler can put there that
    /// is not a body.
    fn answer(&mut self, value: Value) -> Result<Answer, String> {
        let items: Vec<Value> = match self.vm.heap.get(value) {
            Obj::Tuple(items) | Obj::List(items) => items.clone(),
            other => return Err(format!("App.handle must answer a 3-tuple, got {}", other.kind())),
        };
        if items.len() != 3 {
            return Err(format!("App.handle must answer (status, headers, body), got {} items", items.len()));
        }
        let status = match self.vm.as_i64(items[0]) {
            Some(n) if (100..=599).contains(&n) => n as u16,
            _ => return Err("App.handle: the status is not an HTTP status".into()),
        };
        let mut headers = Vec::new();
        let pairs: Vec<Value> = match self.vm.heap.get(items[1]) {
            Obj::List(v) | Obj::Tuple(v) => v.clone(),
            _ => return Err("App.handle: the headers are not a list".into()),
        };
        for pair in pairs {
            let parts: Vec<Value> = match self.vm.heap.get(pair) {
                Obj::Tuple(v) | Obj::List(v) if v.len() == 2 => v.clone(),
                _ => return Err("App.handle: a header is not a (name, value) pair".into()),
            };
            let name = self.vm.as_str(parts[0]).map(|s| s.to_owned());
            let value = self.vm.as_str(parts[1]).map(|s| s.to_owned());
            match (name, value) {
                (Some(n), Some(v)) => headers.push((n, v)),
                _ => return Err("App.handle: a header name or value is not a string".into()),
            }
        }
        let body = match self.vm.heap.get(items[2]) {
            Obj::Bytes(b) => Body::Whole(b.clone()),
            _ => match self.vm.as_str(items[2]) {
                Some(s) => Body::Whole(s.as_bytes().to_vec()),
                None => Body::Stream(self.register_stream(items[2])),
            },
        };
        Ok(Answer { status, headers, body })
    }

    /// Keep a chunk source alive under a token. Rooted in a Python dict, like everything else
    /// here that outlives one call.
    fn register_stream(&mut self, source: Value) -> u32 {
        let token = self.next_token;
        self.next_token = self.next_token.wrapping_add(1).max(1);
        let key = self.vm.int(token as i64);
        self.vm.dict_set(self.streams, key, source);
        token
    }

    /// Ask a registered source for its next chunk. `Started::Done` with an empty answer and
    /// status 0 means the stream is finished.
    pub fn chunk_next(&mut self, stream: u32) -> Result<Started, String> {
        let key = self.vm.int(stream as i64);
        let source = match self.vm.dict_get(self.streams, key) {
            Some(s) => s,
            None => return Err("no such stream".into()),
        };
        let mark = self.vm.roots.len();
        self.vm.roots.push(source);
        let next = {
            let name = self.vm.intern("next");
            match self.vm.get_attr(source, name) {
                Ok(f) => self.vm.call(f, &[], &[]),
                Err(exc) => Err(exc),
            }
        };
        let out = match next {
            Ok(v) => self.after_call_chunk(v),
            Err(exc) => Err(fault(&mut self.vm, exc)),
        };
        self.vm.roots.truncate(mark);
        out
    }

    fn after_call_chunk(&mut self, value: Value) -> Result<Started, String> {
        let is_coroutine = match self.vm.heap.get(value) {
            Obj::Generator(g) => g.is_coroutine,
            _ => false,
        };
        if !is_coroutine {
            return self.chunk(value).map(Started::Done);
        }
        match self.drive_chunk(value)? {
            Some(answer) => Ok(Started::Done(answer)),
            None => {
                let token = self.next_token;
                self.next_token = self.next_token.wrapping_add(1).max(1);
                let key = self.vm.int(token as i64);
                self.vm.dict_set(self.coros, key, value);
                if let Some(fut) = self.pending_wait.take() {
                    self.vm.dict_set(self.waits, key, fut);
                }
                self.kinds.insert(token, Kind::Chunk);
                Ok(Started::Running(token))
            }
        }
    }

    /// One resume of a chunk coroutine: `Some` when it finished, `None` when it suspended.
    fn drive_chunk(&mut self, coro: Value) -> Result<Option<Answer>, String> {
        match self.drive_kind(coro, Kind::Chunk)? {
            Progress::Done(answer) => Ok(Some(answer)),
            Progress::Waiting(fut) => {
                self.pending_wait = Some(fut);
                Ok(None)
            }
        }
    }

    /// `None` from the source ends the stream, and is spelled here as status 0.
    fn chunk(&mut self, value: Value) -> Result<Answer, String> {
        if value.is_none() {
            return Ok(Answer { status: 0, headers: Vec::new(), body: Body::Whole(Vec::new()) });
        }
        let body = match self.vm.heap.get(value) {
            Obj::Bytes(b) => b.clone(),
            _ => match self.vm.as_str(value) {
                Some(s) => s.as_bytes().to_vec(),
                None => return Err("a stream chunk must be bytes or str".into()),
            },
        };
        Ok(Answer { status: 200, headers: Vec::new(), body: Body::Whole(body) })
    }

    pub fn forget_stream(&mut self, stream: u32) {
        let key = self.vm.int(stream as i64);
        self.vm.dict_remove(self.streams, key);
    }

    /// Let the collector run between requests rather than inside one.
    pub fn settle_heap(&mut self) {
        self.vm.maybe_collect();
    }
}
