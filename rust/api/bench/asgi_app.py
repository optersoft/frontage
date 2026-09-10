"""The same two routes as `examples/spike/app.py`, as a bare ASGI app.

This is the honest like-for-like at spike stage: our server has no framework layer yet
either, so this separates the *server* from the framework FastAPI puts on top of it.
`fastapi_app.py` is the gate of `API.md` §6.1.
"""

PAYLOAD = b"x" * 1024


async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    if scope["path"] == "/hello":
        body = PAYLOAD
    else:
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body", False):
                break
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"application/octet-stream")]})
    await send({"type": "http.response.body", "body": body})
