//! Every `tests/cases/*.py` runs on CPython and on `fpy`; the outputs must match byte for
//! byte. CPython is the reference: a case that differs is a bug here, or a documented
//! difference that belongs in a separate case with the runtime's expected output.

use std::path::{Path, PathBuf};
use std::process::Command;

fn cpython() -> PathBuf {
    let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let venv = repo.join(".venv/bin/python");
    if venv.exists() {
        venv
    } else {
        PathBuf::from("python3")
    }
}

fn run(cmd: &mut Command) -> (String, String, i32) {
    let out = cmd.output().expect("spawn");
    (String::from_utf8_lossy(&out.stdout).into_owned(), String::from_utf8_lossy(&out.stderr).into_owned(), out.status.code().unwrap_or(-1))
}

#[test]
fn cases_match_cpython() {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/cases");
    let fpy = env!("CARGO_BIN_EXE_fpy");
    let mut files: Vec<PathBuf> = std::fs::read_dir(&dir).unwrap().filter_map(|e| e.ok().map(|e| e.path())).filter(|p| p.extension().map(|x| x == "py").unwrap_or(false)).collect();
    files.sort();
    let only = std::env::var("CASE").ok();
    let mut failures = Vec::new();
    for file in &files {
        let name = file.file_name().unwrap().to_string_lossy().into_owned();
        if let Some(o) = &only {
            if !name.contains(o.as_str()) {
                continue;
            }
        }
        let (expected, ref_err, ref_code) = run(&mut Command::new(cpython()).arg(file));
        let web = std::fs::read_to_string(file).map(|s| s.starts_with("# runtime: web")).unwrap_or(false);
        let (actual, err, code) = if web {
            // A case for the browser's half (`re` over RegExp): compiled to .fbc, run on the
            // wasm under node. Skipped when the wasm is not built or node is absent.
            let wasm = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../frontage/_runtime/frontage.wasm");
            if !wasm.exists() {
                eprintln!("skipping {name}: run `mk runtime.build` first");
                continue;
            }
            let fbc = std::env::temp_dir().join(format!("{name}.fbc"));
            let (_, cerr, ccode) = run(Command::new(fpy).arg("--compile").arg(&fbc).arg(file));
            if ccode != 0 {
                (String::new(), cerr, ccode)
            } else {
                let out = run(Command::new("node").arg(Path::new(env!("CARGO_MANIFEST_DIR")).join("../web/run.mjs")).arg(&fbc));
                if out.2 == -1 || out.1.contains("ENOENT") {
                    eprintln!("skipping {name}: node not found");
                    continue;
                }
                out
            }
        } else {
            run(Command::new(fpy).arg("--stress").arg(file))
        };
        if expected != actual || (ref_code == 0) != (code == 0) {
            failures.push(format!(
                "--- {name}: cpython exit {ref_code}, fpy exit {code}\n{}\n{}",
                diff(&expected, &actual),
                if err.is_empty() { ref_err } else { format!("fpy stderr:\n{err}") }
            ));
        }
    }
    if !failures.is_empty() {
        panic!("{} of {} cases differ from CPython:\n\n{}", failures.len(), files.len(), failures.join("\n"));
    }
}

fn diff(expected: &str, actual: &str) -> String {
    let mut out = String::new();
    let (e, a): (Vec<&str>, Vec<&str>) = (expected.lines().collect(), actual.lines().collect());
    let n = e.len().max(a.len());
    let mut shown = 0;
    for i in 0..n {
        let (x, y) = (e.get(i).copied().unwrap_or("<missing>"), a.get(i).copied().unwrap_or("<missing>"));
        if x != y {
            out.push_str(&format!("  line {}:\n    cpython: {x}\n    fpy:     {y}\n", i + 1));
            shown += 1;
            if shown >= 6 {
                out.push_str("  …\n");
                break;
            }
        }
    }
    out
}
