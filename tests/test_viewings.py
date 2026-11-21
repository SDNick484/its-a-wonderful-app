"""Viewings, Continue Watching and finishing (spec §10.1, §10.3, §8.3; plan Task 10; Review Focus 1: Matinee down during a
finish). Matinee answers from the FakeMatinee in conftest; Home Assistant from a recorder (tests/test_ha_log.py has the
webhook's own failures). Elf is owned (Matinee title 1), Klaus is not. The people have made-up names."""
import datetime as dt
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import pytest

import app
from test_matinee_client import refresh_cli

ELF, KLAUS = 10719, 508439
HA_URL = "http://ha.example.com:8123/api/webhook/test-webhook-id"
LA = ZoneInfo("America/Los_Angeles")


class HaRecorder:
    """urlopen for ha.example.com: records each JSON body posted; any other host goes to `other`."""

    def __init__(self, other):
        self.other, self.posts = other, []

    def __call__(self, req, timeout=None):
        if urllib.parse.urlparse(req.full_url).hostname != "ha.example.com":
            return self.other(req, timeout=timeout)
        self.posts.append(json.loads(req.data))
        return _Ok()


class _Ok:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def join_ha():
    """Wait for the fire-and-forget webhook threads to finish."""
    for t in threading.enumerate():
        if t.name == "ha-webhook":
            t.join(timeout=5)


@pytest.fixture
def fam(client, matinee_fixtures, monkeypatch):
    """Five people copied from Matinee plus a visitor who lives only here, Elf (owned, 97 min, PG) and Klaus (not owned,
    96 min, PG), ownership checked. Home Assistant is set up and recorded."""
    matinee_fixtures.people_file = "people_five.json"
    client.post("/api/people/sync")
    client.post("/api/people", json={"name": "Grandpa Quill", "kind": "adult"})
    with app.app.app_context():
        con = app.get_db()
        elf = con.execute("INSERT INTO movies (tmdb_id, title, year, runtime_min, certification)"
                          " VALUES (?, 'Elf', 2003, 97, 'PG')", (ELF,)).lastrowid
        klaus = con.execute("INSERT INTO movies (tmdb_id, title, year, runtime_min, certification)"
                            " VALUES (?, 'Klaus', 2019, 96, 'PG')", (KLAUS,)).lastrowid
        con.commit()
        app.movies.refresh_ownership(con, elf)
        app.movies.refresh_ownership(con, klaus)
    matinee_fixtures.calls.clear()
    monkeypatch.setattr(app, "HA_WEBHOOK_URL", HA_URL)
    ha = HaRecorder(urllib.request.urlopen)
    monkeypatch.setattr(urllib.request, "urlopen", ha)
    people = [p["id"] for p in client.get("/api/people").get_json()]
    return {"elf": elf, "klaus": klaus, "people": people, "matinee": matinee_fixtures, "ha": ha}


def tonight(client, movie_id, **body):
    r = client.post(f"/api/movies/{movie_id}/tonight", json=body or None)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def finish(client, viewing_id, **body):
    r = client.post(f"/api/viewings/{viewing_id}/finish", json=body or None)
    join_ha()
    return r


def vrow(viewing_id):
    with app.app.app_context():
        r = app.get_db().execute("SELECT * FROM viewings WHERE id=?", (viewing_id,)).fetchone()
        return dict(r) if r else None


def sql(query, *args):
    with app.app.app_context():
        con = app.get_db()
        con.execute(query, args)
        con.commit()


def watch_posts(fam):
    return [(path, body) for method, path, body in fam["matinee"].calls if method == "POST" and path.endswith("/watches")]


