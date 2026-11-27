"""Play on the Family Room TV, the server core (spec §5.1, §5.2, §8; plan Task 3): what can play a movie (play.options),
the webhook setting, and POST /api/movies/<id>/play, which marks the movie for tonight and posts to Home Assistant.
Review Focus 1: Home Assistant not answering. 2: Play never chooses something we'd pay for. 3: a stale TV event never
confirms. Home Assistant answers from a recorder; the webhook URL carries a made-up secret id that must never leak."""
import datetime as dt
import json
import logging
import urllib.error
import urllib.request

import pytest

import app

URL = "http://ha.example.com:8123/api/webhook/play-secret-id"
SECRET_ID = "play-secret-id"
BLURAY = "Blu-ray"
SHELF = "Family Room › Media Cabinet › Shelf 2"
SHELF_LINE = f"{BLURAY} · {SHELF}"
DIGITAL = "Digital HD (Movies Anywhere)"
FANDANGO = "fandango_at_home"
MISSING = object()


class _Ok:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Recorder:
    """urlopen: keeps each request's URL, JSON body, timeout and User-Agent, and answers 200."""

    def __init__(self):
        self.calls = []

    def __call__(self, req, timeout=None):
        self.calls.append({"url": req.full_url, "body": json.loads(req.data), "timeout": timeout,
                           "agent": req.get_header("User-agent"), "type": req.get_header("Content-type")})
        return _Ok()

    @property
    def bodies(self):
        return [c["body"] for c in self.calls]


@pytest.fixture
def recorder(client, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(urllib.request, "urlopen", rec)
    return rec


@pytest.fixture
def ha_play(recorder, monkeypatch):
    """Play on TV is set up, and every request to Home Assistant is recorded."""
    monkeypatch.setattr(app, "HA_PLAY_WEBHOOK_URL", URL)
    return recorder


# ------------------------------------------------------------------------------------------------ helpers
def db():
    return app.get_db()


def add_movie(con, title, runtime=100):
    tmdb_id = con.execute("SELECT COALESCE(MAX(tmdb_id), 0) + 1 FROM movies").fetchone()[0]
    cur = con.execute("INSERT INTO movies (tmdb_id, title, runtime_min) VALUES (?, ?, ?)", (tmdb_id, title, runtime))
    con.commit()
    return cur.lastrowid


def set_providers(con, movie_id, **tiers):
    """The providers cache: service keys or raw provider names per tier."""
    data = {t: tiers.get(t, []) for t in ("flatrate", "free", "ads", "rent", "buy")}
    con.execute("INSERT INTO providers_cache (movie_id, data, fetched_at) VALUES (?, ?, ?)"
                " ON CONFLICT(movie_id) DO UPDATE SET data=excluded.data", (movie_id, json.dumps(data), app.now_iso()))
    con.commit()


def set_owned(con, movie_id, summary, shelf=None, physical=None, digital=None):
    con.execute("INSERT OR REPLACE INTO matinee_sync (movie_id, matinee_title_id, owned_summary, location_path,"
                " checked_at, has_physical, has_digital) VALUES (?, 1, ?, ?, ?, ?, ?)",
                (movie_id, summary, shelf, app.now_iso(), physical, digital))
    con.commit()


def set_status(con, key, status):
    app.providers.set_status(con, {"key": key, "status": status})


def set_title_id(con, movie_id, title_id, service="netflix", manual=0):
    """A stored title id, written straight into the table (so a test can store what the API would refuse)."""
    con.execute("INSERT OR REPLACE INTO service_titles (movie_id, service, title_id, manual, checked_at) VALUES (?,?,?,?,?)",
                (movie_id, service, title_id, manual, app.now_iso()))
    con.commit()


def movie(title="Home Alone", owned=None, title_id=None, **tiers):
    """A movie in a fresh app context's database; `owned` is (summary, shelf, physical, digital)."""
    with app.app.app_context():
        con = db()
        movie_id = add_movie(con, title)
        set_providers(con, movie_id, **tiers)
        if owned:
            set_owned(con, movie_id, *owned)
        if title_id:
            set_title_id(con, movie_id, title_id)
        return movie_id


def options(movie_id):
    with app.app.app_context():
        return app.play.options(db(), movie_id)


def play(client, movie_id, body=None, status=200):
    r = client.post(f"/api/movies/{movie_id}/play", json={"mode": "auto"} if body is None else body)
    assert r.status_code == status, r.get_json()
    return r.get_json()


def sessions(viewing_id):
    with app.app.app_context():
        return [dict(r) for r in db().execute("SELECT * FROM sessions WHERE viewing_id=? ORDER BY id", (viewing_id,))]


def tv_event(state, source):
    """The TV's remembered state, as the webhook leaves it (no viewing is on, so nothing else changes)."""
    with app.app.app_context():
        con = db()
        app.ha.handle_tv_event(con, state, source, dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5))


