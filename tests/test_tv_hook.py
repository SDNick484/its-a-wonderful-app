"""The Family Room TV webhook and the finish guess (spec §10.2, §10.3; plan Task 11; Review Focus 2: a null runtime gives
no guess; Review Focus 3: duplicates, TV off with no session, "on" twice, events out of order by `at`). Events go
through POST /hooks/tv with the secret, as Home Assistant sends them. Elf is owned (a disc on the receiver), Klaus is
on Netflix, Home Alone on Disney+. Times are a few days back, so nothing here depends on the date the tests run."""
import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest

import app
from test_viewings import fam, tonight, vrow  # noqa: F401  (fam is a fixture)

SECRET = "tv-s3cret"
LA = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def tv(client, fam, monkeypatch):  # noqa: F811
    """fam plus the hook secret, Home Alone (103 min, Disney+) and where each movie streams, in the providers cache."""
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    monkeypatch.setattr(app, "HA_HOOK_SECRET", SECRET)
    home_alone = sql("INSERT INTO movies (tmdb_id, title, year, runtime_min, certification)"
                     " VALUES (771, 'Home Alone', 1990, 103, 'PG')")
    streams(home_alone, flatrate=["disney_plus"])
    streams(fam["klaus"], flatrate=["netflix"], rent=["fandango_at_home"])
    streams(fam["elf"])
    return {**fam, "home_alone": home_alone}


def sql(query, *args):
    """Run one statement and commit; returns the new row's id."""
    with app.app.app_context():
        con = app.get_db()
        rowid = con.execute(query, args).lastrowid
        con.commit()
        return rowid


def streams(movie_id, **tiers):
    data = {t: tiers.get(t, []) for t in ("flatrate", "free", "ads", "rent", "buy")}
    sql("INSERT INTO providers_cache (movie_id, data, fetched_at) VALUES (?, ?, ?)"
        " ON CONFLICT(movie_id) DO UPDATE SET data=excluded.data", movie_id, json.dumps(data), app.now_iso())


def evening(days_ago, hour, minute):
    """A local time on the host's TZ `days_ago` days back."""
    day = dt.datetime.now(LA).date() - dt.timedelta(days=days_ago)
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=LA)


def event(client, state, source, at, status=200):
    body = {"state": state, "source": source, "at": at.isoformat() if isinstance(at, dt.datetime) else at}
    r = client.post("/hooks/tv", json=body, headers={"X-Hook-Secret": SECRET})
    assert r.status_code == status, r.get_json()
    return r.get_json()


def sessions(viewing_id):
    with app.app.app_context():
        return [dict(r) for r in app.get_db().execute("SELECT * FROM sessions WHERE viewing_id=? ORDER BY id", (viewing_id,))]


def stamp(when):
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def prompt(client):
    return client.get("/api/prompt").get_json()["prompt"]


# ------------------------------------------------------------------------------------------------ the spec's scenario
def test_home_alone_two_nights(client, tv):
    """Spec §10.3 end to end: 50 minutes, guess not finished, Not yet, About halfway, Keep watching tonight, 55 more
    minutes, guess finished, Yes."""
    v = tonight(client, tv["home_alone"])["viewing_id"]
    assert event(client, "on", "Disney+", evening(3, 19, 31)) == {"ok": True, "applied": True, "action": "opened",
                                                                  "reason": "on Disney+"}
    assert vrow(v)["status"] == "watching"
    assert event(client, "off", None, evening(3, 20, 21))["action"] == "closed"
    row = vrow(v)
    assert (row["status"], row["watched_seconds"], row["guess"]) == ("paused", 50 * 60, "not_finished")
    assert sessions(v)[0]["end_reason"] == "tv_off" and sessions(v)[0]["tv_source"] == "Disney+"

    p = prompt(client)
    assert (p["viewing_id"], p["title"], p["guess"]) == (v, "Home Alone", "not_finished")
    assert client.post(f"/api/viewings/{v}/not-yet").status_code == 200
    assert prompt(client) is None
    row = next(x for x in client.get("/api/continue").get_json()["viewings"] if x["viewing_id"] == v)
    assert row["progress"] == "About halfway" and row["status"] == "paused"

    # night two: the TV is ignored until someone taps Keep watching tonight
    assert event(client, "on", "Disney+", evening(2, 19, 50))["reason"] == "no viewing tonight"
    assert client.post(f"/api/viewings/{v}/keep").get_json()["status"] == "tonight"
    assert event(client, "on", "Disney+", evening(2, 19, 55))["action"] == "opened"
    assert event(client, "off", None, evening(2, 20, 50))["action"] == "closed"
    row = vrow(v)
    assert (row["status"], row["watched_seconds"], row["guess"]) == ("paused", 105 * 60, "finished")

    assert prompt(client)["guess"] == "finished"
    done = client.post(f"/api/viewings/{v}/finish").get_json()
    assert done["status"] == "finished" and done["finished_on"] == evening(2, 0, 0).date().isoformat()
    assert prompt(client) is None


