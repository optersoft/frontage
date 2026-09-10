//! The axum side: a `Vm` per worker thread, and one crossing per request.
//!
//! ⚠ **The spike runs on tokio's multi-thread runtime with the VM in a thread-local, and that
//! is only correct while no handler suspends.** A task may resume on another thread after an
//! `.await`, and there it would find a *different* `Vm`. Today that is harmless: every worker
//! holds an identical copy of the app, nothing Python-side lives across an await, and only
//! `Send` values (the body bytes) cross one. The moment the host future hook of `PLAN.md`
//! §4.3 lands, a suspended coroutine belongs to *its* VM and the runtime becomes
//! thread-per-core — a `current_thread` runtime per worker over `SO_REUSEPORT`, which is
//! also the picture §4.1 draws. Do not add an await inside the VM before that change.
//!
//! The one-crossing rule of §4.4 is what this file exists to keep: axum parses the request,
//! the body arrives whole, Python is entered exactly once, and the response leaves in one
//! piece. A handler that does not suspend costs one `vm.call` and nothing else.

use crate::app::App;
use axum::body::Bytes;
use axum::extract::Request;
use axum::http::{header, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Router;
use std::cell::RefCell;
use std::path::PathBuf;
use std::sync::OnceLock;

/// Where the app module lives, for the workers that have not built their VM yet.
static SOURCE: OnceLock<(PathBuf, String)> = OnceLock::new();

/// A request body past this is refused rather than buffered.
const MAX_BODY: usize = 8 * 1024 * 1024;

thread_local! {
    static APP: RefCell<Option<App>> = const { RefCell::new(None) };
}

pub struct Config {
    pub dir: PathBuf,
    pub module: String,
    pub addr: String,
}

/// Load the app once on this thread to fail loudly at startup, then serve.
pub async fn serve(config: Config) -> Result<(), String> {
    let _ = SOURCE.set((config.dir.clone(), config.module.clone()));
    let paths = with_app(|app| app.paths().iter().map(|p| p.to_string()).collect::<Vec<_>>())?;
    let listener = tokio::net::TcpListener::bind(&config.addr)
        .await
        .map_err(|e| format!("{}: {e}", config.addr))?;
    let local = listener.local_addr().map(|a| a.to_string()).unwrap_or_else(|_| config.addr.clone());
    println!("frontage-api: {} on http://{local}", config.module);
    for p in &paths {
        println!("  {p}");
    }
    axum::serve(listener, Router::new().fallback(handle)).await.map_err(|e| e.to_string())
}

async fn handle(request: Request) -> Response {
    let path = request.uri().path().to_owned();
    // The body is read before Python is entered, so the VM is never borrowed across an await
    // and the handler holds nothing but `Send` values over one.
    let body = match axum::body::to_bytes(request.into_body(), MAX_BODY).await {
        Ok(b) => b,
        Err(_) => return (StatusCode::PAYLOAD_TOO_LARGE, "body too large").into_response(),
    };
    match with_app(|app| dispatch(app, &path, &body)) {
        Ok(response) => response,
        Err(e) => fault(e),
    }
}

fn dispatch(app: &mut App, path: &str, body: &Bytes) -> Response {
    let answered = match app.dispatch(path, body) {
        Some(r) => r,
        None => return (StatusCode::NOT_FOUND, "no route").into_response(),
    };
    let response = match answered {
        Ok(a) => ([(header::CONTENT_TYPE, a.content_type)], a.body).into_response(),
        // A traceback is the body while this is a spike: there is no user to protect yet and
        // every failure here is ours. `PLAN.md` §4.8's problem JSON replaces it.
        Err(text) => (StatusCode::INTERNAL_SERVER_ERROR, text).into_response(),
    };
    app.settle_heap();
    response
}

/// This thread's VM, built on first use.
fn with_app<T>(f: impl FnOnce(&mut App) -> T) -> Result<T, String> {
    APP.with(|cell| {
        let mut slot = cell.borrow_mut();
        if slot.is_none() {
            let (dir, module) = SOURCE.get().ok_or("serve() was not called")?;
            *slot = Some(App::load(dir.clone(), module)?);
        }
        Ok(f(slot.as_mut().expect("just loaded")))
    })
}

fn fault(text: String) -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, text).into_response()
}