def tonight(client):
    return [(v["movie_id"], v["status"]) for v in client.get("/api/continue").get_json()["viewings"]]


# ------------------------------------------------------------------------------------------------ the option rule
def test_options_order(client, ha_play):
    # the cache lists Disney+ before Netflix; Subscriptions order puts Netflix first
    movie_id = movie("Elf", owned=(f"{BLURAY} · {DIGITAL}", SHELF, 1, 1), flatrate=["disney_plus", "netflix"],
                     ads=["peacock"], rent=["apple_tv"])
    got = options(movie_id)
    assert got == {
        "stream": [{"service": FANDANGO, "name": "Fandango at Home", "owned": True, "direct": False},
                   {"service": "netflix", "name": "Netflix", "owned": False, "direct": False},
                   {"service": "disney_plus", "name": "Disney+", "owned": False, "direct": False},
                   {"service": "peacock", "name": "Peacock", "owned": False, "direct": False}],
        "disc": {"label": f"{BLURAY} · {DIGITAL} · {SHELF}"},
        "auto": "stream"}


def test_free_services_come_after_subscribed_ones_in_services_order(client, ha_play):
    movie_id = movie(flatrate=["netflix"], free=["paramount_plus"], ads=["peacock"])
    assert [s["service"] for s in options(movie_id)["stream"]] == ["netflix", "peacock", "paramount_plus"]


def test_fandango_listed_once_as_owned(client, ha_play):
    movie_id = movie(owned=(DIGITAL, None, 0, 1), flatrate=[FANDANGO])
    assert options(movie_id) == {"stream": [{"service": FANDANGO, "name": "Fandango at Home", "owned": True, "direct": False}],
                                 "disc": None, "auto": "stream"}


def test_fandango_on_tmdb_alone_is_not_owned(client, ha_play):
    movie_id = movie(flatrate=[FANDANGO])   # subscribed in the seed data, so a plain option
    assert options(movie_id)["stream"] == [{"service": FANDANGO, "name": "Fandango at Home", "owned": False, "direct": False}]


def test_digital_copy_ignores_the_subscription_status(client, ha_play):
    movie_id = movie("Elf", owned=(DIGITAL, None, 0, 1))
    with app.app.app_context():
        set_status(db(), FANDANGO, "ignore")
    assert options(movie_id)["stream"] == [{"service": FANDANGO, "name": "Fandango at Home", "owned": True, "direct": False}]
    assert play(client, movie_id)["source"] == "Fandango at Home"
    assert ha_play.bodies == [{"event": "wonderful_play", "mode": "stream", "source": "Fandango at Home", "title": "Elf"}]


@pytest.mark.parametrize("tiers, statuses", [
    ({"flatrate": ["peacock"]}, {}),                                   # considering
    ({"flatrate": ["netflix"]}, {"netflix": "ignore"}),
    ({"flatrate": ["The Roku Channel"]}, {}),                          # a provider we don't know
    ({"ads": ["The Roku Channel"]}, {}),
    ({"flatrate": ["apple_tv"]}, {"apple_tv": "subscribed"}),          # no tv_source: nothing to open
    ({"ads": ["apple_tv"]}, {}),
    ({"ads": ["peacock"]}, {"peacock": "ignore"}),
    ({"rent": ["netflix", "apple_tv"], "buy": ["disney_plus"]}, {}),
    ({}, {}),
])
def test_what_never_streams(client, ha_play, tiers, statuses):
    movie_id = movie("Scrooged", **tiers)
    with app.app.app_context():
        for key, status in statuses.items():
            set_status(db(), key, status)
    assert options(movie_id) == {"stream": [], "disc": None, "auto": None}
    err = play(client, movie_id, {"mode": "stream"}, status=409)["error"]
    assert err == "Scrooged isn't on a service we have."
    assert ha_play.calls == []


