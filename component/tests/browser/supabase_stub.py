"""A stand-in for a Supabase project: PostgREST over HTTP, Realtime over a websocket.

Not a mock inside the test process — a real server on a real port, so the component is exercised
through the browser's own `fetch` and `WebSocket` exactly as it would be in a page. What it
imitates is the wire format: PostgREST's rows and `Content-Range`, its error bodies, GoTrue's
token response, and Phoenix's five-element frames.
"""

import base64
import hashlib
import json
import socket
import struct
import threading

CITIES = [
    {"id": 1, "name": "Madrid", "region": "Madrid", "people": 3340000},
    {"id": 2, "name": "Barcelona", "region": "Catalunya", "people": 1660000},
    {"id": 3, "name": "Valencia", "region": "Valencia", "people": 807000},
    {"id": 4, "name": "Bilbao", "region": "Euskadi", "people": 346000},
]

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _headers(raw):
    out = {}
    for line in raw.split("\r\n")[1:]:
        if ": " in line:
            key, value = line.split(": ", 1)
            out[key.lower()] = value
    return out


def _frame(payload):
    """A server-to-client text frame: never masked, and short enough to skip 64-bit lengths."""
    data = payload.encode()
    if len(data) < 126:
        header = struct.pack("!BB", 0x81, len(data))
    else:
        header = struct.pack("!BBH", 0x81, 126, len(data))
    return header + data


def _read_frame(sock):
    head = sock.recv(2)
    if len(head) < 2:
        return None
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", sock.recv(2))[0]
    masked = head[1] & 0x80
    mask = sock.recv(4) if masked else b""
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            break
        data += chunk
    if masked:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return data.decode("utf-8", "replace")


class Stub(threading.Thread):
    daemon = True

    def __init__(self):
        threading.Thread.__init__(self)
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.port = self.sock.getsockname()[1]
        self.requests = []  # (method, path, headers, body)
        self.joins = []  # every phx_join payload the client sent
        self.sockets = []

    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def run(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    # -- one connection -----------------------------------------------------------------------

    def _serve(self, conn):
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = conn.recv(4096)
            if not chunk:
                conn.close()
                return
            raw += chunk
        head, _, rest = raw.partition(b"\r\n\r\n")
        text = head.decode()
        method, path, _ = text.split("\r\n")[0].split(" ")
        headers = _headers(text)
        body = rest
        needed = int(headers.get("content-length", 0))
        while len(body) < needed:
            body += conn.recv(4096)
        self.requests.append((method, path, headers, body.decode() or None))

        if headers.get("upgrade", "").lower() == "websocket":
            return self._websocket(conn, headers)
        self._http(conn, method, path, headers, body.decode() or None)

    def _send(self, conn, status, payload, extra=None):
        body = json.dumps(payload).encode() if payload is not None else b""
        lines = [
            f"HTTP/1.1 {status} X",
            "Content-Type: application/json",
            f"Content-Length: {len(body)}",
            "Access-Control-Allow-Origin: *",
            "Access-Control-Allow-Headers: *",
            "Access-Control-Allow-Methods: *",
            "Access-Control-Expose-Headers: Content-Range",
            "Connection: close",
        ]
        for key, value in (extra or {}).items():
            lines.append(f"{key}: {value}")
        conn.sendall(("\r\n".join(lines) + "\r\n\r\n").encode() + body)
        conn.close()

    def _http(self, conn, method, path, headers, body):
        if method == "OPTIONS":
            return self._send(conn, 204, None)
        if path.startswith("/auth/v1/token"):
            payload = json.loads(body or "{}")
            return self._send(
                conn,
                200,
                {"access_token": "jwt-for-" + payload.get("email", "?"), "user": {"email": payload.get("email")}},
            )
        if path.startswith("/rest/v1/secret"):
            # What row-level security looks like on the wire.
            return self._send(
                conn,
                403,
                {"code": "42501", "message": "permission denied for table secret", "hint": "check your policy"},
            )
        if path.startswith("/rest/v1/cities"):
            if method == "POST":
                row = json.loads(body)
                row["id"] = 99
                return self._send(conn, 201, [row])
            rows = CITIES
            if "people=gt." in path:
                floor = int(path.split("people=gt.")[1].split("&")[0])
                rows = [r for r in rows if r["people"] > floor]
            if "limit=" in path:
                rows = rows[: int(path.split("limit=")[1].split("&")[0])]
            return self._send(conn, 200, rows, {"Content-Range": f"0-{len(rows) - 1}/{len(CITIES)}"})
        self._send(conn, 404, {"message": "no such route"})

    # -- the websocket half -------------------------------------------------------------------

    def _websocket(self, conn, headers):
        key = headers.get("sec-websocket-key", "")
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        self.sockets.append(conn)
        while True:
            text = _read_frame(conn)
            if text is None:
                return
            try:
                frame = json.loads(text)
            except ValueError:
                continue
            join_ref, ref, topic, event, payload = frame
            if event == "phx_join":
                self.joins.append(payload)
                conn.sendall(_frame(json.dumps([join_ref, ref, topic, "phx_reply", {"status": "ok", "response": {}}])))

    def push(self, topic, kind, record):
        """Pretend a row changed, the way Realtime would."""
        frame = json.dumps(
            [None, "9", topic, "postgres_changes", {"data": {"type": kind, "table": "cities", "record": record}}]
        )
        for conn in list(self.sockets):
            try:
                conn.sendall(_frame(frame))
            except OSError:
                self.sockets.remove(conn)
