"""The randomizer (spec §12, plan Task 7): each filter, the three distinct picks, Pick Again until the pool runs out,
and the year boundary. No network: the rows are written straight into the database, with the holes TMDB leaves (no
runtime, no US certification) written as they are stored (Review Focus 2). Matinee's watches arrive as matinee_sync
rows, as movies.check_ownership writes them."""
import datetime as dt
import random

import pytest

import app
import randomizer

# (title, certification, runtime_min, is_animated)
LIBRARY = [
    ("Tinsel Town", "G", 82, 1),
    ("Nutcracker Nights", "G", 95, 0),
    ("Frosty Fridays", "PG", 88, 1),
    ("Mistletoe Mile", "PG", 104, 0),
    ("Four Christmases Later", "PG-13", 88, 0),     # only passes at PG-13
    ("Silver Sleigh", "NR", 120, 0),
    ("The Quiet Reindeer", None, None, 0),          # no certification (reads as NR) and no runtime
    ("Gritty Noel", "R", 100, 0),                   # never passes a cap
]


def add(con, title, cert, runtime, animated, tmdb_id=None):
    cur = con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title, certification, runtime_min, is_animated)"
                      " VALUES (?, 'movie', ?, ?, ?, ?)", (tmdb_id or 7000 + con.execute("SELECT COUNT(*) FROM movies").fetchone()[0],
                                                           title, cert, runtime, animated))
    con.commit()
    return cur.lastrowid


@pytest.fixture
def con(app_ctx):
    return app_ctx.get_db()


@pytest.fixture
def ids(con):
    return {title: add(con, title, cert, runtime, animated) for title, cert, runtime, animated in LIBRARY}


def titles(con, filters, **kw):
    by_id = {r["id"]: r["title"] for r in con.execute("SELECT id, title FROM movies")}
    return sorted(by_id[i] for i in randomizer.pool(con, filters, **kw))


def finish(con, movie_id, on, status="finished"):
    con.execute("INSERT INTO viewings (movie_id, started_on, status, finished_on) VALUES (?,?,?,?)",
                (movie_id, on, status, on if status == "finished" else None))
    con.commit()


def matinee_watch(con, movie_id, last_watch):
    con.execute("INSERT INTO matinee_sync (movie_id, matinee_title_id, matinee_last_watch) VALUES (?, 1, ?)",
                (movie_id, last_watch))
    con.commit()


# ------------------------------------------------------------------------------------------------ the filters
def test_all_chips_off_is_whole_list(con, ids):
    everything = sorted(ids)
    assert titles(con, {}) == everything
    assert titles(con, None) == everything
    assert titles(con, {"animated": None, "cap": None, "under_90": False, "not_watched_this_year": False,
                        "ready": False}) == everything


def test_animated_and_live_action_are_exclusive_halves(con, ids):
    assert titles(con, {"animated": True}) == ["Frosty Fridays", "Tinsel Town"]
    live = titles(con, {"animated": False})
    assert "Tinsel Town" not in live and "Frosty Fridays" not in live and len(live) == len(ids) - 2


def test_cap_G_excludes_NR_and_cap_PG_includes_NR(con, ids):
    assert titles(con, {"cap": "G"}) == ["Nutcracker Nights", "Tinsel Town"]            # NR and no certification: not G
    pg = titles(con, {"cap": "PG"})
    assert "Silver Sleigh" in pg and "The Quiet Reindeer" in pg                          # NR counts as PG (spec §7.3)
    assert pg == sorted(["Tinsel Town", "Nutcracker Nights", "Frosty Fridays", "Mistletoe Mile", "Silver Sleigh",
                         "The Quiet Reindeer"])
    assert "Silver Sleigh" in titles(con, {"cap": "PG-13"})


def test_four_christmases_only_at_PG13(con, ids):
    assert "Four Christmases Later" not in titles(con, {"cap": "G"})
    assert "Four Christmases Later" not in titles(con, {"cap": "PG"})
    assert "Four Christmases Later" in titles(con, {"cap": "PG-13"})
    assert "Four Christmases Later" in titles(con, {})
    assert "Gritty Noel" not in titles(con, {"cap": "PG-13"})                              # R is above every cap


def test_a_tv_rating_sits_on_the_ladder(con):
    kids = add(con, "Elf Show Special", "TV-Y7", 30, 1)
    teen = add(con, "Teen Tinsel", "TV-14", 45, 0)
    mature = add(con, "Midnight Mass-ish", "TV-MA", 50, 0)
    assert {kids, teen} <= set(randomizer.pool(con, {"cap": "PG-13"})) and mature not in randomizer.pool(con, {"cap": "PG-13"})
    assert kids in randomizer.pool(con, {"cap": "PG"}) and teen not in randomizer.pool(con, {"cap": "PG"})
    assert kids not in randomizer.pool(con, {"cap": "G"})


