//! The axum side: one worker thread, one `Vm`, one current-thread runtime, sharing nothing.
//!
//! **Thread-per-core is what makes a suspended handler correct.** A coroutine that awaits
//! belongs to the VM it started on, so the task that resumes it must not migrate. Each worker
//! is an OS thread with a `current_thread` tokio runtime of its own, accepting from a clone of
//! one listener, and a task on such a runtime never moves. That is also the picture
//! `API.md` §4.1 draws, and it is the difference from the first spike, which ran on the
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

#[cfg(feature = "auth")]
use crate::auth::Auth;
use crate::app::{Answer, App, Body, Poll, Started};
use axum::extract::Request;
use axum::http::{HeaderName, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use axum::Router;
use std::cell::RefCell;
use std::path::PathBuf;
#[cfg(feature = "auth")]
use std::sync::Arc;
use std::sync::OnceLock;
use std::time::Duration;
use axum::body::Bytes;
use tokio::sync::mpsc;
use tokio_stream::wrappers::ReceiverStream;
use tower_http::services::ServeDir;

/// Where the app module lives, for the workers that have not built their VM yet.
static SOURCE: OnceLock<(PathBuf, String, Vec<PathBuf>, bool)> = OnceLock::new();

/// `App(static=…)`, resolved once at startup. Read by every worker, written by none.
static STATIC_DIR: OnceLock<Option<PathBuf>> = OnceLock::new();

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
    /// Extra module search directories, after the app's own. `frontage_api` and
    /// `frontage.schema` live wherever they are installed, and the runtime has no site-packages.
    pub search: Vec<PathBuf>,
    /// Collect at every safe point. Slow on purpose; it is what proves the rooting.
    pub stress: bool,
    /// `--auth google`: put a sign-in gate in front of everything, app and files alike.
    pub auth: bool,
    /// What names the session cookie and titles the login page. Default: the app's module.
    #[cfg_attr(not(feature = "auth"), allow(dead_code))]
    pub auth_label: Option<String>,
}

/// Load the app once here to fail loudly at startup, then hand a clone of the listener to
/// every worker.
pub fn serve(config: Config) -> Result<(), String> {
    let _ = SOURCE.set((config.dir.clone(), config.module.clone(), config.search.clone(), config.stress));
    let probe = App::load(config.dir.clone(), &config.module, &config.search, config.stress)?;
    let paths = probe.paths();
    // Relative to the app's own directory, which is where an author means it.
    let statics = probe.statics.as_ref().map(|d| config.dir.join(d));
    if let Some(dir) = &statics {
        if !dir.is_dir() {
            return Err(format!("static={}: not a directory", dir.display()));
        }
    }
    let _ = STATIC_DIR.set(statics);
    drop(probe);

    // The gate is read once here, not per worker: a failure is a configuration error and
    // must stop the process before it binds, rather than surface as one worker in four
    // serving a private site to nobody in particular.
    #[cfg(feature = "auth")]
    let auth: Option<Arc<Auth>> = if config.auth {
        let label = config.auth_label.clone().unwrap_or_else(|| config.module.clone());
        Some(Arc::new(Auth::from_env(&label, &config.dir)?))
    } else {
        None
    };
    #[cfg(not(feature = "auth"))]
    if config.auth {
        return Err("this build has no sign-in gate: rebuild without --no-default-features".into());
    }

    let listener = std::net::TcpListener::bind(&config.addr).map_err(|e| format!("{}: {e}", config.addr))?;
    listener.set_nonblocking(true).map_err(|e| e.to_string())?;
    let local = listener.local_addr().map(|a| a.to_string()).unwrap_or_else(|_| config.addr.clone());
    println!("frontage-api: {} on http://{local}, {} worker(s){}", config.module, config.workers,
             if config.stress { ", GC stress" } else { "" });
    for p in &paths {
        println!("  {p}");
    }
    if let Some(Some(dir)) = STATIC_DIR.get() {
        println!("  files from {}", dir.display());
    }
    #[cfg(feature = "auth")]
    if let Some(auth) = &auth {
        println!("  {}", auth.summary());
    }

    let mut threads = Vec::with_capacity(config.workers);
    for i in 0..config.workers {
        let socket = listener.try_clone().map_err(|e| e.to_string())?;
        #[cfg(feature = "auth")]
        let gate = auth.clone();
        #[cfg(not(feature = "auth"))]
        let gate = ();
        let worker = std::thread::Builder::new()
            .name(format!("worker-{i}"))
            .spawn(move || worker(socket, gate))
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

#[cfg(feature = "auth")]
type Gate = Option<Arc<Auth>>;
#[cfg(not(feature = "auth"))]
type Gate = ();

fn worker(socket: std::net::TcpListener, gate: Gate) -> Result<(), String> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|e| format!("tokio: {e}"))?;
    runtime.block_on(async move {
        let listener = tokio::net::TcpListener::from_std(socket).map_err(|e| e.to_string())?;
        axum::serve(listener, router(gate)).await.map_err(|e| e.to_string())
    })
}

