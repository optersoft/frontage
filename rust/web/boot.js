// Boot a page on frontage's runtime: the wasm, the compiled modules named in
// `manifest.json`, then the entry as `__main__`. The page declares what to run:
//
//     <script type="module" src="./_frontage/boot.js" data-fr-boot data-fr-entry="counter"></script>
//
// Everything resolves from `import.meta.url`, as the MicroPython `boot.js` does, so a page at
// any depth finds its runtime.

import { load } from "./glue.js";

const asset = (name) => new URL(name, import.meta.url).href;

async function bytes(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`frontage: ${response.status} fetching ${url}`);
  return new Uint8Array(await response.arrayBuffer());
}

async function boot() {
  const tag = document.querySelector("script[data-fr-boot]");
  if (!tag) {
    console.warn("frontage: no <script data-fr-boot> on the page, so nothing was mounted");
    return null;
  }
  const entry = tag.dataset.frEntry || "app";
  const [rt, manifest] = await Promise.all([
    load(asset("frontage.wasm"), {
      stdout: (s) => console.log(s.replace(/\n$/, "")),
      stderr: (s) => console.error(s.replace(/\n$/, "")),
    }),
    fetch(asset("manifest.json")).then((r) => r.json()),
  ]);
  const modules = await Promise.all(manifest.modules.map(async (name) => [name, await bytes(asset(`${name}.fbc`))]));
  for (const [name, fbc] of modules) rt.addModule(name, fbc);
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
  const main = await bytes(asset(`${entry}.fbc`));
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
