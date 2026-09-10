//! `_http`: what a handler needs to talk to anything at all (`API.md` §6.4).
//!
//! The shape is `_host`'s, and deliberately so: a call returns an asyncio future, a tokio
//! task settles it, and the pump is what carries the answer across. Nothing here borrows the
//! `Vm` across an `.await` — the spawned task holds only `Send` values (a URL, a body, a
//! token) and posts its result down a channel the pump drains.
//!
//! **The pending futures are rooted in the module's own `_pending` dict**, never in a Rust
//! map, for the reason `hostmod` gives: a `Value` the collector cannot see is a `Value` that
//! can be freed while a request is still in flight.
//!
//! A **streaming** response is a token rather than a value. Its `Response` stays in Rust,
//! owned by a task that pulls one chunk at a time into a channel of capacity one, so a slow
//! reader slows the transfer instead of buffering a model's whole answer. `chunk(token)`
//! takes that channel's receiver out of the map, awaits one item on it in a task of its own,
//! and the pump puts it back — which is how a future can be awaited without the interpreter
//! ever being inside an `await`.
//!
//! ⚠ **An in-flight request must make the pump wait for it.** `park_value` reads "no deadline
//! anywhere" as a handler awaiting something nobody will complete, so a request in flight has
//! to answer a delay of its own or the first `await client.get(...)` is declared a deadlock.
//! `next_delay` reports a poll interval while anything is outstanding; a per-thread
//! notification would remove the poll, and is the same machinery `server.rs`'s `MAX_PARK`
//! note says is not worth it until a profile asks.

use frontage_vm::builtins::{arg, kwarg, opt};
use frontage_vm::dict::PyDict;
use frontage_vm::object::Obj;
use frontage_vm::value::Value;
use frontage_vm::vm::{PyResult, Vm};
use std::cell::RefCell;
use std::collections::HashMap;
use std::time::Duration;
use tokio::sync::mpsc;

/// How often the pump looks for a completed request while one is outstanding. Small enough
/// that a streamed token is not held back visibly, large enough that a parked handler is not
/// a spin loop.
const POLL: f64 = 0.001;

/// One chunk of a streamed body, or the end of it.
type Piece = Result<Option<Vec<u8>>, String>;

struct Resp {
    status: u16,
    headers: Vec<(String, String)>,
    /// The whole body, or `None` when this was a streaming request and `stream` carries the
    /// token to pull from instead.
    body: Option<Vec<u8>>,
    stream: Option<u64>,
}

/// What a task posts back to the pump.
enum Done {
    Sent { token: u64, result: Result<Resp, String> },
    Chunk { token: u64, stream: u64, rx: mpsc::Receiver<Piece>, result: Piece },
}

thread_local! {
    static CLIENT: RefCell<Option<reqwest::Client>> = const { RefCell::new(None) };
    static CHANNEL: RefCell<Option<(mpsc::UnboundedSender<Done>, mpsc::UnboundedReceiver<Done>)>> =
        const { RefCell::new(None) };
    /// Streams idle between pulls, each holding its own receiver. A token that is absent is
    /// either finished, closed, or currently being pulled from.
    static STREAMS: RefCell<HashMap<u64, mpsc::Receiver<Piece>>> = RefCell::new(HashMap::new());
    /// How many requests and pulls are outstanding, which is what `next_delay` answers from.
    static INFLIGHT: RefCell<usize> = const { RefCell::new(0) };
    static NEXT: RefCell<u64> = const { RefCell::new(1) };
}

pub fn install(vm: &mut Vm) {
    vm.builtin_modules.insert("_http", init);
}

fn init(vm: &mut Vm) -> PyResult {
    let m = vm.new_module("_http");
    let d = vm.module_dict(m);
    let pending = vm.dict(PyDict::new());
    vm.dict_set_str(d, "_pending", pending);
    for (name, f) in [
        ("request", h_request as frontage_vm::object::NativeFn),
        ("chunk", h_chunk),
        ("close", h_close),
    ] {
        let nf = vm.native(name, f);
        vm.dict_set_str(d, name, nf);
    }
    Ok(m)
}

fn token() -> u64 {
    NEXT.with(|n| {
        let mut n = n.borrow_mut();
        *n += 1;
        *n
    })
}

