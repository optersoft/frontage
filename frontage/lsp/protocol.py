"""The Language Server Protocol's base layer: `Content-Length` framing over stdio, and a
dispatch loop.

Hand-written, and stdlib only, on purpose. The package ships with `dependencies = []` and
the one command a user runs is `uvx frontage lsp`; a protocol library would buy typed
message structures and cancellation in exchange for a resolution step and a version to keep
in sync. What this server needs — full-document sync, a handful of request handlers — is a
frame reader and a dict of methods. If cancellation or incremental sync ever earn their
keep, they go behind these same handlers.

The wire is JSON-RPC 2.0: each message is `Content-Length: N\r\n\r\n` followed by N bytes of
UTF-8 JSON. A request carries an `id` and wants a response; a notification has no `id` and
must not get one.
"""

import json
import sys

# JSON-RPC error codes the specification reserves.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
# LSP's own: the server is shutting down, or the client cancelled.
REQUEST_FAILED = -32803


class Disconnected(Exception):
    """The client closed the pipe. Not an error: it is how an editor stops a server."""


def read_message(stream):
    """The next message from a binary stream, as a dict. Raises `Disconnected` at EOF."""
    length = None
    while True:
        line = stream.readline()
        if not line:
            raise Disconnected()
        line = line.strip()
        if not line:  # the blank line that ends the header block
            break
        if b":" in line:
            name, _, value = line.partition(b":")
            if name.strip().lower() == b"content-length":
                length = int(value.strip())
    if length is None:
        # A header block with no length is unrecoverable: we cannot know where the body ends.
        raise Disconnected()
    body = b""
    while len(body) < length:
        chunk = stream.read(length - len(body))
        if not chunk:
            raise Disconnected()
        body += chunk
    return json.loads(body.decode("utf-8"))


def write_message(stream, message):
    """Frame and send one message. Flushes: an editor is waiting on this byte."""
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    stream.write(b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body)
    stream.flush()


class Connection:
    """One client, over a pair of binary streams."""

    def __init__(self, reader=None, writer=None):
        self.reader = reader if reader is not None else sys.stdin.buffer
        self.writer = writer if writer is not None else sys.stdout.buffer

    def notify(self, method, params):
        write_message(self.writer, {"jsonrpc": "2.0", "method": method, "params": params})

    def respond(self, request_id, result):
        write_message(self.writer, {"jsonrpc": "2.0", "id": request_id, "result": result})

    def fail(self, request_id, code, message):
        write_message(self.writer, {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})

    def log(self, message, kind=3):
        """`window/logMessage`. Kind 1 error, 2 warning, 3 info, 4 log. The client decides
        whether anyone sees it, which is why nothing here writes to stdout directly: stdout
        is the protocol."""
        self.notify("window/logMessage", {"type": kind, "message": message})


def serve(handlers, connection=None):
    """Read messages until the client disconnects, dispatching each to `handlers[method]`.

    A handler takes `(connection, params)` and returns a result for a request, or `None` for
    a notification. An unknown notification is ignored — the specification requires it, and
    clients send several the server never asked for. An unknown *request* gets
    `METHOD_NOT_FOUND`, because a client blocks on it.
    """
    connection = connection or Connection()
    while True:
        try:
            message = read_message(connection.reader)
        except Disconnected:
            return 0
        except (ValueError, UnicodeDecodeError) as exc:
            # A malformed frame has no id to answer, so there is nobody to tell but the log.
            connection.log(f"frontage lsp: unreadable message ({exc})", kind=1)
            continue
        request_id = message.get("id")
        method = message.get("method")
        if method is None:  # a response to something we sent; the server sends no requests yet
            continue
        handler = handlers.get(method)
        if handler is None:
            if request_id is not None:
                connection.fail(request_id, METHOD_NOT_FOUND, f"unknown method {method!r}")
            continue
        try:
            result = handler(connection, message.get("params") or {})
        except Exception as exc:  # noqa: BLE001 - one bad request must not take the server down
            connection.log(f"frontage lsp: {method} failed: {exc!r}", kind=1)
            if request_id is not None:
                connection.fail(request_id, INTERNAL_ERROR, str(exc))
            continue
        if request_id is not None:
            connection.respond(request_id, result)
        if method == "exit":
            return 0