def test_under_90_excludes_null_runtime(con, ids):
    """Review Focus 2: runtime null is unknown, not short. Exactly 90 is not under 90."""
    add(con, "Exactly Ninety", "G", 90, 0)
    short = titles(con, {"under_90": True})
    assert short == ["Four Christmases Later", "Frosty Fridays", "Tinsel Town"]
    assert "The Quiet Reindeer" not in short and "Exactly Ninety" not in short
    assert "The Quiet Reindeer" in titles(con, {})


def test_a_title_with_no_poster_providers_or_certification_still_comes_up(con, ids):
    """Review Focus 2: with no US certification, no poster and no providers the movie is still on the list."""
    quiet = ids["The Quiet Reindeer"]
    assert quiet in randomizer.pool(con, {})
    assert quiet in randomizer.pool(con, {"cap": "PG"}) and quiet not in randomizer.pool(con, {"cap": "G"})
    assert quiet not in randomizer.pool(con, {"ready": True})        # nothing known to watch it on


def test_ready_keeps_owned_subscribed_and_free(con, ids):
    owned, subscribed, free, plain = (ids["Tinsel Town"], ids["Nutcracker Nights"], ids["Frosty Fridays"],
                                      ids["Mistletoe Mile"])
    con.execute("INSERT INTO matinee_sync (movie_id, matinee_title_id, owned_summary, checked_at)"
                " VALUES (?, 5, 'Blu-ray', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))", (owned,))
    con.execute("UPDATE services SET status='subscribed' WHERE key='netflix'")
    for movie, data in ((subscribed, '{"flatrate": ["netflix"]}'), (free, '{"ads": ["The Roku Channel"]}'),
                        (plain, '{"rent": ["Apple TV"]}')):
        con.execute("INSERT INTO providers_cache (movie_id, data, fetched_at) VALUES (?,?,'2026-11-18T00:00:00Z')",
                    (movie, data))
    con.commit()
    assert set(randomizer.pool(con, {"ready": True})) == {owned, subscribed, free}


# ------------------------------------------------------------------------------------------------ not watched this year
def test_watched_jan_2_counts_for_new_year(con, ids):
    """Review Focus 5: a viewing finished January 2 counts for the new year, not the old one."""
    elf = ids["Tinsel Town"]
    finish(con, elf, "2027-01-02")
    assert randomizer.watched_this_year(con, elf, 2027) is True
    assert randomizer.watched_this_year(con, elf, 2026) is False
    assert "Tinsel Town" not in titles(con, {"not_watched_this_year": True}, year=2027)
    assert "Tinsel Town" in titles(con, {"not_watched_this_year": True}, year=2026)


def test_a_december_30_watch_counts_for_the_year_it_happened(con, ids):
    movie = ids["Mistletoe Mile"]
    finish(con, movie, "2026-12-30")
    assert randomizer.watched_this_year(con, movie, 2026) and not randomizer.watched_this_year(con, movie, 2027)


def test_year_comes_from_the_hosts_today_not_utc(app_ctx, con, ids, monkeypatch):
    """The route asks common.today() (the host's TZ). On January 2 on the host, last December's watch is forgotten."""
    finish(con, ids["Tinsel Town"], "2026-12-30")
    finish(con, ids["Nutcracker Nights"], "2027-01-01")
    monkeypatch.setattr(app, "today", lambda: dt.date(2027, 1, 2))
    got = set(randomizer.pool(con, {"not_watched_this_year": True}))
    assert ids["Tinsel Town"] in got and ids["Nutcracker Nights"] not in got
    monkeypatch.setattr(app, "today", lambda: dt.date(2026, 12, 31))
    got = set(randomizer.pool(con, {"not_watched_this_year": True}))
    assert ids["Tinsel Town"] not in got and ids["Nutcracker Nights"] in got


def test_only_a_finished_viewing_counts(con, ids):
    movie = ids["Tinsel Town"]
    for status in ("tonight", "watching", "paused", "abandoned"):
        finish(con, movie, "2026-12-01", status=status)
    assert randomizer.watched_this_year(con, movie, 2026) is False
    finish(con, movie, "2026-12-02")
    assert randomizer.watched_this_year(con, movie, 2026) is True


def test_a_matinee_watch_counts_for_an_owned_movie(con, ids):
    movie = ids["Silver Sleigh"]
    matinee_watch(con, movie, "2026-12-20")
    assert randomizer.watched_this_year(con, movie, 2026) is True
    assert randomizer.watched_this_year(con, movie, 2027) is False
    assert "Silver Sleigh" not in titles(con, {"not_watched_this_year": True}, year=2026)
    assert randomizer.watched_this_year(con, ids["Tinsel Town"], 2026) is False       # no sync row: never watched
    matinee_watch(con, ids["Frosty Fridays"], None)                                    # owned, never watched
    assert randomizer.watched_this_year(con, ids["Frosty Fridays"], 2026) is False


# ------------------------------------------------------------------------------------------------ picking
def test_three_distinct_picks(con, ids):
    for seed in range(20):
        picks = randomizer.pick(randomizer.pool(con, {}), set(), 3, random.Random(seed))
        assert len(picks) == 3 and len(set(picks)) == 3 and set(picks) <= set(ids.values())