/// The app itself is the fallback — every path is Python's until it says otherwise, and a
/// file answers after that. With `--auth`, the four sign-in routes and the gate go around it,
/// so the middleware sees the static files too: a directory of prerendered HTML is exactly
/// what a private site is, and `ServeDir` would otherwise hand it to anyone with the URL.
fn router(gate: Gate) -> Router {
    let router = Router::new().fallback(handle);
    #[cfg(feature = "auth")]
    let router = match gate {
        Some(auth) => crate::auth::wrap(router, auth),
        None => router,
    };
    #[cfg(not(feature = "auth"))]
    let _ = gate;
    router
}

async fn handle(request: Request) -> Response {
    let method = request.method().as_str().to_owned();
    let path = request.uri().path().to_owned();
    let query = request.uri().query().unwrap_or("").to_owned();
    // Kept in case the app claims no route and a file has to answer instead.
    let (parts, request) = {
        let (parts, body) = request.into_parts();
        (parts.clone(), Request::from_parts(parts, body))
    };
    // The body is read before Python is entered, so the VM is never borrowed across an await
    // and the handler holds nothing but `Send` values over one.
    let body = match axum::body::to_bytes(request.into_body(), MAX_BODY).await {
        Ok(b) => b,
        Err(_) => return (StatusCode::PAYLOAD_TOO_LARGE, "body too large").into_response(),
    };
    let started = match with_app(|app| app.start(&method, &path, &query, &body)) {
        Ok(r) => r,
        Err(e) => return fault(e),
    };
    let mut response = match started {
        Ok(Started::Done(answer)) => respond(answer),
        Ok(Started::Running(token)) => park(token).await,
        Err(text) => fault(text),
    };
    // **The app is asked first and files answer second**, which is the order that matters:
    // `ServeDir` handles only GET and HEAD, so files-first would answer 405 to every POST
    // instead of falling through to the route that wanted it.
    if response.status() == StatusCode::NOT_FOUND {
        if let Some(Some(dir)) = STATIC_DIR.get() {
            let origin = parts.headers.get("origin").and_then(|v| v.to_str().ok()).map(|s| s.to_owned());
            if let Some(mut file) = serve_file(dir, parts).await {
                if let Some(origin) = origin {
                    if let Ok(extra) = with_app(|app| app.cors_headers(&origin)) {
                        let out = file.headers_mut();
                        for (name, value) in extra {
                            if let (Ok(n), Ok(v)) = (HeaderName::from_bytes(name.as_bytes()), HeaderValue::from_str(&value)) {
                                out.append(n, v);
                            }
                        }
                    }
                }
                response = file;
            }
        }
    }
    // Collect between requests rather than inside one.
    let _ = with_app(|app| app.settle_heap());
    response
}

/// Pump this thread's loop until the request's coroutine finishes, yielding to tokio in
/// between so the worker keeps answering other connections.
async fn park(token: u32) -> Response {
    // ⚠ The pump-then-poll order inside `park_value` is not a style choice. A turn of the
    // loop settles the last future and reports "nothing scheduled" in the same breath, so
    // polling first and reading `None` as a deadlock declares every awaiting handler stuck.
    match park_value(token).await {
        Ok(answer) => respond(answer),
        Err(text) => fault(text),
    }
}

fn respond(answer: Answer) -> Response {
    let body = match answer.body {
        Body::Whole(bytes) => axum::body::Body::from(bytes),
        Body::Stream(token) => stream_body(token),
    };
    let mut response = Response::new(body);
    *response.status_mut() = StatusCode::from_u16(answer.status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR);
    let out = response.headers_mut();
    for (name, value) in answer.headers {
        match (HeaderName::from_bytes(name.as_bytes()), HeaderValue::from_str(&value)) {
            (Ok(n), Ok(v)) => {
                out.append(n, v);
            }
            // A header the app invented that HTTP cannot carry is the app's bug, but dropping
            // one silently is worse than answering without it; say so on the way past.
            _ => eprintln!("frontage-api: dropped an invalid header {name}: {value}"),
        }
    }
    response
}