def test_a_disc_alone_is_not_a_stream(client, ha_play):
    movie_id = movie(owned=(BLURAY, SHELF, 1, 0))
    assert options(movie_id) == {"stream": [], "disc": {"label": SHELF_LINE}, "auto": "disc"}


def test_a_stale_ownership_line_says_so(client, ha_play):
    movie_id = movie(owned=(BLURAY, SHELF, 1, 0))
    with app.app.app_context():
        db().execute("UPDATE matinee_sync SET checked_at='2020-12-03T12:00:00Z' WHERE movie_id=?", (movie_id,))
        db().commit()
        label = app.play.options(db(), movie_id)["disc"]["label"]
    assert label.startswith(SHELF_LINE) and "(as of Dec 3)" in label


def test_a_digital_only_copy_has_no_disc(client, ha_play):
    movie_id = movie(owned=(DIGITAL, None, 0, 1))
    assert options(movie_id)["disc"] is None


def test_a_row_from_before_the_upgrade_reads_its_summary(client, ha_play):
    movie_id = movie(owned=(f"{BLURAY} · {DIGITAL}", SHELF, None, None))
    got = options(movie_id)
    assert got["stream"][0]["owned"] is True and got["disc"] == {"label": f"{BLURAY} · {DIGITAL} · {SHELF}"}


# ------------------------------------------------------------------------------------------------ auto
def test_auto_falls_back_to_the_disc(client, ha_play):
    movie_id = movie("Elf", owned=(BLURAY, SHELF, 1, 0), rent=["netflix"])
    assert options(movie_id)["auto"] == "disc"
    got = play(client, movie_id)
    assert ha_play.bodies == [{"event": "wonderful_play", "mode": "disc", "source": "AV Receiver", "title": "Elf"}]
    assert (got["ok"], got["mode"], got["source"], got["name"], got["label"]) == (True, "disc", "AV Receiver", None, SHELF_LINE)


def test_auto_prefers_the_digital_copy_over_netflix(client, ha_play):
    movie_id = movie("Elf", owned=(f"{BLURAY} · {DIGITAL}", SHELF, 1, 1), flatrate=["netflix"])
    got = play(client, movie_id)
    assert ha_play.bodies == [{"event": "wonderful_play", "mode": "stream", "source": "Fandango at Home", "title": "Elf"}]
    assert (got["mode"], got["source"], got["name"], got["label"]) == ("stream", "Fandango at Home", "Fandango at Home", None)


def test_nothing_to_play(client, ha_play):
    movie_id = movie("Scrooged", rent=["netflix"])
    assert options(movie_id) == {"stream": [], "disc": None, "auto": None}
    for body in ({"mode": "auto"}, {"mode": "stream"}):
        assert play(client, movie_id, body, status=409)["error"] == "Scrooged isn't on a service we have."
    assert play(client, movie_id, {"mode": "disc"}, status=409)["error"] == "We don't own Scrooged on disc."
    assert ha_play.calls == [] and tonight(client) == []   # a 409 marks nothing


def test_disc_mode_needs_a_physical_copy(client, ha_play):
    movie_id = movie("Elf", owned=(DIGITAL, None, 0, 1), flatrate=["netflix"])
    assert play(client, movie_id, {"mode": "disc"}, status=409)["error"] == "We don't own Elf on disc."
    assert ha_play.calls == []


# ------------------------------------------------------------------------------------------------ starting the movie itself
KLAUS_ID = "80183187"


def test_netflix_with_an_id_is_direct(client, ha_play):
    movie_id = movie("Klaus", flatrate=["netflix", "disney_plus"], title_id=KLAUS_ID)
    assert [(s["service"], s["direct"]) for s in options(movie_id)["stream"]] == [("netflix", True), ("disney_plus", False)]
    got = play(client, movie_id, {"mode": "stream", "service": "netflix"})
    assert ha_play.bodies == [{"event": "wonderful_play", "mode": "stream", "source": "Netflix", "title": "Klaus",
                               "content_id": KLAUS_ID}]
    assert got["direct"] is True and got["source"] == "Netflix"
    assert play(client, movie_id)["direct"] is True and ha_play.bodies[-1]["content_id"] == KLAUS_ID   # auto, too
    assert KLAUS_ID not in json.dumps(options(movie_id))   # the id itself is never in the options


