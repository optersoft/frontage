"""frontage-supabase: the Phoenix frames the channel sends, and what it does with what arrives.

Supabase Realtime is a Phoenix channel over a websocket: every frame is a JSON array
`[join_ref, ref, topic, event, payload]`. That framing is the whole of what this package owns,
so these tests hold a fake socket and read what was written to it. Whether Supabase then
forwards the row is Supabase's business, and no test here has talked to it.
"""

import json

from frontage import Signal
from frontage.supabase import Channel, Client


class FakeSocket:
    def __init__(self, url):
        self.url = url
        self.sent = []
        self.listeners = {}
        self.closed = False

    def addEventListener(self, event, handler):  # noqa: N802 - the browser's spelling
        self.listeners.setdefault(event, []).append(handler)

    def send(self, text):
        self.sent.append(json.loads(text))

    def close(self):
        self.closed = True

    # -- driving it from a test ---------------------------------------------------------------

    def fire(self, event, payload=None):
        for handler in self.listeners.get(event, []):
            handler(payload)

    def deliver(self, frame):
        class Message:
            data = json.dumps(frame)

        self.fire("message", Message())

    def frames(self, event):
        return [f for f in self.sent if f[3] == event]


class FakeWindow:
    def __init__(self):
        self.sockets = []
        self.intervals = []

        outer = self

        class WebSocket:
            @staticmethod
            def new(url):
                socket = FakeSocket(url)
                outer.sockets.append(socket)
                return socket

        self.WebSocket = WebSocket

    def setInterval(self, fn, ms):  # noqa: N802 - the browser's spelling
        self.intervals.append((fn, ms))
        return len(self.intervals)

    def clearInterval(self, handle):  # noqa: N802 - the browser's spelling
        self.intervals[handle - 1] = None


def channel(monkeypatch, **kwargs):
    from frontage.supabase import realtime as module

    window = FakeWindow()
    monkeypatch.setattr(module, "window", window)
    monkeypatch.setattr(module, "create_proxy", lambda fn: fn)
    monkeypatch.setattr(module, "on_cleanup", lambda fn: None)
    client = Client("https://project.supabase.co", "anon-key")
    return window, Channel(client, kwargs.pop("table", "cities"), **kwargs).subscribe()


def test_the_socket_url_is_the_project_over_wss_with_the_key(monkeypatch):
    window, _ = channel(monkeypatch)
    url = window.sockets[0].url
    assert url.startswith("wss://project.supabase.co/realtime/v1/websocket?")
    assert "vsn=1.0.0" in url and "apikey=anon-key" in url


def test_a_plain_http_postgrest_gets_ws_not_wss(monkeypatch):
    from frontage.supabase import realtime as module

    window = FakeWindow()
    monkeypatch.setattr(module, "window", window)
    monkeypatch.setattr(module, "create_proxy", lambda fn: fn)
    monkeypatch.setattr(module, "on_cleanup", lambda fn: None)
    Channel(Client("http://localhost:4000"), "t").subscribe()
    assert window.sockets[0].url.startswith("ws://localhost:4000/")


def test_opening_joins_the_topic_and_names_the_table(monkeypatch):
    window, _ = channel(monkeypatch, table="orders", event="INSERT")
    socket = window.sockets[0]
    socket.fire("open")
    join = socket.frames("phx_join")[0]
    assert join[2] == "realtime:public:orders"
    watched = join[4]["config"]["postgres_changes"][0]
    assert watched == {"event": "INSERT", "schema": "public", "table": "orders"}


def test_a_filter_travels_with_the_subscription(monkeypatch):
    window, _ = channel(monkeypatch, filter="region=eq.Galicia")
    window.sockets[0].fire("open")
    watched = window.sockets[0].frames("phx_join")[0][4]["config"]["postgres_changes"][0]
    assert watched["filter"] == "region=eq.Galicia"