def test_guess_is_finished_from_85_percent_of_the_runtime():
    assert app.viewings.guess_for(5252, 103) == "not_finished"   # 85 % of 103 min is 5253 s
    assert app.viewings.guess_for(5253, 103) == "finished"
    assert app.viewings.guess_for(0, 103) == "not_finished"
    assert app.viewings.guess_for(9999, None) is None and app.viewings.guess_for(9999, 0) is None


# ------------------------------------------------------------------------------------------------ the rules
def test_source_youtube_closes_session(client, tv):
    v = tonight(client, tv["klaus"])["viewing_id"]
    assert event(client, "on", "Netflix", evening(1, 19, 0))["action"] == "opened"
    assert event(client, "on", "YouTube", evening(1, 19, 20)) == {"ok": True, "applied": True, "action": "closed",
                                                                  "reason": "source_changed"}
    s = sessions(v)
    assert len(s) == 1 and s[0]["end_reason"] == "source_changed" and s[0]["ended_at"] == stamp(evening(1, 19, 20))
    row = vrow(v)
    assert (row["status"], row["watched_seconds"], row["guess"]) == ("paused", 20 * 60, "not_finished")
    assert prompt(client)["viewing_id"] == v
    # back to Netflix: the viewing is paused now, so nothing opens until Keep watching tonight
    assert event(client, "on", "Netflix", evening(1, 19, 25))["action"] == "ignored"
    assert len(sessions(v)) == 1


def test_an_input_that_cannot_play_it_opens_nothing(client, tv):
    v = tonight(client, tv["klaus"])["viewing_id"]
    assert event(client, "on", "Live TV", evening(1, 19, 0))["reason"] == "Live TV can't play it"
    assert event(client, "on", "Disney+", evening(1, 19, 1))["action"] == "ignored"
    assert sessions(v) == [] and vrow(v)["status"] == "tonight"
    assert event(client, "on", "fandango at home", evening(1, 19, 2))["action"] == "opened"   # a rental counts; any case


def test_disc_counts_on_av_receiver_only_when_owned(client, tv):
    v = tonight(client, tv["klaus"])["viewing_id"]                          # not owned
    assert event(client, "on", "AV Receiver", evening(1, 19, 0))["reason"] == "AV Receiver can't play it"
    assert sessions(v) == []

    w = tonight(client, tv["elf"])["viewing_id"]                            # owned on Blu-ray, streams nowhere
    assert event(client, "on", "AV Receiver", evening(1, 19, 5))["action"] == "opened"
    assert sessions(w)[0]["tv_source"] == "AV Receiver" and vrow(w)["status"] == "watching"
    assert event(client, "off", None, evening(1, 20, 47))["action"] == "closed"
    assert (vrow(w)["watched_seconds"], vrow(w)["guess"]) == (102 * 60, "finished")   # 97 min Elf


def test_digital_copy_counts_on_fandango_not_av_receiver(client, tv):
    movie = sql("INSERT INTO movies (tmdb_id, title, year, runtime_min, certification)"
                " VALUES (888, 'The Digital Carol', 2001, 90, 'G')")
    streams(movie)                                                          # streams nowhere
    tv["matinee"].owned_files[888] = "owned_digital_only.json"
    with app.app.app_context():
        app.movies.refresh_ownership(app.get_db(), movie)
    v = tonight(client, movie)["viewing_id"]
    assert event(client, "on", "AV Receiver", evening(1, 19, 0))["reason"] == "AV Receiver can't play it"
    assert sessions(v) == []
    assert event(client, "on", "Fandango at Home", evening(1, 19, 5))["action"] == "opened"
    assert sessions(v)[0]["tv_source"] == "Fandango at Home"