/// The file a request names, if there is one. A directory answers its `index.html`, which is
/// what `frontage build` writes and what a page at `/` means.
async fn serve_file(dir: &PathBuf, parts: axum::http::request::Parts) -> Option<Response> {
    use tower::util::ServiceExt;
    let request = Request::from_parts(parts, axum::body::Body::empty());
    let service = ServeDir::new(dir).append_index_html_on_directories(true);
    match service.oneshot(request).await {
        Ok(response) if response.status() != StatusCode::NOT_FOUND => Some(response.map(axum::body::Body::new)),
        _ => None,
    }
}

/// A chunk source, pulled one piece at a time and written as it comes.
///
/// **The VM never crosses an `.await` here either.** The pulling task holds a token and a
/// sender, both `Send`, and every touch of the interpreter is inside a synchronous closure —
/// which is what lets `tokio::spawn` take it. It stays on this thread because the runtime is
/// `current_thread`, and it must, because the source belongs to this thread's `Vm`.
///
/// A channel of one: the producer is not allowed to run ahead of the reader, so a slow client
/// slows the handler instead of filling memory with chunks nobody has read.
fn stream_body(token: u32) -> axum::body::Body {
    let (tx, rx) = mpsc::channel::<Result<Bytes, std::io::Error>>(1);
    tokio::spawn(async move {
        loop {
            let started = match with_app(|app| app.chunk_next(token)) {
                Ok(Ok(s)) => s,
                Ok(Err(text)) | Err(text) => {
                    // A stream that fails after its headers went out cannot change status,
                    // so the only honest thing is to abort the body and say why on the way.
                    eprintln!("frontage-api: stream {token} failed: {text}");
                    let _ = tx.send(Err(std::io::Error::other(text))).await;
                    break;
                }
            };
            let answer = match started {
                Started::Done(answer) => answer,
                Started::Running(inner) => match park_value(inner).await {
                    Ok(answer) => answer,
                    Err(text) => {
                        eprintln!("frontage-api: stream {token} failed while parked: {text}");
                        let _ = tx.send(Err(std::io::Error::other(text))).await;
                        break;
                    }
                },
            };
            // Status 0 is how the source says it is finished; see `App::chunk`.
            if answer.status == 0 {
                break;
            }
            let bytes = match answer.body {
                Body::Whole(bytes) => bytes,
                Body::Stream(_) => break,
            };
            if tx.send(Ok(Bytes::from(bytes))).await.is_err() {
                break; // the client went away
            }
        }
        let _ = with_app(|app| app.forget_stream(token));
    });
    axum::body::Body::from_stream(ReceiverStream::new(rx))
}

/// `park`, but answering the value rather than a `Response`: a chunk needs the same pump.
async fn park_value(token: u32) -> Result<Answer, String> {
    loop {
        let delay = with_app(|app| app.pump())??;
        match with_app(|app| app.poll(token))?? {
            Poll::Done(answer) => return Ok(answer),
            Poll::Advanced => continue,
            Poll::Blocked => {}
        }
        match delay {
            None => return Err("this handler is waiting on something nothing will complete".into()),
            Some(seconds) if seconds > 0.0 => {
                tokio::time::sleep(Duration::from_secs_f64(seconds).min(MAX_PARK)).await;
            }
            Some(_) => tokio::task::yield_now().await,
        }
    }
}

/// This thread's VM, built on first use.
fn with_app<T>(f: impl FnOnce(&mut App) -> T) -> Result<T, String> {
    APP.with(|cell| {
        let mut slot = cell.borrow_mut();
        if slot.is_none() {
            let (dir, module, search, stress) = SOURCE.get().ok_or("serve() was not called")?;
            *slot = Some(App::load(dir.clone(), module, search, *stress)?);
        }
        Ok(f(slot.as_mut().expect("just loaded")))
    })
}

/// A traceback is the body while this is a spike: there is no user to protect yet and every
/// failure here is ours. `API.md` §4.8's problem JSON replaces it.
fn fault(text: String) -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, text).into_response()
}
