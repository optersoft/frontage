"""The server's surface (`API.md` §6.2), through the client that has no server under it."""

import asyncio

import pytest

from frontage.schema import integer, optional, record, text
from frontage_api import App, Cors, Depends, HTTPError, Stream, sse, text_response
from frontage_api.routing import Route, Router, compile_path
from frontage_api.testing import Client


def test_compile_path_splits_literals_and_parameters():
    assert compile_path("/trips/{trip_id}/legs") == (["trips", None, "legs"], ["trip_id"])
    assert compile_path("/") == ([""], [])


@pytest.mark.parametrize("bad", ["trips", "/trips/{}", "/trips/{a}/{a}", "/trips/x{a}"])
def test_a_path_that_is_not_one_is_refused_at_declaration(bad):
    with pytest.raises(ValueError):
        compile_path(bad)


def test_routes_match_in_declaration_order():
    router = Router()
    router.add(Route("GET", "/trips/new", lambda: None, {}))
    router.add(Route("GET", "/trips/{id}", lambda: None, {}))
    assert router.find("GET", "/trips/new")[0].path == "/trips/new"
    assert router.find("GET", "/trips/42") == (router.routes[1], {"id": "42"})


def test_a_trailing_slash_matches():
    router = Router()
    router.add(Route("GET", "/trips", lambda: None, {}))
    assert router.find("GET", "/trips/")[0] is not None


@pytest.fixture
def client():
    app = App()
    Trip = record(("id", integer(ge=0)), ("note", optional(text()), None))

    @app.get("/hello")
    async def hello():
        return {"hello": "world"}

    @app.get("/trips/{trip_id}", path_types={"trip_id": int})
    async def trip(trip_id):
        if trip_id == 9:
            raise HTTPError(404, "no such trip")
        return {"id": trip_id}

    @app.post("/trips", body=Trip)
    async def create(body):
        return {"stored": body}

    @app.get("/search", query={"q": str, "n": int, "deep": bool})
    async def search(q="", n=10, deep=False):
        return {"q": q, "n": n, "deep": deep}

    @app.get("/plain")
    async def plain():
        return text_response("just words")

    @app.delete("/trips/{trip_id}", path_types={"trip_id": int})
    async def remove(trip_id):
        return None

    @app.get("/boom")
    async def boom():
        raise ZeroDivisionError("division by zero")

    @app.get("/sync")
    def sync_handler():
        return {"sync": True}

    return Client(app)


def test_a_dict_answers_as_json(client):
    answer = client.get("/hello")
    assert answer.status == 200
    assert answer.json() == {"hello": "world"}
    assert answer.header("content-type") == "application/json"


def test_a_path_parameter_is_converted(client):
    assert client.get("/trips/42").json() == {"id": 42}


def test_a_path_parameter_that_will_not_convert_is_422(client):
    answer = client.get("/trips/abc")
    assert answer.status == 422
    assert answer.json()["detail"][0]["loc"] == "path.trip_id"


def test_http_error_carries_its_status_and_detail(client):
    answer = client.get("/trips/9")
    assert (answer.status, answer.json()) == (404, {"detail": "no such trip"})


def test_an_unknown_path_is_404_and_a_wrong_method_is_405(client):
    assert client.get("/nope").status == 404
    answer = client.post("/hello", json={})
    assert answer.status == 405
    assert answer.header("allow") == "GET"


def test_a_body_is_validated_by_the_schema(client):
    answer = client.post("/trips", json={"id": 7, "note": "north"})
    assert answer.json() == {"stored": {"id": 7, "note": "north"}}


def test_a_body_that_fails_the_schema_is_422_with_the_field(client):
    answer = client.post("/trips", json={"id": -1})
    assert answer.status == 422
    assert answer.json()["detail"][0]["loc"].startswith("body")


def test_a_body_that_is_not_json_is_400(client):
    answer = client.post("/trips", body=b"{oh no")
    assert (answer.status, answer.json()) == (400, {"detail": "the body is not JSON"})


def test_query_parameters_convert_and_keep_their_defaults(client):
    assert client.get("/search?q=hello+world&n=3&deep=true").json() == {
        "q": "hello world",
        "n": 3,
        "deep": True,
    }
    assert client.get("/search").json() == {"q": "", "n": 10, "deep": False}


def test_a_response_object_sets_its_own_type(client):
    answer = client.get("/plain")
    assert answer.text() == "just words"
    assert answer.header("content-type") == "text/plain; charset=utf-8"


def test_none_is_204_with_no_body(client):
    answer = client.delete("/trips/3")
    assert (answer.status, answer.body) == (204, b"")