# ------------------------------------------------------------------------------------------------ the row (spec §10.1)
def test_one_tonight_at_a_time(client, fam):
    elf = tonight(client, fam["elf"])
    assert elf["status"] == "tonight" and elf["people"] == fam["people"]          # everyone, the visitor too
    assert tonight(client, fam["elf"])["viewing_id"] == elf["viewing_id"]         # the open one again, not a second
    klaus = tonight(client, fam["klaus"])
    assert vrow(elf["viewing_id"]) is None                                        # never watched: gone
    sql("UPDATE viewings SET watched_seconds=1200 WHERE id=?", klaus["viewing_id"])
    elf2 = tonight(client, fam["elf"], people=fam["people"][:2])
    assert elf2["people"] == fam["people"][:2]
    assert vrow(klaus["viewing_id"])["status"] == "paused"                        # watched some: back to the row
    with app.app.app_context():
        n = app.get_db().execute("SELECT COUNT(*) FROM viewings WHERE status IN ('tonight','watching')").fetchone()[0]
    assert n == 1
    row = client.get("/api/continue").get_json()["viewings"]
    assert [(v["title"], v["status"]) for v in row] == [("Elf", "tonight"), ("Klaus", "paused")]   # tonight's first
    assert row[1]["progress"] == "Just started"                                   # 20 of 96 min
    assert client.post(f"/api/viewings/{klaus['viewing_id']}/keep").get_json()["status"] == "tonight"
    assert vrow(elf2["viewing_id"]) is None and vrow(klaus["viewing_id"])["status"] == "tonight"


def test_tonight_bad_requests(client, fam):
    assert client.post("/api/movies/999/tonight").status_code == 404
    assert client.post(f"/api/movies/{fam['elf']}/tonight", json={"people": [999]}).status_code == 400
    assert client.post(f"/api/movies/{fam['elf']}/tonight", json={"people": "everyone"}).status_code == 400
    assert client.post("/api/viewings/999/finish").status_code == 404


