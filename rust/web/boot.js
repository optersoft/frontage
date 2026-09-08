// Boot a page on frontage's runtime: the wasm, the compiled modules named in
// `manifest.json`, then the entry as `__main__`. The page declares what to run:
//
//     <script type="module" src="./_frontage/boot.js" data-fr-boot data-fr-entry="counter"></script>
//
// `data-fr-compiler` on the tag loads `frontage-compiler.wasm` instead, the same runtime with
// the compiler in it, for a page that runs a program someone types (the playground).
// Everything resolves from `import.meta.url`, so a page at any depth finds its runtime.

import { load } from "./glue.js";

const asset = (name) => new URL(name, import.meta.url).href;
let rtAssets = "";

async function bytes(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`frontage: ${response.status} fetching ${url}`);
  return new Uint8Array(await response.arrayBuffer());
}

const console_io = {
  stdout: (s) => console.log(s.replace(/\n$/, "")),
  stderr: (s) => console.error(s.replace(/\n$/, "")),
};

/**
 * The runtime with the compiler in it and no application: for a page that holds its program
 * in a URL fragment or a text box (the runner, the playground) and has nothing to fetch.
 * `rt.runSource(code)` runs it as `__main__`. Deliberately touches nothing in the document.
 */
export async function startRuntime() {
  const [rt, framework] = await Promise.all([
    load(asset("frontage-compiler.wasm"), console_io),
    fetch(asset("framework.json")).then((r) => r.json()),
  ]);
  await addModules(rt, framework.modules);
  return rt;
}

// A built app's manifest names each module's content-hashed file; the dev server's does not.
let files = {};
const fileOf = (name) => files[name] || `${name}.fbc`;

async function addModules(rt, names) {
  const modules = await Promise.all(names.map(async (name) => [name, await bytes(asset(fileOf(name)))]));
  for (const [name, fbc] of modules) rt.addModule(name, fbc);
}

async function boot() {
  const tag = document.querySelector("script[data-fr-boot]");
  if (!tag) {
    // Not an error: a page may import this module for `startRuntime` alone.
    console.warn("frontage: no <script data-fr-boot> on the page, so nothing was mounted");
    return null;
  }
  const entry = tag.dataset.frEntry || "app";
  // A page that runs a typed program (`data-fr-compiler`) gets the whole framework, since
  // the program may import any of it; a built app gets its entry's import closure.
  const compiler = tag.dataset.frCompiler !== undefined;
  const [manifest, framework] = await Promise.all([
    fetch(asset("manifest.json")).then((r) => r.json()),
    compiler ? fetch(asset("framework.json")).then((r) => r.json()) : { modules: [] },
  ]);
  files = manifest.files || {};
  // What a chunk fetch needs later: where these files live, and which modules are in each.
  rtAssets = asset("");
  const rt = await load(asset(compiler ? "frontage-compiler.wasm" : manifest.wasm || "frontage.wasm"), console_io);
  const names = [...new Set([...framework.modules, ...manifest.modules])];
  await addModules(rt, names);
  // JavaScript modules the app asked for (`data-fr-js="name=./lib.js, ./other.js"`): the
  // glue around a C or Rust library compiled to WebAssembly. Named ones become Python
  // modules. Resolved from `../` of this file, the app's own directory in every layout.
  const appRoot = new URL("../", import.meta.url);
  for (const item of (tag.dataset.frJs || "").split(",")) {
    const spec = item.trim();
    if (!spec) continue;
    const eq = spec.indexOf("=");
    const name = eq > 0 ? spec.slice(0, eq).trim() : "";
    const specifier = eq > 0 ? spec.slice(eq + 1).trim() : spec;
    const namespace = await import(new URL(specifier, appRoot).href);
    if (name) rt.registerJsModule(name, namespace);
  }
  const main = await bytes(asset(manifest.entry || `${entry}.fbc`));
  rt.assetBase = rtAssets;
  rt.manifest = manifest;
  window.frontage = rt;
  const code = rt.run(main);
  if (code === 1) console.error("frontage: the entry raised; see above");
  return rt;
}

const parsed =
  document.readyState === "loading"
    ? new Promise((done) => document.addEventListener("DOMContentLoaded", done, { once: true }))
    : Promise.resolve();

export const ready = parsed.then(boot);
ready.catch((error) => {
  setTimeout(() => {
    throw error;
  });
});
