// The whole VS Code client. It starts `frontage lsp` and gets out of the way — everything
// an editor shows for a template comes from the server, so this file only has to find a
// Python that can run it, and it is deliberately plain JavaScript so there is no build step
// between an edit here and a reload.

const fs = require("fs");
const path = require("path");
const vscode = require("vscode");
const { LanguageClient, TransportKind } = require("vscode-languageclient/node");

let client = null;

/** How to start the server: the setting, else the workspace's venv, else uvx. */
function serverCommand() {
  const config = vscode.workspace.getConfiguration("frontage");
  const explicit = config.get("server.command") || [];
  if (explicit.length > 0) return { command: explicit[0], args: explicit.slice(1) };

  const python = config.get("python");
  if (python) return { command: python, args: ["-m", "frontage", "lsp"] };

  for (const folder of vscode.workspace.workspaceFolders || []) {
    const root = folder.uri.fsPath;
    const candidates = [
      path.join(root, ".venv", "bin", "python"),
      path.join(root, ".venv", "Scripts", "python.exe"),
    ];
    for (const candidate of candidates) {
      if (fs.existsSync(candidate)) return { command: candidate, args: ["-m", "frontage", "lsp"] };
    }
  }
  // Nothing installed: run the published package without installing it. The pin matters —
  // template strings do not parse below 3.14, and two of the three checks live in them.
  return { command: "uvx", args: ["--python", "3.14", "frontage", "lsp"] };
}

function start() {
  const { command, args } = serverCommand();
  const server = { command, args, transport: TransportKind.stdio };
  const options = {
    documentSelector: [
      { scheme: "file", language: "python" },
      { scheme: "file", language: "markdown" },
    ],
    outputChannelName: "Frontage",
    // A file the server never opened is a file it says nothing about; the CLI covers the rest.
    synchronize: { configurationSection: "frontage" },
  };
  client = new LanguageClient("frontage", "Frontage", server, options);
  client.start().catch((error) => {
    vscode.window.showErrorMessage(
      `Frontage: could not start \`${command}\` (${error.message}). ` +
        "Set frontage.server.command, or install uv."
    );
  });
}

async function stop() {
  if (client) {
    await client.stop();
    client = null;
  }
}

/** Run a frontage subcommand in a terminal, so its output stays where a person can read it. */
function runInTerminal(name, args) {
  const { command, args: base } = serverCommand();
  const prefix = base.slice(0, base.indexOf("lsp"));
  const terminal = vscode.window.createTerminal({ name: `frontage ${name}` });
  terminal.show();
  terminal.sendText([command, ...prefix, ...args].map(quote).join(" "));
}

function quote(word) {
  return /[^\w@%+=:,./-]/.test(word) ? `'${word.replace(/'/g, "'\\''")}'` : word;
}

function activate(context) {
  if (vscode.workspace.getConfiguration("frontage").get("enable")) start();

  const register = (name, run) =>
    context.subscriptions.push(vscode.commands.registerCommand(name, run));

  register("frontage.restartServer", async () => {
    await stop();
    start();
  });
  register("frontage.check", () => {
    const editor = vscode.window.activeTextEditor;
    runInTerminal("check", ["check", editor ? editor.document.uri.fsPath : "."]);
  });
  register("frontage.serve", () => runInTerminal("serve", ["serve"]));
  register("frontage.export", async () => {
    const app = await vscode.window.showInputBox({ prompt: "App to export", value: "app.py" });
    if (app) runInTerminal("export", ["export", app]);
  });
  register("frontage.prerender", async () => {
    const app = await vscode.window.showInputBox({ prompt: "App to prerender", value: "app.py" });
    if (app) runInTerminal("prerender", ["prerender", app]);
  });
  register("frontage.tailwind", () => runInTerminal("tailwind", ["tailwind", "--watch"]));

  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(async (event) => {
      if (event.affectsConfiguration("frontage.server") || event.affectsConfiguration("frontage.python")) {
        await stop();
        if (vscode.workspace.getConfiguration("frontage").get("enable")) start();
      }
    })
  );
}

// `serverCommand` and `quote` are exported for test/extension.test.js: how the server is
// found is the only logic in this file, and it is the part a person cannot see is wrong.
module.exports = { activate, deactivate: stop, serverCommand, quote };