fn sender() -> mpsc::UnboundedSender<Done> {
    CHANNEL.with(|c| {
        let mut c = c.borrow_mut();
        if c.is_none() {
            *c = Some(mpsc::unbounded_channel());
        }
        c.as_ref().expect("just made").0.clone()
    })
}

fn client(vm: &mut Vm) -> Result<reqwest::Client, Value> {
    CLIENT.with(|c| {
        let mut c = c.borrow_mut();
        if c.is_none() {
            // No pool timeout of its own: the connection pool is per thread, and a worker
            // that keeps a connection to the model's host open between requests is the
            // point of having a client at all rather than one per call.
            let built = reqwest::Client::builder()
                .user_agent(concat!("frontage-api/", env!("CARGO_PKG_VERSION")))
                .build();
            match built {
                Ok(client) => *c = Some(client),
                Err(e) => return Err(vm.runtime_error(format!("_http: no client: {e}"))),
            }
        }
        Ok(c.as_ref().expect("just built").clone())
    })
}

fn pending_dict(vm: &mut Vm) -> PyResult<Value> {
    let m = vm.import_module("_http")?;
    let d = vm.module_dict(m);
    match vm.dict_get_str(d, "_pending") {
        Some(p) => Ok(p),
        None => Err(vm.runtime_error("_http._pending is missing")),
    }
}

/// A new asyncio future, rooted under `token` until it settles.
fn future(vm: &mut Vm, token: u64) -> PyResult<Value> {
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
    let pending = pending_dict(vm)?;
    let key = vm.int(token as i64);
    vm.dict_set(pending, key, fut);
    INFLIGHT.with(|n| *n.borrow_mut() += 1);
    Ok(fut)
}

fn bytes_of(vm: &Vm, v: Value) -> Option<Vec<u8>> {
    if !v.is_obj() {
        return None;
    }
    match vm.heap.get(v) {
        Obj::Bytes(b) | Obj::ByteArray(b) => Some(b.clone()),
        Obj::Str(s) => Some(s.s.as_bytes().to_vec()),
        _ => None,
    }
}

/// `[(name, value), …]` out of a list or tuple of pairs of strings.
fn headers_of(vm: &mut Vm, v: Value) -> PyResult<Vec<(String, String)>> {
    let items = match vm.heap.get(v) {
        Obj::List(items) | Obj::Tuple(items) => items.clone(),
        _ => return Err(vm.type_error("_http: headers must be a list of (name, value) pairs")),
    };
    let mut out = Vec::with_capacity(items.len());
    for item in items {
        let pair = match vm.heap.get(item) {
            Obj::List(p) | Obj::Tuple(p) => p.clone(),
            _ => return Err(vm.type_error("_http: headers must be a list of (name, value) pairs")),
        };
        if pair.len() != 2 {
            return Err(vm.type_error("_http: a header is a (name, value) pair"));
        }
        let (Some(name), Some(value)) = (vm.as_str(pair[0]).map(str::to_owned), vm.as_str(pair[1]).map(str::to_owned))
        else {
            return Err(vm.type_error("_http: a header name and value are both str"));
        };
        out.push((name, value));
    }
    Ok(out)
}

