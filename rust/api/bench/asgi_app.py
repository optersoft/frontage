"""The same routes as `../examples/spike/app.py`, as a bare ASGI app with no framework.

This is the honest like-for-like for the *server*: routing, conversion and checking are all
hand-written here, which is what "no framework" has to mean if the columns are to compare.
`fastapi_app.py` is the one §6.1 sets its gate against.
"""

import json

PAYLOAD = b"x" * 1024
TRIPS = {1: {"id": 1, "note": "north"}, 2: {"id": 2, "note": None}}
JSON = [(b"content-type", b"application/json")]


async def read(receive):
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    return body


async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    path, method = scope["path"], scope["method"]
    status, headers, body = 404, JSON, b'{"detail": "not found"}'

    if path == "/hello":
        status, headers, body = 200, [(b"content-type", b"text/plain; charset=utf-8")], PAYLOAD
    elif path == "/echo":
        status, headers, body = 200, [(b"content-type", b"application/octet-stream")], await read(receive)
    elif path.startswith("/trips/"):
        raw = path[len("/trips/"):]
        try:
            trip_id = int(raw)
        except ValueError:
            status, body = 422, b'{"detail": "trip_id is not an integer"}'
        else:
            row = TRIPS.get(trip_id)
            status, body = (200, json.dumps(row).encode()) if row else (404, b'{"detail": "no such trip"}')
        headers = JSON
    elif path == "/trips" and method == "POST":
        headers = JSON
        try:
            payload = json.loads(await read(receive))
        except ValueError:
            status, body = 400, b'{"detail": "the body is not JSON"}'
        else:
            trip_id, note = payload.get("id"), payload.get("note")
            if not isinstance(trip_id, int) or isinstance(trip_id, bool) or trip_id < 0:
                status, body = 422, b'{"detail": "id must be an integer at least 0"}'
            elif note is not None and not isinstance(note, str):
                status, body = 422, b'{"detail": "note must be a string"}'
            else:
                TRIPS[trip_id] = {"id": trip_id, "note": note}
                status, body = 200, json.dumps({"stored": trip_id}).encode()
    elif path == "/search":
        query = {}
        for pair in scope.get("query_string", b"").decode().split("&"):
            key, _, value = pair.partition("=")
            query[key] = value
        status, headers = 200, JSON
        body = json.dumps({"q": query.get("q", ""), "n": int(query.get("n") or 10)}).encode()

    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