def test_netflix_without_an_id_is_not_direct(client, ha_play):
    movie_id = movie("Klaus", flatrate=["netflix"])
    assert options(movie_id)["stream"][0]["direct"] is False
    got = play(client, movie_id)
    assert ha_play.bodies == [{"event": "wonderful_play", "mode": "stream", "source": "Netflix", "title": "Klaus"}]
    assert got["direct"] is False
    with app.app.app_context():
        set_title_id(db(), movie_id, None)   # "none found" is a stored row with no id
    assert play(client, movie_id)["direct"] is False and "content_id" not in ha_play.bodies[-1]


def test_other_services_are_never_direct(client, ha_play):
    movie_id = movie("Klaus", flatrate=["disney_plus"], title_id=KLAUS_ID)
    assert options(movie_id)["stream"][0]["direct"] is False
    got = play(client, movie_id, {"mode": "stream", "service": "disney_plus"})
    assert got["direct"] is False and "content_id" not in ha_play.bodies[0]
    with app.app.app_context():
        set_title_id(db(), movie_id, KLAUS_ID, service="disney_plus")   # an id kept for another service is no different
    assert play(client, movie_id)["direct"] is False and "content_id" not in ha_play.bodies[-1]


def test_a_digital_copy_ranks_first_and_is_not_direct(client, ha_play):
    movie_id = movie("Klaus", owned=(DIGITAL, None, 0, 1), flatrate=["netflix"], title_id=KLAUS_ID)
    assert [(s["service"], s["direct"]) for s in options(movie_id)["stream"]] == [(FANDANGO, False), ("netflix", True)]
    got = play(client, movie_id)   # auto goes to the digital copy
    assert (got["source"], got["direct"]) == ("Fandango at Home", False) and "content_id" not in ha_play.bodies[0]
    got = play(client, movie_id, {"mode": "stream", "service": "netflix"})
    assert got["direct"] is True and ha_play.bodies[1]["content_id"] == KLAUS_ID


def test_an_id_for_a_movie_no_longer_on_netflix_is_unused(client, ha_play):
    movie_id = movie("Klaus", flatrate=["disney_plus"], rent=["netflix"], title_id=KLAUS_ID)   # TMDB dropped it from flatrate
    assert [s["service"] for s in options(movie_id)["stream"]] == ["disney_plus"]
    assert play(client, movie_id, {"mode": "stream", "service": "netflix"}, status=409)["error"] == \
           "Klaus can't be played on that service."
    got = play(client, movie_id)
    assert got["direct"] is False and ha_play.bodies == [
        {"event": "wonderful_play", "mode": "stream", "source": "Disney+", "title": "Klaus"}]


def test_netflix_on_the_free_tiers_is_unused(client, ha_play):
    # Subscribed but only on an ads tier: TMDB doesn't say the movie is on our plan, so the id is not sent
    movie_id = movie("Klaus", ads=["netflix"], title_id=KLAUS_ID)
    assert options(movie_id)["stream"][0]["direct"] is False
    assert play(client, movie_id)["direct"] is False and "content_id" not in ha_play.bodies[0]


def test_netflix_considering_is_unused(client, ha_play):
    movie_id = movie("Klaus", flatrate=["netflix"], title_id=KLAUS_ID)
    with app.app.app_context():
        set_status(db(), "netflix", "considering")
    assert options(movie_id) == {"stream": [], "disc": None, "auto": None}
    assert play(client, movie_id, {"mode": "stream", "service": "netflix"}, status=409)["error"] == \
           "Klaus can't be played on that service."
    assert ha_play.calls == []
    with app.app.app_context():   # and not through the ads tier either
        set_providers(db(), movie_id, flatrate=["netflix"], ads=["netflix"])
    assert options(movie_id)["stream"][0]["direct"] is False
    assert play(client, movie_id)["direct"] is False and "content_id" not in ha_play.bodies[0]


@pytest.mark.parametrize("bad", ["80183187; rm", "1234567890123", "80183187/../x", "", " 80183187", "80183187\n", "８０１８３１８７"])
def test_a_stored_id_that_is_not_digits_is_ignored(client, ha_play, bad):
    movie_id = movie("Klaus", flatrate=["netflix"])
    with app.app.app_context():
        set_title_id(db(), movie_id, bad)   # straight into the table, past every check
    assert options(movie_id)["stream"][0]["direct"] is False
    got = play(client, movie_id)
    assert got["direct"] is False and "content_id" not in ha_play.bodies[0]