/// `await _http.request(method, url, headers=[], body=None, timeout=None, stream=False)`.
///
/// Answers `(status, headers, body)` — or `(status, headers, token)` with `stream=True`,
/// where the token is what `chunk` pulls from.
fn h_request(vm: &mut Vm, args: &[Value], kwargs: &[(Value, Value)]) -> PyResult {
    let method = arg(vm, args, 0, "request")?;
    let Some(method) = vm.as_str(method).map(str::to_owned) else {
        return Err(vm.type_error("request(method, url): method is a str"));
    };
    let url = arg(vm, args, 1, "request")?;
    let Some(url) = vm.as_str(url).map(str::to_owned) else {
        return Err(vm.type_error("request(method, url): url is a str"));
    };
    let headers = match opt(args, 2).or_else(|| kwarg(vm, kwargs, "headers")) {
        Some(v) if !v.is_none() => headers_of(vm, v)?,
        _ => Vec::new(),
    };
    let body = match opt(args, 3).or_else(|| kwarg(vm, kwargs, "body")) {
        Some(v) if !v.is_none() => match bytes_of(vm, v) {
            Some(b) => Some(b),
            None => return Err(vm.type_error("request(..., body=): bytes or str")),
        },
        _ => None,
    };
    let timeout = match opt(args, 4).or_else(|| kwarg(vm, kwargs, "timeout")) {
        Some(v) if !v.is_none() => vm.as_f64(v),
        _ => None,
    };
    let stream = match opt(args, 5).or_else(|| kwarg(vm, kwargs, "stream")) {
        Some(v) => vm.truthy(v)?,
        None => false,
    };

    let method = match reqwest::Method::from_bytes(method.as_bytes()) {
        Ok(m) => m,
        Err(_) => return Err(vm.value_error(format!("request(): {method} is not an HTTP method"))),
    };
    let client = client(vm)?;
    let token = token();
    let fut = future(vm, token)?;
    let tx = sender();
    tokio::spawn(async move {
        let mut request = client.request(method, &url);
        for (name, value) in headers {
            request = request.header(name, value);
        }
        if let Some(body) = body {
            request = request.body(body);
        }
        if let Some(seconds) = timeout {
            request = request.timeout(Duration::from_secs_f64(seconds.max(0.0)));
        }
        let result = match request.send().await {
            Err(e) => Err(describe(&e)),
            Ok(response) => {
                let status = response.status().as_u16();
                let headers = response
                    .headers()
                    .iter()
                    .map(|(n, v)| (n.as_str().to_owned(), v.to_str().unwrap_or("").to_owned()))
                    .collect();
                if stream {
                    // Capacity one: the transfer runs exactly one chunk ahead of the reader.
                    let (chunks, rx) = mpsc::channel::<Piece>(1);
                    let stream_token = token;
                    tokio::spawn(pull(response, chunks));
                    STREAMS.with(|s| s.borrow_mut().insert(stream_token, rx));
                    Ok(Resp { status, headers, body: None, stream: Some(stream_token) })
                } else {
                    match response.bytes().await {
                        Ok(body) => Ok(Resp { status, headers, body: Some(body.to_vec()), stream: None }),
                        Err(e) => Err(describe(&e)),
                    }
                }
            }
        };
        let _ = tx.send(Done::Sent { token, result });
    });
    Ok(fut)
}

/// The task that owns a streaming `Response`. It stops the moment the reader goes away,
/// because the send fails — a client that hangs up is not a reason to download the rest.
async fn pull(mut response: reqwest::Response, chunks: mpsc::Sender<Piece>) {
    loop {
        match response.chunk().await {
            Ok(Some(bytes)) => {
                if chunks.send(Ok(Some(bytes.to_vec()))).await.is_err() {
                    return;
                }
            }
            Ok(None) => {
                let _ = chunks.send(Ok(None)).await;
                return;
            }
            Err(e) => {
                let _ = chunks.send(Err(describe(&e))).await;
                return;
            }
        }
    }
}

/// `await _http.chunk(token)`: the next piece of a streamed body, or `None` at the end.
fn h_chunk(vm: &mut Vm, args: &[Value], _kwargs: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "chunk")?;
    let Some(stream) = vm.as_i64(v).map(|i| i as u64) else {
        return Err(vm.type_error("chunk(token): token is an int"));
    };
    let token = token();
    let fut = future(vm, token)?;
    let Some(rx) = STREAMS.with(|s| s.borrow_mut().remove(&stream)) else {
        // Finished, closed, or pulled from twice at once. `None` is the honest answer to the
        // first two and the third is the caller's bug, which the Python layer prevents.
        settle_now(vm, token, Ok(None))?;
        return Ok(fut);
    };
    let tx = sender();
    tokio::spawn(async move {
        let mut rx = rx;
        let result = match rx.recv().await {
            Some(piece) => piece,
            None => Ok(None),
        };
        let _ = tx.send(Done::Chunk { token, stream, rx, result });
    });
    Ok(fut)
}

/// `_http.close(token)`: drop a streamed body nobody is going to read. The task that owns the
/// response ends on its next send.
fn h_close(vm: &mut Vm, args: &[Value], _kwargs: &[(Value, Value)]) -> PyResult {
    let v = arg(vm, args, 0, "close")?;
    let Some(stream) = vm.as_i64(v).map(|i| i as u64) else {
        return Err(vm.type_error("close(token): token is an int"));
    };
    STREAMS.with(|s| s.borrow_mut().remove(&stream));
    Ok(Value::NONE)
}

