// What the protocol tests cannot reach: the TextMate grammar (tokenised here by the same
// engine VS Code uses), the snippets, and how the client decides which server to start.
//
//   npm test          in editors/vscode, after `npm install`
//
// The grammar test is the point of the file. `vsce package` checks that the grammar is JSON;
// only an Oniguruma run says whether its regexes compile and whether a template comes out as
// HTML with Python holes inside it.

const assert = require("node:assert");
const { test } = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");

const HERE = path.join(__dirname, "..");
const read = (file) => JSON.parse(fs.readFileSync(path.join(HERE, file), "utf8"));

// --- the client's server discovery ------------------------------------------------------------

/** Load client.js with `vscode` and the language client stubbed out. */
function loadClient(settings, folders) {
  const config = {
    get: (key) => (key in settings ? settings[key] : undefined),
  };
  const stub = {
    workspace: {
      getConfiguration: () => config,
      workspaceFolders: (folders || []).map((p) => ({ uri: { fsPath: p } })),
      onDidChangeConfiguration: () => ({ dispose() {} }),
    },
    window: { showErrorMessage() {}, createTerminal: () => ({ show() {}, sendText() {} }) },
    commands: { registerCommand: () => ({ dispose() {} }) },
  };
  const load = Module._load;
  Module._load = function (request, ...rest) {
    if (request === "vscode") return stub;
    if (request === "vscode-languageclient/node") {
      return { LanguageClient: class {}, TransportKind: { stdio: "stdio" } };
    }
    return load.call(this, request, ...rest);
  };
  try {
    delete require.cache[require.resolve("../client.js")];
    return require("../client.js");
  } finally {
    Module._load = load;
  }
}

test("with nothing configured the server comes from uvx, pinned to 3.14", () => {
  const { serverCommand } = loadClient({ "server.command": [], python: "" }, []);
  assert.deepStrictEqual(serverCommand(), {
    command: "uvx",
    args: ["--python", "3.14", "frontage", "lsp"],
  });
});

test("an explicit command wins over everything", () => {
  const { serverCommand } = loadClient({ "server.command": ["my-frontage", "lsp"], python: "/p" }, []);
  assert.deepStrictEqual(serverCommand(), { command: "my-frontage", args: ["lsp"] });
});

test("a configured interpreter runs the module", () => {
  const { serverCommand } = loadClient({ "server.command": [], python: "/usr/bin/python3.14" }, []);
  assert.deepStrictEqual(serverCommand(), {
    command: "/usr/bin/python3.14",
    args: ["-m", "frontage", "lsp"],
  });
});

