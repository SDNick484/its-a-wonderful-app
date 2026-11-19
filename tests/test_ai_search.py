"""Smart search (spec §9, plan Task 12): one Messages API call against the recorded fixtures in tests/fixtures/anthropic/
(message shapes as the API sends them; the list and the answers are made up for these tests), TMDB lookups of the
suggestions against tests/fixtures/tmdb/, no live network. Covers the answer, the checks on it (unknown ids, ids and
suggestions already on the list), the cache, the daily cap and every way the call can fail (no key, 529, malformed
reply, refusal, timeout), which all fall back to the local filter with a notice."""
import datetime as dt
import json
import urllib.error

import pytest

import ai
import app
import search
from conftest import ANTHROPIC_KEY

NOTICE = "Smart search is off right now."

# (id, tmdb_id, title, year, cast, overview, parent note); the ids are the ones the fixtures name
LIBRARY = [
    (11, 900201, "The Star", 2017, ["Steven Yeun", "Zachary Levi"], "A small donkey and his friends follow a bright star to Bethlehem.", "Gentle."),
    (12, 900202, "Elf", 2003, ["Will Ferrell", "James Caan"], "A human raised at the North Pole goes to New York.", None),
    (13, 900203, "White Christmas", 1954, ["Bing Crosby", "Danny Kaye"], "Two entertainers put on a show at an inn.", None),
    (14, 900204, "The Muppet Christmas Carol", 1992, ["Michael Caine"], "The Muppets tell Dickens's story.", "Gonzo narrates."),
]


def load(con):
    for i, tmdb_id, title, year, cast, overview, note in LIBRARY:
        con.execute("INSERT INTO movies (id, tmdb_id, title, year, top_cast, overview, parent_note, added_by) VALUES (?,?,?,?,?,?,?,?)",
                    (i, tmdb_id, title, year, json.dumps(cast), overview, note, "test"))
    con.commit()


@pytest.fixture
def smart(client, tmdb_fixtures, anthropic_fixtures):
    """The test client with the list loaded, TMDB and Anthropic answering from the fixtures: (client, anthropic, tmdb)."""
    with app.app.app_context():
        load(app.get_db())
    return client, anthropic_fixtures, tmdb_fixtures


def find(client, q):
    r = client.get("/api/search", query_string={"q": q})
    assert r.status_code == 200
    return r.get_json()


def movie_count():
    with app.app.app_context():
        return app.get_db().execute("SELECT COUNT(*) FROM movies").fetchone()[0]


# ------------------------------------------------------------------------------------------------ the answer
def test_jesus_returns_the_star_and_suggests_nativity_story(smart):
    client, anthropic, _ = smart
    body = find(client, "a movie about Jesus")
    assert body == {
        "mode": "ai", "notice": None,
        "matches": [{"id": 11, "why": "the Nativity story, told by the animals"}],
        "suggestions": [{"title": "The Nativity Story", "year": 2006, "tmdb_id": 900302, "tmdb_type": "movie",
                         "why": "Mary and Joseph's journey to Bethlehem, played straight"}]}
    assert len(anthropic.calls) == 1
    call = anthropic.calls[0]
    assert call["model"] == "claude-haiku-5-5" and "a movie about Jesus" in anthropic.prompt(call)
    assert anthropic.headers == [{"key": ANTHROPIC_KEY, "version": ai.API_VERSION, "type": "application/json"}]
    assert anthropic.timeouts == [ai.AI_TIMEOUT]


def test_the_request_asks_for_json_and_sends_no_sampling_or_thinking_settings(smart):
    client, anthropic, _ = smart
    find(client, "a movie about Jesus")
    call = anthropic.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema" and call["output_config"]["effort"] == "low"
    assert not {"temperature", "top_p", "top_k", "thinking", "tool_choice"} & call.keys()
    assert call["max_tokens"] == ai.MAX_TOKENS


