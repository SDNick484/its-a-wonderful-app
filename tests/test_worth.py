"""Worth a Month? (spec §13, decision 16, plan Task 15): which considering service would add the most unwatched list
movies. Reads the providers cache and matinee_sync only, so these tests write the cache rows directly (no TMDB and no
Matinee call is made by the feature); the route test uses the client fixture, so the editor rule applies."""
import datetime as dt
import json

import pytest

import app
from common import now_iso
from worth import compute, season

GRINCH_1966, GRINCH_2000, GRINCH_2018, POLAR, EIGHT_BIT, CHARLIE = 101, 102, 103, 104, 105, 106
GRINCH_TITLES = ("How the Grinch Stole Christmas! (1966)", "How the Grinch Stole Christmas (2000)", "The Grinch (2018)")


@pytest.fixture
def con(app_ctx):
    return app_ctx.get_db()


def add_movie(con, tmdb_id, title):
    cur = con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title) VALUES (?, 'movie', ?)", (tmdb_id, title))
    con.commit()
    return cur.lastrowid


def cache(con, movie_id, flatrate=(), free=(), ads=(), rent=()):
    """A providers cache row as providers.refresh writes it: service keys for known services, raw names otherwise."""
    data = {"flatrate": list(flatrate), "free": list(free), "ads": list(ads), "rent": list(rent), "buy": []}
    con.execute("INSERT OR REPLACE INTO providers_cache (movie_id, data, link, fetched_at) VALUES (?, ?, 'https://example.com', ?)",
                (movie_id, json.dumps(data), now_iso()))
    con.commit()


def set_status(con, key, status):
    con.execute("UPDATE services SET status=? WHERE key=?", (status, key))
    con.commit()


def own(con, movie_id):
    con.execute("INSERT INTO matinee_sync (movie_id, matinee_title_id, owned_summary) VALUES (?, 7, 'Blu-ray')", (movie_id,))
    con.commit()


def finish(con, movie_id, on):
    con.execute("INSERT INTO viewings (movie_id, started_on, status, finished_on) VALUES (?, ?, 'finished', ?)",
                (movie_id, on, on))
    con.commit()


def counts(result):
    return {e["service"]: e["count"] for e in result}


def entry(result, key):
    return next(e for e in result if e["service"] == key)


@pytest.fixture
def grinches(con):
    """The three Grinches on Peacock, and The Polar Express and 8-Bit Christmas on HBO Max; Charlie Brown on Apple TV."""
    ids = {}
    for tmdb_id, title in ((GRINCH_1966, "How the Grinch Stole Christmas! (1966)"), (GRINCH_2000, "How the Grinch Stole Christmas (2000)"),
                           (GRINCH_2018, "The Grinch (2018)")):
        ids[title] = add_movie(con, tmdb_id, title)
        cache(con, ids[title], flatrate=["peacock"])
    ids["Polar"] = add_movie(con, POLAR, "The Polar Express")
    cache(con, ids["Polar"], flatrate=["hbo_max"])
    ids["8-Bit"] = add_movie(con, EIGHT_BIT, "8-Bit Christmas")
    cache(con, ids["8-Bit"], flatrate=["hbo_max"])
    ids["Charlie"] = add_movie(con, CHARLIE, "A Charlie Brown Christmas")
    cache(con, ids["Charlie"], flatrate=["apple_tv"])
    return ids


def test_peacock_counts_the_three_grinches(con, grinches):
    got = compute(con, 2026)
    assert entry(got, "peacock")["count"] == 3
    assert sorted(entry(got, "peacock")["movies"]) == sorted(grinches[t] for t in GRINCH_TITLES)
    assert got[0]["service"] == "peacock"                           # most movies first


def test_owned_movie_not_counted(con, grinches):
    assert entry(compute(con, 2026), "hbo_max")["count"] == 2
    own(con, grinches["Polar"])                                     # Matinee has the Blu-ray
    got = compute(con, 2026)
    assert entry(got, "hbo_max")["count"] == 1
    assert grinches["Polar"] not in entry(got, "hbo_max")["movies"]


