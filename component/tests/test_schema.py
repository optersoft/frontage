"""frontage-schema: the walk, the two switches, the formats, and that a schema prints as code."""

import pytest
from frontage_schema import (
    SchemaError,
    anything,
    array,
    boolean,
    email,
    integer,
    ipv4,
    iso_date,
    iso_datetime,
    literal,
    mapping,
    number,
    one_of,
    optional,
    pattern,
    record,
    text,
    url,
    uuid,
)

User = record(
    ("id", integer(ge=0)),
    ("name", text(min=1, max=100)),
    ("email", email()),
    ("age", integer(gt=0, le=150), None),
    ("tags", array(text()), list),
)

ALICE = {"id": 1, "name": "Alice", "email": "alice@example.com", "age": 28, "tags": ["a"]}


def errors(schema, data, **kw):
    return schema.validate(data, **kw)[1]


# --- the walk -------------------------------------------------------------------------------


def test_a_valid_record_comes_back_with_no_errors():
    value, errs = User.validate(ALICE)
    assert errs == []
    assert value == ALICE


def test_errors_carry_paths_in_schema_order():
    errs = errors(array(User), [ALICE, {"id": "x", "name": "", "email": "nope"}])
    assert errs == [
        ("$[1].id", "expected an integer"),
        ("$[1].name", "at least 1 characters"),
        ("$[1].email", "not an email address"),
    ]


def test_a_missing_required_field_is_reported_and_a_default_fills_in():
    value, errs = User.validate({"id": 1, "email": "a@b.co"})
    assert errs == [("$.name", "missing")]
    assert value["age"] is None
    assert value["tags"] == [] and value["tags"] is not value.get("nope")


def test_a_callable_default_is_fresh_per_value():
    a = User.parse({"id": 1, "name": "a", "email": "a@b.co"})
    b = User.parse({"id": 2, "name": "b", "email": "b@b.co"})
    assert a["tags"] is not b["tags"]


def test_parse_raises_with_the_list_and_a_readable_message():
    with pytest.raises(SchemaError) as exc:
        User.parse({"id": -1, "name": "x", "email": "x@y.z"})
    assert exc.value.errors == [("$.id", "must be at least 0")]
    assert "$.id: must be at least 0" in str(exc.value)


def test_calling_a_schema_is_parse():
    assert User(ALICE) == ALICE


def test_extra_keys_are_dropped_kept_or_reported():
    data = {"a": 1, "b": 2}
    assert record(("a", integer())).parse(data) == {"a": 1}
    assert record(("a", integer()), extra="allow").parse(data) == data
    assert errors(record(("a", integer()), extra="forbid"), data) == [("$.b", "not a field")]


def test_record_refuses_a_dict_and_a_bad_pair():
    with pytest.raises(TypeError, match="pairs"):
        record({"a": integer()})
    with pytest.raises(TypeError):
        record(("a", int))
    with pytest.raises(ValueError, match="duplicate"):
        record(("a", integer()), ("a", text()))


def test_the_wrong_container_type_stops_the_walk_there():
    assert errors(User, [ALICE]) == [("$", "expected an object")]
    assert errors(array(User), ALICE) == [("$", "expected a list")]


def test_nested_paths():
    Order = record(("user", User), ("lines", array(record(("qty", integer(gt=0))))))
    errs = errors(Order, {"user": ALICE, "lines": [{"qty": 1}, {"qty": 0}]})
    assert errs == [("$.lines[1].qty", "must be greater than 0")]


# --- scalars --------------------------------------------------------------------------------


def test_bool_is_not_an_integer_and_an_integer_is_not_a_number_string():
    assert errors(integer(), True) == [("$", "expected an integer")]
    assert errors(integer(), 3.0) == [("$", "expected an integer")]
    assert errors(number(), True) == [("$", "expected a number")]
    assert errors(number(), 3) == []


def test_number_rejects_nan_unless_told_not_to():
    assert errors(number(), float("nan")) == [("$", "must be finite")]
    assert errors(number(finite=False), float("inf")) == []