def test_unknown_ids_from_model_dropped(smart):
    client, _, _ = smart
    body = find(client, "a musical")
    assert sorted(m["id"] for m in body["matches"]) == [13, 14]


def test_suggestion_already_on_list_dropped(smart):
    client, _, tmdb = smart
    body = find(client, "a musical")
    # White Christmas is on the list, The Phantom Reindeer Opera is not on TMDB, Meet Me in St. Louis is the fourth (only
    # three are looked up): Holiday Inn is what is left
    assert [s["title"] for s in body["suggestions"]] == ["Holiday Inn"]
    assert body["suggestions"][0]["tmdb_id"] == 900301
    assert len([u for u in tmdb.api if "/search/multi" in u]) == 3


def test_a_suggestion_with_the_wrong_year_or_title_is_not_taken(app_ctx):
    found = [{"title": "The Nativity", "year": 2010, "tmdb_id": 1, "tmdb_type": "tv"},
             {"title": "The Nativity Story", "year": 2006, "tmdb_id": 2, "tmdb_type": "movie"}]
    assert search._pick(found, "The Nativity Story", 2006)["tmdb_id"] == 2
    assert search._pick(found, "The Nativity Story", 2007)["tmdb_id"] == 2      # a year out is fine
    assert search._pick(found, "The Nativity Story", 1999) is None             # a different film of that name
    assert search._pick(found, "The Nativity Story", None)["tmdb_id"] == 2
    assert search._pick(found, "Nativity Story 2", 2006) is None


def test_suggestions_never_added_without_tap(smart):
    client, _, _ = smart
    before = movie_count()
    assert find(client, "a movie about Jesus")["suggestions"] and find(client, "a musical")["suggestions"]
    assert movie_count() == before == len(LIBRARY)


def test_a_suggestion_is_added_by_the_add_route_and_then_leaves_the_suggestions(smart):
    client, anthropic, _ = smart
    s = find(client, "a movie about Jesus")["suggestions"][0]
    r = client.post("/api/movies", json={"tmdb_id": s["tmdb_id"], "tmdb_type": s["tmdb_type"]})
    assert r.status_code == 201 and movie_count() == len(LIBRARY) + 1
    body = find(client, "a movie about Jesus")      # the list changed, so the model is asked again
    assert len(anthropic.calls) == 2 and body["suggestions"] == []


def test_an_exact_title_and_an_empty_search_make_no_call(smart):
    client, anthropic, _ = smart
    assert find(client, "elf")["mode"] == "exact"
    assert find(client, "")["mode"] == "local"
    assert anthropic.calls == []


def test_prompt_contains_no_people_or_ratings(smart):
    client, anthropic, _ = smart
    with app.app.app_context():
        con = app.get_db()
        person = app.people.add_person(con, {"name": "Wren Quillfeather", "kind": "kid"})
        app.ratings.set(con, 11, person["id"], 7.5)
        con.execute("INSERT INTO viewings (movie_id, started_on, status) VALUES (11, '2026-12-01', 'tonight')")
        con.commit()
    find(client, "a movie about Jesus")
    prompt = anthropic.prompt(anthropic.calls[0])
    assert "Wren" not in json.dumps(anthropic.calls[0]) and "Quillfeather" not in prompt
    listed = json.loads(prompt.split("<list>\n", 1)[1].split("\n</list>", 1)[0])
    assert sorted(m["id"] for m in listed) == [11, 12, 13, 14]
    assert "7.5" not in json.dumps(anthropic.calls[0]) and "rating" not in json.dumps(anthropic.calls[0]).lower()
    assert {k for m in listed for k in m} == {"id", "title", "year", "certification", "runtime_min", "animated", "collection",
                                              "cast", "overview", "parent_note"}
    star = next(m for m in listed if m["id"] == 11)
    assert star["parent_note"] == "Gentle." and star["cast"] == ["Steven Yeun", "Zachary Levi"]