def test_pick_is_roughly_uniform():
    rng, seen = random.Random(11), {i: 0 for i in range(6)}
    for _ in range(3000):
        for i in randomizer.pick(list(range(6)), set(), 3, rng):
            seen[i] += 1
    assert all(1300 < n < 1700 for n in seen.values()), seen        # 1500 each, with room for chance


def test_fewer_than_three_returns_what_matches(con, ids):
    got = randomizer.surprise(con, {"filters": {"cap": "G", "under_90": True}}, random.Random(1))
    assert got == {"picks": [ids["Tinsel Town"]], "pool_size": 1, "restarted": False}
    got = randomizer.surprise(con, {"filters": {"cap": "G"}}, random.Random(1))
    assert sorted(got["picks"]) == sorted([ids["Tinsel Town"], ids["Nutcracker Nights"]]) and got["pool_size"] == 2
    none = randomizer.surprise(con, {"filters": {"animated": True, "under_90": True, "cap": "G", "ready": True}})
    assert none == {"picks": [], "pool_size": 0, "restarted": False}


def test_pick_again_excludes_shown_until_exhausted_then_restarts(con, ids):
    rng = random.Random(5)
    shown, rounds = [], []
    for _ in range(3):                              # 8 movies: 3 + 3 + the last 2 and one more
        got = randomizer.surprise(con, {"filters": {}, "exclude": shown}, rng)
        rounds.append(got)
        if not got["restarted"]:
            assert not set(got["picks"]) & set(shown)           # nothing shown twice until the pool runs out
            shown += got["picks"]
    first, second, third = rounds
    assert not first["restarted"] and not second["restarted"] and first["pool_size"] == 8
    assert len(first["picks"]) == len(second["picks"]) == 3 and len(set(first["picks"] + second["picks"])) == 6
    left = set(ids.values()) - set(first["picks"] + second["picks"])
    assert third["restarted"] is True and len(third["picks"]) == 3 and len(set(third["picks"])) == 3
    assert left <= set(third["picks"])                          # the two never shown come first, then a fresh draw
    again = randomizer.surprise(con, {"filters": {}, "exclude": third["picks"]}, rng)      # after a restart: new exclude
    assert not again["restarted"] and not set(again["picks"]) & set(third["picks"])


def test_pick_again_with_everything_shown_restarts_in_full(con, ids):
    got = randomizer.surprise(con, {"filters": {}, "exclude": list(ids.values())}, random.Random(2))
    assert got["restarted"] is True and len(got["picks"]) == 3 and got["pool_size"] == 8


def test_exclude_ids_outside_the_pool_are_ignored(con, ids):
    got = randomizer.surprise(con, {"filters": {"cap": "G"}, "exclude": [ids["Gritty Noel"], 99999]}, random.Random(3))
    assert sorted(got["picks"]) == sorted([ids["Tinsel Town"], ids["Nutcracker Nights"]]) and not got["restarted"]


def test_an_empty_list_has_no_picks(app_ctx):
    assert randomizer.surprise(app_ctx.get_db(), {}) == {"picks": [], "pool_size": 0, "restarted": False}


# ------------------------------------------------------------------------------------------------ the route
def test_surprise_route(client, ids_client):
    c, ids = ids_client
    r = c.post("/api/surprise", json={"filters": {"cap": "G"}, "exclude": []})
    assert r.status_code == 200
    body = r.get_json()
    assert sorted(body["picks"]) == sorted([ids["Tinsel Town"], ids["Nutcracker Nights"]])
    assert body["pool_size"] == 2 and body["restarted"] is False


def test_surprise_route_without_a_body_is_the_whole_list(client, ids_client):
    c, ids = ids_client
    r = c.post("/api/surprise", json={})
    assert r.status_code == 200 and len(r.get_json()["picks"]) == 3 and r.get_json()["pool_size"] == len(ids)


@pytest.mark.parametrize("body", [
    "nope", [1], {"filters": "all"}, {"filters": {"cap": "R"}}, {"filters": {"cap": "g"}}, {"filters": {"animated": "yes"}},
    {"filters": {"under_90": 1}}, {"filters": {"ready": None}}, {"filters": {"shiny": True}},
    {"filters": {}, "exclude": "1,2"}, {"filters": {}, "exclude": ["1"]}, {"filters": {}, "exclude": [True]},
])
def test_bad_surprise_requests_are_a_400(client, body):
    r = client.post("/api/surprise", json=body)
    assert r.status_code == 400 and r.get_json()["error"]


def test_surprise_needs_an_editor(anon_client):
    assert anon_client.post("/api/surprise", json={}).status_code == 401


@pytest.fixture
def ids_client(client):
    with app.app.app_context():
        con = app.get_db()
        ids = {title: add(con, title, cert, runtime, animated) for title, cert, runtime, animated in LIBRARY}
    return client, ids
