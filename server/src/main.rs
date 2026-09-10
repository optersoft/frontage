//! `frontage-api APP.py [--addr HOST:PORT] [--workers N]` — the spike of `PLAN.md` §6.1.
//!
//! The app is a Python module with a `ROUTES` dict of path to handler. Every handler takes
//! the request body as `bytes` and returns `str` or `bytes`; `async def` is allowed as long
//! as it does not suspend (§4.3 is the next commit). That is the whole surface until §6.2.

mod app;
mod hostmod;
mod server;

use std::path::PathBuf;

fn main() {
    let mut args = std::env::args().skip(1);
    let mut file: Option<PathBuf> = None;
    let mut addr = String::from("127.0.0.1:8000");
    let mut workers: Option<usize> = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--addr" => match args.next() {
                Some(a) => addr = a,
                None => fail("--addr needs HOST:PORT"),
            },
            "--workers" => match args.next().and_then(|n| n.parse().ok()) {
                Some(n) if n > 0 => workers = Some(n),
                _ => fail("--workers needs a positive count"),
            },
            "-h" | "--help" => {
                println!("usage: frontage-api APP.py [--addr HOST:PORT] [--workers N]");
                return;
            }
            other if file.is_none() => file = Some(PathBuf::from(other)),
            other => fail(&format!("unexpected argument: {other}")),
        }
    }
    let Some(file) = file else { fail("usage: frontage-api APP.py [--addr HOST:PORT] [--workers N]") };
    let file = match file.canonicalize() {
        Ok(f) => f,
        Err(e) => fail(&format!("{}: {e}", file.display())),
    };
    let Some(module) = file.file_stem().and_then(|s| s.to_str()).map(|s| s.to_owned()) else {
        fail("the app must be a .py file")
    };
    let dir = file.parent().map(|p| p.to_path_buf()).unwrap_or_else(|| PathBuf::from("."));

    // One OS thread per worker, each with a `current_thread` runtime and a VM of its own.
    // `--workers` is also what makes a comparison against another server fair, since it pins
    // both to the same core count.
    let workers = workers.unwrap_or_else(|| std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1));
    if let Err(e) = server::serve(server::Config { dir, module, addr, workers }) {
        fail(&e);
    }
}

fn fail(message: &str) -> ! {
    eprintln!("frontage-api: {message}");
    std::process::exit(2);
}
