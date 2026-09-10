//! The VM side: load a Python module, hold its routes, call one.
//!
//! One `App` is one `Vm`, and a `Vm` is not `Send` — which is the design and not a
//! limitation (`PLAN.md` §4.1). Every worker thread owns one, they share nothing, and there
//! is no lock anywhere because there is nothing to lock.
//!
//! **Values held in Rust between calls must be rooted.** The collector is precise and traces
//! the stack, the frames, the module table and `vm.roots`; a `Value` sitting in a Rust local
//! is reachable from none of those. So anything allocated here is pushed onto `vm.roots`
//! before the next call into Python and truncated back after — the mechanism the VM already
//! documents as "temporary roots for native code that calls back into Python".

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
}

/// What a handler answered: bytes and the content type to send them with.
pub struct Answer {
    pub body: Vec<u8>,
    pub content_type: &'static str,
}

impl App {
    /// Import `module` from `dir` and read its `ROUTES` table.
    pub fn load(dir: PathBuf, module: &str) -> Result<App, String> {
        let mut vm = Vm::new(Box::new(StdHost::new(vec![dir])));
        frontage_compile::install(&mut vm);
        let m = match vm.import_module(module) {
            Ok(m) => m,
            Err(exc) => return Err(vm.format_exception(exc)),
        };
        // The module is in `vm.modules`, so it and everything it names stay reachable: the
        // handler values below need no root of their own.
        let key = vm.intern("ROUTES");
        let table = match vm.get_attr(m, key) {
            Ok(t) => t,
            Err(exc) => return Err(vm.format_exception(exc)),
        };
        let pairs = match vm.take_dict_snapshot(table) {
            Ok(p) => p,
            Err(exc) => return Err(vm.format_exception(exc)),
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
        Ok(App { vm, routes })
    }

    pub fn paths(&self) -> Vec<&str> {
        self.routes.iter().map(|(p, _)| p.as_str()).collect()
    }

    /// Call the handler for `path` with the request body. `None` when nothing matches, which
    /// the caller turns into a 404.
    pub fn dispatch(&mut self, path: &str, body: &[u8]) -> Option<Result<Answer, String>> {
        let handler = self.routes.iter().find(|(p, _)| p == path).map(|(_, h)| *h)?;
        Some(self.call(handler, body))
    }

    fn call(&mut self, handler: Value, body: &[u8]) -> Result<Answer, String> {
        let mark = self.vm.roots.len();
        let arg = self.vm.heap.alloc(Obj::Bytes(body.to_vec()));
        self.vm.roots.push(arg);
        let result = self.vm.call(handler, &[arg], &[]);
        let out = match result {
            Ok(v) => self.settle(v),
            Err(exc) => Err(self.vm.format_exception(exc)),
        };
        self.vm.roots.truncate(mark);
        out
    }

    /// A handler may be `def` or `async def`. A coroutine that never suspends finishes on its
    /// first resume, which is the whole cost of `async` on this path: one `gen_resume` and no
    /// loop turn at all. One that *does* suspend needs the host future hook of `PLAN.md`
    /// §4.3, which is the next commit; until then it is an error rather than a hang.
    fn settle(&mut self, value: Value) -> Result<Answer, String> {
        let is_coroutine = match self.vm.heap.get(value) {
            Obj::Generator(g) => g.is_coroutine,
            _ => false,
        };
        if !is_coroutine {
            return self.answer(value);
        }
        let mark = self.vm.roots.len();
        self.vm.roots.push(value);
        let mut returned = Value::NONE;
        let stepped = self.vm.gen_resume(value, Value::NONE, None, &mut returned);
        let out = match stepped {
            Ok(None) => self.answer(returned),
            Ok(Some(_)) => Err("this handler awaited: the host future hook is not written yet \
                                (PLAN.md §4.3)"
                .into()),
            Err(exc) => Err(self.vm.format_exception(exc)),
        };
        self.vm.roots.truncate(mark);
        out
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
