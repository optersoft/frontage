"""The server's surface (`API.md` §6.2), through the client that has no server under it."""

import pytest

from frontage.schema import integer, optional, record, text
from frontage_api import App, HTTPError, text_response
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
