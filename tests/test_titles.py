"""The Netflix title id (netflix-title design §4.1, plan Task 1): wikidata.netflix_id against recorded Wikidata answers
(tests/fixtures/wikidata/), titles.lookup / due / set_manual / parse_link, the id through PUT /api/movies/<id> and
POST /api/movies, and the nightly step of ops/wonderful-refresh. Wikidata answers from the FakeWikidata in conftest;
no network."""
import json
import logging
import urllib.error
import urllib.parse

import pytest
from werkzeug.exceptions import HTTPException

import app
from test_matinee_client import refresh_cli

KLAUS_TMDB, KLAUS_ID = 508965, "80183187"
PRANCER = 14181          # a TMDB id with a recorded details fixture
SENTENCE = "That doesn't look like a Netflix link."


def provider_data(netflix=True):
    return json.dumps({"flatrate": ["netflix"] if netflix else ["disney_plus"], "free": [], "ads": [], "rent": [], "buy": []})


def add_movie(con, tmdb_id, title, tmdb_type="movie", netflix=True):
    """A movie row whose providers cache (fresh, no TMDB call) says Netflix streams it, or not."""
    movie_id = con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title) VALUES (?, ?, ?)",
                           (tmdb_id, tmdb_type, title)).lastrowid
    con.execute("INSERT INTO providers_cache (movie_id, data, link, fetched_at) VALUES (?, ?, NULL, ?)",
                (movie_id, provider_data(netflix), app.now_iso()))
    con.commit()
    return movie_id


def stored(con, movie_id):
    row = con.execute("SELECT * FROM service_titles WHERE movie_id=? AND service='netflix'", (movie_id,)).fetchone()
    return None if row is None else dict(row)


def age(con, movie_id, days):
    con.execute("UPDATE service_titles SET checked_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?) WHERE movie_id=?",
                (f"-{days} days", movie_id))
    con.commit()


def query_of(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


@pytest.fixture
def con(app_ctx):
    return app_ctx.get_db()


# ------------------------------------------------------------------------------------------------ the Wikidata client
def test_netflix_id_reads_the_first_binding(client, wikidata_fixtures):
    assert app.wikidata.netflix_id(KLAUS_TMDB, "movie") == KLAUS_ID
    assert wikidata_fixtures.calls == 1
    url = wikidata_fixtures.urls[0]
    assert url.startswith("https://query.wikidata.org/sparql?")
    q = query_of(url)
    assert q["format"] == ["json"]
    assert q["query"] == ['SELECT ?netflix WHERE { ?item wdt:P4947 "508965" ; wdt:P1874 ?netflix . }']
    headers = wikidata_fixtures.headers[0]
    assert headers["User-agent"] == app.UA and headers["Accept"] == "application/sparql-results+json"
    assert wikidata_fixtures.timeouts == [10]


def test_tv_uses_the_tv_property(client, wikidata_fixtures):
    assert app.wikidata.netflix_id(900002, "tv") == KLAUS_ID
    query = query_of(wikidata_fixtures.urls[0])["query"][0]
    assert "wdt:P4983" in query and "P4947" not in query and '"900002"' in query


def test_a_type_that_is_not_movie_or_tv_is_a_bug(client, wikidata_fixtures):
    with pytest.raises(ValueError):
        app.wikidata.netflix_id(1, "person")
    assert wikidata_fixtures.calls == 0


def test_none_found(client, wikidata_fixtures):
    wikidata_fixtures.file = "none.json"
    assert app.wikidata.netflix_id(99999999, "movie") is None


def test_first_of_two(client, wikidata_fixtures):
    wikidata_fixtures.file = "two_ids.json"
    assert app.wikidata.netflix_id(771, "movie") == "596974"


def test_values_that_are_not_ids_are_skipped(client, wikidata_fixtures):
    wikidata_fixtures.file = "bad_value.json"       # "80183187; rm", then 13 digits, then 60031255
    assert app.wikidata.netflix_id(10719, "movie") == "60031255"


def test_nothing_but_bad_values_is_none(client, wikidata_fixtures):
    wikidata_fixtures.body = json.dumps({"results": {"bindings": [
        {"netflix": {"value": "12345\n"}}, {"netflix": {"value": 80183187}}, {"netflix": "80183187"}, "x", {}]}}).encode()
    assert app.wikidata.netflix_id(10719, "movie") is None


@pytest.mark.parametrize("error, body", [
    (urllib.error.URLError("down"), None),
    (TimeoutError(), None),
    (500, None),
    (None, b"<html>Service unavailable</html>"),
    (None, b"[]"),
    (None, b'{"results": {}}'),
    (None, b'{"results": {"bindings": {}}}'),
    (None, b'{"results": []}'),
], ids=["urlerror", "timeout", "http500", "html", "list", "no-bindings", "bindings-not-a-list", "results-not-a-dict"])
def test_wikidata_errors(client, wikidata_fixtures, error, body):
    wikidata_fixtures.error, wikidata_fixtures.body = error, body
    with pytest.raises(app.wikidata.WikidataError) as e:
        app.wikidata.netflix_id(KLAUS_TMDB, "movie")
    assert e.value.message and "wikidata" in e.value.message.lower()


def test_a_status_other_than_200_is_an_error(client, monkeypatch):
    class Answer:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, n=-1):
            return (b'{"results": {"bindings": []}}')

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: Answer())
    with pytest.raises(app.wikidata.WikidataError):
        app.wikidata.netflix_id(KLAUS_TMDB, "movie")


