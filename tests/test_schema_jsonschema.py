"""The JSON Schema bridge, in both directions, on the shape Pydantic and OpenAPI produce."""

import pytest
from frontage_schema import array, email, integer, literal, optional, record, text
from frontage_schema.jsonschema import from_json_schema, to_json_schema

# What `pydantic.BaseModel.model_json_schema()` writes for a model with a nested model, an
# optional int, an EmailStr, a Field(gt=0, le=150), a default and a list.
PYDANTIC = {
    "$defs": {
        "Address": {
            "properties": {"city": {"title": "City", "type": "string"}, "zip": {"title": "Zip", "type": "string", "minLength": 5}},
            "required": ["city", "zip"],
            "title": "Address",
            "type": "object",
        }
    },
    "properties": {
        "id": {"title": "Id", "type": "integer", "minimum": 0},
        "name": {"title": "Name", "type": "string", "minLength": 1, "maxLength": 100},
        "email": {"format": "email", "title": "Email", "type": "string"},
        "age": {"anyOf": [{"exclusiveMinimum": 0, "maximum": 150, "type": "integer"}, {"type": "null"}], "default": None, "title": "Age"},
        "role": {"default": "user", "enum": ["admin", "user"], "title": "Role", "type": "string"},
        "tags": {"default": [], "items": {"type": "string"}, "title": "Tags", "type": "array"},
        "address": {"$ref": "#/$defs/Address"},
        "website": {"anyOf": [{"format": "uri", "type": "string"}, {"type": "null"}], "title": "Website"},
    },
    "required": ["id", "name", "email", "address"],
    "title": "User",
    "type": "object",
}


def test_a_pydantic_document_reads_back_as_the_schema_one_would_write():
    User = from_json_schema(PYDANTIC)
    assert repr(User) == (
        "record(('id', integer(ge=0)), ('name', text(min=1, max=100)), ('email', email()), "
        "('address', record(('city', text()), ('zip', text(min=5)))), "
        "('age', optional(integer(gt=0, le=150)), None), ('role', literal('admin', 'user'), 'user'), "
        "('tags', array(text()), " + repr(User.fields[6][2]) + "), "
        "('website', optional(url()), None))"
    )


def test_the_read_schema_validates_and_fills_defaults():
    User = from_json_schema(PYDANTIC)
    value, errors = User.validate({"id": 1, "name": "A", "email": "a@b.co", "address": {"city": "X", "zip": "08001"}})
    assert errors == []
    assert value["role"] == "user" and value["tags"] == [] and value["age"] is None and value["website"] is None
    assert User.validate({"id": 1, "name": "A", "email": "a@b.co", "address": {"city": "X", "zip": "1"}})[1] == [("$.address.zip", "at least 5 characters")]


def test_a_list_default_is_fresh_per_value():
    User = from_json_schema(PYDANTIC)
    base = {"id": 1, "name": "A", "email": "a@b.co", "address": {"city": "X", "zip": "08001"}}
    assert User.parse(base)["tags"] is not User.parse(base)["tags"]


def test_openapi_refs_and_a_type_list():
    document = {
        "components": {"schemas": {"Item": {"type": "object", "properties": {"n": {"type": ["integer", "null"]}}, "required": ["n"], "additionalProperties": False}}},
    }
    Item = from_json_schema({"$ref": "#/components/schemas/Item"}, document)
    assert repr(Item) == "record(('n', optional(integer())), extra='forbid')"
    with pytest.raises(ValueError, match="unresolved"):
        from_json_schema({"$ref": "#/components/schemas/Nope"}, document)


def test_recursion_is_refused_rather_than_looping():
    document = {"$defs": {"Node": {"type": "object", "properties": {"next": {"$ref": "#/$defs/Node"}}}}, "$ref": "#/$defs/Node"}
    with pytest.raises(ValueError, match="recursive"):
        from_json_schema(document)


def test_const_enum_mapping_and_draft4_bounds():
    assert repr(from_json_schema({"const": 3})) == "literal(3)"
    assert repr(from_json_schema({"type": "object", "additionalProperties": {"type": "number"}})) == "mapping(number())"
    assert repr(from_json_schema({"type": "integer", "minimum": 0, "exclusiveMinimum": True})) == "integer(gt=0)"
    assert repr(from_json_schema({"type": "string", "pattern": "^a+$"})) == "text(pattern='^a+$')"
    assert repr(from_json_schema({"anyOf": [{"type": "integer"}, {"type": "string"}]})) == "one_of(integer(), text())"


def test_a_pattern_with_a_counted_repeat_is_refused():
    with pytest.raises(ValueError, match="counted repeats"):
        from_json_schema({"type": "string", "pattern": "^[0-9]{5}$"})


def test_to_json_schema_is_what_from_json_schema_reads():
    User = record(("id", integer(ge=0)), ("email", email()), ("age", optional(integer(gt=0)), None), ("kind", literal("a", "b"), "a"), ("tags", array(text(max=3))))
    document = to_json_schema(User)
    assert document == {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "minimum": 0},
            "email": {"type": "string", "format": "email"},
            "age": {"anyOf": [{"type": "integer", "exclusiveMinimum": 0}, {"type": "null"}], "default": None},
            "kind": {"enum": ["a", "b"], "default": "a"},
            "tags": {"type": "array", "items": {"type": "string", "maxLength": 3}},
        },
        "required": ["id", "email", "tags"],
    }
    assert repr(from_json_schema(document)) == repr(User)