def test_a_handler_that_raises_is_500_and_says_so_once(client):
    answer = client.get("/boom")
    assert answer.status == 500
    assert "division by zero" in answer.json()["detail"]


def test_a_plain_def_handler_works_too(client):
    assert client.get("/sync").json() == {"sync": True}


def test_the_same_record_checks_a_form_and_a_body():
    """§4.6, which is the whole pitch: one record, both sides, one file."""
    Booking = record(("email", text(min=3)), ("nights", integer(ge=1, le=30)))

    app = App()

    @app.post("/book", body=Booking)
    async def book(body):
        return body

    client = Client(app)
    # What the server accepts on the wire.
    assert client.post("/book", json={"email": "a@b.c", "nights": 2}).status == 200
    assert client.post("/book", json={"email": "a@b.c", "nights": 99}).status == 422
    # What the page accepts from a form, from the very same object, strings and all.
    assert Booking.validate({"email": "a@b.c", "nights": "2"}, coerce=True)[1] == []
    assert Booking.validate({"email": "a@b.c", "nights": "99"}, coerce=True)[1] != []


# --- dependencies, lifespan and CORS (API.md §4.7, §4.8) ------------------------------------


def test_a_dependency_is_resolved_and_shared_within_one_request():
    calls = []

    def counter():
        calls.append(1)
        return len(calls)

    app = App()

    def inner(headers):
        return counter()

    @app.get("/twice", needs={"a": Depends(inner), "b": Depends(inner)})
    async def twice(a, b):
        return {"a": a, "b": b}

    answer = Client(app).get("/twice")
    assert answer.json() == {"a": 1, "b": 1}, "resolved once, shared by both"
    assert len(calls) == 1


def test_a_dependency_reads_the_request_the_way_a_handler_does():
    app = App()

    def who(headers):
        token = headers.get("authorization")
        if token is None:
            raise HTTPError(401, "sign in")
        return token.replace("Bearer ", "")

    @app.get("/me", needs={"user": Depends(who)})
    async def me(user):
        return {"user": user}

    client = Client(app)
    assert client.get("/me", headers=[("authorization", "Bearer ada")]).json() == {"user": "ada"}
    assert client.get("/me").status == 401


def test_a_generator_dependency_runs_its_second_half_after_the_answer():
    order = []

    def handle():
        order.append("open")
        yield "the handle"
        order.append("close")

    app = App()

    @app.get("/use", needs={"h": Depends(handle)})
    async def use(h):
        order.append("handler")
        return {"h": h}

    answer = Client(app).get("/use")
    assert answer.json() == {"h": "the handle"}
    assert order == ["open", "handler", "close"]


def test_an_async_dependency_is_awaited():
    app = App()

    async def slow():
        return 7

    @app.get("/n", needs={"n": Depends(slow)})
    async def n(n):
        return {"n": n}

    assert Client(app).get("/n").json() == {"n": 7}


def test_headers_and_scope_reach_a_handler_by_name():
    app = App()

    @app.get("/echo-header")
    async def echo_header(headers, scope):
        return {"ua": headers.get("user-agent"), "path": scope["path"]}

    answer = Client(app).get("/echo-header", headers=[("User-Agent", "probe")])
    assert answer.json() == {"ua": "probe", "path": "/echo-header"}


def test_cors_answers_a_listed_origin_and_ignores_another():
    app = App(cors=["https://example.com"])

    @app.get("/data")
    async def data():
        return {"ok": True}

    client = Client(app)
    good = client.get("/data", headers=[("origin", "https://example.com")])
    assert good.header("access-control-allow-origin") == "https://example.com"
    assert good.header("vary") == "origin"
    other = client.get("/data", headers=[("origin", "https://evil.example")])
    assert other.header("access-control-allow-origin") is None


def test_a_preflight_is_answered_from_what_the_path_accepts():
    app = App(cors=["*"])

    @app.post("/submit")
    async def submit(body):
        return body

    answer = Client(app).request("OPTIONS", "/submit", headers=[("origin", "https://any.example")])
    assert answer.status == 204
    assert answer.header("access-control-allow-origin") == "*"
    assert "POST" in answer.header("access-control-allow-methods")
    assert answer.header("allow") == "POST"


def test_star_with_credentials_echoes_the_origin_rather_than_a_star():
    """`*` is not a legal answer with credentials, and a browser refuses the pair."""
    app = App(cors=Cors(["*"], credentials=True))

    @app.get("/who")
    async def who():
        return {}

    answer = Client(app).get("/who", headers=[("origin", "https://a.example")])
    assert answer.header("access-control-allow-origin") == "https://a.example"
    assert answer.header("access-control-allow-credentials") == "true"


