"""Where to watch and the subscriptions (spec §7.2, decisions 15 and 20, plan Task 4): TMDB's US providers mapped to the
family's services, the ordered "where to watch" lines, "ready tonight", the 7-day cache and the services routes. TMDB
answers from the recorded fixtures (tests/fixtures/tmdb/providers_*.json); no network."""
import json
import urllib.error

import pytest

import app
import tmdb

ELF, KLAUS, PEACOCK, FROSTY, QUIET = 10719, 508439, 990001, 990002, 900001   # TMDB ids with a providers fixture


def add_row(con, tmdb_id, title):
    """A movie row with no TMDB call (providers only need the id and the type)."""
    cur = con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title) VALUES (?, 'movie', ?)", (tmdb_id, title))
    con.commit()
    return cur.lastrowid


@pytest.fixture
def con(app_ctx):
    return app_ctx.get_db()


def providers_calls(fake):
    return [u for u in fake.api if "/watch/providers" in u]


def age_cache(con, movie_id, days):
    con.execute("UPDATE providers_cache SET fetched_at=strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?) WHERE movie_id=?",
                (f"-{days} days", movie_id))
    con.commit()


def lines(con, movie_id):
    return [(w["kind"], w["label"]) for w in app.providers.where_to_watch(con, movie_id)]


# ------------------------------------------------------------------------------------------------ the services
def test_services_seeded_with_decision_15_statuses(con):
    by_status = {}
    for s in app.providers.list_services(con):
        by_status.setdefault(s["status"], []).append(s["name"])
    assert by_status == {
        "subscribed": ["Netflix", "Disney+", "Hulu", "Prime Video", "Fandango at Home", "YouTube TV"],
        "considering": ["HBO Max", "Peacock", "Paramount+", "Apple TV"]}
    tv = {s["key"]: s["tv_source"] for s in app.providers.list_services(con)}
    assert tv["disney_plus"] == "Disney+" and tv["fandango_at_home"] == "Fandango at Home" and tv["apple_tv"] is None


def test_reseeding_keeps_a_status_somebody_changed_and_refreshes_the_rest(con, tmp_path):
    app.providers.set_status(con, {"key": "peacock", "status": "subscribed"})
    con.execute("UPDATE services SET name='Old', tv_source='x', tmdb_provider_ids='[]' WHERE key='peacock'")
    app.migrate(con)
    peacock = next(s for s in app.providers.list_services(con) if s["key"] == "peacock")
    assert peacock["status"] == "subscribed" and peacock["name"] == "Peacock"
    assert peacock["tv_source"] == "Peacock" and peacock["tmdb_provider_ids"] == [386, 387]


def test_a_missing_or_broken_services_file_changes_nothing(con, tmp_path):
    before = app.providers.list_services(con)
    app.providers.seed_services(con, tmp_path / "nope.json")
    (tmp_path / "bad.json").write_text("{not json")
    app.providers.seed_services(con, tmp_path / "bad.json")
    assert app.providers.list_services(con) == before


# ------------------------------------------------------------------------------------------------ the lines
def test_klaus_on_netflix_is_subscribed_first(con, tmdb_fixtures):
    klaus = add_row(con, KLAUS, "Klaus")
    app.providers.get(con, klaus)
    assert lines(con, klaus) == [("subscribed", "On Netflix"), ("rent_buy", "Rent or buy")]
    assert app.providers.ready_tonight(con, klaus) is True
    assert app.providers.get(con, klaus)["flatrate"] == ["netflix"]       # stored as the service's key


def test_free_with_ads_counts_as_ready(con, tmdb_fixtures):     # decision 20
    elf = add_row(con, ELF, "Elf")
    app.providers.get(con, elf)
    assert lines(con, elf) == [
        ("free", "Free with ads on The Roku Channel"),
        ("considering", "On HBO Max (you don't have it)"),
        ("rent_buy", "Rent or buy")]
    assert app.providers.ready_tonight(con, elf) is True


def test_peacock_only_title_reads_on_peacock_you_dont_have_it(con, tmdb_fixtures):
    movie = add_row(con, PEACOCK, "The Peacock Parade")
    app.providers.get(con, movie)
    assert lines(con, movie) == [("considering", "On Peacock (you don't have it)")]
    assert app.providers.ready_tonight(con, movie) is False
    app.providers.set_status(con, {"key": "peacock", "status": "subscribed"})      # subscribe and it is ready
    assert lines(con, movie) == [("subscribed", "On Peacock")] and app.providers.ready_tonight(con, movie) is True
    app.providers.set_status(con, {"key": "peacock", "status": "ignore"})          # ignore and it is never mentioned
    assert lines(con, movie) == [("rent_buy", "Rent or buy")]


def test_no_us_providers_reads_rent_or_buy(con, tmdb_fixtures):
    quiet = add_row(con, QUIET, "The Quiet Reindeer")            # the fixture lists only Canada
    assert app.providers.get(con, quiet) == {"flatrate": [], "free": [], "ads": [], "rent": [], "buy": []}
    assert lines(con, quiet) == [("rent_buy", "Rent or buy")]
    assert app.providers.ready_tonight(con, quiet) is False


