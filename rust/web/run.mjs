// node run.mjs MAIN.fbc [name=module.fbc …]: run bytecode on the wasm runtime.
// The harness for the browser build without a browser: `fpy --compile` makes the .fbc files.
import { readFileSync } from "node:fs";
import { load } from "./glue.js";

const [main, ...modules] = process.argv.slice(2);
if (!main) {
  console.error("usage: node run.mjs MAIN.fbc [name=module.fbc …]");
  process.exit(2);
}
const wasm = readFileSync(new URL("./frontage.wasm", import.meta.url));
const t0 = performance.now();
const rt = await load(wasm, { stdout: (s) => process.stdout.write(s), stderr: (s) => process.stderr.write(s) });
const t1 = performance.now();
for (const spec of modules) {
  const [name, file] = spec.split("=");
  rt.addModule(name, readFileSync(file));
}
const code = rt.run(readFileSync(main));
const t2 = performance.now();
if (process.env.FR_TIMING) console.error(`init ${(t1 - t0).toFixed(1)} ms, run ${(t2 - t1).toFixed(1)} ms, heap ${rt.heapLen()}`);
// `sys.exit(n)` ends the process now. Otherwise pending JavaScript timers (promises the Python
// side awaits) keep it alive, the asyncio loop is pumped from them, and the process exits with
// the run's code once everything drains.
if (code >= 2) process.exit(code - 2);
process.exitCode = code;