# ------------------------------------------------------------------------------------------------ the lookup
def test_lookup_stores_the_id(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    assert app.titles.lookup(con, movie) == KLAUS_ID
    row = stored(con, movie)
    assert (row["title_id"], row["manual"]) == (KLAUS_ID, 0) and row["checked_at"]
    assert app.titles.get(con, movie) == KLAUS_ID
    assert app.titles.out(con, movie) == {"title_id": KLAUS_ID, "manual": False}
    assert app.titles.get(con, movie, "netflix") == KLAUS_ID and app.titles.NETFLIX == "netflix"
    assert query_of(wikidata_fixtures.urls[0])["query"][0].count("508965") == 1      # only the TMDB id leaves


def test_lookup_asks_the_tv_property_for_a_tv_special(con, wikidata_fixtures):
    movie = add_movie(con, 900002, "A TV special", tmdb_type="tv")
    assert app.titles.lookup(con, movie) == KLAUS_ID
    assert "wdt:P4983" in query_of(wikidata_fixtures.urls[0])["query"][0]


def test_lookup_stores_none_and_does_not_ask_again_for_30_days(con, wikidata_fixtures):
    wikidata_fixtures.file = "none.json"
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    assert app.titles.due(con) == [movie]
    assert app.titles.lookup(con, movie) is None
    row = stored(con, movie)
    assert row["title_id"] is None and row["checked_at"]            # "none found" is stored too
    assert app.titles.out(con, movie) == {"title_id": None, "manual": False}
    assert app.titles.due(con) == []
    age(con, movie, 29)
    assert app.titles.due(con) == []
    age(con, movie, 31)
    assert app.titles.due(con) == [movie] and app.titles.STALE_DAYS == 30
    assert wikidata_fixtures.calls == 1                              # due() asks nothing


def test_a_new_answer_replaces_an_old_one(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    wikidata_fixtures.file = "two_ids.json"
    app.titles.lookup(con, movie)
    age(con, movie, 31)
    wikidata_fixtures.file = "netflix_klaus.json"
    assert app.titles.lookup(con, movie) == KLAUS_ID
    assert app.titles.get(con, movie) == KLAUS_ID
    assert con.execute("SELECT COUNT(*) FROM service_titles").fetchone()[0] == 1


def test_lookup_skips_a_movie_not_on_netflix(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus", netflix=False)
    assert app.titles.lookup(con, movie) is None
    assert wikidata_fixtures.calls == 0 and stored(con, movie) is None
    assert app.titles.out(con, movie) is None and app.titles.on_netflix(con, movie) is False
    assert app.titles.due(con) == []


def test_lookup_skips_a_movie_with_no_providers_cache(con, wikidata_fixtures):
    movie = con.execute("INSERT INTO movies (tmdb_id, title) VALUES (1, 'Never fetched')").lastrowid
    con.commit()
    assert app.titles.lookup(con, movie) is None and wikidata_fixtures.calls == 0
    assert app.titles.out(con, movie) is None


def test_a_stored_id_is_kept_when_the_movie_leaves_netflix(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    app.titles.lookup(con, movie)
    con.execute("UPDATE providers_cache SET data=? WHERE movie_id=?", (provider_data(False), movie))
    con.commit()
    assert app.titles.out(con, movie) is None                        # not on Netflix now: nothing to offer
    assert app.titles.lookup(con, movie) == KLAUS_ID and wikidata_fixtures.calls == 1    # and nothing asked
    assert app.titles.due(con) == []


def test_lookup_never_changes_a_manual_id(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    app.titles.set_manual(con, movie, "https://www.netflix.com/title/70000001")
    assert app.titles.lookup(con, movie) == "70000001"
    assert wikidata_fixtures.calls == 0
    assert stored(con, movie)["title_id"] == "70000001" and stored(con, movie)["manual"] == 1
    assert app.titles.out(con, movie) == {"title_id": "70000001", "manual": True}
    age(con, movie, 400)
    assert app.titles.due(con) == []                                 # the nightly job leaves it alone, however old


def test_a_manual_id_set_while_the_lookup_was_out_wins(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    wikidata_fixtures.on_request = lambda: app.titles.set_manual(con, movie, "70000001")   # saved while Wikidata thinks
    app.titles.lookup(con, movie)
    assert app.titles.get(con, movie) == "70000001" and stored(con, movie)["manual"] == 1


def test_clearing_a_manual_id_lets_the_lookup_fill_it(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    app.titles.set_manual(con, movie, "70000001")
    app.titles.set_manual(con, movie, "")
    assert stored(con, movie) is None
    assert app.titles.out(con, movie) == {"title_id": None, "manual": False}
    assert app.titles.due(con) == [movie]
    assert app.titles.lookup(con, movie) == KLAUS_ID
    assert app.titles.out(con, movie) == {"title_id": KLAUS_ID, "manual": False}


def test_saving_it_empty_keeps_a_found_id(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    app.titles.lookup(con, movie)
    app.titles.set_manual(con, movie, "  ")
    assert app.titles.get(con, movie) == KLAUS_ID and wikidata_fixtures.calls == 1


def test_lookup_lets_a_wikidata_failure_out_and_stores_nothing(con, wikidata_fixtures):
    wikidata_fixtures.error = 500
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    with pytest.raises(app.wikidata.WikidataError):
        app.titles.lookup(con, movie)
    assert stored(con, movie) is None and app.titles.due(con) == [movie]


def test_a_failure_keeps_the_last_answer(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    app.titles.lookup(con, movie)
    age(con, movie, 31)
    before = stored(con, movie)
    wikidata_fixtures.body = b"<html>"
    with pytest.raises(app.wikidata.WikidataError):
        app.titles.lookup(con, movie)
    assert stored(con, movie) == before


def test_lookup_quietly_logs_one_warning(con, wikidata_fixtures, caplog):
    wikidata_fixtures.error = urllib.error.URLError("nope")
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    with caplog.at_level(logging.WARNING):
        assert app.titles.lookup_quietly(con, movie) is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and str(movie) in warnings[0].getMessage()
    assert "Wikidata" in warnings[0].getMessage() and stored(con, movie) is None


def test_lookup_quietly_fills_the_id(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    app.titles.lookup_quietly(con, movie)
    assert app.titles.get(con, movie) == KLAUS_ID


def test_a_removed_movie_takes_its_id_with_it(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    app.titles.lookup(con, movie)
    app.movies.remove_movie(con, movie)
    assert con.execute("SELECT COUNT(*) FROM service_titles").fetchone()[0] == 0


# ------------------------------------------------------------------------------------------------ pasted links
@pytest.mark.parametrize("raw", [
    "https://www.netflix.com/title/80183187",
    "http://netflix.com/watch/80183187?trackId=1",
    "https://www.netflix.com/us/title/80183187",
    "https://www.netflix.com/en-gb/title/80183187#x",
    "80183187",
    " 80183187 ",
    "netflix.com/title/80183187/",
    "HTTPS://WWW.NETFLIX.COM/Title/80183187?s=a&trkid=2",
])
def test_parse_link(app_ctx, raw):
    assert app.titles.parse_link(raw) == "80183187"


@pytest.mark.parametrize("raw", ["", "  ", None])
def test_parse_link_empty_is_none(app_ctx, raw):
    assert app.titles.parse_link(raw) is None


@pytest.mark.parametrize("raw", [
    "netflix.com/title/abc",
    "https://www.disneyplus.com/browse/entity-1",
    "80183187/../x",
    "1234567890123",
    "https://evil.example.com/?u=netflix.com/title/1",
    5,
    "https://netflix.com.evil.example.com/title/80183187",
    "https://evil.example.com@netflix.com.example.org/title/80183187",
    "https://www.netflix.com/title/80183187/../../x",
    "https://www.netflix.com/title/80183187\n#x",
    "80183187\n1",
    "https://www.netflix.com/browse?jbv=80183187",
    ["80183187"],
    True,
])
def test_parse_link_refuses(app_ctx, raw):
    with pytest.raises(HTTPException) as e:
        app.titles.parse_link(raw)
    assert e.value.response.status_code == 400 and e.value.response.get_json()["error"] == SENTENCE


def test_set_manual_stores_with_the_hand_flag(con):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    app.titles.set_manual(con, movie, "https://www.netflix.com/watch/80183187?x=1")
    row = stored(con, movie)
    assert (row["title_id"], row["manual"]) == (KLAUS_ID, 1)
    app.titles.set_manual(con, movie, "70000001")
    assert app.titles.get(con, movie) == "70000001"


def test_set_manual_refuses_before_it_stores(con):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    app.titles.set_manual(con, movie, KLAUS_ID)
    with pytest.raises(HTTPException):
        app.titles.set_manual(con, movie, "netflix.com/title/abc")
    assert app.titles.get(con, movie) == KLAUS_ID


# ------------------------------------------------------------------------------------------------ the API
def put(client, movie_id, body):
    return client.put(f"/api/movies/{movie_id}", json=body)


def new_movie(**kw):
    with app.app.app_context():
        return add_movie(app.get_db(), kw.pop("tmdb_id", KLAUS_TMDB), kw.pop("title", "Klaus"), **kw)


def test_put_saves_and_clears_the_link(client):
    movie = new_movie()
    r = put(client, movie, {"netflix_link": "https://www.netflix.com/title/80183187"})
    assert r.status_code == 200 and r.get_json()["netflix"] == {"title_id": KLAUS_ID, "manual": True}
    assert client.get(f"/api/movies/{movie}").get_json()["netflix"] == {"title_id": KLAUS_ID, "manual": True}
    r = put(client, movie, {"netflix_link": ""})
    assert r.status_code == 200 and r.get_json()["netflix"] == {"title_id": None, "manual": False}


def test_put_takes_the_link_alongside_the_other_fields(client):
    movie = new_movie()
    r = put(client, movie, {"netflix_link": "80183187", "parent_note": "Warm", "certification": "PG"})
    body = r.get_json()
    assert r.status_code == 200 and body["netflix"]["title_id"] == KLAUS_ID
    assert body["parent_note"] == "Warm" and body["certification"] == "PG"
    r = put(client, movie, {"parent_note": "Cozy"})                    # a note alone leaves the link alone
    assert r.get_json()["parent_note"] == "Cozy" and r.get_json()["netflix"]["title_id"] == KLAUS_ID


def test_put_refuses_a_link_that_is_not_netflix_and_changes_nothing(client):
    movie = new_movie()
    put(client, movie, {"netflix_link": KLAUS_ID})
    for bad in ("https://www.disneyplus.com/browse/entity-1", "netflix.com/title/abc", "80183187; rm", 5, ["1"]):
        r = put(client, movie, {"netflix_link": bad, "parent_note": "should not stick"})
        assert r.status_code == 400 and r.get_json()["error"] == SENTENCE
    body = client.get(f"/api/movies/{movie}").get_json()
    assert body["netflix"] == {"title_id": KLAUS_ID, "manual": True} and body["parent_note"] is None


def test_a_bad_note_does_not_save_the_link(client):
    movie = new_movie()
    r = put(client, movie, {"netflix_link": KLAUS_ID, "parent_note": 5})
    assert r.status_code == 400
    assert client.get(f"/api/movies/{movie}").get_json()["netflix"] == {"title_id": None, "manual": False}


def test_put_link_for_a_movie_that_is_not_there_is_404(client):
    assert put(client, 999, {"netflix_link": KLAUS_ID}).status_code == 404


def test_put_still_wants_something_to_change(client):
    movie = new_movie()
    assert put(client, movie, {}).status_code == 400
    assert put(client, movie, {"colour": "red"}).status_code == 400


def test_a_movie_not_on_netflix_has_no_netflix_object(client):
    movie = new_movie(netflix=False)
    r = put(client, movie, {"netflix_link": KLAUS_ID})
    assert r.status_code == 200 and r.get_json()["netflix"] is None


def test_the_list_carries_the_netflix_object(client):
    on, off = new_movie(), new_movie(tmdb_id=2, title="Other", netflix=False)
    by_id = {m["id"]: m for m in client.get("/api/movies").get_json()}
    assert by_id[on]["netflix"] == {"title_id": None, "manual": False} and by_id[off]["netflix"] is None


def test_add_looks_the_id_up(client, tmdb_fixtures, wikidata_fixtures):
    tmdb_fixtures.provider_files[PRANCER] = "providers_klaus.json"      # Netflix streams it
    r = client.post("/api/movies", json={"tmdb_id": PRANCER, "tmdb_type": "movie"})
    assert r.status_code == 201
    assert r.get_json()["netflix"] == {"title_id": KLAUS_ID, "manual": False}
    assert wikidata_fixtures.calls == 1
    query = query_of(wikidata_fixtures.urls[0])["query"][0]
    assert f'"{PRANCER}"' in query and "Prancer" not in wikidata_fixtures.urls[0]
    assert client.get(f"/api/movies/{r.get_json()['id']}").get_json()["netflix"]["title_id"] == KLAUS_ID


def test_add_asks_nothing_for_a_movie_not_on_netflix(client, tmdb_fixtures, wikidata_fixtures):
    r = client.post("/api/movies", json={"tmdb_id": 10719, "tmdb_type": "movie"})       # Elf: on Max
    assert r.status_code == 201 and r.get_json()["netflix"] is None and wikidata_fixtures.calls == 0


@pytest.mark.parametrize("error, body", [
    (500, None), (urllib.error.URLError("down"), None), (TimeoutError(), None),
    (None, b"<html>"), (None, b'{"nothing": 1}')], ids=["http500", "urlerror", "timeout", "html", "other-json"])
def test_add_survives_wikidata_down(client, tmdb_fixtures, wikidata_fixtures, caplog, error, body):
    tmdb_fixtures.provider_files[PRANCER] = "providers_klaus.json"
    wikidata_fixtures.error, wikidata_fixtures.body = error, body
    with caplog.at_level(logging.WARNING):
        r = client.post("/api/movies", json={"tmdb_id": PRANCER, "tmdb_type": "movie"})
    assert r.status_code == 201 and r.get_json()["netflix"] == {"title_id": None, "manual": False}
    warnings = [x for x in caplog.records if "Netflix title id" in x.getMessage()]
    assert len(warnings) == 1 and f"movie {r.get_json()['id']}" in warnings[0].getMessage()
    with app.app.app_context():
        assert app.get_db().execute("SELECT COUNT(*) FROM service_titles").fetchone()[0] == 0


# ------------------------------------------------------------------------------------------------ the nightly step
def test_refresh_asks_only_what_is_due(con, wikidata_fixtures):
    due = add_movie(con, KLAUS_TMDB, "Klaus")
    checked = add_movie(con, 771, "Checked")
    add_movie(con, 5, "On Disney+", netflix=False)
    by_hand = add_movie(con, 6, "By hand")
    app.titles.lookup(con, checked)
    app.titles.set_manual(con, by_hand, "70000001")
    wikidata_fixtures.urls.clear()
    said = []
    assert refresh_cli.refresh_titles(con, say=said.append) == (1, 0, 0)
    assert [query_of(u)["query"][0].count('"508965"') for u in wikidata_fixtures.urls] == [1]
    assert app.titles.get(con, due) == KLAUS_ID and said == []
    assert refresh_cli.refresh_titles(con, say=said.append) == (0, 0, 0)
    assert wikidata_fixtures.calls == 1                              # the second run asked nothing


def test_refresh_dry_run_lists_and_asks_nothing(con, wikidata_fixtures):
    movie = add_movie(con, KLAUS_TMDB, "Klaus")
    said = []
    assert refresh_cli.refresh_titles(con, dry_run=True, say=said.append) == (1, 0, 0)
    assert said == ["would ask Wikidata for the Netflix id of Klaus"]
    assert wikidata_fixtures.calls == 0 and stored(con, movie) is None


def test_refresh_stops_at_the_first_wikidata_failure(con, wikidata_fixtures):
    wikidata_fixtures.error = 500
    for n in range(3):
        add_movie(con, 1000 + n, f"Movie {n}")
    said = []
    assert refresh_cli.refresh_titles(con, say=said.append) == (0, 1, 2)
    assert wikidata_fixtures.calls == 1                              # not one timeout per movie
    assert len(said) == 1 and "Movie 0" in said[0] and "2 more left for tomorrow" in said[0]
    assert con.execute("SELECT COUNT(*) FROM service_titles").fetchone()[0] == 0


def test_refresh_main_reports_the_step_and_exits_1_on_a_failure(client, wikidata_fixtures, capsys):
    with app.app.app_context():
        add_movie(app.get_db(), KLAUS_TMDB, "Klaus")
    assert refresh_cli.main([]) == 0
    assert "Netflix ids looked up for 1 (0 failed, 0 left for tomorrow)" in capsys.readouterr().out
    wikidata_fixtures.error = 500
    with app.app.app_context():
        add_movie(app.get_db(), 771, "Another")
    assert refresh_cli.main([]) == 1
    out = capsys.readouterr().out
    assert "Netflix ids looked up for 0 (1 failed, 0 left for tomorrow)" in out and "Another" in out


def test_refresh_main_dry_run(client, wikidata_fixtures, capsys):
    with app.app.app_context():
        add_movie(app.get_db(), KLAUS_TMDB, "Klaus")
    assert refresh_cli.main(["--dry-run"]) == 0
    assert "would ask Wikidata for the Netflix id of Klaus" in capsys.readouterr().out
    assert wikidata_fixtures.calls == 0