def test_a_twelve_digit_id_is_sent(client, ha_play):
    movie_id = movie("Klaus", flatrate=["netflix"], title_id="123456789012")
    assert play(client, movie_id)["direct"] is True and ha_play.bodies[0]["content_id"] == "123456789012"


def test_a_direct_play_is_confirmed_like_any_other(client, ha_play):
    movie_id = movie("Klaus", flatrate=["netflix"], title_id=KLAUS_ID)
    tv_event("on", "Netflix")
    got = play(client, movie_id)
    assert got["direct"] is True and got["confirmed"] is True and got["viewing"]["status"] == "watching"


# ------------------------------------------------------------------------------------------------ the route
def test_play_marks_tonight_and_posts_once(client, ha_play):
    movie_id = movie("Home Alone", flatrate=["disney_plus"])
    before = dt.datetime.now(dt.timezone.utc)
    got = play(client, movie_id)
    assert len(ha_play.calls) == 1
    call = ha_play.calls[0]
    assert call["url"] == URL and call["timeout"] == 5 and call["type"] == "application/json"
    assert call["agent"] == app.UA
    assert call["body"] == {"event": "wonderful_play", "mode": "stream", "source": "Disney+", "title": "Home Alone"}
    assert tonight(client) == [(movie_id, "tonight")]
    assert (got["ok"], got["mode"], got["source"], got["name"], got["label"], got["confirmed"]) == \
           (True, "stream", "Disney+", "Disney+", None, False)
    assert got["viewing"]["movie_id"] == movie_id and got["viewing"]["status"] == "tonight"
    assert got["tv"] == {"state": None, "source": None, "at": None}
    sent = dt.datetime.fromisoformat(got["sent_at"])
    assert sent.tzinfo is not None and before - dt.timedelta(seconds=1) <= sent <= dt.datetime.now(dt.timezone.utc)
    assert URL not in json.dumps(got) and SECRET_ID not in json.dumps(got)


def test_play_stream_with_a_named_service(client, ha_play):
    movie_id = movie(flatrate=["netflix", "disney_plus"])
    got = play(client, movie_id, {"mode": "stream", "service": "disney_plus"})
    assert (got["mode"], got["source"], got["name"]) == ("stream", "Disney+", "Disney+")
    got = play(client, movie_id, {"mode": "stream"})   # left out: the first stream option
    assert got["source"] == "Netflix"
    assert [b["source"] for b in ha_play.bodies] == ["Disney+", "Netflix"]


def test_a_named_service_the_movie_is_not_on_is_409(client, ha_play):
    movie_id = movie("Home Alone", flatrate=["netflix"], ads=["peacock"])
    with app.app.app_context():
        set_status(db(), "peacock", "ignore")
    for service in ("peacock", "disney_plus", "no_such_service"):
        err = play(client, movie_id, {"mode": "stream", "service": service}, status=409)["error"]
        assert err == "Home Alone can't be played on that service."
    assert ha_play.calls == [] and tonight(client) == []


def test_tv_already_there_confirms_and_opens_a_session(client, ha_play):
    movie_id = movie("Home Alone", flatrate=["disney_plus"])
    tv_event("on", "disney+")   # lower case, as the TV may say it
    got = play(client, movie_id)
    assert got["confirmed"] is True and got["viewing"]["status"] == "watching"
    assert got["tv"]["state"] == "on" and got["tv"]["source"] == "disney+"
    (session,) = sessions(got["viewing"]["viewing_id"])
    assert session["ended_at"] is None and session["tv_source"] == "Disney+"
    again = play(client, movie_id)   # a second tap opens no second session
    assert again["confirmed"] is True and again["viewing"]["viewing_id"] == got["viewing"]["viewing_id"]
    assert len(sessions(got["viewing"]["viewing_id"])) == 1
    assert tonight(client) == [(movie_id, "watching")]


