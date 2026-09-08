"""frontage-supabase: the request it builds, and what it makes of the answer.

The component owns two things and only two: the URL and headers it sends, and the meaning it
takes from what comes back. PostgREST's behaviour is PostgREST's. So these tests build queries
and assert their strings, and drive the client against a stubbed `fetch` — the same shape the
other components' tests use for their JavaScript half.
"""

import asyncio
import json

import pytest
from frontage_supabase import Client, PostgrestError, Query, Result

# -- the query builder ----------------------------------------------------------------------


def test_a_bare_table_is_just_its_name():
    assert Query("cities").path == "cities"


def test_select_and_filters_become_query_parameters():
    q = Query("cities").select("id,name").eq("region", "Galicia").gt("people", 100000)
    assert q.path == "cities?people=gt.100000&region=eq.Galicia&select=id%2Cname"


def test_parameters_are_sorted_so_the_same_query_is_the_same_string():
    """A Resource uses this as its source; two spellings of one query must not refetch."""
    a = Query("cities").eq("a", 1).eq("b", 2).select("*")
    b = Query("cities").select("*").eq("b", 2).eq("a", 1)
    assert a.path == b.path


def test_values_are_percent_encoded():
    q = Query("cities").ilike("name", "%Sant Cugat & Co%")
    assert "Sant%20Cugat%20%26%20Co" in q.path
    assert "&" not in q.path.split("name=")[1]


def test_none_and_booleans_use_postgrest_spelling():
    assert Query("t").is_("deleted", None).path == "t?deleted=is.null"
    assert Query("t").eq("live", True).path == "t?live=eq.true"


def test_in_quotes_members_that_contain_the_separator():
    q = Query("t").in_("name", ["ada", "hop,per", 'say"s'])
    assert "in.%28ada%2C%22hop%2C%2Cper%22" not in q.path  # not double-escaped commas
    assert q.path == "t?name=in.%28ada%2C%22hop%2Cper%22%2C%22say%22%22s%22%29"


def test_order_says_which_way_and_where_nulls_go():
    assert Query("t").order("n", desc=True).path == "t?order=n.desc.nullslast"
    assert Query("t").order("n", nulls_first=True).path == "t?order=n.asc.nullsfirst"


def test_range_is_a_header_and_asks_for_the_count():
    q = Query("t").range(0, 24)
    assert q.headers["Range"] == "0-24"
    assert "count=exact" in q.headers["Prefer"]


def test_one_asks_postgrest_to_enforce_it():
    q = Query("t").eq("id", 1).one()
    assert q.headers["Accept"] == "application/vnd.pgrst.object+json"
    assert q.single is True


def test_a_query_is_immutable_so_a_held_one_can_be_branched():
    base = Query("cities").select("*")
    galicia = base.eq("region", "Galicia")
    aragon = base.eq("region", "Aragon")
    assert base.path == "cities?select=%2A"
    assert "Galicia" in galicia.path and "Galicia" not in aragon.path


def test_match_is_several_eq():
    assert Query("t").match(a=1, b=2).path == "t?a=eq.1&b=eq.2"


# -- errors ---------------------------------------------------------------------------------


def test_a_denied_read_is_told_apart_from_a_wrong_one():
    """The distinction the whole component exists to make: a policy refusing is not a bug."""
    assert PostgrestError(403, {"code": "42501", "message": "no"}).denied
    assert PostgrestError(401, {"message": "JWT expired"}).denied
    assert PostgrestError(400, {"code": "PGRST100", "message": "bad"}).denied is False


def test_an_error_carries_the_hint_because_that_is_the_useful_part():
    exc = PostgrestError(400, {"message": "column x does not exist", "hint": "did you mean y?"})
    assert "did you mean y?" in str(exc)
    assert exc.message == "column x does not exist"


def test_a_non_json_body_still_produces_a_usable_error():
    exc = PostgrestError(502, "<html>bad gateway</html>")
    assert exc.status == 502 and "bad gateway" in exc.message


# -- the client against a stubbed fetch -------------------------------------------------------


class FakeResponse:
    def __init__(self, status=200, body="", headers=None):
        self.status = status
        self.ok = 200 <= status < 300
        self._body = body
        self.headers = headers or {}

    async def text(self):
        return self._body


class FakeFetch:
    """Stands in for `window.fetch`. Records what was asked for; answers what it was told to."""

    def __init__(self, *responses):
        self.responses = list(responses) or [FakeResponse(200, "[]")]
        self.calls = []

    async def __call__(self, url, options=None):
        self.calls.append((url, options or {}))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


