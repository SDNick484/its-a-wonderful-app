"""The TMDB client against recorded fixtures: search, details, the certification rule, and every way TMDB fails."""
import io
import urllib.error

import pytest
from conftest import TMDB_FIXTURES, TMDB_TOKEN

import app


def test_search_returns_movies_and_tv_and_drops_people(tmdb_fixtures):
    results = app.tmdb.search("Prancer")
    assert [(r["tmdb_type"], r["title"], r["year"]) for r in results] == [
        ("movie", "Prancer", 1989), ("tv", "Prancer Pals", 2015), ("movie", "Prancer Untitled", None)]
    assert results[0] == {"tmdb_id": 14181, "tmdb_type": "movie", "title": "Prancer", "year": 1989,
                          "poster_path": "/prancer-poster.jpg"}
    assert results[2]["poster_path"] is None
    assert tmdb_fixtures.api and "query=Prancer" in tmdb_fixtures.api[0]


def test_search_miss_is_an_empty_list(tmdb_fixtures):
    assert app.tmdb.search("zzzz nothing") == []


def test_search_blank_asks_nobody(tmdb_fixtures):
    assert app.tmdb.search("   ") == [] and tmdb_fixtures.api == []


def test_details_for_elf(tmdb_fixtures):
    d = app.tmdb.details(10719, "movie")
    assert (d["title"], d["year"], d["runtime_min"], d["us_certification"], d["is_animated"]) == ("Elf", 2003, 97, "PG", False)
    assert d["genres"] == ["Comedy", "Family", "Fantasy"]
    assert d["top_cast"] == ["Will Ferrell", "James Caan", "Bob Newhart", "Edward Asner", "Mary Steenburgen",
                             "Zooey Deschanel", "Daniel Tay", "Peter Dinklage"]   # 10 billed, first 8 kept
    assert d["collection_id"] is None and d["tmdb_vote"] == 7.0
    assert d["poster_path"] == "/elf-poster.jpg" and d["backdrop_path"] == "/elf-backdrop.jpg"
    assert "append_to_response=release_dates%2Ccredits" in tmdb_fixtures.api[0]


def test_certification_is_the_first_non_empty_in_the_us_set(tmdb_fixtures):
    # Elf's US set lists a blank certification (the premiere) before PG; the GB set is ignored.
    assert app.tmdb.us_certification({"release_dates": {"results": [
        {"iso_3166_1": "GB", "release_dates": [{"certification": "12A"}]},
        {"iso_3166_1": "US", "release_dates": [{"certification": ""}, {"certification": "PG-13"}, {"certification": "R"}]}]}}) == "PG-13"


def test_no_us_certification_is_NR(tmdb_fixtures):
    d = app.tmdb.details(900001, "movie")
    assert d["us_certification"] == "NR"
    assert app.tmdb.us_certification({}) == "NR"
    assert app.tmdb.us_certification({"release_dates": {"results": [{"iso_3166_1": "GB", "release_dates": [{"certification": "U"}]}]}}) == "NR"


def test_null_runtime_collection_and_no_poster(tmdb_fixtures):
    d = app.tmdb.details(900001, "movie")
    assert d["runtime_min"] is None and d["poster_path"] is None and d["backdrop_path"] is None
    assert (d["collection_id"], d["collection_name"]) == (77001, "The Quiet Reindeer Collection")
    assert d["year"] is None and d["overview"] is None and d["tmdb_vote"] is None and d["top_cast"] == []


def test_tv_special(tmdb_fixtures):
    d = app.tmdb.details(900002, "tv")
    assert (d["title"], d["year"], d["runtime_min"], d["us_certification"], d["is_animated"]) == ("The Tinsel Express", 2011, 24, "TV-Y7", True)
    assert d["top_cast"] == ["Ada Fenwick", "Bo Larkspur"]
    assert "/3/tv/900002" in tmdb_fixtures.api[0]


def test_a_zero_runtime_is_unknown():
    assert app.tmdb._runtime({"runtime": 0}, "movie") is None
    assert app.tmdb._runtime({"episode_run_time": []}, "tv") is None


def test_details_rejects_an_unknown_type(tmdb_fixtures):
    with pytest.raises(ValueError):
        app.tmdb.details(1, "person")


# ------------------------------------------------------------------------------------------- misses and failures
def test_unknown_title_is_not_found(tmdb_fixtures):
    with pytest.raises(app.TmdbError) as e:
        app.tmdb.details(1, "movie")
    assert (e.value.reason, e.value.status) == ("not_found", 404)


def test_no_token_is_not_configured(client):     # the isolated app has no token, and any network call would fail the test
    with pytest.raises(app.TmdbError) as e:
        app.tmdb.search("elf")
    assert (e.value.reason, e.value.status) == ("not_configured", 503) and "TMDB_READ_TOKEN" in e.value.message


@pytest.mark.parametrize("code, reason, status", [(500, "unavailable", 502), (503, "unavailable", 502),
                                                  (401, "unavailable", 502), (429, "rate_limited", 503)])
def test_http_errors(tmdb_down, monkeypatch, code, reason, status):
    import urllib.request

    def fail(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "x", {"Retry-After": "30"}, None)

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(app.TmdbError) as e:
        app.tmdb.search("elf")
    assert (e.value.reason, e.value.status) == (reason, status)
    if code == 429:
        assert "30 s" in e.value.message


def test_http_500_from_the_fixture(tmdb_down):
    with pytest.raises(app.TmdbError) as e:
        app.tmdb.details(10719, "movie")
    assert e.value.status == 502 and "HTTP 500" in e.value.message


@pytest.mark.parametrize("exc", [urllib.error.URLError("no route"), TimeoutError(), ConnectionResetError()])
def test_network_failures(client, monkeypatch, exc):
    import urllib.request

    def fail(req, timeout=None):
        raise exc

    monkeypatch.setattr(app, "TMDB_READ_TOKEN", TMDB_TOKEN)
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(app.TmdbError) as e:
        app.tmdb.search("elf")
    assert e.value.reason == "unavailable"


@pytest.mark.parametrize("body", [b"<html>oops</html>", b"[1, 2]", b""])
def test_unreadable_answers(client, monkeypatch, body):
    import urllib.request
    monkeypatch.setattr(app, "TMDB_READ_TOKEN", TMDB_TOKEN)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(body))
    with pytest.raises(app.TmdbError) as e:
        app.tmdb.search("elf")
    assert e.value.reason == "unavailable"


def test_fixtures_are_valid_json():
    import json
    for p in TMDB_FIXTURES.glob("*.json"):
        json.loads(p.read_text(encoding="utf-8"))