@pytest.mark.parametrize("state, source", [("on", "Netflix"), ("on", None), ("off", "Disney+"), ("unavailable", "Disney+")])
def test_tv_on_another_app_does_not_confirm(client, ha_play, state, source):
    movie_id = movie("Home Alone", flatrate=["disney_plus", "netflix"])
    tv_event(state, source)
    got = play(client, movie_id, {"mode": "stream", "service": "disney_plus"})
    assert got["confirmed"] is False and got["viewing"]["status"] == "tonight"
    assert sessions(got["viewing"]["viewing_id"]) == []


def test_the_disc_is_confirmed_by_the_receiver_input(client, ha_play):
    movie_id = movie("Elf", owned=(BLURAY, SHELF, 1, 0))
    tv_event("on", "AV Receiver")
    got = play(client, movie_id)
    assert got["confirmed"] is True and sessions(got["viewing"]["viewing_id"])[0]["tv_source"] == "AV Receiver"


class _Status:
    """urlopen answering a status outside 200-299 without raising."""

    def __call__(self, req, timeout=None):
        return _Ok(status=404)


def _raise(error):
    def fake(req, timeout=None):
        raise error
    return fake


@pytest.mark.parametrize("fake", [
    _raise(urllib.error.URLError(f"cannot reach {URL}")),                       # str(exc) would carry the secret
    _raise(TimeoutError(f"timed out talking to {URL}")),
    _raise(urllib.error.HTTPError(URL, 500, f"Server Error at {URL}", {}, None)),
    _Status(),
], ids=["unreachable", "timeout", "http-500", "http-404"])
def test_home_assistant_down(client, monkeypatch, caplog, fake):
    monkeypatch.setattr(app, "HA_PLAY_WEBHOOK_URL", URL)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    movie_id = movie("Home Alone", flatrate=["disney_plus"])
    with caplog.at_level(logging.WARNING):
        r = client.post(f"/api/movies/{movie_id}/play", json={"mode": "auto"})
    assert r.status_code == 502
    assert r.get_json() == {"error": "Couldn't reach the TV. Home Alone is on for tonight; use the remote."}
    assert tonight(client) == [(movie_id, "tonight")]   # still marked: the family is watching it
    assert SECRET_ID not in r.get_data(as_text=True) and SECRET_ID not in caplog.text and URL not in caplog.text
    assert "ha.example.com" in caplog.text


def test_post_play_without_a_url_raises_and_sends_nothing(app_ctx, recorder):
    assert app_ctx.HA_PLAY_WEBHOOK_URL == ""
    with pytest.raises(app.ha.PlayFailed):
        app.ha.post_play({"event": "wonderful_play"})
    assert recorder.calls == []


# ------------------------------------------------------------------------------------------------ off, bad bodies, auth
def test_off_without_the_setting(client, recorder):
    assert app.HA_PLAY_WEBHOOK_URL == ""
    movie_id = movie("Home Alone", owned=(f"{BLURAY} · {DIGITAL}", SHELF, 1, 1), flatrate=["disney_plus"])
    assert options(movie_id) is None
    assert [m["play"] for m in client.get("/api/movies").get_json()] == [None]
    assert client.get(f"/api/movies/{movie_id}").get_json()["play"] is None
    client.post(f"/api/movies/{movie_id}/tonight")
    assert [v["play"] for v in client.get("/api/continue").get_json()["viewings"]] == [None]
    assert play(client, movie_id, status=503) == {"error": "Play on TV isn't set up."}
    assert recorder.calls == []
    assert tonight(client) == [(movie_id, "tonight")]   # only the Watch tonight above: Play marked nothing


def test_every_movie_answer_carries_play(client, ha_play):
    movie_id = movie("Home Alone", flatrate=["disney_plus"])
    want = {"stream": [{"service": "disney_plus", "name": "Disney+", "owned": False, "direct": False}], "disc": None, "auto": "stream"}
    assert [m["play"] for m in client.get("/api/movies").get_json()] == [want]
    assert client.get(f"/api/movies/{movie_id}").get_json()["play"] == want
    client.post(f"/api/movies/{movie_id}/tonight")
    assert [v["play"] for v in client.get("/api/continue").get_json()["viewings"]] == [want]


def test_a_new_movie_carries_play(client, tmdb_fixtures, monkeypatch):
    monkeypatch.setattr(app, "HA_PLAY_WEBHOOK_URL", URL)
    r = client.post("/api/movies", json={"tmdb_id": 10719, "tmdb_type": "movie"})
    assert r.status_code == 201 and set(r.get_json()["play"]) == {"stream", "disc", "auto"}