/// reqwest's `Display` is one line about the outermost error, so the cause is what says
/// *why* — "error sending request for url" alone has sent people looking in the wrong place.
fn describe(e: &reqwest::Error) -> String {
    let mut text = e.to_string();
    let mut source = std::error::Error::source(e);
    while let Some(inner) = source {
        text.push_str(": ");
        text.push_str(&inner.to_string());
        source = inner.source();
    }
    if e.is_timeout() {
        text.push_str(" (timeout)");
    }
    text
}

fn take_future(vm: &mut Vm, token: u64) -> PyResult<Option<Value>> {
    let pending = pending_dict(vm)?;
    let key = vm.int(token as i64);
    let fut = vm.dict_remove(pending, key);
    if fut.is_some() {
        INFLIGHT.with(|n| {
            let mut n = n.borrow_mut();
            *n = n.saturating_sub(1);
        });
    }
    Ok(fut)
}

fn resolve(vm: &mut Vm, fut: Value, value: Value) -> PyResult<()> {
    let k = vm.intern("set_result");
    let f = vm.get_attr(fut, k)?;
    vm.call(f, &[value], &[])?;
    Ok(())
}

fn reject(vm: &mut Vm, fut: Value, text: &str) -> PyResult<()> {
    let class = if text.ends_with("(timeout)") { vm.t.timeout_error } else { vm.t.os_error };
    let exc = vm.exception(class, text.to_owned());
    let k = vm.intern("set_exception");
    let f = vm.get_attr(fut, k)?;
    vm.call(f, &[exc], &[])?;
    Ok(())
}

fn settle_now(vm: &mut Vm, token: u64, piece: Piece) -> PyResult<()> {
    if let Some(fut) = take_future(vm, token)? {
        settle_piece(vm, fut, piece)?;
    }
    Ok(())
}

fn settle_piece(vm: &mut Vm, fut: Value, piece: Piece) -> PyResult<()> {
    match piece {
        Ok(Some(bytes)) => {
            let v = vm.heap.alloc(Obj::Bytes(bytes));
            resolve(vm, fut, v)
        }
        Ok(None) => resolve(vm, fut, Value::NONE),
        Err(text) => reject(vm, fut, &text),
    }
}

/// Settle every request and pull that finished since the last turn. Called by the pump,
/// beside `hostmod::expire`.
pub fn settle(vm: &mut Vm) -> PyResult<()> {
    loop {
        let done = CHANNEL.with(|c| {
            let mut c = c.borrow_mut();
            match c.as_mut() {
                Some((_, rx)) => rx.try_recv().ok(),
                None => None,
            }
        });
        let Some(done) = done else { return Ok(()) };
        match done {
            Done::Sent { token, result } => {
                let Some(fut) = take_future(vm, token)? else {
                    // Nobody is waiting any more; a stream it opened would leak, so drop it.
                    if let Ok(Resp { stream: Some(s), .. }) = result {
                        STREAMS.with(|m| m.borrow_mut().remove(&s));
                    }
                    continue;
                };
                match result {
                    Ok(resp) => {
                        let status = vm.int(resp.status as i64);
                        let items: Vec<Value> = resp
                            .headers
                            .iter()
                            .map(|(n, v)| {
                                let n = vm.str(n);
                                let v = vm.str(v);
                                vm.tuple(vec![n, v])
                            })
                            .collect();
                        let headers = vm.list(items);
                        let body = match (resp.body, resp.stream) {
                            (Some(bytes), _) => vm.heap.alloc(Obj::Bytes(bytes)),
                            (None, Some(token)) => vm.int(token as i64),
                            (None, None) => Value::NONE,
                        };
                        let answer = vm.tuple(vec![status, headers, body]);
                        resolve(vm, fut, answer)?;
                    }
                    Err(text) => reject(vm, fut, &text)?,
                }
            }
            Done::Chunk { token, stream, rx, result } => {
                // The receiver goes back before the future settles: the handler this wakes
                // can ask for the next chunk inside the same turn.
                let ended = !matches!(result, Ok(Some(_)));
                if !ended {
                    STREAMS.with(|s| s.borrow_mut().insert(stream, rx));
                }
                settle_now(vm, token, result)?;
            }
        }
    }
}

/// How long the pump may wait before looking again, while anything is in flight.
pub fn next_delay() -> Option<f64> {
    if INFLIGHT.with(|n| *n.borrow()) > 0 {
        Some(POLL)
    } else {
        None
    }
}