@pytest.fixture
def fetch(monkeypatch):
    from frontage_supabase import client as module

    fake = FakeFetch()

    class Window:
        fetch = staticmethod(fake)

    monkeypatch.setattr(module, "window", Window)
    monkeypatch.setattr(module, "to_js", lambda x: x)
    return fake


def db():
    return Client("https://project.supabase.co", "anon-key")


def test_a_read_sends_the_key_and_the_bearer(fetch):
    async def scenario():
        fetch.responses = [FakeResponse(200, '[{"id":1}]')]
        await db().run(Query("cities").select("*"))
        url, options = fetch.calls[0]
        assert url == "https://project.supabase.co/rest/v1/cities?select=%2A"
        assert options["headers"]["apikey"] == "anon-key"
        # Without a session the anon key is the bearer, which is what PostgREST expects.
        assert options["headers"]["Authorization"] == "Bearer anon-key"

    asyncio.run(scenario())


def test_rows_and_the_total_come_back_together(fetch):
    async def scenario():
        fetch.responses = [FakeResponse(200, '[{"id":1},{"id":2}]', {"content-range": "0-1/573"})]
        result = await db().run(Query("cities").range(0, 1))
        assert isinstance(result, Result)
        assert [r["id"] for r in result] == [1, 2]
        assert result.count == 573

    asyncio.run(scenario())


def test_an_uncounted_query_says_so_rather_than_guessing(fetch):
    async def scenario():
        fetch.responses = [FakeResponse(200, "[]", {"content-range": "*/*"})]
        assert (await db().run(Query("t"))).count is None

    asyncio.run(scenario())


def test_one_returns_the_row_itself(fetch):
    async def scenario():
        fetch.responses = [FakeResponse(200, '{"id":1,"name":"ada"}')]
        row = await db().run(Query("t").eq("id", 1).one())
        assert row == {"id": 1, "name": "ada"}

    asyncio.run(scenario())


def test_a_refusal_becomes_a_postgrest_error_with_denied_set(fetch):
    async def scenario():
        body = json.dumps({"code": "42501", "message": "new row violates row-level security policy"})
        fetch.responses = [FakeResponse(403, body)]
        with pytest.raises(PostgrestError) as caught:
            await db().run(Query("cities").select("*"))
        assert caught.value.denied
        assert caught.value.status == 403

    asyncio.run(scenario())


def test_a_write_sends_json_and_asks_for_the_row_back(fetch):
    async def scenario():
        fetch.responses = [FakeResponse(201, '[{"id":9,"name":"Girona"}]')]
        result = await db().table("cities").insert({"name": "Girona"})
        url, options = fetch.calls[0]
        assert options["method"] == "POST"
        assert options["headers"]["Content-Type"] == "application/json"
        assert json.loads(options["body"]) == {"name": "Girona"}
        assert "return=representation" in options["headers"]["Prefer"]
        assert result[0]["id"] == 9

    asyncio.run(scenario())


def test_an_update_is_not_sent_until_it_is_awaited(fetch):
    async def scenario():
        """`update` returns a query on purpose, so the filter can come after it."""
        query = db().table("cities").update({"people": 1}).eq("id", 7)
        assert fetch.calls == []
        assert isinstance(query, Query) and query.method == "PATCH"
        assert query.path == "cities?id=eq.7"

    asyncio.run(scenario())


def test_signing_in_keeps_the_token_and_uses_it(fetch):
    async def scenario():
        session = json.dumps({"access_token": "jwt-123", "user": {"id": "u1", "email": "a@b.c"}})
        fetch.responses = [FakeResponse(200, session), FakeResponse(200, "[]")]
        client = db()
        await client.auth.sign_in("a@b.c", "hunter2")
        assert client.auth.user()["email"] == "a@b.c"
        await client.run(Query("cities"))
        assert fetch.calls[1][1]["headers"]["Authorization"] == "Bearer jwt-123"

    asyncio.run(scenario())


def test_a_project_with_confirmation_on_signs_up_without_a_token(fetch):
    async def scenario():
        """A user and no session is the confirmation flow working, not a failure."""
        fetch.responses = [FakeResponse(200, json.dumps({"user": {"id": "u1"}, "access_token": None}))]
        client = db()
        await client.auth.sign_up("a@b.c", "hunter2")
        assert client.auth.session() is None

    asyncio.run(scenario())


def test_a_self_hosted_postgrest_needs_only_a_different_url():
    plain = Client("http://localhost:3000", rest="")
    assert plain.headers().get("apikey") is None
    assert plain.url + plain.rest + "/" + Query("cities").path == "http://localhost:3000/cities"