def test_free_or_subscribed_elsewhere_not_counted(con, grinches):
    set_status(con, "netflix", "subscribed")
    cache(con, grinches["Polar"], flatrate=["hbo_max", "netflix"])     # also on Netflix: the family can watch it now
    free = add_movie(con, 201, "Free Peacock Tale")
    cache(con, free, flatrate=["peacock"], free=["tubi"])               # free elsewhere
    ads = add_movie(con, 202, "Ads Peacock Tale")
    cache(con, ads, flatrate=["peacock"], ads=["the_roku_channel"])     # free with ads elsewhere
    assert entry(compute(con, 2026), "peacock")["count"] == 3          # the three Grinches only
    assert entry(compute(con, 2026), "hbo_max")["count"] == 1          # 8-Bit Christmas; Polar is on Netflix too


def test_a_movie_never_fetched_is_not_counted(con, grinches):
    add_movie(con, 203, "Never Fetched Grinch")
    assert entry(compute(con, 2026), "peacock")["count"] == 3


def test_watched_this_year_not_counted(con, grinches):
    finish(con, grinches["How the Grinch Stole Christmas! (1966)"], "2026-12-20")
    con.execute("INSERT INTO matinee_sync (movie_id, matinee_title_id, matinee_last_watch) VALUES (?, NULL, '2026-11-30')",
                (grinches["The Grinch (2018)"],))             # Matinee's newest watch is this year too
    con.commit()
    got = compute(con, 2026)
    assert entry(got, "peacock")["count"] == 1
    assert entry(compute(con, 2025), "peacock")["count"] == 3       # a watch in 2026 is not 2025's


def test_a_watch_on_january_2_counts_for_the_new_year(con, grinches):
    finish(con, grinches["The Grinch (2018)"], "2027-01-02")
    assert entry(compute(con, 2026), "peacock")["count"] == 3          # still unwatched in 2026
    assert entry(compute(con, 2027), "peacock")["count"] == 2          # watched in 2027


def test_zero_service_listed_with_reason(con, grinches):
    got = compute(con, 2026)
    para = entry(got, "paramount_plus")
    assert para["count"] == 0 and para["movies"] == []
    assert para["reason"] == "None of our movies is on it."
    own(con, grinches["Charlie"])
    apple = entry(compute(con, 2026), "apple_tv")
    assert apple["count"] == 0
    assert apple["reason"] == "All 1 of its movies here are owned, already on a service you have, free, or watched this year."


def test_only_considering_services_listed_sorted_by_count_then_name(con, grinches):
    set_status(con, "paramount_plus", "considering")
    set_status(con, "apple_tv", "ignore")
    set_status(con, "hbo_max", "subscribed")
    got = compute(con, 2026)
    assert [e["service"] for e in got] == ["peacock", "paramount_plus"]
    assert got[0]["reason"] is None and got[1]["reason"] is not None


def test_nothing_considering_is_an_empty_list(con, grinches):
    for key in ("peacock", "hbo_max", "paramount_plus", "apple_tv"):
        set_status(con, key, "subscribed")
    assert compute(con, 2026) == []


def test_season_is_november_and_december_on_the_host_date():
    assert season(dt.date(2026, 11, 1)) and season(dt.date(2026, 12, 31))
    assert not season(dt.date(2026, 10, 31)) and not season(dt.date(2027, 1, 1))


def test_worth_route_answers_for_an_editor(client):
    with app.app.app_context():
        con = app.get_db()
        cache(con, add_movie(con, GRINCH_2018, "The Grinch (2018)"), flatrate=["peacock"])
    body = client.get("/api/worth").get_json()
    assert set(body) == {"year", "season", "services"} and isinstance(body["season"], bool)
    peacock = entry(body["services"], "peacock")
    assert peacock["count"] == 1 and set(peacock) == {"service", "name", "movies", "count", "reason"}