def test_a_disc_alone_does_not_count_on_fandango(client, tv):
    w = tonight(client, tv["elf"])["viewing_id"]                            # a Blu-ray only
    assert event(client, "on", "Fandango at Home", evening(1, 19, 0))["action"] == "ignored"
    assert sessions(w) == []


def test_timeout_closes_at_runtime_plus_60(client, tv):
    v = tonight(client, tv["klaus"])["viewing_id"]                          # 96 min
    start = evening(2, 19, 0)
    event(client, "on", "Netflix", start)
    # the TV never said off; the next event is the next evening: the session ended at 96 + 60 min
    assert event(client, "on", "Netflix", evening(1, 19, 0))["reason"] == "no viewing tonight"
    s = sessions(v)
    assert len(s) == 1 and s[0]["end_reason"] == "timeout" and s[0]["ended_at"] == stamp(start + dt.timedelta(minutes=156))
    row = vrow(v)
    assert (row["status"], row["watched_seconds"], row["guess"]) == ("paused", 156 * 60, "finished")
    assert prompt(client)["viewing_id"] == v


def test_timeout_is_applied_when_the_app_is_opened(client, tv):
    v = tonight(client, tv["klaus"])["viewing_id"]
    start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)
    event(client, "on", "Netflix", start)
    assert vrow(v)["status"] == "watching"
    p = prompt(client)                                                     # no more events: opening the app closes it
    assert p["viewing_id"] == v and p["guess"] == "finished"
    assert sessions(v)[0]["end_reason"] == "timeout" and vrow(v)["watched_seconds"] == 156 * 60


def test_we_finished_never_counts_past_the_timeout(client, tv):
    v = tonight(client, tv["klaus"])["viewing_id"]
    event(client, "on", "Netflix", dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=20))
    with app.app.app_context():   # straight to the module: no /api read gets to close it first
        app.viewings.finish(app.get_db(), v)
    assert sessions(v)[0]["end_reason"] == "timeout" and vrow(v)["watched_seconds"] == 156 * 60


def test_event_with_no_tonight_viewing_is_ignored(client, tv):
    assert event(client, "on", "Disney+", evening(1, 19, 0)) == {"ok": True, "applied": False, "action": "ignored",
                                                                 "reason": "no viewing tonight"}
    v = tonight(client, tv["home_alone"])["viewing_id"]
    sql("UPDATE viewings SET status='paused', watched_seconds=600 WHERE id=?", v)            # only a paused one
    assert event(client, "on", "Disney+", evening(1, 19, 5))["action"] == "ignored"
    assert sessions(v) == [] and prompt(client) is None


def test_two_open_viewings_are_ignored(client, tv):
    a = tonight(client, tv["home_alone"])["viewing_id"]
    b = sql("INSERT INTO viewings (movie_id, started_on, status) VALUES (?, '2025-12-12', 'tonight')", tv["klaus"])
    assert event(client, "on", "Disney+", evening(1, 19, 0))["reason"] == "more than one viewing tonight"
    assert event(client, "off", None, evening(1, 20, 0))["action"] == "ignored"
    assert sessions(a) == sessions(b) == [] and prompt(client) is None


def test_duplicate_on_and_off_with_no_session_are_noops(client, tv):
    v = tonight(client, tv["home_alone"])["viewing_id"]
    assert event(client, "off", None, evening(1, 18, 0))["reason"] == "TV off with no session open"
    assert vrow(v)["status"] == "tonight" and sessions(v) == []

    on = evening(1, 19, 31)
    assert event(client, "on", "Disney+", on)["action"] == "opened"
    assert event(client, "on", "Disney+", on)["reason"] == "duplicate"                     # HA sent it twice
    assert event(client, "on", "Disney+", evening(1, 19, 40))["reason"] == "session already open"   # "on" twice
    assert event(client, "playing", "Disney+", evening(1, 19, 41))["reason"] == "session already open"
    assert len(sessions(v)) == 1

    off = evening(1, 20, 21)
    assert event(client, "off", None, off)["action"] == "closed"
    assert event(client, "off", None, off)["reason"] == "duplicate"
    assert event(client, "off", None, evening(1, 20, 30))["action"] == "ignored"
    assert (vrow(v)["watched_seconds"], len(sessions(v))) == (50 * 60, 1)