def test_the_token_is_sent_separately_from_the_join(monkeypatch):
    """Realtime checks the JWT against the policies for every change, not once at connect."""
    from frontage.supabase import realtime as module

    window = FakeWindow()
    monkeypatch.setattr(module, "window", window)
    monkeypatch.setattr(module, "create_proxy", lambda fn: fn)
    monkeypatch.setattr(module, "on_cleanup", lambda fn: None)
    client = Client("https://project.supabase.co", "anon-key", token="jwt-123")
    Channel(client, "cities").subscribe()
    window.sockets[0].fire("open")
    sent = window.sockets[0].frames("access_token")
    assert sent and sent[0][4] == {"access_token": "jwt-123"}


def test_a_heartbeat_is_scheduled_and_is_a_phoenix_frame(monkeypatch):
    window, _ = channel(monkeypatch)
    window.sockets[0].fire("open")
    assert window.intervals, "an idle Realtime socket is closed at sixty seconds"
    beat, ms = window.intervals[0]
    assert ms < 60_000
    beat()
    assert window.sockets[0].frames("heartbeat")[0][2] == "phoenix"


def test_a_successful_reply_marks_the_channel_joined(monkeypatch):
    window, chan = channel(monkeypatch)
    assert chan.state() == "connecting"
    window.sockets[0].deliver([None, "1", chan._topic, "phx_reply", {"status": "ok", "response": {}}])
    assert chan.state() == "joined"


def test_a_refused_join_is_reported_rather_than_looking_connected(monkeypatch):
    window, chan = channel(monkeypatch)
    window.sockets[0].deliver(
        [None, "1", chan._topic, "phx_reply", {"status": "error", "response": {"reason": "unauthorized"}}]
    )
    assert chan.state() == "errored"
    assert chan.error() == {"reason": "unauthorized"}


def test_a_change_becomes_the_signal(monkeypatch):
    window, chan = channel(monkeypatch)
    window.sockets[0].deliver(
        [
            None,
            "2",
            chan._topic,
            "postgres_changes",
            {"data": {"type": "INSERT", "table": "cities", "record": {"id": 9, "name": "Girona"}}},
        ]
    )
    assert chan.change()["type"] == "INSERT"
    assert chan.change()["record"]["name"] == "Girona"


def test_a_frame_that_is_not_ours_is_ignored_rather_than_crashing(monkeypatch):
    window, chan = channel(monkeypatch)
    window.sockets[0].deliver({"not": "an array"})
    window.sockets[0].fire("message", type("M", (), {"data": "}{ not json"})())
    assert chan.change() is None


def test_closing_stops_the_heartbeat_and_the_socket(monkeypatch):
    window, chan = channel(monkeypatch)
    window.sockets[0].fire("open")
    chan.close()
    assert window.sockets[0].closed
    assert window.intervals[0] is None
    assert chan.state() == "closed"


# -- follow ----------------------------------------------------------------------------------


def test_follow_appends_replaces_and_removes(monkeypatch):
    window, chan = channel(monkeypatch)
    rows = Signal([{"id": 1, "name": "ada"}])
    chan.follow(rows)

    def change(kind, record, old=None):
        window.sockets[0].deliver(
            [None, "2", chan._topic, "postgres_changes", {"data": {"type": kind, "record": record, "old_record": old}}]
        )

    change("INSERT", {"id": 2, "name": "grace"})
    assert [r["id"] for r in rows()] == [1, 2]
    change("UPDATE", {"id": 1, "name": "Ada L"})
    assert rows()[0]["name"] == "Ada L"
    change("DELETE", None, {"id": 1})
    assert [r["id"] for r in rows()] == [2]


def test_follow_ignores_an_insert_it_already_has(monkeypatch):
    """A page that read the row and then got its change must not show it twice."""
    window, chan = channel(monkeypatch)
    rows = Signal([{"id": 1}])
    chan.follow(rows)
    window.sockets[0].deliver(
        [None, "2", chan._topic, "postgres_changes", {"data": {"type": "INSERT", "record": {"id": 1}}}]
    )
    assert len(rows()) == 1