# ------------------------------------------------------------------------------------------------ the cache
def test_cache_hit_makes_no_call(smart):
    client, anthropic, tmdb = smart
    first = find(client, "a movie about Jesus")
    lookups = len(tmdb.api)
    again = find(client, "A movie about Jesus!")      # same normalized query
    assert again == first and len(anthropic.calls) == 1 and len(tmdb.api) == lookups


def test_list_change_busts_cache(smart):
    client, anthropic, _ = smart
    find(client, "a movie about Jesus")
    with app.app.app_context():
        con = app.get_db()
        con.execute("INSERT INTO movies (id, tmdb_id, title, year) VALUES (15, 900205, 'Klaus', 2019)")
        con.commit()
    find(client, "a movie about Jesus")
    assert len(anthropic.calls) == 2
    assert "Klaus" in anthropic.prompt(anthropic.calls[1]) and "Klaus" not in anthropic.prompt(anthropic.calls[0])


# ------------------------------------------------------------------------------------------------ falling back
def local_ids(q):
    with app.app.app_context():
        return search.local_matches(app.get_db(), q)


def test_malformed_json_falls_back_to_local_with_notice(smart):
    client, anthropic, _ = smart
    anthropic.file = "malformed.json"
    body = find(client, "christmas")
    assert body == {"mode": "local", "matches": local_ids("christmas"), "suggestions": [], "notice": NOTICE}
    assert sorted(m["id"] for m in body["matches"]) == [13, 14]
    find(client, "christmas")
    assert len(anthropic.calls) == 2      # a failure is not cached


def test_529_falls_back(smart):
    client, anthropic, _ = smart
    anthropic.error = 529
    body = find(client, "christmas")
    assert body["mode"] == "local" and body["notice"] == NOTICE and body["suggestions"] == []
    assert sorted(m["id"] for m in body["matches"]) == [13, 14]


@pytest.mark.parametrize("failure", [429, 500, 401, urllib.error.URLError("refused"), TimeoutError(), OSError("reset")],
                         ids=["429", "500", "401", "refused", "timeout", "reset"])
def test_every_other_failure_falls_back_too(smart, failure):
    client, anthropic, _ = smart
    anthropic.error = failure
    body = find(client, "a musical")
    assert body["mode"] == "local" and body["notice"] == NOTICE and body["suggestions"] == []


def test_no_key_falls_back(smart, monkeypatch):
    client, anthropic, _ = smart
    monkeypatch.setattr(app, "ANTHROPIC_API_KEY", "")
    body = find(client, "christmas")
    assert body["mode"] == "local" and body["notice"] == NOTICE
    assert sorted(m["id"] for m in body["matches"]) == [13, 14] and anthropic.calls == []


def test_no_key_falls_back_even_with_a_cached_answer(smart, monkeypatch):
    client, anthropic, _ = smart
    find(client, "a movie about Jesus")
    monkeypatch.setattr(app, "ANTHROPIC_API_KEY", "")
    assert find(client, "a movie about Jesus")["mode"] == "local"


def test_daily_cap_falls_back(smart, monkeypatch):
    client, anthropic, _ = smart
    monkeypatch.setattr(app, "AI_DAILY_CAP", 2)
    assert find(client, "a movie about Jesus")["mode"] == "ai"
    assert find(client, "a musical")["mode"] == "ai"
    spent = find(client, "christmas")
    assert spent["mode"] == "local" and spent["notice"] == NOTICE and len(anthropic.calls) == 2
    assert find(client, "a musical")["mode"] == "ai" and len(anthropic.calls) == 2      # a cached answer costs no call
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    monkeypatch.setattr(app, "today", lambda: tomorrow)
    anthropic.files["christmas"] = "jesus.json"
    assert find(client, "christmas")["mode"] == "ai" and len(anthropic.calls) == 3      # a new day, a new count