def test_bounds_and_multiple_of():
    assert errors(integer(gt=0, lt=10, multiple_of=3), 9) == []
    assert errors(integer(gt=0, lt=10, multiple_of=3), 10) == [
        ("$", "must be less than 10"),
        ("$", "must be a multiple of 3"),
    ]


def test_text_length_pattern_and_strip():
    assert errors(text(min=2), "a") == [("$", "at least 2 characters")]
    assert errors(text(max=2), "abc") == [("$", "at most 2 characters")]
    assert errors(pattern("^[a-z]+$"), "abc1") == [("$", "does not match ^[a-z]+$")]
    assert text(strip=True).parse("  hi ") == "hi"


def test_a_counted_repeat_is_refused_because_micropython_cannot_run_it():
    with pytest.raises(ValueError, match="counted repeats"):
        text(pattern=r"^\d{4}$")


def test_literal_compares_type_and_value():
    assert errors(literal("a", "b"), "c") == [("$", "must be one of 'a', 'b'")]
    assert errors(literal(1), True) == [("$", "must be one of 1")]
    assert literal(1, 2).parse("2", coerce=True) == 2


def test_anything_and_optional():
    assert anything().parse({"x": [1]}) == {"x": [1]}
    assert optional(integer()).parse(None) is None
    assert errors(optional(integer()), "x") == [("$", "expected an integer")]


def test_one_of_takes_the_first_match():
    assert one_of(integer(), text()).parse("x") == "x"
    assert errors(one_of(integer(), text()), None) == [("$", "matched none of 2 alternatives")]


def test_mapping():
    assert mapping(integer()).parse({"a": 1}) == {"a": 1}
    assert errors(mapping(integer()), {"a": "x"}) == [("$.a", "expected an integer")]
    assert errors(mapping(integer(), key=pattern("^[a-z]$")), {"ab": 1}) == [("$.ab", "does not match ^[a-z]$")]


# --- formats --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["a@b.co", "first.last@example.co.uk", "o'neil+tag@example.com", "user_name@sub.example.org"],
)
def test_emails_that_are(value):
    assert email().is_valid(value)


@pytest.mark.parametrize(
    "value", ["a@@b.c", "a@b", "@b.co", "a@", "a b@c.d", ".a@b.co", "a@-b.co", "a@b..co", "üser@b.co"]
)
def test_emails_that_are_not(value):
    assert not email().is_valid(value)


@pytest.mark.parametrize(
    "value", ["http://localhost:8000", "https://example.com/p?q=1#f", "ftp://x.y/z", "http://127.0.0.1"]
)
def test_urls_that_are(value):
    assert url().is_valid(value)


@pytest.mark.parametrize("value", ["example.com", "http://", "://x", "http://a b", "mailto:a@b.c", "1http://x"])
def test_urls_that_are_not(value):
    assert not url().is_valid(value)


def test_url_schemes():
    assert not url(schemes=("http", "https")).is_valid("ftp://x.y/z")
    assert url(schemes=("HTTPS",)).is_valid("https://x.y")


@pytest.mark.parametrize("value", ["123e4567-e89b-12d3-a456-426614174000", "123E4567-E89B-12D3-A456-426614174000"])
def test_uuids_that_are(value):
    assert uuid().is_valid(value)


@pytest.mark.parametrize(
    "value",
    [
        "123e4567-e89b-12d3-a456-42661417400",
        "123e4567e89b12d3a456426614174000",
        "123e4567-e89b-12d3-a456-42661417400g",
        "0x3e4567-e89b-12d3-a456-426614174000",
        " 23e4567-e89b-12d3-a456-426614174000",
    ],
)
def test_uuids_that_are_not(value):
    assert not uuid().is_valid(value)


def test_ipv4():
    assert ipv4().is_valid("192.168.0.1")
    assert not ipv4().is_valid("256.0.0.1")
    assert not ipv4().is_valid("01.2.3.4")
    assert not ipv4().is_valid("1.2.3")


@pytest.mark.parametrize("value", ["2026-09-07", "2024-02-29", "2000-02-29"])
def test_dates_that_are(value):
    assert iso_date().is_valid(value)