def test_out_of_order_at_is_ignored(client, tv):
    v = tonight(client, tv["home_alone"])["viewing_id"]
    assert event(client, "on", "Disney+", evening(1, 19, 31))["action"] == "opened"
    # an "off" from before the "on" arrives late: it changes nothing
    assert event(client, "off", None, evening(1, 19, 0)) == {"ok": True, "applied": False, "action": "ignored",
                                                             "reason": "out of order"}
    assert vrow(v)["status"] == "watching" and sessions(v)[0]["ended_at"] is None
    assert event(client, "off", None, evening(1, 20, 21))["action"] == "closed"
    assert vrow(v)["watched_seconds"] == 50 * 60
    assert event(client, "on", "YouTube", evening(1, 20, 0))["reason"] == "out of order"
    assert sessions(v)[0]["end_reason"] == "tv_off"


def test_null_runtime_gives_no_guess(client, tv):
    v = tonight(client, tv["home_alone"])["viewing_id"]
    sql("UPDATE movies SET runtime_min=NULL WHERE id=?", tv["home_alone"])
    event(client, "on", "Disney+", evening(1, 19, 0))
    assert event(client, "off", None, evening(1, 21, 0))["action"] == "closed"
    row = vrow(v)
    assert (row["status"], row["watched_seconds"], row["guess"]) == ("paused", 2 * 3600, None)
    p = prompt(client)                                     # still asked, with nothing preselected
    assert p["viewing_id"] == v and p["guess"] is None
    assert client.post(f"/api/viewings/{v}/not-yet").status_code == 200
    assert prompt(client) is None


def test_null_runtime_session_times_out_after_four_hours(client, tv):
    v = tonight(client, tv["home_alone"])["viewing_id"]
    sql("UPDATE movies SET runtime_min=NULL WHERE id=?", tv["home_alone"])
    start = evening(2, 19, 0)
    event(client, "on", "Disney+", start)
    event(client, "on", "Disney+", start + dt.timedelta(hours=3, minutes=59))
    assert sessions(v)[0]["ended_at"] is None
    event(client, "on", "Disney+", start + dt.timedelta(hours=4))
    s = sessions(v)[0]
    assert s["end_reason"] == "timeout" and vrow(v)["guess"] is None and vrow(v)["watched_seconds"] == 4 * 3600


@pytest.mark.parametrize("answer", ["keep", "abandon", "finish"])
def test_any_answer_clears_the_question(client, tv, answer):
    v = tonight(client, tv["home_alone"])["viewing_id"]
    sql("UPDATE movies SET runtime_min=NULL WHERE id=?", tv["home_alone"])
    event(client, "on", "Disney+", evening(1, 19, 0))
    event(client, "off", None, evening(1, 19, 30))
    assert prompt(client)["viewing_id"] == v
    assert client.post(f"/api/viewings/{v}/{answer}").status_code == 200
    assert prompt(client) is None
    with app.app.app_context():
        assert app.get_db().execute("SELECT COUNT(*) FROM meta WHERE k LIKE 'finish_ask:%'").fetchone()[0] == 0


def test_picking_another_movie_drops_an_unanswered_unwatched_question(client, tv):
    v = tonight(client, tv["home_alone"])["viewing_id"]
    sql("UPDATE movies SET runtime_min=NULL WHERE id=?", tv["home_alone"])
    event(client, "on", "Disney+", evening(1, 19, 0))
    event(client, "off", None, evening(1, 19, 0) + dt.timedelta(seconds=30))
    assert prompt(client)["viewing_id"] == v                     # 30 s watched, still asked
    tonight(client, tv["home_alone"])                            # Watch tonight again answers it
    assert prompt(client) is None


# ------------------------------------------------------------------------------------------------ the body
@pytest.mark.parametrize("source", [None, "None", "unknown", "unavailable", ""])
def test_a_missing_source_says_nothing(client, tv, source):
    v = tonight(client, tv["home_alone"])["viewing_id"]
    event(client, "on", "Disney+", evening(1, 19, 0))
    assert event(client, "on", source, evening(1, 19, 1))["reason"] == "no source"   # HA renders a missing attribute "None"
    assert vrow(v)["status"] == "watching"


@pytest.mark.parametrize("state", ["unavailable", "unknown"])
def test_unavailable_tv_closes_nothing(client, tv, state):
    v = tonight(client, tv["home_alone"])["viewing_id"]
    event(client, "on", "Disney+", evening(1, 19, 0))
    assert event(client, state, None, evening(1, 19, 10))["action"] == "ignored"
    assert sessions(v)[0]["ended_at"] is None