def test_a_new_movie_has_no_play_when_it_is_off(client, tmdb_fixtures):
    r = client.post("/api/movies", json={"tmdb_id": 10719, "tmdb_type": "movie"})
    assert r.status_code == 201 and r.get_json()["play"] is None


@pytest.mark.parametrize("body", [[], "stream", None, {}, {"mode": "x"}, {"mode": 5}, {"mode": "stream", "service": 5},
                                  {"mode": "stream", "service": ""}, {"mode": "auto", "service": "netflix"},
                                  {"mode": "disc", "service": "netflix"}])
def test_bad_bodies_are_400(client, ha_play, body):
    movie_id = movie(flatrate=["netflix"], owned=(BLURAY, SHELF, 1, 0))
    r = client.post(f"/api/movies/{movie_id}/play", json=body)
    assert r.status_code == 400 and r.get_json()["error"]
    assert ha_play.calls == [] and tonight(client) == []


def test_no_body_at_all_is_400(client, ha_play):
    movie_id = movie(flatrate=["netflix"])
    assert client.post(f"/api/movies/{movie_id}/play").status_code == 400
    assert ha_play.calls == []


def test_unknown_movie_is_404(client, ha_play):
    assert play(client, 999, status=404)["error"]
    assert ha_play.calls == []


def test_play_needs_sign_in(anon_client):
    r = anon_client.post("/api/movies/1/play", json={"mode": "auto"}, headers={"Cf-Connecting-Ip": "1.2.3.4"})
    assert r.status_code == 401


def test_the_second_pick_sets_the_first_aside(client, ha_play):
    first = movie("Home Alone", flatrate=["disney_plus"])
    second = movie("Klaus", flatrate=["netflix"])
    play(client, first)
    play(client, second)
    assert tonight(client) == [(second, "tonight")]
    assert [b["title"] for b in ha_play.bodies] == ["Home Alone", "Klaus"]


# ------------------------------------------------------------------------------------------------ a pick made during the post
def _other_pick_during_the_post(monkeypatch, other_movie_id):
    """The webhook's urlopen makes another movie tonight, on its own connection, while the first play waits on Home
    Assistant (a second phone tapping Watch tonight or Play in that window)."""
    monkeypatch.setattr(app, "HA_PLAY_WEBHOOK_URL", URL)

    def urlopen(req, timeout=None):
        other = app.connect()
        try:
            app.viewings.watch_tonight(other, other_movie_id)
        finally:
            other.close()
        return _Ok()
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)


def _live():
    with app.app.app_context():
        return [tuple(r) for r in db().execute("SELECT movie_id, status FROM viewings WHERE status IN ('tonight', 'watching')")]


@pytest.mark.parametrize("tv_there", [False, True])
def test_a_viewing_deleted_during_the_post_is_not_an_error(client, monkeypatch, tv_there):
    first = movie("Home Alone", flatrate=["disney_plus"])
    second = movie("Klaus", flatrate=["netflix"])
    if tv_there:
        tv_event("on", "Disney+")
    _other_pick_during_the_post(monkeypatch, second)
    got = play(client, first)   # Home Assistant was told to play, so the answer is still ok
    assert got["ok"] is True and got["confirmed"] is False and got["viewing"] is None
    assert _live() == [(second, "tonight")]
    with app.app.app_context():
        assert db().execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_a_viewing_paused_during_the_post_opens_no_session(client, monkeypatch):
    first = movie("Home Alone", flatrate=["disney_plus"])
    second = movie("Klaus", flatrate=["netflix"])
    with app.app.app_context():
        con = db()
        viewing_id = app.viewings.watch_tonight(con, first)
        con.execute("UPDATE viewings SET watched_seconds=600, status='paused' WHERE id=?", (viewing_id,))
        con.commit()
    tv_event("on", "Disney+")
    _other_pick_during_the_post(monkeypatch, second)
    got = play(client, first)
    assert got["ok"] is True and got["confirmed"] is False
    assert got["viewing"]["viewing_id"] == viewing_id and got["viewing"]["status"] == "paused"
    assert _live() == [(second, "tonight")]
    assert sessions(viewing_id) == []