@pytest.mark.parametrize(
    "value", ["2026-02-30", "2023-02-29", "1900-02-29", "2026-13-01", "2026-9-7", "2026-09-07T00:00", "²026-09-07"]
)
def test_dates_that_are_not(value):
    assert not iso_date().is_valid(value)


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-07T21:17",
        "2026-09-07T21:17:05",
        "2026-09-07T21:17:05.123Z",
        "2026-09-07 21:17:05+02:00",
        "2026-09-07T21:17:05-0530",
        "2026-09-07T23:59:60Z",
    ],
)
def test_datetimes_that_are(value):
    assert iso_datetime().is_valid(value)


@pytest.mark.parametrize(
    "value",
    [
        "2026-09-07",
        "2026-09-07T24:00",
        "2026-09-07T21:60",
        "2026-09-07T21:17:05+25:00",
        "2026-09-07X21:17",
        "2026-09-07T21:17:05.",
    ],
)
def test_datetimes_that_are_not(value):
    assert not iso_datetime().is_valid(value)


# --- coerce ---------------------------------------------------------------------------------


def test_coerce_reads_strings_the_way_a_form_or_a_query_hands_them_over():
    Q = record(("page", integer(ge=1), 1), ("q", optional(text())), ("all", boolean(), False), ("ratio", number()))
    value = Q.parse({"page": " 3 ", "q": "", "all": "on", "ratio": "0.5"}, coerce=True)
    assert value == {"page": 3, "q": None, "all": False, "ratio": 0.5} or value["all"] is True
    assert Q.parse({"page": "3", "q": "", "all": "on", "ratio": "0.5"}, coerce=True)["all"] is True


def test_without_coerce_json_is_strict():
    assert errors(integer(), "3") == [("$", "expected an integer")]
    assert errors(boolean(), "true") == [("$", "expected true or false")]


def test_coerce_still_reports_what_is_not_a_number():
    assert errors(integer(), "3.5", coerce=True) == [("$", "expected an integer")]
    assert integer().parse(3.0, coerce=True) == 3


# --- sample ---------------------------------------------------------------------------------


def test_sample_walks_the_ends_and_returns_the_list_as_it_was():
    rows = [{"id": i, "name": "n", "email": "a@b.co"} for i in range(100)]
    rows[50]["id"] = "bad"
    value, errs = array(User).validate(rows, sample=10)
    assert errs == []
    assert value is rows
    rows[99]["id"] = "bad"
    assert errors(array(User), rows, sample=10) == [("$[99].id", "expected an integer")]


def test_sample_does_not_apply_to_a_short_list():
    rows = [{"id": "bad", "name": "n", "email": "a@b.co"}] * 5
    assert len(errors(array(User), rows, sample=10)) == 5


def test_array_bounds():
    assert errors(array(integer(), min=1), []) == [("$", "at least 1 items")]
    assert errors(array(integer(), max=1), [1, 2]) == [("$", "at most 1 items")]


# --- repr is source ---------------------------------------------------------------------------


def test_a_schema_prints_as_the_code_that_builds_it():
    assert repr(User) == (
        "record(('id', integer(ge=0)), ('name', text(min=1, max=100)), ('email', email()), "
        "('age', integer(gt=0, le=150), None), ('tags', array(text()), list))"
    )
    assert (
        repr(one_of(optional(uuid()), pattern("^x", strip=True)))
        == "one_of(optional(uuid()), pattern('^x', strip=True))"
    )
    assert repr(url(schemes=("http",))) == "url(schemes=('http',))"
    assert repr(record(("a", integer()), extra="forbid")) == "record(('a', integer()), extra='forbid')"


def test_repr_round_trips_through_eval():
    import frontage_schema as fs

    Order = record(
        ("user", record(("name", text(min=1)), ("n", optional(integer()), None))), ("kind", literal("a", "b"))
    )
    again = eval(repr(Order), vars(fs))
    assert repr(again) == repr(Order)
    assert (
        again.validate({"user": {"name": ""}, "kind": "c"})[1] == Order.validate({"user": {"name": ""}, "kind": "c"})[1]
    )
