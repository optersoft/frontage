//! `frontage-api APP.py [--addr HOST:PORT] [--workers N] [--path DIR] [--auth google]` —
//! `API.md` §6.2, and §5a for the gate.
//!
//! The app is a Python module defining `app`, a `frontage_api.App`. `--path` adds module
//! search directories, which is how `frontage_api` and `frontage.schema` are found: this
//! runtime has no site-packages, so a checkout is `--path /path/to/frontage`.

mod app;
#[cfg(feature = "auth")]
mod auth;
mod hostmod;
mod server;

use std::path::PathBuf;

fn main() {
    let mut args = std::env::args().skip(1);
    let mut file: Option<PathBuf> = None;
    let mut addr = String::from("127.0.0.1:8000");
    let mut workers: Option<usize> = None;
    let mut stress = false;
    let mut search: Vec<PathBuf> = Vec::new();
    let mut auth = false;
    let mut auth_label: Option<String> = None;
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
            "--stress" => stress = true,
            // A provider name rather than a bare flag: the day there is a second one, the
            // spelling every deploy already carries stays right.
            "--auth" => match args.next().as_deref() {
                Some("google") => auth = true,
                Some(other) => fail(&format!("--auth google is the only provider ({other} is not one)")),
                None => fail("--auth needs a provider (google)"),
            },
            "--auth-label" => match args.next() {
                Some(l) => auth_label = Some(l),
                None => fail("--auth-label needs a name"),
            },
            "--path" => match args.next() {
                Some(d) => search.push(PathBuf::from(d)),
                None => fail("--path needs a directory"),
            },
            "-h" | "--help" => {
                println!("usage: frontage-api APP.py [--addr HOST:PORT] [--workers N] [--path DIR] [--stress]");
                println!("                          [--auth google] [--auth-label NAME]");
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
    if let Err(e) = server::serve(server::Config { dir, module, addr, workers, search, stress, auth, auth_label }) {
        fail(&e);
    }
}

fn fail(message: &str) -> ! {
    eprintln!("frontage-api: {message}");
    std::process::exit(2);
}
