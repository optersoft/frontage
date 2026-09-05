"""SPEC §5, T1–T5, T7. No browser."""

import pytest

from frontage.reactive import Effect
from frontage.store import Store, snapshot


def counter(fn):
    """An effect over `fn` and the list of values it produced."""
    log = []
    Effect(lambda: log.append(fn()))
    return log


# T1 ------------------------------------------------------------------------------------------
def test_reads_like_the_data_it_wraps():
    s = Store({"user": {"name": "Ann", "tags": ["a", "b"]}, "n": 3})
    assert s["n"] == 3 and s.n == 3
    assert s["user"]["name"] == "Ann" and s.user.name == "Ann"
    assert isinstance(s["user"], Store) and isinstance(s.user.tags, Store)
    assert len(s) == 2 and "n" in s and sorted(s) == ["n", "user"]
    assert len(s.user.tags) == 2 and list(s.user.tags) == ["a", "b"]
    assert s.get("missing", 0) == 0
    assert s.user == {"name": "Ann", "tags": ["a", "b"]}


def test_wrapping_requires_a_container():
    with pytest.raises(TypeError):
        Store(3)


# T2 ------------------------------------------------------------------------------------------
def test_nodes_are_created_only_for_tracked_reads():
    s = Store({"a": 1, "b": 2})
    assert s["a"] == 1  # untracked read
    assert s._nodes == {}
    counter(lambda: s["a"])
    assert list(s._nodes) == ["a"]


def test_nested_wrapper_identity_is_stable():
    s = Store({"user": {"name": "Ann"}})
    assert s.user is s.user


# T3 ------------------------------------------------------------------------------------------
def test_set_notifies_exactly_the_keys_written():
    s = Store({"a": 1, "b": 2})
    la = counter(lambda: s["a"])
    lb = counter(lambda: s["b"])
    s.set(lambda d: d.__setitem__("a", 10))
    assert la == [1, 10] and lb == [2]


def test_nested_write_notifies_the_path_not_the_siblings():
    s = Store({"user": {"name": "Ann", "email": "a@x"}})
    name = counter(lambda: s.user.name)
    email = counter(lambda: s.user.email)
    s.set(lambda d: d.user.__setattr__("name", "Bob"))
    assert name == ["Ann", "Bob"] and email == ["a@x"]


def test_set_is_one_batch():
    s = Store({"a": 1, "b": 2})
    both = counter(lambda: (s["a"], s["b"]))

    def many(d):
        d["a"] = 10
        d["b"] = 20

    s.set(many)
    assert both == [(1, 2), (10, 20)]


def test_list_append_notifies_length_and_iteration_not_existing_items():
    s = Store({"items": [1, 2]})
    first = counter(lambda: s["items"][0])
    length = counter(lambda: len(s["items"]))
    listing = counter(lambda: list(s["items"]))
    s.set(lambda d: d["items"].append(3))
    assert first == [1]
    assert length == [2, 3]
    assert listing == [[1, 2], [1, 2, 3]]


def test_list_insert_notifies_shifted_indices():
    s = Store([10, 20, 30])
    at0 = counter(lambda: s[0])
    at1 = counter(lambda: s[1])
    at2 = counter(lambda: s[2])
    s.set(lambda d: d.insert(1, 15))
    assert at0 == [10]
    assert at1 == [20, 15]
    assert at2 == [30, 20]


def test_list_pop_and_remove_and_clear():
    s = Store([1, 2, 3])
    length = counter(lambda: len(s))
    s.set(lambda d: d.pop())
    s.set(lambda d: d.remove(1))
    assert snapshot(s) == [2]
    s.set(lambda d: d.clear())
    assert snapshot(s) == [] and length == [3, 2, 1, 0]


def test_replacing_a_nested_container_rewraps_it():
    s = Store({"user": {"name": "Ann"}})
    name = counter(lambda: s.user.name)
    s.set(lambda d: d.__setitem__("user", {"name": "Zed"}))
    assert name == ["Ann", "Zed"]
    assert s.user.name == "Zed"


# T4 ------------------------------------------------------------------------------------------
def test_writing_the_same_value_notifies_nobody():
    s = Store({"a": 1})
    la = counter(lambda: s["a"])
    s.set(lambda d: d.__setitem__("a", 1))
    assert la == [1]


def test_delete_notifies_the_key_and_membership():
    s = Store({"a": 1, "b": 2})
    has_a = counter(lambda: "a" in s)
    keys = counter(lambda: sorted(s))
    s.set(lambda d: d.__delitem__("a"))
    assert has_a == [True, False]
    assert keys == [["a", "b"], ["b"]]


def test_adding_a_key_notifies_membership_and_iteration():
    s = Store({"a": 1})
    keys = counter(lambda: sorted(s))
    s.set(lambda d: d.__setitem__("z", 26))
    assert keys == [["a"], ["a", "z"]]


# writes outside set() ------------------------------------------------------------------------
def test_store_is_read_only_outside_set():
    s = Store({"a": 1})
    with pytest.raises(TypeError):
        s["a"] = 2
    with pytest.raises(TypeError):
        s.a = 2
    with pytest.raises(TypeError):
        s.set(lambda d: None) or s.__setitem__("a", 2)


# T5 ------------------------------------------------------------------------------------------
def test_set_path():
    s = Store({"user": {"name": "Ann"}, "n": 1})
    name = counter(lambda: s.user.name)
    s.set_path("user", "name", "Bob")
    s.set_path("n", 2)
    assert name == ["Ann", "Bob"] and s.n == 2
    with pytest.raises(TypeError):
        s.set_path("only-a-key")


# T7 ------------------------------------------------------------------------------------------
def test_snapshot_is_plain_data():
    data = {"user": {"name": "Ann"}}
    s = Store(data)
    assert snapshot(s) is data
    assert snapshot(s.user) is data["user"]
    assert type(snapshot(s)) is dict