def test_never_fetched_reads_rent_or_buy_without_calling_tmdb(con, tmdb_fixtures):
    elf = add_row(con, ELF, "Elf")
    assert lines(con, elf) == [("rent_buy", "Rent or buy")] and not app.providers.ready_tonight(con, elf)
    assert tmdb_fixtures.api == []


def test_unknown_tmdb_provider_name_shown_raw(con, tmdb_fixtures):
    movie = add_row(con, FROSTY, "The Frosty Gift")
    data = app.providers.get(con, movie)
    assert data["flatrate"] == ["Frosty Plus"] and data["free"] == ["Snowball TV"]       # no service has these ids
    assert lines(con, movie) == [("free", "Free on Snowball TV"), ("considering", "On Frosty Plus (you don't have it)")]


def test_ignoring_a_free_service_hides_it(con, tmdb_fixtures):
    elf = add_row(con, ELF, "Elf")
    app.providers.get(con, elf)
    con.execute("INSERT INTO services (key, name, tmdb_provider_ids, status) VALUES ('roku', 'The Roku Channel', '[207]', 'ignore')")
    app.providers.refresh(con, elf)                              # 207 now maps to a service that is ignored
    assert ("free", "Free with ads on The Roku Channel") not in lines(con, elf)


def test_rent_only_on_a_subscribed_service_is_still_just_rent_or_buy(con, tmdb_fixtures):
    elf = add_row(con, ELF, "Elf")
    app.providers.get(con, elf)
    assert all(kind != "subscribed" for kind, _ in lines(con, elf))     # Apple TV rent/buy is not "on a service"


# ------------------------------------------------------------------------------------------------ the cache
def test_stale_cache_refreshes_and_fresh_cache_does_not(con, tmdb_fixtures):
    klaus = add_row(con, KLAUS, "Klaus")
    app.providers.get(con, klaus)
    app.providers.get(con, klaus)
    assert len(providers_calls(tmdb_fixtures)) == 1              # the second read came from the cache
    age_cache(con, klaus, 6)
    app.providers.get(con, klaus)
    assert len(providers_calls(tmdb_fixtures)) == 1              # 6 days old is still fresh
    age_cache(con, klaus, 8)
    app.providers.get(con, klaus)
    assert len(providers_calls(tmdb_fixtures)) == 2              # 8 days old is stale
    app.providers.get(con, klaus)
    assert len(providers_calls(tmdb_fixtures)) == 2              # and fresh again
    assert app.providers.get(con, klaus, max_age_days=0) and len(providers_calls(tmdb_fixtures)) == 3


def test_tmdb_down_keeps_serving_the_old_cache(con, tmdb_fixtures, monkeypatch):
    klaus = add_row(con, KLAUS, "Klaus")
    app.providers.get(con, klaus)
    age_cache(con, klaus, 30)
    monkeypatch.setattr(app, "TMDB_READ_TOKEN", "")              # "TMDB is not set up": any TmdbError will do
    assert app.providers.get(con, klaus)["flatrate"] == ["netflix"]
    assert lines(con, klaus)[0] == ("subscribed", "On Netflix")
    with pytest.raises(tmdb.TmdbError):
        app.providers.refresh(con, klaus)
    assert app.providers.cached(con, klaus)[3] is True           # still marked stale, so the page tries again


def test_tmdb_down_with_no_cache_raises(con, tmdb_down):
    klaus = add_row(con, KLAUS, "Klaus")
    with pytest.raises(tmdb.TmdbError) as e:
        app.providers.get(con, klaus)
    assert e.value.reason == "unavailable" and e.value.status == 502
    assert app.providers.cached(con, klaus)[0] == {t: [] for t in app.providers.TIERS}


def test_tmdb_has_no_providers_entry_is_not_found(con, tmdb_fixtures):          # the miss
    stranger = add_row(con, 424242, "Not Recorded")
    with pytest.raises(tmdb.TmdbError) as e:
        app.providers.get(con, stranger)
    assert e.value.reason == "not_found"


def test_watch_providers_reads_us_only_in_display_order(tmdb_fixtures):
    got = tmdb.watch_providers(ELF, "movie")
    assert got["link"] == "https://www.themoviedb.org/movie/10719-elf/watch?locale=US"
    assert got["flatrate"] == [{"id": 1899, "name": "Max"}] and got["ads"][0]["name"] == "The Roku Channel"
    assert tmdb.watch_providers(QUIET, "movie") == {"link": None, "flatrate": [], "free": [], "ads": [], "rent": [], "buy": []}
    assert tmdb_fixtures.api[0].endswith("/3/movie/10719/watch/providers")
    with pytest.raises(ValueError):
        tmdb.watch_providers(ELF, "person")


def test_deleting_a_movie_takes_its_cache_with_it(con, tmdb_fixtures):
    klaus = add_row(con, KLAUS, "Klaus")
    app.providers.get(con, klaus)
    app.movies.remove_movie(con, klaus)
    assert con.execute("SELECT COUNT(*) FROM providers_cache").fetchone()[0] == 0


