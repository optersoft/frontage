"""Realtime: the database pushes, a signal takes the value, one hole updates.

This is the answer to Streamlit's live dashboard, which is a script re-run on a timer. Here a
row changes in Postgres, the change arrives over a websocket, and the only parts of the page
that read it are the parts that change. Nothing polls and no server of ours is involved.

Supabase Realtime speaks Phoenix channels: every frame is a JSON array

    [join_ref, ref, topic, event, payload]

and a subscription is a `phx_join` on `realtime:<name>` whose payload names the tables to watch.
Written against the browser's own `WebSocket` because MicroPython can reach it through `js`, so
this package still ships no JavaScript.
"""

import json

from frontage import Signal, on_cleanup
from frontage.runtime import create_proxy, window

__all__ = ["Channel"]

HEARTBEAT_MS = 25_000  # Realtime closes an idle socket at 60s; a comfortable third of that
VERSION = "1.0.0"


class Channel:
    """One subscription. `changes` is a signal holding the last change; `rows` keeps a list in
    step with the table if you give it one to start from."""

    def __init__(self, client, table, event="*", schema="public", filter=None, name=None):
        self._client = client
        self._table = table
        self._event = event
        self._schema = schema
        self._filter = filter
        self._topic = "realtime:" + (name or (schema + ":" + table))
        self._socket = None
        self._proxies = []
        self._timer = None
        self._ref = 0
        self._joined = False

        self.change = Signal(None)  # the last {type, record, old_record}
        self.state = Signal("closed")  # closed | connecting | joined | errored
        self.error = Signal(None)

    # -- lifecycle ----------------------------------------------------------------------------

    def subscribe(self):
        """Open the socket and join. Closes itself when the owning view is disposed, so a
        channel opened inside a component does not outlive it."""
        if self._socket is not None:
            return self
        token = self._client.token() or self._client.key
        url = self._client.url.replace("https://", "wss://").replace("http://", "ws://")
        url = url + "/realtime/v1/websocket?vsn=" + VERSION
        if self._client.key:
            url = url + "&apikey=" + self._client.key
        self.state.set("connecting")
        self._socket = window.WebSocket.new(url)
        self._listen("open", lambda ev: self._on_open(token))
        self._listen("message", self._on_message)
        self._listen("error", self._on_error)
        self._listen("close", lambda ev: self.state.set("closed"))
        on_cleanup(self.close)
        return self

    def close(self):
        if self._timer is not None:
            window.clearInterval(self._timer)
            self._timer = None
        socket, self._socket = self._socket, None
        if socket is not None:
            try:
                socket.close()
            except Exception:  # a socket that never opened throws on close in some browsers
                pass
        for proxy in self._proxies:
            destroy = getattr(proxy, "destroy", None)
            if destroy is not None:
                destroy()
        self._proxies = []
        self._joined = False
        self.state.set("closed")

    def _listen(self, event, handler):
        proxy = create_proxy(handler)
        self._proxies.append(proxy)
        assert self._socket is not None
        self._socket.addEventListener(event, proxy)

    # -- the protocol -------------------------------------------------------------------------

    def _next_ref(self):
        self._ref += 1
        return str(self._ref)

    def _send(self, topic, event, payload, join_ref=None):
        if self._socket is None:
            return
        self._socket.send(json.dumps([join_ref, self._next_ref(), topic, event, payload]))

    def _on_open(self, token):
        change = {"event": self._event, "schema": self._schema, "table": self._table}
        if self._filter:
            change["filter"] = self._filter
        self._send(
            self._topic,
            "phx_join",
            {"config": {"postgres_changes": [change], "private": False}},
            join_ref="1",
        )
        if token:
            # Sent separately from the join, because Realtime checks the JWT against the row
            # policies for every change it forwards, not once at connect.
            self._send(self._topic, "access_token", {"access_token": token})
        self._timer = window.setInterval(create_proxy(self._heartbeat), HEARTBEAT_MS)

    def _heartbeat(self):
        self._send("phoenix", "heartbeat", {})

    def _on_message(self, event):
        try:
            frame = json.loads(event.data)
        except (ValueError, TypeError):
            return
        if not isinstance(frame, list) or len(frame) < 5:
            return
        _, _, topic, name, payload = frame[0], frame[1], frame[2], frame[3], frame[4]
        if name == "phx_reply" and topic == self._topic:
            status = (payload or {}).get("status")
            if status == "ok":
                self._joined = True
                self.state.set("joined")
            else:
                self.state.set("errored")
                self.error.set((payload or {}).get("response"))
        elif name == "postgres_changes":
            data = (payload or {}).get("data") or {}
            self.change.set(
                {
                    "type": data.get("type"),
                    "record": data.get("record"),
                    "old": data.get("old_record"),
                    "table": data.get("table"),
                }
            )

    def _on_error(self, event):
        self.state.set("errored")
        self.error.set("websocket error")

    # -- a list that keeps itself in step -----------------------------------------------------

    def follow(self, rows, key="id"):
        """Apply every change to a list signal, so a table shows the database as it is now.

        `rows` is a `Signal` holding a list of dicts — usually seeded from a first read. This is
        deliberately the whole of the reconciliation: an INSERT appends, an UPDATE replaces by
        key, a DELETE removes. Anything cleverer (ordering, filtering, a window) belongs to the
        app, which knows what its query meant and this does not.
        """

        def apply(change, previous):
            if not change:
                return
            kind = change["type"]
            record = change["record"] or change["old"] or {}
            identity = record.get(key)

            def updated(current):
                current = list(current or ())
                if kind == "DELETE":
                    return [r for r in current if r.get(key) != identity]
                if kind == "INSERT":
                    if any(r.get(key) == identity for r in current):
                        return current
                    return current + [change["record"]]
                return [change["record"] if r.get(key) == identity else r for r in current]

            rows.update(updated)

        from frontage import Effect

        Effect(self.change, apply)
        return self