def test_a_failed_call_still_counts_against_the_cap(smart, monkeypatch):
    client, anthropic, _ = smart
    monkeypatch.setattr(app, "AI_DAILY_CAP", 1)
    anthropic.error = 529
    find(client, "a musical")
    anthropic.error = None
    assert find(client, "a movie about Jesus")["mode"] == "local" and len(anthropic.calls) == 1


def test_tmdb_down_keeps_the_matches_and_does_not_cache(client, tmdb_down, anthropic_fixtures):
    with app.app.app_context():
        load(app.get_db())
    anthropic = anthropic_fixtures
    body = find(client, "a movie about Jesus")
    assert body["mode"] == "ai" and body["matches"] == [{"id": 11, "why": "the Nativity story, told by the animals"}]
    assert body["suggestions"] == [] and body["notice"] == search.SUGGESTIONS_NOTICE
    find(client, "a movie about Jesus")
    assert len(anthropic.calls) == 2


# ------------------------------------------------------------------------------------------------ ai.ask itself
def with_reply(monkeypatch, message):
    import io
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(json.dumps(message).encode()))


def text_message(text, **fields):
    return {"type": "message", "role": "assistant", "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", **fields}


def test_ask_returns_the_recorded_answer(anthropic_fixtures):
    answer = ai.ask("[]", "a movie about Jesus")
    assert answer == {"matches": [{"id": 11, "why": "the Nativity story, told by the animals"}],
                      "suggestions": [{"title": "The Nativity Story", "year": 2006, "why": "Mary and Joseph's journey to Bethlehem, played straight"}]}


@pytest.mark.parametrize("message, reason", [
    (text_message("{}", stop_reason="refusal"), "refused"),
    (text_message('{"matches": [], "suggestions": []}', stop_reason="max_tokens"), "malformed"),
    ({"type": "message", "content": [], "stop_reason": "end_turn"}, "malformed"),
    ({"type": "message", "content": [{"type": "thinking", "thinking": ""}], "stop_reason": "end_turn"}, "malformed"),
    (text_message("[1, 2, 3]"), "malformed"),
    (text_message('{"matches": []}'), "malformed"),
    (text_message('{"matches": "all", "suggestions": []}'), "malformed"),
    (["not", "a", "message"], "malformed"),
], ids=["refusal", "cut-off", "no content", "no text", "a list", "no suggestions", "wrong type", "not an object"])
def test_ask_raises_for_a_reply_it_cannot_use(client, monkeypatch, message, reason):
    monkeypatch.setattr(app, "ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    with_reply(monkeypatch, message)
    with pytest.raises(ai.AiError) as e:
        ai.ask("[]", "a musical")
    assert e.value.reason == reason and ANTHROPIC_KEY not in e.value.message


def test_ask_drops_items_of_the_wrong_shape(client, monkeypatch):
    monkeypatch.setattr(app, "ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    items = {"matches": [{"id": 11, "why": "ok"}, {"id": "12", "why": "a string id"}, {"id": True, "why": "a bool"},
                         {"why": "no id"}, "13", {"id": 14}],
             "suggestions": [{"title": "Holiday Inn", "year": "1942", "why": "a string year"}, {"year": 1942}, 5,
                             {"title": "  ", "year": 1}]}
    with_reply(monkeypatch, text_message(json.dumps(items)))
    assert ai.ask("[]", "x") == {"matches": [{"id": 11, "why": "ok"}, {"id": 14, "why": None}],
                                 "suggestions": [{"title": "Holiday Inn", "year": None, "why": "a string year"}]}


def test_ask_without_a_key_never_calls_out(client):
    with pytest.raises(ai.AiError) as e:
        ai.ask("[]", "a musical")      # the client fixture makes urlopen raise if it were reached
    assert e.value.reason == "not_configured"


def test_ask_turns_an_unreadable_body_into_an_error(client, monkeypatch):
    import io
    import urllib.request
    monkeypatch.setattr(app, "ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(b"<html>bad gateway</html>"))
    with pytest.raises(ai.AiError) as e:
        ai.ask("[]", "a musical")
    assert e.value.reason == "unavailable"