# ------------------------------------------------------------------------------------------------ the routes
def test_services_routes(client):
    got = client.get("/api/services").get_json()
    assert [s["key"] for s in got][:2] == ["netflix", "disney_plus"] and got[0]["status"] == "subscribed"
    r = client.put("/api/services", json={"key": "peacock", "status": "subscribed"})
    assert r.status_code == 200 and {s["key"]: s["status"] for s in r.get_json()}["peacock"] == "subscribed"
    assert client.put("/api/services", json={"key": "peacock", "status": "maybe"}).status_code == 400
    assert client.put("/api/services", json={"key": "peacock"}).status_code == 400
    assert client.put("/api/services", json={"key": "nope", "status": "ignore"}).status_code == 404
    assert client.put("/api/services", data="not json", content_type="application/json").status_code == 400
    assert {s["key"]: s["status"] for s in client.get("/api/services").get_json()}["peacock"] == "subscribed"


def test_add_fetches_providers_and_the_list_and_detail_carry_them(client, tmdb_fixtures):
    added = client.post("/api/movies", json={"tmdb_id": ELF, "tmdb_type": "movie"})
    assert added.status_code == 201 and added.get_json()["where_to_watch"][0]["label"] == "Free with ads on The Roku Channel"
    listed = client.get("/api/movies").get_json()
    assert listed[0]["where_to_watch"][0]["kind"] == "free"
    detail = client.get(f"/api/movies/{added.get_json()['id']}").get_json()
    assert [w["kind"] for w in detail["where_to_watch"]] == ["free", "considering", "rent_buy"]
    assert detail["providers_link"].startswith("https://www.themoviedb.org/") and detail["providers_stale"] is False
    assert len(providers_calls(tmdb_fixtures)) == 1               # list and detail read the cache only


def test_add_still_works_when_the_providers_call_fails(client, tmdb_fixtures):
    tmdb_fixtures.provider_files.clear()                           # TMDB answers 404 for providers
    r = client.post("/api/movies", json={"tmdb_id": ELF, "tmdb_type": "movie"})
    assert r.status_code == 201
    body = r.get_json()
    assert body["where_to_watch"] == [{"kind": "rent_buy", "label": "Rent or buy"}] and body["providers_stale"] is True


def test_refresh_route(client, tmdb_fixtures):
    movie = client.post("/api/movies", json={"tmdb_id": ELF, "tmdb_type": "movie"}).get_json()["id"]
    tmdb_fixtures.provider_files[ELF] = "providers_klaus.json"      # TMDB's answer changed
    r = client.post(f"/api/movies/{movie}/providers/refresh")
    assert r.status_code == 200 and r.get_json()["where_to_watch"][0] == {"kind": "subscribed", "label": "On Netflix"}
    assert client.post("/api/movies/9999/providers/refresh").status_code == 404


def test_refresh_route_with_tmdb_down_is_502_with_a_message_and_keeps_the_old_answer(client, tmdb_fixtures, monkeypatch):
    with app.app.app_context():                                    # Klaus has no details fixture: add the row directly
        mid = add_row(app.get_db(), KLAUS, "Klaus")
        app.providers.get(app.get_db(), mid)

    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {}, None)
    monkeypatch.setattr("urllib.request.urlopen", boom)
    r = client.post(f"/api/movies/{mid}/providers/refresh")
    assert r.status_code == 502 and "TMDB had a problem" in r.get_json()["error"]
    assert client.get(f"/api/movies/{mid}").get_json()["where_to_watch"][0]["label"] == "On Netflix"


def test_refresh_route_without_a_token_is_503(client):
    with app.app.app_context():
        mid = add_row(app.get_db(), KLAUS, "Klaus")
    r = client.post(f"/api/movies/{mid}/providers/refresh")
    assert r.status_code == 503 and "TMDB_READ_TOKEN" in r.get_json()["error"]


def test_a_cache_with_junk_in_it_reads_as_empty(con):
    klaus = add_row(con, KLAUS, "Klaus")
    con.execute("INSERT INTO providers_cache (movie_id, data, link, fetched_at) VALUES (?, 'junk', 'javascript:alert(1)', 'never')", (klaus,))
    con.commit()
    out = app.providers.movie_providers(con, klaus)
    assert out["where_to_watch"] == [{"kind": "rent_buy", "label": "Rent or buy"}]
    assert out["providers_link"] is None and out["providers_stale"] is True


def test_seed_cli_fetches_providers(tmdb_fixtures, tmp_path):
    import test_seed
    path = test_seed.write_seed(tmp_path, [test_seed.ELF])
    with app.app.app_context():
        con = app.get_db()
        test_seed.seed.seed(con, json.loads(path.read_text()), say=lambda *_: None)
        movie = con.execute("SELECT id FROM movies").fetchone()["id"]
        assert app.providers.where_to_watch(con, movie)[0]["kind"] == "free"
