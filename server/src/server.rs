//! The axum side: one worker thread, one `Vm`, one current-thread runtime, sharing nothing.
//!
//! **Thread-per-core is what makes a suspended handler correct.** A coroutine that awaits
//! belongs to the VM it started on, so the task that resumes it must not migrate. Each worker
//! is an OS thread with a `current_thread` tokio runtime of its own, accepting from a clone of
//! one listener, and a task on such a runtime never moves. That is also the picture
//! `PLAN.md` §4.1 draws, and it is the difference from the first spike, which ran on the
//! multi-thread runtime and was correct only while nothing suspended.
//!
//! **The VM is never borrowed across an `.await`.** Every access goes through `with_app`, a
//! synchronous closure; only `Send` values (the body, a token, an `Answer`) cross a suspension
//! point. That keeps axum's bounds satisfiable without a `LocalSet`, so the router stays a
//! plain `axum::Router` — which is what `hive-server` takes in §4.8.
//!
//! The one-crossing rule of §4.4 is what this file exists to keep: axum parses the request,
//! the body arrives whole, Python is entered once, and the response leaves in one piece. A
//! handler that does not suspend never touches the event loop at all.

use crate::app::{Answer, App, Poll, Started};
use axum::extract::Request;
use axum::http::{header, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Router;
use std::cell::RefCell;
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::Duration;

/// Where the app module lives, for the workers that have not built their VM yet.
static SOURCE: OnceLock<(PathBuf, String, bool)> = OnceLock::new();

/// A request body past this is refused rather than buffered.
const MAX_BODY: usize = 8 * 1024 * 1024;

/// How long a suspended request may sleep before it looks at the loop again. The loop's own
/// answer is usually right, but another request on this thread can settle *this* one's future
/// meanwhile, and a long timer elsewhere would otherwise hold this answer back. A per-thread
/// notification removes the cap; it is not worth the machinery until a profile asks.
const MAX_PARK: Duration = Duration::from_millis(5);

thread_local! {
    static APP: RefCell<Option<App>> = const { RefCell::new(None) };
}

pub struct Config {
    pub dir: PathBuf,
    pub module: String,
    pub addr: String,
    pub workers: usize,
    /// Collect at every safe point. Slow on purpose; it is what proves the rooting.
    pub stress: bool,
}

/// Load the app once here to fail loudly at startup, then hand a clone of the listener to
/// every worker.
pub fn serve(config: Config) -> Result<(), String> {
    let _ = SOURCE.set((config.dir.clone(), config.module.clone(), config.stress));
    let paths = App::load(config.dir.clone(), &config.module, config.stress)?.paths();

    let listener = std::net::TcpListener::bind(&config.addr).map_err(|e| format!("{}: {e}", config.addr))?;
    listener.set_nonblocking(true).map_err(|e| e.to_string())?;
    let local = listener.local_addr().map(|a| a.to_string()).unwrap_or_else(|_| config.addr.clone());
    println!("frontage-api: {} on http://{local}, {} worker(s){}", config.module, config.workers,
             if config.stress { ", GC stress" } else { "" });
    for p in &paths {
        println!("  {p}");
    }

    let mut threads = Vec::with_capacity(config.workers);
    for i in 0..config.workers {
        let socket = listener.try_clone().map_err(|e| e.to_string())?;
        let worker = std::thread::Builder::new()
            .name(format!("worker-{i}"))
            .spawn(move || worker(socket))
            .map_err(|e| e.to_string())?;
        threads.push(worker);
    }
    for t in threads {
        match t.join() {
            Ok(Ok(())) => {}
            Ok(Err(e)) => return Err(e),
            Err(_) => return Err("a worker panicked".into()),
        }
    }
    Ok(())
}

fn worker(socket: std::net::TcpListener) -> Result<(), String> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| format!("tokio: {e}"))?;
    runtime.block_on(async move {
        let listener = tokio::net::TcpListener::from_std(socket).map_err(|e| e.to_string())?;
        axum::serve(listener, Router::new().fallback(handle)).await.map_err(|e| e.to_string())
    })
}

async fn handle(request: Request) -> Response {
    let path = request.uri().path().to_owned();
    // The body is read before Python is entered, so the VM is never borrowed across an await
    // and the handler holds nothing but `Send` values over one.
    let body = match axum::body::to_bytes(request.into_body(), MAX_BODY).await {
        Ok(b) => b,
        Err(_) => return (StatusCode::PAYLOAD_TOO_LARGE, "body too large").into_response(),
    };
    let started = match with_app(|app| app.start(&path, &body)) {
        Ok(Some(r)) => r,
        Ok(None) => return (StatusCode::NOT_FOUND, "no route").into_response(),
        Err(e) => return fault(e),
    };
    let response = match started {
        Ok(Started::Done(answer)) => respond(answer),
        Ok(Started::Running(token)) => park(token).await,
        Err(text) => fault(text),
    };
    // Collect between requests rather than inside one.
    let _ = with_app(|app| app.settle_heap());
    response
}

/// Pump this thread's loop until the request's coroutine finishes, yielding to tokio in
/// between so the worker keeps answering other connections.
async fn park(token: u32) -> Response {
    loop {
        // ⚠ Pump, *then* poll, and never the other way round. A turn of the loop settles the
        // future and reports "nothing scheduled" in the same breath — the timer it was
        // waiting for is the last one — so polling before the pump and reading `None` as a
        // deadlock declares every awaiting handler stuck. It did, until this order.
        let delay = match with_app(|app| app.pump()) {
            Ok(Ok(d)) => d,
            Ok(Err(text)) => return fault(text),
            Err(e) => return fault(e),
        };
        match with_app(|app| app.poll(token)) {
            Ok(Ok(Poll::Done(answer))) => return respond(answer),
            // The coroutine moved: it may have awaited something new, so `delay` is stale.
            // Go round and measure again rather than judge the request on an old answer.
            Ok(Ok(Poll::Advanced)) => continue,
            Ok(Ok(Poll::Blocked)) => {}
            Ok(Err(text)) => return fault(text),
            Err(e) => return fault(e),
        }
        match delay {
            // Nothing is scheduled, and the poll above did not finish this request: it
            // awaited something no timer and no host future will ever settle. Say so rather
            // than hang.
            None => return fault("this handler is waiting on something nothing will complete".into()),
            Some(seconds) if seconds > 0.0 => {
                tokio::time::sleep(Duration::from_secs_f64(seconds).min(MAX_PARK)).await;
            }
            Some(_) => tokio::task::yield_now().await,
        }
    }
}

fn respond(answer: Answer) -> Response {
    ([(header::CONTENT_TYPE, answer.content_type)], answer.body).into_response()
}

/// This thread's VM, built on first use.
fn with_app<T>(f: impl FnOnce(&mut App) -> T) -> Result<T, String> {
    APP.with(|cell| {
        let mut slot = cell.borrow_mut();
        if slot.is_none() {
            let (dir, module, stress) = SOURCE.get().ok_or("serve() was not called")?;
            *slot = Some(App::load(dir.clone(), module, *stress)?);
        }
        Ok(f(slot.as_mut().expect("just loaded")))
    })
}

/// A traceback is the body while this is a spike: there is no user to protect yet and every
/// failure here is ours. `PLAN.md` §4.8's problem JSON replaces it.
fn fault(text: String) -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, text).into_response()
}
