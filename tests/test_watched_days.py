"""The Calendar's API (calendar spec §4, §5; calendar plan Task 1; Review Focus 1 to 3): which nights a viewing shows on,
GET /api/calendar?month=YYYY-MM and its 400s. The host is in Los Angeles and today is 2026-12-05; sessions are stored
in UTC, as the TV hook writes them. Movie titles only, no people."""
import datetime as dt

import pytest

import app
import watched_days

BAD_MONTH = {"error": "month must look like 2026-12"}


@pytest.fixture
def cal(client, monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    monkeypatch.setattr(app, "today", lambda: dt.date(2026, 12, 5))
    with app.app.app_context():
        yield client, app.get_db()


def add_movie(con, tmdb_id, title, year, poster=None):
    cur = con.execute("INSERT INTO movies (tmdb_id, tmdb_type, title, year, poster_path) VALUES (?, 'movie', ?, ?, ?)",
                      (tmdb_id, title, year, poster))
    con.commit()
    return cur.lastrowid


def add_viewing(con, movie_id, status, started_on, finished_on=None, sessions=()):
    """A viewing and one sessions row per UTC "…Z" start stamp in `sessions`."""
    vid = con.execute("INSERT INTO viewings (movie_id, started_on, status, finished_on) VALUES (?, ?, ?, ?)",
                      (movie_id, started_on, status, finished_on)).lastrowid
    for at in sessions:
        con.execute("INSERT INTO sessions (viewing_id, tv_source, started_at) VALUES (?, 'Shield', ?)", (vid, at))
    con.commit()
    return vid


def month(client, value=None):
    r = client.get("/api/calendar" if value is None else f"/api/calendar?month={value}")
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def titles(day):
    return [e["title"] for e in day]


def test_elf_over_two_nights_and_home_alone(cal):
    client, con = cal
    elf = add_movie(con, 10719, "Elf", 2003)
    home = add_movie(con, 771, "Home Alone", 1990)
    elf_v = add_viewing(con, elf, "finished", "2026-12-03", "2026-12-05",
                        sessions=("2026-12-04T03:40:00Z", "2026-12-06T02:55:00Z"))
    home_v = add_viewing(con, home, "paused", "2026-12-05")
    data = month(client, "2026-12")
    assert data["month"] == "2026-12" and data["today"] == "2026-12-05"
    assert sorted(data["days"]) == ["2026-12-03", "2026-12-05"]
    assert data["days"]["2026-12-03"] == [{"movie_id": elf, "viewing_id": elf_v, "title": "Elf", "year": 2003,
                                           "poster_url": None, "finished": False}]
    dec5 = data["days"]["2026-12-05"]
    assert titles(dec5) == ["Elf", "Home Alone"]
    assert [e["finished"] for e in dec5] == [True, False]
    assert dec5[1]["viewing_id"] == home_v


@pytest.mark.parametrize("stamp, night", [
    ("2026-12-06T07:30:00Z", dt.date(2026, 12, 5)),    # 11:30 pm
    ("2026-12-06T09:00:00Z", dt.date(2026, 12, 5)),    # 1:00 am, the evening before
    ("2026-12-06T11:59:00Z", dt.date(2026, 12, 5)),    # 3:59 am
    ("2026-12-06T12:00:00Z", dt.date(2026, 12, 6)),    # 4:00 am counts that day
    ("garbage", None),
    (None, None),
])
def test_night_of(stamp, night, monkeypatch):
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    assert watched_days.night_of(stamp) == night


def test_month_edges(cal):
    client, con = cal
    elf = add_movie(con, 10719, "Elf", 2003)
    vid = add_viewing(con, elf, "paused", "2026-11-30", sessions=("2026-12-01T07:59:00Z",))   # Nov 30, 11:59 pm
    assert [e["viewing_id"] for e in month(client, "2026-11")["days"]["2026-11-30"]] == [vid]
    assert month(client, "2026-12")["days"] == {}


def test_tonight_without_sessions_and_abandoned_are_left_out(cal):
    client, con = cal
    elf = add_movie(con, 10719, "Elf", 2003)
    klaus = add_movie(con, 508439, "Klaus", 2019)
    add_viewing(con, elf, "tonight", "2026-12-05")
    add_viewing(con, klaus, "abandoned", "2026-12-02", sessions=("2026-12-03T03:00:00Z",))
    assert month(client, "2026-12")["days"] == {}


def test_picked_again_viewing_keeps_its_earlier_nights(cal):
    client, con = cal
    elf = add_movie(con, 10719, "Elf", 2003)
    vid = add_viewing(con, elf, "tonight", "2026-12-03", sessions=("2026-12-04T03:40:00Z",))
    days = month(client, "2026-12")["days"]
    assert list(days) == ["2026-12-03"]
    assert days["2026-12-03"][0]["viewing_id"] == vid


def test_rewatch_is_two_entries(cal):
    client, con = cal
    elf = add_movie(con, 10719, "Elf", 2003)
    first = add_viewing(con, elf, "finished", "2026-12-08", "2026-12-08")
    second = add_viewing(con, elf, "paused", "2026-12-20")
    days = month(client, "2026-12")["days"]
    assert sorted(days) == ["2026-12-08", "2026-12-20"]
    assert days["2026-12-08"][0]["viewing_id"] == first and days["2026-12-20"][0]["viewing_id"] == second
    assert first != second


def test_finished_movies_sort_first_then_earliest_session(cal):
    client, con = cal
    late = add_viewing(con, add_movie(con, 1, "The Polar Express", 2004), "paused", "2026-12-10",
                       sessions=("2026-12-11T04:00:00Z",))    # 8 pm
    early = add_viewing(con, add_movie(con, 2, "Klaus", 2019), "paused", "2026-12-10",
                        sessions=("2026-12-11T02:00:00Z",))   # 6 pm
    done = add_viewing(con, add_movie(con, 3, "Elf", 2003), "finished", "2026-12-10", "2026-12-10",
                       sessions=("2026-12-11T05:00:00Z",))    # 9 pm, but finished
    day = month(client, "2026-12")["days"]["2026-12-10"]
    assert [e["viewing_id"] for e in day] == [done, early, late]


def test_poster_url_and_missing_poster(cal):
    client, con = cal
    add_viewing(con, add_movie(con, 10719, "Elf", 2003, poster="tmdb-movie-10719-poster.jpg"), "paused", "2026-12-01")
    add_viewing(con, add_movie(con, 508439, "Klaus", 2019), "paused", "2026-12-02")
    days = month(client, "2026-12")["days"]
    assert days["2026-12-01"][0]["poster_url"] == "/posters/tmdb-movie-10719-poster.jpg"
    assert days["2026-12-02"][0]["poster_url"] is None


@pytest.mark.parametrize("value", ["2026-13", "Dec", "", "2026-1", "0000-12", "2026-12-01"])
def test_bad_month_is_400(cal, value):
    client, _ = cal
    r = client.get(f"/api/calendar?month={value}")
    assert r.status_code == 400
    assert r.get_json() == BAD_MONTH


def test_no_month_is_the_current_month(cal):
    client, _ = cal
    assert month(client) == {"month": "2026-12", "today": "2026-12-05", "days": {}}


def test_empty_month(cal):
    client, _ = cal
    assert month(client, "2026-12") == {"month": "2026-12", "today": "2026-12-05", "days": {}}


def test_anonymous_is_401(anon_client):
    assert anon_client.get("/api/calendar", headers={"Cf-Connecting-Ip": "1.2.3.4"}).status_code == 401


def test_an_after_midnight_watch_is_one_night(cal):
    """Picked at 00:30 on Dec 6, TV on at 00:35, finished: watch_tonight writes started_on and finish() writes
    finished_on as calendar dates (Dec 6), but the night the family watched is Dec 5, as the session says. One cell."""
    client, con = cal
    elf = add_movie(con, 10719, "Elf", 2003)
    vid = add_viewing(con, elf, "finished", "2026-12-06", "2026-12-06", sessions=("2026-12-06T08:35:00Z",))
    days = month(client, "2026-12")["days"]
    assert list(days) == ["2026-12-05"]
    assert [(e["viewing_id"], e["finished"]) for e in days["2026-12-05"]] == [(vid, True)]


def test_a_finish_on_a_later_night_without_the_tv_still_shows(cal):
    """Only a calendar date that is an after-midnight session's own date folds into its night; a later finish date
    (watched the end somewhere the TV didn't see) still has its own cell."""
    client, con = cal
    elf = add_movie(con, 10719, "Elf", 2003)
    add_viewing(con, elf, "finished", "2026-12-03", "2026-12-07", sessions=("2026-12-04T03:40:00Z",))
    days = month(client, "2026-12")["days"]
    assert sorted(days) == ["2026-12-03", "2026-12-07"]
    assert days["2026-12-07"][0]["finished"] is True and days["2026-12-03"][0]["finished"] is False