def test_lifespan_runs_per_worker_in_order():
    order = []
    app = App()

    @app.on_startup
    def up():
        order.append("up")

    @app.on_shutdown
    async def down():
        order.append("down")

    import asyncio

    asyncio.run(app.startup())
    asyncio.run(app.shutdown())
    assert order == ["up", "down"]


# --- streaming (API.md §6.2) ----------------------------------------------------------------


def _drain(chunks):
    import asyncio

    async def go():
        out = []
        while True:
            piece = await chunks.next()
            if piece is None:
                return out
            out.append(piece)

    return asyncio.run(go())


def test_a_stream_over_a_generator_yields_each_piece():
    from frontage_api.streaming import Chunks

    def frames():
        yield "a"
        yield b"b"
        yield {"c": 1}

    assert _drain(Chunks(frames())) == [b"a", b"b", b'{"c": 1}']


def test_a_stream_over_a_producer_hands_pieces_out_one_at_a_time():
    from frontage_api.streaming import Chunks

    async def produce(send):
        for i in range(3):
            await send("n%d" % i)

    assert _drain(Chunks(produce)) == [b"n0", b"n1", b"n2"]


def test_a_producer_that_raises_ends_the_stream_with_its_error():
    from frontage_api.streaming import Chunks

    async def produce(send):
        await send("first")
        raise ValueError("halfway")

    import asyncio

    async def go():
        chunks = Chunks(produce)
        assert await chunks.next() == b"first"
        try:
            await chunks.next()
        except ValueError as exc:
            return str(exc)
        return "no error"

    assert asyncio.run(go()) == "halfway"


def test_sse_frames_survive_a_newline():
    from frontage_api import sse

    assert sse("a\nb") == 'data: "a\\nb"\n\n'


def test_an_event_stream_gets_the_headers_a_proxy_needs():
    app = App()

    @app.get("/events")
    async def events():
        def frames():
            yield sse({"n": 1})

        return Stream(frames(), media_type="text/event-stream")

    status, headers, body = asyncio.run(app.handle({"method": "GET", "path": "/events"}))
    names = {name: value for name, value in headers}
    assert names["content-type"] == "text/event-stream"
    assert names["cache-control"] == "no-cache"
    assert names["x-accel-buffering"] == "no", "a proxy would otherwise buffer the whole stream"
    assert _drain(body) == [b'data: {"n": 1}\n\n'], "the body is a source, not bytes"


# --- a route read from the signature (API.md §6.2) -------------------------------------------


def test_a_route_reads_its_types_from_annotations():
    app = App()
    Trip = record(("id", integer(ge=0)), ("note", optional(text()), None))

    @app.get("/trips/{trip_id}")
    async def trip(trip_id: int, verbose: bool = False):
        return {"id": trip_id, "verbose": verbose}

    @app.post("/trips")
    async def create(body: Trip):  # ty: ignore[invalid-type-form]
        return {"stored": body}

    client = Client(app)
    assert client.get("/trips/7?verbose=true").json() == {"id": 7, "verbose": True}
    assert client.get("/trips/nope").status == 422, "the path type came from the signature"
    assert client.post("/trips", json={"id": 1}).json() == {"stored": {"id": 1, "note": None}}
    assert client.post("/trips", json={"id": -1}).status == 422


def test_the_decorator_still_wins_over_a_signature():
    app = App()

    @app.get("/n/{n}", path_types={"n": str})
    async def n(n: int):
        return {"n": n, "kind": type(n).__name__}

    assert Client(app).get("/n/abc").json() == {"n": "abc", "kind": "str"}


def test_a_request_name_is_not_turned_into_a_query_parameter():
    app = App()

    @app.get("/h")
    async def h(headers: str = ""):
        return {"kind": type(headers).__name__}

    assert Client(app).get("/h").json() == {"kind": "Headers"}


def test_an_annotation_nothing_can_resolve_is_ignored_not_an_error():
    app = App()

    @app.get("/x")
    async def x(thing: "SomethingUndefined" = "default"):  # noqa: F821  # ty: ignore[unresolved-reference]
        return {"thing": thing}

    assert Client(app).get("/x?thing=given").json() == {"thing": "default"}


def test_every_method_decorator_takes_exactly_the_arguments_route_does():
    """The seven decorators are written out, not installed in a loop, so a type checker and
    an editor can see them (`frontage_api/__init__.py`). This is what guards the duplication:
    an argument added to `route` and forgotten on the seven fails here instead of being
    silently dropped."""
    import inspect

    wanted = list(inspect.signature(App.route).parameters)
    wanted.remove("method")  # each decorator supplies its own
    for name in ("get", "post", "put", "patch", "delete", "head", "options"):
        assert list(inspect.signature(getattr(App, name)).parameters) == wanted, name
