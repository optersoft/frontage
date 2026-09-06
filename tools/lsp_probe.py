"""What the language server says about a file, with no editor in the way.

`mk lsp.probe path/to/app.py`. It drives the real server over an in-memory pipe — the same
bytes VS Code would send — so a report here is a report an editor would show.
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frontage.lsp.protocol import Connection, Disconnected, read_message, write_message  # noqa: E402
from frontage.lsp.server import Server, uri_from_path  # noqa: E402


def main(argv):
    path = Path(argv[0] if argv else "examples/todo/todo.py").resolve()
    text = path.read_text()
    uri = uri_from_path(path)
    outgoing = io.BytesIO()
    for message in (
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {"uri": uri, "languageId": "python", "version": 1, "text": text}},
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "textDocument/semanticTokens/full",
            "params": {"textDocument": {"uri": uri}},
        },
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        {"jsonrpc": "2.0", "method": "exit", "params": {}},
    ):
        write_message(outgoing, message)
    outgoing.seek(0)
    replies = io.BytesIO()
    Server(Connection(outgoing, replies)).run()
    replies.seek(0)
    lines = text.splitlines()
    found = 0
    while True:
        try:
            message = read_message(replies)
        except Disconnected:
            break
        if message.get("method") == "textDocument/publishDiagnostics":
            for diagnostic in message["params"]["diagnostics"]:
                start = diagnostic["range"]["start"]
                found += 1
                print(f"{path}:{start['line'] + 1}:{start['character'] + 1}: {diagnostic['message']}")
                print(f"    {lines[start['line']].strip()}")
        elif message.get("id") == 2:
            print(f"{len(message['result']['data']) // 5} semantic tokens")
        elif message.get("method") == "window/showMessage":
            print(f"! {message['params']['message']}")
    print(f"{found} finding{'s' if found != 1 else ''}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