test("a workspace .venv is preferred to uvx, and a missing one is skipped", (t) => {
  const root = fs.mkdtempSync(path.join(require("node:os").tmpdir(), "fr-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const empty = fs.mkdtempSync(path.join(require("node:os").tmpdir(), "fr-"));
  t.after(() => fs.rmSync(empty, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, ".venv", "bin"), { recursive: true });
  fs.writeFileSync(path.join(root, ".venv", "bin", "python"), "");
  const { serverCommand } = loadClient({ "server.command": [], python: "" }, [empty, root]);
  assert.deepStrictEqual(serverCommand(), {
    command: path.join(root, ".venv", "bin", "python"),
    args: ["-m", "frontage", "lsp"],
  });
});

test("quote leaves a plain word alone and wraps a path with a space", () => {
  const { quote } = loadClient({ "server.command": [], python: "" }, []);
  assert.strictEqual(quote("export"), "export");
  assert.strictEqual(quote("/tmp/my app.py"), "'/tmp/my app.py'");
  assert.strictEqual(quote("it's.py"), "'it'\\''s.py'");
});

// --- the manifest and the snippets -------------------------------------------------------------

test("every contributed command is registered by the client", () => {
  const manifest = read("package.json");
  const source = fs.readFileSync(path.join(HERE, "client.js"), "utf8");
  for (const { command } of manifest.contributes.commands) {
    assert.ok(source.includes(`"${command}"`), `${command} is contributed but never registered`);
  }
});

test("the files the manifest points at exist", () => {
  const manifest = read("package.json");
  const paths = [
    manifest.main,
    ...manifest.contributes.grammars.map((g) => g.path),
    ...manifest.contributes.snippets.map((s) => s.path),
  ];
  for (const p of paths) assert.ok(fs.existsSync(path.join(HERE, p)), `${p} is missing`);
});

test("snippets have a prefix, a body and balanced placeholders", () => {
  const snippets = read("snippets/frontage.json");
  assert.ok(Object.keys(snippets).length >= 10);
  for (const [name, snippet] of Object.entries(snippets)) {
    assert.ok(snippet.prefix, `${name} has no prefix`);
    const body = Array.isArray(snippet.body) ? snippet.body.join("\n") : snippet.body;
    assert.ok(body && body.length, `${name} has no body`);
    // `${1:name}` placeholders must close, or VS Code drops the rest of the snippet.
    let depth = 0;
    for (let i = 0; i < body.length; i++) {
      if (body[i] === "$" && body[i + 1] === "{") depth++;
      else if (body[i] === "}" && depth > 0) depth--;
    }
    assert.strictEqual(depth, 0, `${name} has an unclosed \${…} placeholder`);
  }
});

// --- the grammar, through Oniguruma ------------------------------------------------------------

async function tokenize(lines) {
  const oniguruma = require("vscode-oniguruma");
  const textmate = require("vscode-textmate");
  const wasm = fs.readFileSync(require.resolve("vscode-oniguruma/release/onig.wasm"));
  await oniguruma.loadWASM(wasm.buffer.slice(wasm.byteOffset, wasm.byteOffset + wasm.byteLength));
  const registry = new textmate.Registry({
    onigLib: Promise.resolve({
      createOnigScanner: (sources) => new oniguruma.OnigScanner(sources),
      createOnigString: (s) => new oniguruma.OnigString(s),
    }),
    // Only the injection is under test: the Python and HTML grammars it composes with are
    // VS Code's, so they are stubbed with an empty grammar of the same scope name.
    loadGrammar: async (scope) => {
      if (scope === "frontage.template.injection") {
        return textmate.parseRawGrammar(
          fs.readFileSync(path.join(HERE, "syntaxes/frontage.injection.json"), "utf8"),
          "frontage.injection.json"
        );
      }
      return textmate.parseRawGrammar(JSON.stringify({ scopeName: scope, patterns: [] }), `${scope}.json`);
    },
    getInjections: (scope) => (scope === "source.python" ? ["frontage.template.injection"] : undefined),
  });
  const grammar = await registry.loadGrammar("source.python");
  assert.ok(grammar, "the injection did not load");
  let state = textmate.INITIAL;
  const out = [];
  for (const line of lines) {
    const result = grammar.tokenizeLine(line, state);
    state = result.ruleStack;
    for (const token of result.tokens) {
      out.push({ text: line.slice(token.startIndex, token.endIndex), scopes: token.scopes });
    }
  }
  return out;
}

// The host grammars are stubbed, so a run of markup arrives as one token: ask which scopes
// cover a piece of text rather than assuming where the tokenizer split it.
const scopesAt = (tokens, needle) =>
  (tokens.find((t) => t.text.includes(needle)) || { scopes: [] }).scopes;

test("a template's markup is HTML and its braces are Python", async () => {
  const tokens = await tokenize(['x = html(t"<b on:click={go}>hi</b>")']);
  assert.ok(scopesAt(tokens, "html").includes("support.function.frontage"), "the html( call is not marked");
  assert.ok(scopesAt(tokens, "hi").includes("meta.embedded.block.html"), "markup is not embedded HTML");
  assert.ok(scopesAt(tokens, "go").includes("meta.embedded.expression.python"), "a hole is not Python");
  assert.ok(scopesAt(tokens, "on").includes("keyword.control.frontage"), "the on: prefix is not marked");
  assert.ok(
    scopesAt(tokens, "click").includes("entity.other.attribute-name.frontage"),
    "the event name is not marked"
  );
  // The hole closes: what follows it is markup again, not Python.
  assert.ok(!scopesAt(tokens, "</b>").includes("meta.embedded.expression.python"), "the hole never closed");
});

test("all four quote styles open and close, and the underscore prefixes count too", async () => {
  for (const [open, close] of [['"', '"'], ["'", "'"], ['"""', '"""'], ["'''", "'''"]]) {
    const tokens = await tokenize([`x = html(t${open}<i class_big={big}>hi</i>${close})`]);
    assert.ok(scopesAt(tokens, "hi").includes("meta.embedded.block.html"), `${open} did not open a template`);
    assert.ok(
      scopesAt(tokens, "class").includes("keyword.control.frontage"),
      `class_ is not marked inside ${open}`
    );
  }
});

test("the template ends at its own quote, so code after it is not markup", async () => {
  const tokens = await tokenize(['x = html(t"<b>hi</b>")', 'y = "plain"']);
  assert.ok(!scopesAt(tokens, "plain").includes("meta.embedded.block.html"), "the template never ended");
});

test("a triple-quoted template spans lines and ends on its own closing quote", async () => {
  const tokens = await tokenize(['x = html(t"""', "  <b>hi</b>", '""")', 'y = "plain"']);
  assert.ok(scopesAt(tokens, "hi").includes("meta.embedded.block.html"), "the second line is not markup");
  assert.ok(!scopesAt(tokens, "plain").includes("meta.embedded.block.html"), "the template never ended");
});

test("an f-string is not a template", async () => {
  // A comment holding `html(t"…")` is excluded by the injection selector (`-comment`), which
  // needs the real Python grammar to mark the comment; that part is not testable from here.
  const tokens = await tokenize(['x = html(f"<b>{name}</b>")']);
  const markup = tokens.filter((t) => t.scopes.includes("meta.embedded.block.html"));
  assert.strictEqual(markup.length, 0, "an f-string was treated as a template");
});
