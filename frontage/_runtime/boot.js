// Frontage boot. MicroPython compiled to WebAssembly, the framework as precompiled bytecode,
// the app as source. Four requests, no PyScript, nothing of the framework parsed in the page.
//
// The page declares what to run and this file works out the rest:
//
//     <script type="module" src="./_frontage/boot.js" data-fr-boot data-fr-entry="app"></script>
//
// Every runtime path resolves from `import.meta.url`, never from the document. That is not a
// style choice: `micropython.mjs` locates its own `.wasm` relative to itself, so a
// document-relative path would give one loader two different bases, and a prerendered page at
// /about/ would silently fetch the wrong thing. It also means the prerenderer never has to
// rewrite a runtime path when it moves a page down a directory.

import { loadMicroPython } from "./micropython.mjs";

const asset = (name) => new URL(name, import.meta.url).href;

/** Members of an uncompressed USTAR archive, as [name, bytes]. */
function untar(buffer) {
  const files = [];
  const bytes = new Uint8Array(buffer);
  const text = new TextDecoder();
  for (let at = 0; at + 512 <= bytes.length; ) {
    const name = text.decode(bytes.subarray(at, at + 100)).replace(/\0.*$/, "");
    if (!name) break; // the trailing zero blocks
    const size = parseInt(text.decode(bytes.subarray(at + 124, at + 136)).replace(/[\0 ]/g, ""), 8) || 0;
    const kind = String.fromCharCode(bytes[at + 156]);
    at += 512;
    if (kind === "0" || kind === "\0") files.push([name, bytes.slice(at, at + size)]);
    at += Math.ceil(size / 512) * 512;
  }
  return files;
}

async function bytes(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`frontage: ${response.status} fetching ${url}`);
  return response.arrayBuffer();
}

function unpack(mp, archive) {
  for (const [name, content] of untar(archive)) {
    const slash = name.lastIndexOf("/");
    if (slash > 0) mp.FS.mkdirTree("/lib/" + name.slice(0, slash));
    mp.FS.writeFile("/lib/" + name, content);
  }
}

/** `data-fr-js="name=./lib.js, ./other.js"` as [name, specifier] pairs. */
function declaredModules(value) {
  return (value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const split = item.indexOf("=");
      if (split < 0) return ["", item];
      return [item.slice(0, split).trim(), item.slice(split + 1).trim()];
    });
}

/**
 * The interpreter with the framework in it, and no application.
 *
 * Exported because not every page has an app directory to fetch. An embedded runner — the
 * academy's live-code frames, the playground — holds the program in a URL fragment or a text
 * box, and needs somewhere to run it rather than something to load:
 *
 *     const mp = await startRuntime();
 *     mp.globals.set("__src", program);
 *     mp.runPython("exec(__src)");
 *
 * It deliberately does not touch the document. A frame can call it from an opaque origin,
 * where there is no boot tag and nothing to query.
 */
export async function startRuntime() {
  // `/lib` is already on MicroPython's sys.path, so nothing has to edit it.
  const [mp, framework] = await Promise.all([
    loadMicroPython({ url: asset("micropython.wasm") }), // heapsize/pystack: upstream defaults
    bytes(asset("frontage.tar")),
  ]);
  unpack(mp, framework);
  return mp;
}

async function boot() {
  const tag = document.querySelector("script[data-fr-boot]");
  if (!tag) {
    // Not an error. A page can import this module purely for `startRuntime` — an embedded
    // runner holds its program in a fragment and has no app to boot. A real app that has
    // simply lost its tag gets the warning and a page stuck on its placeholder.
    console.warn("frontage: no <script data-fr-boot> on the page, so nothing was mounted");
    return null;
  }
  const entry = tag.dataset.frEntry || "app";

  const [mp, app] = await Promise.all([startRuntime(), bytes(asset("app.tar"))]);
  unpack(mp, app);

  // JavaScript modules the app asked for — the glue around a C or Rust library compiled to
  // WebAssembly is exactly this shape. Named ones become real Python modules, so the app
  // writes `import mathlib` rather than reaching through `window`.
  //
  // Resolved from `../` of this file, which is the app's own directory in every layout:
  // `<app>/index.html` beside `<app>/_frontage/boot.js`. That keeps them correct on a
  // prerendered page at any depth, with nothing for the prerenderer to rewrite.
  const appRoot = new URL("../", import.meta.url);
  for (const [name, specifier] of declaredModules(tag.dataset.frJs)) {
    const namespace = await import(new URL(specifier, appRoot).href);
    if (name) mp.registerJsModule(name, namespace);
  }

  // The entry runs as __main__, the way `<script type="mpy" src>` ran it, so an app that
  // guards on __name__ behaves the same. runPython already executes in __main__ and
  // MicroPython cannot construct a module object, so exec against its own globals is both
  // the simplest and the only route.
  mp.globals.set("__fr_entry", entry);
  mp.runPython(
    "with open('/lib/' + __fr_entry + '.py') as _f: _src = _f.read()\n" +
      "del __fr_entry\n" +
      "exec(_src)\n" +
      "del _src\n"
  );
  return mp;
}

// A parsed document, always. With every asset warm in cache the interpreter can otherwise
// outrun the parser, and mount() then finds no target — or worse, finds the target but not
// the prerendered data block, and quietly refetches everything the server already sent.
const parsed =
  document.readyState === "loading"
    ? new Promise((done) => document.addEventListener("DOMContentLoaded", done, { once: true }))
    : Promise.resolve();

// Rethrow out of band. A rejected promise is not reliably reported to window.onerror or to a
// test runner's page-error hook, and a boot failure that shows up as nothing at all is the
// worst thing this file could do.
export const ready = parsed.then(boot);
ready.catch((error) => {
  setTimeout(() => {
    throw error;
  });
});
