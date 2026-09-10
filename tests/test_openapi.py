"""The document, and the gate it has to meet (`API.md` §6.3).

The gate is §4.6's: the record that validates a form in the page is the record that describes
the body here, so the schema the document publishes must accept **exactly** the values the
route accepts. That is asserted by running both — every case through `from_json_schema` on
the published fragment and through the live route — rather than by reading the two and
agreeing they look alike.
"""

import json

import pytest

from frontage.schema import integer, optional, record, text
from frontage.schema.jsonschema import from_json_schema
from frontage_api import App, Response
from frontage_api.docs import page
from frontage_api.openapi import document
from frontage_api.testing import Client

Trip = record(("id", integer(ge=0)), ("note", optional(text(max=8)), None))


def an_app():
    app = App(title="trips", version="2.0.0", description="the fleet's trips")

    @app.get("/trips/{trip_id}", summary="One trip")
    async def trip(trip_id: int) -> Trip:
        return {"id": trip_id, "note": None}

    @app.post("/trips")
    async def create(body: Trip):
        return {"stored": body["id"]}

    @app.get("/search")
    async def search(q: str = "", n: int = 10):
        return {"q": q, "n": n}

    @app.post("/upload", body=bytes)
    async def upload(body) -> bytes:
        return Response(body)

    @app.get("/healthz", schema=False)
    async def healthz():
        return "ok"

    return app


def test_the_document_describes_every_route_but_the_ones_kept_out():
    doc = an_app().openapi()
    assert doc["openapi"] == "3.1.0"
    assert doc["info"] == {"title": "trips", "version": "2.0.0", "description": "the fleet's trips"}
    assert sorted(doc["paths"]) == ["/search", "/trips", "/trips/{trip_id}", "/upload"]
    # `schema=False` keeps a route out, and the docs' own two routes use it — otherwise every
    # document would describe the page that renders it.
    assert "/healthz" not in doc["paths"]
    assert "/docs" not in doc["paths"] and "/openapi.json" not in doc["paths"]


def test_a_path_parameter_is_required_and_carries_its_type():
    op = an_app().openapi()["paths"]["/trips/{trip_id}"]["get"]
    assert op["summary"] == "One trip"
    assert op["operationId"] == "trip"
    assert op["parameters"] == [{"name": "trip_id", "in": "path", "required": True, "schema": {"type": "integer"}}]


def test_a_query_parameter_is_optional_because_the_handler_owns_its_default():
    op = an_app().openapi()["paths"]["/search"]["get"]
    names = [(p["name"], p["in"], p["required"], p["schema"]) for p in op["parameters"]]
    assert names == [
        ("q", "query", False, {"type": "string"}),
        ("n", "query", False, {"type": "integer"}),
    ]


def test_a_named_record_is_a_ref_and_appears_once():
    doc = an_app().openapi()
    body = doc["paths"]["/trips"]["post"]["requestBody"]
    assert body["required"] is True
    assert body["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/Trip"}
    # The same record as a *return* annotation is the same ref, not a second copy.
    answer = doc["paths"]["/trips/{trip_id}"]["get"]["responses"]["200"]
    assert answer["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/Trip"}
    assert doc["components"]["schemas"]["Trip"] == Trip.json_schema()


def test_an_anonymous_record_stays_inline():
    app = App()

    @app.post("/x")
    async def x(body=None):
        return {}

    app.router.routes[-1].spec["body"] = record(("n", integer()))
    schema = document(app)["paths"]["/x"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert schema["type"] == "object" and "$ref" not in schema


def test_bytes_in_and_out_is_binary_not_json():
    op = an_app().openapi()["paths"]["/upload"]["post"]
    assert op["requestBody"]["content"] == {
        "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
    }
    assert "application/octet-stream" in op["responses"]["200"]["content"]


def test_422_is_promised_only_where_something_can_fail():
    doc = an_app().openapi()
    assert "422" in doc["paths"]["/trips/{trip_id}"]["get"]["responses"]
    assert "422" in doc["paths"]["/trips"]["post"]["responses"]
    ref = doc["paths"]["/trips"]["post"]["responses"]["422"]["content"]["application/json"]["schema"]
    assert ref == {"$ref": "#/components/schemas/ValidationError"}

    plain = App(docs=None, openapi_url="/openapi.json")

    @plain.get("/ping")
    async def ping():
        return "pong"

    assert list(plain.openapi()["paths"]["/ping"]["get"]["responses"]) == ["200"]


def test_two_handlers_of_the_same_name_get_different_operation_ids():
    app = App()

    @app.get("/a")
    async def item():
        return {}

    @app.post("/b")
    async def item():  # noqa: F811 - deliberately the same name
        return {}

    ids = [op["operationId"] for methods in app.openapi()["paths"].values() for op in methods.values()]
    assert sorted(ids) == ["item", "item_post"]


def test_a_docstring_fills_in_the_summary_where_there_is_one():
    """CPython keeps docstrings and the runtime's compiler does not, so this is what a
    developer sees under pytest and `summary=` is what a reader sees in production."""
    app = App()

    @app.get("/d")
    async def d():
        """Does a thing.

        At length.
        """
        return {}

    op = app.openapi()["paths"]["/d"]["get"]
    assert op["summary"] == "Does a thing."
    assert op["description"] == "At length."


def test_the_document_is_built_once():
    app = an_app()
    assert app.openapi() is app.openapi()


# -- the gate (§4.6) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"id": 0},
        {"id": 7, "note": "north"},
        {"id": 7, "note": None},
        {"id": -1},
        {"id": "seven"},
        {"note": "north"},
        {"id": 1, "note": "far too long to fit"},
    ],
)
def test_the_published_schema_accepts_exactly_what_the_route_accepts(payload):
    """§4.6, asserted rather than admired: the same record on both sides of the wire."""
    app = an_app()
    doc = app.openapi()
    published = doc["components"]["schemas"]["Trip"]
    rebuilt = from_json_schema(published)

    try:
        rebuilt.parse(payload)
        schema_took_it = True
    except Exception:
        schema_took_it = False

    answer = Client(app).post("/trips", json=payload)
    route_took_it = answer.status == 200

    assert schema_took_it == route_took_it, (payload, answer.status, answer.body[:120])


def test_the_document_is_json_and_the_server_answers_it():
    app = an_app()
    answer = Client(app).get("/openapi.json")
    assert answer.status == 200
    assert answer.header("content-type") == "application/json"
    assert answer.json() == json.loads(json.dumps(app.openapi()))


def test_the_docs_page_is_one_file_that_fetches_the_document():
    app = an_app()
    answer = Client(app).get("/docs")
    assert answer.status == 200
    assert answer.header("content-type").startswith("text/html")
    html = answer.body.decode("utf-8")
    assert "/openapi.json" in html
    # No CDN, no dependency: whatever it needs is in the file. A private deployment behind
    # the §5a gate must not reach off-host to render its own documentation.
    assert "<script src" not in html and "//cdn" not in html
    assert "trips" in html


def test_the_docs_url_cannot_be_closed_off_the_end_of_the_script():
    assert "<\\/x" in page("/a</x", "t")


def test_the_two_routes_can_be_turned_off():
    app = App(docs=None, openapi_url=None)
    assert app.router.routes == []
    assert Client(app).get("/docs").status == 404
