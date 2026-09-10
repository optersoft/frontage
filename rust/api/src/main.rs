//! `frontage-api APP.py [--addr HOST:PORT] [--workers N] [--path DIR] [--auth google]`, or
//! `frontage-api --serve DIR` for files alone — `API.md` §6.2, and §5a for the gate.
//!
//! The app is a Python module defining `app`, a `frontage_api.App`. `--path` adds module
//! search directories, which is how `frontage_api` and `frontage.schema` are found: this
//! runtime has no site-packages, so a checkout is `--path /path/to/frontage`.
//!
//! **Every option is also an environment variable**, because a fleet unit's `ExecStart=` takes
//! no arguments — it is the release's binary path and nothing else, and its configuration
//! arrives through `EnvironmentFile=`. A flag on the command line wins over the variable.

mod app;
#[cfg(feature = "auth")]
mod auth;
mod hostmod;
mod server;

use std::path::PathBuf;

const USAGE: &str = "usage: frontage-api APP.py [--addr HOST:PORT] [--workers N] [--path DIR] [--stress]\n\
                     \x20                        [--auth google] [--auth-label NAME]\n\
                     \x20      frontage-api --serve DIR [the same options]\n\
                     \n\
                     env: FRONTAGE_API_APP, FRONTAGE_API_SERVE, FRONTAGE_API_ADDR, FRONTAGE_API_WORKERS,\n\
                     \x20    FRONTAGE_API_PATH (colon separated), FRONTAGE_API_AUTH, FRONTAGE_API_AUTH_LABEL";

fn main() {
    let mut args = std::env::args().skip(1);
    let mut file: Option<PathBuf> = None;
    let mut files: Option<PathBuf> = None;
    let mut addr: Option<String> = None;
    let mut workers: Option<usize> = None;
    let mut stress = false;
    let mut search: Vec<PathBuf> = Vec::new();
    let mut auth = false;
    let mut auth_label: Option<String> = None;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--addr" => match args.next() {
                Some(a) => addr = Some(a),
                None => fail("--addr needs HOST:PORT"),
            },
            "--workers" => match args.next().and_then(|n| n.parse().ok()) {
                Some(n) if n > 0 => workers = Some(n),
                _ => fail("--workers needs a positive count"),
            },
            "--stress" => stress = true,
            // Files and nothing else: no app module, no interpreter in the process. A private
            // site is a directory of prerendered pages, and a Python app that only serves them
            // would be one more thing to ship and nothing to run.
            "--serve" => match args.next() {
                Some(d) => files = Some(PathBuf::from(d)),
                None => fail("--serve needs a directory"),
            },
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
                println!("{USAGE}");
                return;
            }
            other if file.is_none() && files.is_none() => file = Some(PathBuf::from(other)),
            other => fail(&format!("unexpected argument: {other}")),
        }
    }

    // The environment fills in whatever the command line did not say.
    let file = file.or_else(|| env("APP").map(PathBuf::from));
    let files = files.or_else(|| env("SERVE").map(PathBuf::from));
    let addr = addr.or_else(|| env("ADDR")).unwrap_or_else(|| "127.0.0.1:8000".into());
    let workers = workers.or_else(|| env("WORKERS").and_then(|n| n.parse().ok()).filter(|n| *n > 0));
    if !auth {
        match env("AUTH").as_deref() {
            Some("google") => auth = true,
            Some(other) => fail(&format!("FRONTAGE_API_AUTH=google is the only provider ({other} is not one)")),
            None => {}
        }
    }
    let auth_label = auth_label.or_else(|| env("AUTH_LABEL"));
    if let Some(raw) = env("PATH") {
        search.extend(raw.split(':').filter(|p| !p.is_empty()).map(PathBuf::from));
    }

    let (dir, module) = match (file, files) {
        (Some(_), Some(_)) => fail("an app and --serve are two different servers: pass one"),
        (Some(file), None) => {
            let file = match file.canonicalize() {
                Ok(f) => f,
                Err(e) => fail(&format!("{}: {e}", file.display())),
            };
            let Some(module) = file.file_stem().and_then(|s| s.to_str()).map(|s| s.to_owned()) else {
                fail("the app must be a .py file")
            };
            (file.parent().map(|p| p.to_path_buf()).unwrap_or_else(|| PathBuf::from(".")), Some(module))
        }
        (None, Some(dir)) => match dir.canonicalize() {
            Ok(dir) if dir.is_dir() => (dir, None),
            Ok(dir) => fail(&format!("--serve {}: not a directory", dir.display())),
            Err(e) => fail(&format!("{}: {e}", dir.display())),
        },
        (None, None) => fail(USAGE),
    };

    // One OS thread per worker, each with a `current_thread` runtime and a VM of its own.
    // `--workers` is also what makes a comparison against another server fair, since it pins
    // both to the same core count.
    let workers = workers.unwrap_or_else(|| std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1));
    if let Err(e) = server::serve(server::Config { dir, module, addr, workers, search, stress, auth, auth_label }) {
        fail(&e);
    }
}

/// `FRONTAGE_API_{name}` — always prefixed, so `env("PATH")` is the module search path and
/// never the shell's.
fn env(name: &str) -> Option<String> {
    std::env::var(format!("FRONTAGE_API_{name}"))
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

fn fail(message: &str) -> ! {
    eprintln!("frontage-api: {message}");
    std::process::exit(2);
}
