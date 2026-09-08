//! What the runtime asks of the environment it runs in.
//!
//! In the browser this is the JavaScript glue; natively (tests, the `fpy` runner) it is the
//! process. The runtime never touches a clock, a file or an output stream except through it,
//! which is what lets the same VM run the SPEC suite under `cargo test` and a page under
//! `boot.js`.

pub struct ModuleSource {
    pub filename: String,
    pub source: String,
    pub is_package: bool,
}

pub trait Host {
    fn write_stdout(&mut self, s: &str);
    fn write_stderr(&mut self, s: &str);
    /// Milliseconds on a monotonic clock (`performance.now`).
    fn now_ms(&self) -> f64;
    /// Seconds since the epoch (`Date.now() / 1000`).
    fn time_s(&self) -> f64;
    /// Python source for a module, by dotted name, or `None`.
    fn find_module(&mut self, name: &str) -> Option<ModuleSource>;
    fn random_u64(&mut self) -> u64;
    /// Block for `ms` (the native runner); the browser's host does nothing here.
    fn sleep_ms(&mut self, ms: f64) {
        let _ = ms;
    }
    /// Compiled bytecode for a module, when the host carries `.fbc` files.
    fn find_module_code(&mut self, _name: &str) -> Option<Vec<u8>> {
        None
    }
    fn add_module(&mut self, _name: &str, _bytes: Vec<u8>) {}
}

/// A host for the native runner and the tests: stdio, the system clock, modules from a
/// search path.
pub struct StdHost {
    pub search: Vec<std::path::PathBuf>,
    rng: u64,
    pub stdout: Option<String>,
}

impl StdHost {
    pub fn new(search: Vec<std::path::PathBuf>) -> StdHost {
        StdHost { search, rng: 0x2545_f491_4f6c_dd1d, stdout: None }
    }
    /// Keep output in memory (tests) instead of writing it.
    pub fn capture(mut self) -> StdHost {
        self.stdout = Some(String::new());
        self
    }
}

impl Host for StdHost {
    fn write_stdout(&mut self, s: &str) {
        if let Some(buf) = &mut self.stdout {
            buf.push_str(s);
        } else {
            use std::io::Write;
            let out = std::io::stdout();
            let mut lock = out.lock();
            let _ = lock.write_all(s.as_bytes());
            let _ = lock.flush();
        }
    }
    fn write_stderr(&mut self, s: &str) {
        eprint!("{s}");
    }
    fn now_ms(&self) -> f64 {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64() * 1000.0).unwrap_or(0.0)
    }
    fn time_s(&self) -> f64 {
        self.now_ms() / 1000.0
    }
    fn find_module(&mut self, name: &str) -> Option<ModuleSource> {
        let rel: std::path::PathBuf = name.split('.').collect();
        for root in &self.search {
            let file = root.join(&rel).with_extension("py");
            if file.is_file() {
                return Some(ModuleSource {
                    filename: file.to_string_lossy().into_owned(),
                    source: std::fs::read_to_string(&file).ok()?,
                    is_package: false,
                });
            }
            let init = root.join(&rel).join("__init__.py");
            if init.is_file() {
                return Some(ModuleSource {
                    filename: init.to_string_lossy().into_owned(),
                    source: std::fs::read_to_string(&init).ok()?,
                    is_package: true,
                });
            }
        }
        None
    }
    fn sleep_ms(&mut self, ms: f64) {
        if ms > 0.0 {
            std::thread::sleep(std::time::Duration::from_micros((ms * 1000.0) as u64));
        }
    }
    fn random_u64(&mut self) -> u64 {
        // xorshift64*: enough for `random.random()` in a test.
        let mut x = self.rng;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.rng = x;
        x.wrapping_mul(0x2545_f491_4f6c_dd1d)
    }
}