def test_standby_counts_as_off_and_a_naive_at_is_host_local(client, tv):
    v = tonight(client, tv["home_alone"])["viewing_id"]
    event(client, "on", "Disney+", evening(1, 19, 0).replace(tzinfo=None).isoformat())
    assert sessions(v)[0]["started_at"] == stamp(evening(1, 19, 0))
    assert event(client, "standby", None, evening(1, 19, 45).astimezone(dt.timezone.utc).isoformat()
                 .replace("+00:00", "Z"))["reason"] == "tv_off"
    assert vrow(v)["watched_seconds"] == 45 * 60


@pytest.mark.parametrize("body", [None, [], {}, {"state": ""}, {"state": 1}, {"state": "on", "source": 5},
                                  {"state": "on", "at": "yesterday"}, {"state": "on", "at": 1765596664}])
def test_bad_bodies_are_400(client, tv, body):
    r = client.post("/hooks/tv", data=json.dumps(body), content_type="application/json",
                    headers={"X-Hook-Secret": SECRET})
    assert r.status_code == 400 and r.get_json()["error"]


def test_missing_at_means_now(client, tv):
    v = tonight(client, tv["home_alone"])["viewing_id"]
    r = client.post("/hooks/tv", json={"state": "on", "source": "Disney+"}, headers={"X-Hook-Secret": SECRET})
    assert r.get_json()["action"] == "opened"
    began = dt.datetime.strptime(sessions(v)[0]["started_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    assert abs((dt.datetime.now(dt.timezone.utc) - began).total_seconds()) < 60


def test_the_hook_still_needs_the_secret(client, tv):
    tonight(client, tv["home_alone"])
    r = client.post("/hooks/tv", json={"state": "on", "source": "Disney+"}, headers={"X-Hook-Secret": "wrong"})
    assert r.status_code == 403


def test_handle_tv_event_directly(client, tv):
    v = tonight(client, tv["home_alone"])["viewing_id"]
    with app.app.app_context():
        con = app.get_db()
        assert app.ha.handle_tv_event(con, "on", "Disney+", evening(1, 19, 0)) == {"action": "opened",
                                                                                  "reason": "on Disney+"}
        assert app.ha.handle_tv_event(con, "off", None, evening(1, 19, 10))["action"] == "closed"
        assert not con.in_transaction
    assert vrow(v)["watched_seconds"] == 600


# ------------------------------------------------------------------------------------------------ where the TV is (GET /api/tv)
def tv_state(client):
    r = client.get("/api/tv")
    assert r.status_code == 200
    return r.get_json()


def test_tv_state_is_null_before_any_event(client, tv):
    assert tv_state(client) == {"state": None, "source": None, "at": None}


def test_tv_state_follows_events_with_nothing_picked(client, tv):
    at = evening(1, 19, 31)
    assert event(client, "on", "Disney+", at)["action"] == "ignored"   # no viewing is on for tonight
    assert tv_state(client) == {"state": "on", "source": "Disney+", "at": at.isoformat()}


def test_an_out_of_order_event_does_not_change_tv_state(client, tv):
    newer = evening(1, 19, 31)
    event(client, "on", "Disney+", newer)
    assert event(client, "off", None, evening(1, 19, 0))["reason"] == "out of order"
    assert event(client, "on", "YouTube", newer)["reason"] == "duplicate"
    assert tv_state(client) == {"state": "on", "source": "Disney+", "at": newer.isoformat()}


def test_off_keeps_no_source(client, tv):
    event(client, "on", "Disney+", evening(1, 19, 31))
    off = evening(1, 20, 21)
    event(client, "off", None, off)
    assert tv_state(client) == {"state": "off", "source": None, "at": off.isoformat()}


def test_tv_state_is_kept_while_a_viewing_is_on(client, tv):
    tonight(client, tv["home_alone"])
    at = evening(1, 19, 31)
    assert event(client, "on", "Disney+", at)["action"] == "opened"
    assert tv_state(client) == {"state": "on", "source": "Disney+", "at": at.isoformat()}


def test_tv_is_on_for_the_on_states_only():
    assert all(app.ha.tv_is_on(s) for s in ("on", "playing", "paused", "idle", "buffering"))
    assert not any(app.ha.tv_is_on(s) for s in ("off", "standby", "unavailable", "", None))


def test_api_tv_needs_sign_in(anon_client):
    assert anon_client.get("/api/tv", headers={"Cf-Connecting-Ip": "1.2.3.4"}).status_code == 401