def test_stale_tonight_reverts_at_4am_local(client, fam, monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    picked = tonight(client, fam["elf"])["viewing_id"]
    sql("UPDATE viewings SET updated_at='2026-12-13T03:30:00Z' WHERE id=?", picked)   # Dec 12, 7:30 pm local
    with app.app.app_context():
        con = app.get_db()
        assert app.viewings.expire_stale(con, dt.datetime(2026, 12, 13, 3, 59, tzinfo=LA)) == 0
        assert vrow(picked)["status"] == "tonight"
        # 4 am local is noon UTC: in UTC terms the pick would already be a "day" old at 3:30 am UTC on the 14th
        assert app.viewings.expire_stale(con, dt.datetime(2026, 12, 13, 4, 0, tzinfo=LA)) == 1
    assert vrow(picked) is None                                                    # never watched: gone
    again = tonight(client, fam["klaus"])["viewing_id"]                           # picked after midnight, at 1 am
    sql("UPDATE viewings SET updated_at='2026-12-14T09:00:00Z', watched_seconds=600 WHERE id=?", again)
    with app.app.app_context():
        con = app.get_db()
        assert app.viewings.expire_stale(con, dt.datetime(2026, 12, 14, 3, 0, tzinfo=LA)) == 0
        assert app.viewings.expire_stale(con, dt.datetime(2026, 12, 14, 4, 0, tzinfo=LA)) == 1
    assert vrow(again)["status"] == "paused"                                      # watched some: back to the row


def test_continue_sets_aside_last_nights_pick(client, fam, monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    picked = tonight(client, fam["elf"])["viewing_id"]
    sql("UPDATE viewings SET updated_at='2020-12-13T03:30:00Z', watched_seconds=60 WHERE id=?", picked)
    assert client.get("/api/continue").get_json()["viewings"][0]["status"] == "paused"


# ------------------------------------------------------------------------------------------------ finishing (§8.3, §8.5)
def test_finish_owned_posts_matinee_watch_with_known_names_only_and_no_live_flag(client, fam):
    v = tonight(client, fam["elf"])
    r = finish(client, v["viewing_id"], finished_on="2025-12-24")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert (body["status"], body["finished_on"], body["watch_pending"]) == ("finished", "2025-12-24", False)
    assert watch_posts(fam) == [("/admin/api/titles/1/watches",
                                 {"watched_date": "2025-12-24", "attendees": ["Avery", "Blake", "Casey", "Drew", "Emery"]})]
    assert "live" not in watch_posts(fam)[0][1]                                    # the visitor is dropped, no live flag
    assert vrow(v["viewing_id"])["matinee_watch_id"] == 3
    assert client.get("/api/continue").get_json()["viewings"] == []               # off the row


def test_finish_not_owned_sends_matinee_nothing(client, fam):
    v = tonight(client, fam["klaus"])
    assert finish(client, v["viewing_id"]).status_code == 200
    assert watch_posts(fam) == [] and vrow(v["viewing_id"])["matinee_watch_id"] is None
    assert len(fam["ha"].posts) == 1                                               # owned or not, HA hears of it


def test_finish_posts_ha_payload(client, fam):
    v = tonight(client, fam["klaus"])
    assert finish(client, v["viewing_id"], finished_on="2025-12-13").status_code == 200
    assert fam["ha"].posts == [{"event": "matinee_watch_logged", "source": "wonderful", "title": "Klaus", "year": 2019,
                                "runtime": 96, "certification": "PG", "formats": [], "location": None,
                                "watched_date": "2025-12-13", "title_id": None}]
    elf = tonight(client, fam["elf"])
    assert finish(client, elf["viewing_id"], finished_on="2025-12-14").status_code == 200
    assert fam["ha"].posts[-1] == {"event": "matinee_watch_logged", "source": "wonderful", "title": "Elf", "year": 2003,
                                   "runtime": 97, "certification": "PG", "formats": ["Blu-ray"],
                                   "location": "Family Room › Media Cabinet › Shelf 2", "watched_date": "2025-12-14",
                                   "title_id": None}


def test_finish_happens_once(client, fam):
    v = tonight(client, fam["elf"])
    assert finish(client, v["viewing_id"]).status_code == 200
    second = finish(client, v["viewing_id"])
    assert second.status_code == 409
    assert len(fam["ha"].posts) == 1 and len(watch_posts(fam)) == 1
    assert client.post(f"/api/viewings/{v['viewing_id']}/abandon").status_code == 409
    assert client.post(f"/api/viewings/{v['viewing_id']}/keep").status_code == 409


def test_two_finishes_at_once_send_once(client, fam):
    """Two phones tap We finished together: one wins, the other is a 409, and each side effect happens once."""
    v = tonight(client, fam["klaus"])
    start, codes = threading.Barrier(2), []

    def tap():
        with app.app.test_client() as c:
            start.wait()
            codes.append(c.post(f"/api/viewings/{v['viewing_id']}/finish").status_code)

    taps = [threading.Thread(target=tap) for _ in range(2)]
    for t in taps:
        t.start()
    for t in taps:
        t.join(timeout=10)
    join_ha()
    assert sorted(codes) == [200, 409] and len(fam["ha"].posts) == 1


@pytest.mark.parametrize("error", ["refused", "timeout", 502, 401], ids=["refused", "timeout", "http502", "wrong-key"])
def test_matinee_down_on_finish_keeps_viewing_finished_and_flags_unsynced(client, fam, monkeypatch, error):
    v = tonight(client, fam["elf"])
    up, tried = urllib.request.urlopen, []

    def down(req, timeout=None):
        if urllib.parse.urlparse(req.full_url).hostname != "movies.example.com":
            return up(req, timeout=timeout)
        tried.append(req.full_url)
        if error == "refused":
            raise urllib.error.URLError(ConnectionRefusedError())
        if error == "timeout":
            raise TimeoutError()
        raise urllib.error.HTTPError(req.full_url, error, "Error", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", down)
    r = finish(client, v["viewing_id"], finished_on="2025-12-20")
    assert r.status_code == 200 and tried                                          # the app still answers
    assert (r.get_json()["status"], r.get_json()["watch_pending"]) == ("finished", True)
    assert vrow(v["viewing_id"])["matinee_watch_id"] is None
    assert len(fam["ha"].posts) == 1                                               # HA is told at the finish
    with app.app.app_context():                                                    # still down tonight: stays owed
        assert refresh_cli.retry_watches(app.get_db(), say=lambda m: None) == (0, 1, 0)
    monkeypatch.setattr(urllib.request, "urlopen", up)                             # Matinee is back: the nightly retry
    with app.app.app_context():
        con = app.get_db()
        assert refresh_cli.retry_watches(con, dry_run=True, say=lambda m: None) == (1, 0, 0)
        assert refresh_cli.retry_watches(con, say=lambda m: None) == (1, 0, 0)
        assert app.viewings.watch_pending(con, v["viewing_id"]) is False
        assert refresh_cli.retry_watches(con, say=lambda m: None) == (0, 0, 0)     # nothing owed any more
    join_ha()
    assert vrow(v["viewing_id"])["matinee_watch_id"] == 3
    assert watch_posts(fam) == [("/admin/api/titles/1/watches",
                                 {"watched_date": "2025-12-20", "attendees": ["Avery", "Blake", "Casey", "Drew", "Emery"]})]
    assert len(fam["ha"].posts) == 1                                               # and not again on the retry


def test_finish_with_matinee_off_owes_nothing(client, fam, monkeypatch):
    monkeypatch.setattr(app, "MATINEE_API_KEY", "")
    v = tonight(client, fam["elf"])
    r = finish(client, v["viewing_id"])
    assert r.status_code == 200 and r.get_json()["watch_pending"] is False and watch_posts(fam) == []
    assert len(fam["ha"].posts) == 1


def test_finish_asks_ownership_first_when_never_asked(client, fam):
    sql("DELETE FROM matinee_sync WHERE movie_id=?", fam["elf"])
    v = tonight(client, fam["elf"])
    assert finish(client, v["viewing_id"]).status_code == 200
    assert ("GET", f"/admin/api/tmdb/{ELF}/owned", None) in fam["matinee"].calls and len(watch_posts(fam)) == 1
    assert fam["ha"].posts[0]["formats"] == ["Blu-ray"]


def test_finished_on_defaults_to_last_session_then_today(client, fam, monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    v = tonight(client, fam["klaus"])
    sql("INSERT INTO sessions (viewing_id, tv_source, started_at, ended_at, end_reason) VALUES"
        " (?, 'Netflix', '2025-12-13T03:31:04Z', '2025-12-13T04:21:00Z', 'tv_off')", v["viewing_id"])   # Dec 12 local
    assert finish(client, v["viewing_id"]).get_json()["finished_on"] == "2025-12-12"
    w = tonight(client, fam["elf"])
    assert finish(client, w["viewing_id"]).get_json()["finished_on"] == app.today().isoformat()


def test_finish_closes_an_open_session(client, fam):
    v = tonight(client, fam["klaus"])
    sql("UPDATE viewings SET status='watching' WHERE id=?", v["viewing_id"])
    sql("INSERT INTO sessions (viewing_id, tv_source, started_at) VALUES (?, 'Netflix', ?)", v["viewing_id"],
        (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert finish(client, v["viewing_id"]).status_code == 200
    with app.app.app_context():
        s = app.get_db().execute("SELECT * FROM sessions WHERE viewing_id=?", (v["viewing_id"],)).fetchone()
    assert s["ended_at"] and s["end_reason"] == "manual"
    assert 29 * 60 <= vrow(v["viewing_id"])["watched_seconds"] <= 31 * 60


@pytest.mark.parametrize("bad", ["12/24/2025", "2025-13-01", 20251224, "2999-01-01"])
def test_bad_finished_on_is_400(client, fam, bad):
    v = tonight(client, fam["klaus"])
    assert finish(client, v["viewing_id"], finished_on=bad).status_code == 400
    assert vrow(v["viewing_id"])["status"] == "tonight" and fam["ha"].posts == []


def test_finished_viewing_counts_as_watched_this_year(client, fam):
    v = tonight(client, fam["klaus"])
    finish(client, v["viewing_id"])
    with app.app.app_context():
        assert app.randomizer.watched_this_year(app.get_db(), fam["klaus"], app.today().year)


# ------------------------------------------------------------------------------------------------ Not yet, gave up, the prompt
def test_prompt_not_yet_and_gave_up(client, fam):
    assert client.get("/api/prompt").get_json() == {"prompt": None}
    v = tonight(client, fam["elf"])
    sql("UPDATE viewings SET status='paused', watched_seconds=3000, guess='not_finished' WHERE id=?", v["viewing_id"])
    p = client.get("/api/prompt").get_json()["prompt"]
    assert p == {"viewing_id": v["viewing_id"], "title": "Elf", "guess": "not_finished", "movie_id": fam["elf"],
                 "people": fam["people"]}
    assert client.post(f"/api/viewings/{v['viewing_id']}/not-yet").get_json()["progress"] == "About halfway"
    assert client.get("/api/prompt").get_json() == {"prompt": None}
    assert vrow(v["viewing_id"])["status"] == "paused"                            # still in Continue Watching
    assert client.post(f"/api/viewings/{v['viewing_id']}/abandon").get_json()["status"] == "abandoned"
    assert client.post(f"/api/viewings/{v['viewing_id']}/abandon").status_code == 200   # twice is fine
    assert client.get("/api/continue").get_json()["viewings"] == []
    assert finish(client, v["viewing_id"]).status_code == 409                      # given up: nothing is sent
    assert fam["ha"].posts == [] and watch_posts(fam) == []


def test_detail_carries_the_open_viewing(client, fam):
    assert client.get(f"/api/movies/{fam['elf']}").get_json()["viewing"] is None
    v = tonight(client, fam["elf"])
    assert client.get(f"/api/movies/{fam['elf']}").get_json()["viewing"]["viewing_id"] == v["viewing_id"]


def test_removing_a_movie_takes_its_owed_watch_with_it(client, fam, monkeypatch):
    v = tonight(client, fam["elf"])
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("down")))
    finish(client, v["viewing_id"])
    client.delete(f"/api/movies/{fam['elf']}")
    with app.app.app_context():
        con = app.get_db()
        assert app.viewings.owed_ids(con) == [v["viewing_id"]]
        assert app.viewings.retry_watches(con) == (1, 0, 0)                        # nothing to send: the mark goes
        assert app.viewings.owed_ids(con) == []


# ------------------------------------------------------------------------------------------------ labels
def test_progress_labels():
    label = app.viewings.progress_label
    assert label(0, 100) == "Just started"
    assert label(24 * 60, 100) == "Just started"
    assert label(25 * 60, 100) == "About halfway"
    assert label(75 * 60, 100) == "About halfway"
    assert label(76 * 60, 100) == "Almost done"
    assert label(200 * 60, 100) == "Almost done"
    assert label(600, None) is None and label(600, 0) is None                     # runtime unknown: no label


# ------------------------------------------------------------------------------------------------ the Watched list, deleting
def watched(client, movie_id):
    return client.get(f"/api/movies/{movie_id}").get_json()["watched"]


def test_detail_lists_finished_viewings_newest_first(client, fam):
    assert watched(client, fam["klaus"]) == []
    first = tonight(client, fam["klaus"], people=fam["people"][:2])["viewing_id"]
    finish(client, first, finished_on="2025-12-20")
    second = tonight(client, fam["klaus"])["viewing_id"]
    finish(client, second, finished_on="2026-11-20")
    gave_up = tonight(client, fam["klaus"])["viewing_id"]
    client.post(f"/api/viewings/{gave_up}/abandon")
    tonight(client, fam["klaus"])                                                 # open: not in the list either
    assert watched(client, fam["klaus"]) == [
        {"viewing_id": second, "finished_on": "2026-11-20", "people": fam["people"], "watch_pending": False},
        {"viewing_id": first, "finished_on": "2025-12-20", "people": fam["people"][:2], "watch_pending": False}]


def test_deleting_a_viewing_deletes_its_matinee_watch_too(client, fam):
    v = tonight(client, fam["elf"])["viewing_id"]
    finish(client, v, finished_on=app.today().isoformat())
    assert vrow(v)["matinee_watch_id"] == 3
    fam["matinee"].calls.clear()
    r = client.delete(f"/api/viewings/{v}")
    assert r.status_code == 200 and r.get_json() == {"ok": True, "watched": []}
    assert ("DELETE", "/admin/api/titles/1/watches/3", None) in fam["matinee"].calls
    assert ("GET", f"/admin/api/tmdb/{ELF}/owned", None) in fam["matinee"].calls    # Matinee's last watch read again
    assert vrow(v) is None and watched(client, fam["elf"]) == []
    with app.app.app_context():
        con = app.get_db()
        assert con.execute("SELECT COUNT(*) FROM viewing_people WHERE viewing_id=?", (v,)).fetchone()[0] == 0
        month = app.watched_days.month_view(con, app.today().strftime("%Y-%m"))
    assert month["days"] == {}                                                    # gone from the Calendar
    assert client.delete(f"/api/viewings/{v}").status_code == 404
    assert len(fam["ha"].posts) == 1                                              # Home Assistant isn't told anything


def test_deleting_the_second_of_two_viewings_keeps_the_first(client, fam):
    first = tonight(client, fam["klaus"])["viewing_id"]
    finish(client, first)
    second = tonight(client, fam["klaus"])["viewing_id"]
    finish(client, second)
    assert client.delete(f"/api/viewings/{second}").get_json()["watched"][0]["viewing_id"] == first
    with app.app.app_context():
        assert app.randomizer.watched_this_year(app.get_db(), fam["klaus"], app.today().year)


@pytest.mark.parametrize("error", ["refused", 502, 401], ids=["refused", "http502", "wrong-key"])
def test_matinee_down_keeps_the_viewing(client, fam, monkeypatch, error):
    v = tonight(client, fam["elf"])["viewing_id"]
    finish(client, v)
    up = urllib.request.urlopen

    def down(req, timeout=None):
        if urllib.parse.urlparse(req.full_url).hostname != "movies.example.com":
            return up(req, timeout=timeout)
        if error == "refused":
            raise urllib.error.URLError(ConnectionRefusedError())
        raise urllib.error.HTTPError(req.full_url, error, "Error", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", down)
    r = client.delete(f"/api/viewings/{v}")
    assert r.status_code == 502 and r.get_json()["error"]
    assert vrow(v)["matinee_watch_id"] == 3 and len(watched(client, fam["elf"])) == 1


def test_a_watch_matinee_already_lost_still_deletes(client, fam):
    v = tonight(client, fam["elf"])["viewing_id"]
    finish(client, v)
    sql("UPDATE viewings SET matinee_watch_id=99 WHERE id=?", v)                    # Matinee answers 404 for 99
    assert client.delete(f"/api/viewings/{v}").status_code == 200 and vrow(v) is None


def test_deleting_an_unsent_watch_sends_nothing_and_owes_nothing(client, fam, monkeypatch):
    v = tonight(client, fam["elf"])["viewing_id"]
    up = urllib.request.urlopen
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError("down")))
    finish(client, v)
    monkeypatch.setattr(urllib.request, "urlopen", up)
    fam["matinee"].calls.clear()
    assert client.delete(f"/api/viewings/{v}").status_code == 200
    assert not [c for c in fam["matinee"].calls if c[0] == "DELETE"]
    with app.app.app_context():
        assert app.viewings.owed_ids(app.get_db()) == []


def test_deleting_with_matinee_off_deletes_here(client, fam, monkeypatch):
    v = tonight(client, fam["elf"])["viewing_id"]
    finish(client, v)
    monkeypatch.setattr(app, "MATINEE_API_KEY", "")
    assert client.delete(f"/api/viewings/{v}").status_code == 200 and vrow(v) is None


def test_only_a_finished_viewing_can_be_deleted(client, fam):
    v = tonight(client, fam["klaus"])["viewing_id"]
    assert client.delete(f"/api/viewings/{v}").status_code == 409
    client.post(f"/api/viewings/{v}/abandon")
    assert client.delete(f"/api/viewings/{v}").status_code == 409
    assert client.delete("/api/viewings/999").status_code == 404
